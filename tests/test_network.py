import json
import os
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import monitor
    import srun
except Exception:
    monitor = None
    srun = None


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        pages = {
            "/connect": (200, b"Microsoft Connect Test"),
            "/empty": (200, b""),
            "/hijack": (200, b"<html><body>login</body></html>"),
        }
        code, body = pages.get(self.path, (404, b"not found"))
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@unittest.skipIf(monitor is None, "monitor 依赖 Windows 才能导入")
class ProbeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def probe(self, path, marker):
        old = monitor.PROBE_TARGETS
        monitor.PROBE_TARGETS = ((self.base + path, marker),)
        try:
            return monitor.probe(timeout=3.0)
        finally:
            monitor.PROBE_TARGETS = old

    def test_marker_target_requires_marker(self):
        self.assertTrue(self.probe("/connect", b"Microsoft Connect Test")[0])
        ok, detail = self.probe("/hijack", b"Microsoft Connect Test")
        self.assertFalse(ok)
        self.assertIn("内容异常", detail)

    def test_empty_200_does_not_pass_marker_target(self):
        ok, _ = self.probe("/empty", b"Microsoft Connect Test")
        self.assertFalse(ok)

    def test_generate_204_accepts_empty_200_but_not_content(self):
        self.assertTrue(self.probe("/empty", None)[0])
        ok, _ = self.probe("/hijack", None)
        self.assertFalse(ok)

    def test_404_fails(self):
        self.assertFalse(self.probe("/nope", None)[0])


@unittest.skipIf(srun is None, "srun 依赖 Windows 才能导入")
class SrunHostTest(unittest.TestCase):
    def test_normalize_host(self):
        self.assertEqual(srun.normalize_host(" 10.0.0.1 "), "10.0.0.1")
        self.assertEqual(srun.normalize_host("http://10.0.0.1:8080/"), "10.0.0.1:8080")
        self.assertEqual(srun.normalize_host("https://portal.example.edu/login?x=1"), "portal.example.edu")
        self.assertEqual(srun.normalize_host(""), "")

    def test_split_host_port(self):
        self.assertEqual(srun.split_host_port("10.0.0.1"), ("10.0.0.1", 80))
        self.assertEqual(srun.split_host_port("10.0.0.1:8080"), ("10.0.0.1", 8080))
        self.assertEqual(srun.split_host_port("http://10.0.0.1:8080/"), ("10.0.0.1", 8080))
        self.assertEqual(srun.split_host_port("[::1]:8443"), ("::1", 8443))
        self.assertEqual(srun.split_host_port(""), ("", 80))
        self.assertEqual(srun.split_host_port("10.0.0.1:99999"), ("10.0.0.1", 80))
        self.assertEqual(srun.split_host_port("10.0.0.1:0"), ("10.0.0.1", 80))

    def test_invalid_port_falls_back_consistently(self):
        for raw in ("10.0.0.1:99999", "10.0.0.1:0", "10.0.0.1:abc"):
            with self.subTest(raw=raw):
                self.assertEqual(srun.normalize_host(raw), "10.0.0.1")
                self.assertEqual(srun.split_host_port(raw), ("10.0.0.1", 80))
                self.assertEqual(srun.SrunPortal("u", "p", raw).host, "10.0.0.1")

    def test_ipv6_round_trip_keeps_brackets(self):
        self.assertEqual(srun.normalize_host("[::1]:8443"), "[::1]:8443")
        self.assertEqual(srun.normalize_host("[::1]:99999"), "[::1]")
        self.assertEqual(srun.normalize_host("http://[::1]:8080/"), "[::1]:8080")

    def test_local_ip_with_bad_port_does_not_raise(self):
        self.assertIsInstance(srun.local_ip("127.0.0.1:99999"), str)

    def test_portal_normalizes_on_init(self):
        portal = srun.SrunPortal("u", "p", " http://10.0.0.1:8080/ ")
        self.assertEqual(portal.host, "10.0.0.1:8080")


@unittest.skipIf(srun is None, "srun 依赖 Windows 才能导入")
class SrunResultTest(unittest.TestCase):
    def make_portal(self, res):
        class FakePortal(srun.SrunPortal):
            def __init__(self):
                super().__init__("20260000000", "secret", "10.0.0.1")
                self.res = res

            def get_challenge(self, ip):
                return {"challenge": "tok", "client_ip": ip}

            def _get(self, path, params):
                return dict(self.res)

        return FakePortal()

    def test_success_ecodes(self):
        cases = [
            ({"ecode": 0}, True),
            ({"ecode": "0"}, True),
            ({"error": "ok"}, True),
            ({"ecode": "ip_already_online_error"}, True),
            ({"ecode": "1", "error_msg": "密码错误"}, False),
            ({"ecode": None}, False),
        ]
        for res, expect in cases:
            with self.subTest(res=res):
                self.assertEqual(self.make_portal(res).login()["ok"], expect)


@unittest.skipIf(monitor is None, "monitor 依赖 Windows 才能导入")
class PortalReachableTest(unittest.TestCase):
    def make_monitor(self, host):
        m = monitor.Monitor.__new__(monitor.Monitor)
        m.cfg = {"portal_host": host}
        return m

    def test_empty_host_is_unreachable(self):
        self.assertFalse(self.make_monitor("")._portal_reachable())

    def test_reachable_and_port_is_honoured(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(50)
        port = listener.getsockname()[1]
        try:
            self.assertTrue(self.make_monitor("127.0.0.1:%d" % port)._portal_reachable())
            self.assertTrue(self.make_monitor("http://127.0.0.1:%d/" % port)._portal_reachable())
            self.assertFalse(self.make_monitor("127.0.0.1:%d" % (port + 1))._portal_reachable())
        finally:
            listener.close()

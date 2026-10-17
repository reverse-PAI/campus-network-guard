import http.client
import json
import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import monitor
    import webui
except Exception:
    monitor = None
    webui = None


class FakeMon:
    def __init__(self):
        self.cfg = dict(monitor.DEFAULTS)
        self.password = ""
        self.state = {"has_password": False, "autostart": False}
        self.log = logging.getLogger("test-webui")
        self.saved = 0
        self.rescheduled = 0

    def snapshot(self, log_from=0):
        return {"version": "test", "cfg": dict(self.cfg), "logs": [], "log_total": 0}

    def save_config(self):
        self.saved += 1

    def reschedule(self):
        self.rescheduled += 1

    def force_check(self):
        pass

    def force_recover(self):
        pass


@unittest.skipIf(webui is None, "webui 依赖 Windows 才能导入")
class WebuiGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mon = FakeMon()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.srv, err = webui.start(cls.mon, base, 0)
        if cls.srv is None:
            raise unittest.SkipTest("无法启动测试服务器：%s" % err)
        cls.port = cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        if cls.srv is not None:
            cls.srv.shutdown()
            cls.srv.server_close()

    def request(self, method, path="/api/action", payload=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = b""
        h = dict(headers or {})
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            h.setdefault("Content-Type", "application/json")
        h["Content-Length"] = str(len(body))
        try:
            conn.request(method, path, body=body or None, headers=h)
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, data
        finally:
            conn.close()

    def test_save_advanced_fields(self):
        code, data = self.request("POST", payload={
            "action": "save", "ac_id": " 7 ", "interface": "",
            "only_on_campus": False, "allow_renew_ip": False, "tray": False,
            "tray_overflow": False,
            "min_interval_seconds": "0", "max_fail": "999", "cooldown_seconds": "-5",
        })
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(data)["ok"])
        self.assertEqual(self.mon.cfg["ac_id"], "7")
        self.assertEqual(self.mon.cfg["interface"], "WLAN")
        self.assertFalse(self.mon.cfg["only_on_campus"])
        self.assertFalse(self.mon.cfg["allow_renew_ip"])
        self.assertFalse(self.mon.cfg["tray"])
        self.assertFalse(self.mon.cfg["tray_overflow"])
        self.assertEqual(self.mon.cfg["min_interval_seconds"], 1)
        self.assertEqual(self.mon.cfg["max_fail"], 99)
        self.assertEqual(self.mon.cfg["cooldown_seconds"], 0)
        self.assertGreaterEqual(self.mon.saved, 1)

    def test_empty_ac_id_falls_back_to_default(self):
        code, _ = self.request("POST", payload={"action": "save", "ac_id": "   "})
        self.assertEqual(code, 200)
        self.assertEqual(self.mon.cfg["ac_id"], "1")

    def test_cross_site_host_is_rejected(self):
        code, _ = self.request("POST", payload={"action": "check"}, headers={"Host": "evil.example"})
        self.assertEqual(code, 403)

    def test_foreign_origin_is_rejected(self):
        code, _ = self.request("POST", payload={"action": "check"},
                               headers={"Origin": "http://evil.example"})
        self.assertEqual(code, 403)

    def test_wrong_origin_port_is_rejected(self):
        code, _ = self.request("POST", payload={"action": "check"},
                               headers={"Origin": "http://127.0.0.1:9999"})
        self.assertEqual(code, 403)

    def test_local_origin_without_port_is_allowed(self):
        code, _ = self.request("POST", payload={"action": "check"},
                               headers={"Origin": "http://127.0.0.1"})
        self.assertEqual(code, 200)

    def test_non_json_content_type_is_rejected(self):
        code, _ = self.request("POST", payload={"action": "check"},
                               headers={"Content-Type": "text/plain"})
        self.assertEqual(code, 403)

    def test_state_requires_local_host(self):
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": "evil.example"})[0], 403)
        code, data = self.request("GET", "/api/state")
        self.assertEqual(code, 200)
        self.assertIn("cfg", json.loads(data))

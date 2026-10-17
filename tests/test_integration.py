import collections
import http.client
import json
import logging
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import monitor
    import webui
except Exception:
    monitor = None
    webui = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipIf(monitor is None, "monitor 依赖 Windows 才能导入")
class WindowedLoggerTest(unittest.TestCase):
    def test_no_stream_handler_when_stderr_missing(self):
        old = sys.stderr
        sys.stderr = None
        try:
            lg = monitor.build_logger(tempfile.mkdtemp(), collections.deque(), console=True)
        finally:
            sys.stderr = old
        self.assertFalse(any(isinstance(h, logging.StreamHandler)
                             and not isinstance(h, logging.FileHandler) for h in lg.handlers))


@unittest.skipIf(webui is None, "webui 依赖 Windows 才能导入")
class RealMonitorSaveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mon = monitor.Monitor(self.tmp.name, console=False)
        self.srv, err = webui.start(self.mon, ROOT, 0)
        if self.srv is None:
            self.skipTest("无法启动测试服务器：%s" % err)
        self.port = self.srv.server_address[1]

    def tearDown(self):
        if self.srv is not None:
            self.srv.shutdown()
            self.srv.server_close()
        for handler in list(self.mon.log.handlers):
            try:
                handler.close()
            finally:
                self.mon.log.removeHandler(handler)
        self.tmp.cleanup()

    def post(self, payload):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = json.dumps(payload).encode("utf-8")
        try:
            conn.request("POST", "/api/action", body=body,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            return resp.status, json.loads(resp.read())
        finally:
            conn.close()

    def test_save_persists_advanced_fields(self):
        code, data = self.post({
            "action": "save", "username": "20260000000", "password": "",
            "ssid_list": ["Campus-WiFi"], "portal_host": "10.0.0.1:8080",
            "ac_id": "2", "interface": "WLAN", "periodic_seconds": "600",
            "only_on_campus": False, "allow_renew_ip": False, "tray": False,
            "min_interval_seconds": "3", "max_fail": "7", "cooldown_seconds": "120",
        })
        self.assertEqual(code, 200)
        self.assertTrue(data["ok"])
        with open(os.path.join(self.tmp.name, "config.json"), encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(saved["ac_id"], "2")
        self.assertEqual(saved["portal_host"], "10.0.0.1:8080")
        self.assertEqual(saved["min_interval_seconds"], 3)
        self.assertEqual(saved["max_fail"], 7)
        self.assertEqual(saved["cooldown_seconds"], 120)
        self.assertFalse(saved["only_on_campus"])
        self.assertFalse(saved["allow_renew_ip"])
        self.assertFalse(saved["tray"])

    def test_test_login_without_portal_returns_fast(self):
        self.mon.cfg["username"] = "20260000000"
        self.mon.password = "x"
        start = time.monotonic()
        res = self.mon.test_login()
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertFalse(res["ok"])
        self.assertIn("认证服务器", res["error_msg"])

    def test_srun_step_skips_without_portal(self):
        self.mon.cfg["username"] = "20260000000"
        self.mon.cfg["portal_host"] = ""
        self.mon.password = "x"
        start = time.monotonic()
        self.mon._srun_step()
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertIn("未配置认证服务器", self.mon.ring[-1][1])

    def test_srun_step_skips_unreachable_portal_quickly(self):
        self.mon.cfg["username"] = "20260000000"
        self.mon.cfg["portal_host"] = "127.0.0.1:1"
        self.mon.password = "x"
        start = time.monotonic()
        self.mon._srun_step()
        self.assertLess(time.monotonic() - start, 3.0)
        self.assertIn("不可达", self.mon.ring[-1][1])

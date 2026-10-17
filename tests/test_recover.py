import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import monitor
except Exception:  # pragma: no cover - 非 Windows 环境
    monitor = None


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mon = self.make_monitor()
        self.mon.cfg.update({
            "username": "", "portal_host": "", "ssid_list": [],
            "only_on_campus": False, "allow_renew_ip": False,
            "allow_restart_adapter": False, "max_fail": 2,
            "cooldown_seconds": 600,
        })
        self.mon.password = ""

    def make_monitor(self):
        return monitor.Monitor(self.tmp.name, console=False)

    def tearDown(self):
        for handler in list(self.mon.log.handlers):
            try:
                handler.close()
            finally:
                self.mon.log.removeHandler(handler)
        self.tmp.cleanup()


@unittest.skipIf(monitor is None, "monitor 依赖 Windows 才能导入")
class BreakerTest(_Base):
    def test_breaker_after_max_fail(self):
        self.mon.probe_fn = lambda: (False, "probe failed")
        self.assertFalse(self.mon.recover())
        self.assertEqual(self.mon.state["fail_streak"], 1)
        self.assertFalse(self.mon.recover())
        self.assertEqual(self.mon.state["fail_streak"], 0)
        self.assertGreater(self.mon.state["cooldown_until"], time.time())
        self.assertIn("暂停", self.mon.state["status_text"])

    def test_stops_at_first_success(self):
        class Recording(monitor.Monitor):
            def __init__(self, base_dir):
                super().__init__(base_dir, console=False)
                self.calls = []

            def _srun_step(self, note=""):
                self.calls.append("srun")

            def _step_renew(self):
                self.calls.append("renew")

            def _step_wifi(self):
                self.calls.append("wifi")

            def _step_restart(self):
                self.calls.append("restart")

        self.mon = Recording(self.tmp.name)
        self.mon.cfg.update({
            "username": "", "portal_host": "", "ssid_list": [],
            "only_on_campus": False, "allow_renew_ip": True,
            "allow_restart_adapter": True, "max_fail": 2,
            "cooldown_seconds": 600,
        })
        self.mon.probe_fn = lambda: (True, "ok")
        self.assertTrue(self.mon.recover())
        self.assertEqual(self.mon.calls, ["srun"])
        self.assertEqual(self.mon.state["status"], "online")
        self.assertEqual(self.mon.state["status_text"], "网络已恢复")


@unittest.skipIf(monitor is None, "monitor 依赖 Windows 才能导入")
class HttpsHintTest(_Base):
    def test_https_portal_logs_hint(self):
        self.mon.cfg["username"] = "u"
        self.mon.cfg["portal_host"] = "https://portal.example.edu/"
        self.mon.password = "p"
        self.mon._portal_reachable = lambda timeout=2.0: False
        with self.assertLogs("shouwang", level="INFO") as cm:
            self.mon._srun_step()
        self.assertTrue(any("只支持 http" in line for line in cm.output))

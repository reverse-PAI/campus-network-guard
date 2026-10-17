import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import monitor
except Exception as exc:  # pragma: no cover - 非 Windows 环境
    monitor = None
    _IMPORT_ERR = exc


def fix(cfg):
    return monitor._fix_config(dict(cfg))


@unittest.skipIf(monitor is None, "monitor 依赖 Windows 才能导入")
class FixConfigTest(unittest.TestCase):
    def test_legacy_ssid_migrates_only_when_list_empty(self):
        fixed, notes = fix({"ssid": " Campus-WiFi ", "ssid_list": []})
        self.assertEqual(fixed["ssid_list"], ["Campus-WiFi"])
        self.assertTrue(notes)

        fixed, _ = fix({"ssid": "Campus-WiFi", "ssid_list": ["Campus-WiFi"]})
        self.assertEqual(fixed["ssid_list"], ["Campus-WiFi"])

    def test_ssid_list_is_cleaned(self):
        fixed, _ = fix({"ssid_list": ["", " Campus-WiFi ", "campus-wifi", 7]})
        self.assertEqual(fixed["ssid_list"], ["Campus-WiFi", "7"])

    def test_period_and_port_are_clamped(self):
        self.assertEqual(fix({"periodic_seconds": 1})[0]["periodic_seconds"], 30)
        self.assertEqual(fix({"periodic_seconds": 99999})[0]["periodic_seconds"], 3600)
        self.assertEqual(fix({"periodic_seconds": "abc"})[0]["periodic_seconds"], 300)
        self.assertEqual(fix({"periodic_seconds": float("nan")})[0]["periodic_seconds"], 300)
        self.assertEqual(fix({"port": 70000})[0]["port"], 8765)

    def test_bool_strings(self):
        self.assertFalse(fix({"open_browser": "false"})[0]["open_browser"])
        self.assertTrue(fix({"open_browser": "是"})[0]["open_browser"])
        self.assertFalse(fix({"tray": "0"})[0]["tray"])
        self.assertTrue(fix({"tray": "on"})[0]["tray"])

    def test_missing_keys_get_defaults(self):
        fixed, _ = fix({})
        self.assertEqual(fixed["interface"], "WLAN")
        self.assertEqual(fixed["ssid_list"], [])
        self.assertEqual(set(fixed), set(monitor.DEFAULTS))


@unittest.skipIf(monitor is None, "monitor 依赖 Windows 才能导入")
class PersistenceTest(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        d = tempfile.mkdtemp(prefix="sw_cfg_")
        mon = monitor.Monitor(d, console=False)
        try:
            mon.cfg["ssid_list"] = ["Campus-WiFi", "Campus-*"]
            mon.cfg["periodic_seconds"] = 120
            mon.save_config()
            loaded = monitor.Monitor(d, console=False).load_config()
            self.assertEqual(loaded["ssid_list"], ["Campus-WiFi", "Campus-*"])
            self.assertEqual(loaded["periodic_seconds"], 120)
            with open(mon.cfg_path, encoding="utf-8") as fh:
                self.assertNotIn("password", json.load(fh))
        finally:
            mon.stop_evt.set()


if __name__ == "__main__":
    unittest.main()

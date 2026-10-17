import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import monitor
except Exception:  # pragma: no cover
    monitor = None


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class UiWiringTest(unittest.TestCase):
    @unittest.skipIf(monitor is None, "monitor 依赖 Windows 才能导入")
    def test_ui_version_matches_program(self):
        ui = read("ui.html")
        m = re.search(r'name="ui-version" content="([^"]+)"', ui)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), monitor.APP_VERSION)
        self.assertIn('ShouWangUI/%s' % monitor.APP_VERSION, read("webui.py"))

    def test_save_sends_advanced_fields(self):
        ui = read("ui.html")
        for key in ('ac_id: $("fAcid").value',
                    'only_on_campus: $("swCampus").checked',
                    'allow_renew_ip: $("swRenew").checked',
                    'min_interval_seconds: $("fMinInt").value',
                    'max_fail: $("fMaxFail").value',
                    'cooldown_seconds: $("fCooldown").value',
                    'tray: $("swTray").checked'):
            with self.subTest(key=key):
                self.assertIn(key, ui)

    def test_advanced_inputs_exist(self):
        ui = read("ui.html")
        for elem in ("fAcid", "swCampus", "swRenew", "swTray", "fMinInt", "fMaxFail", "fCooldown"):
            with self.subTest(elem=elem):
                self.assertIn('id="%s"' % elem, ui)

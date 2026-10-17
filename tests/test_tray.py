import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import winutil
except Exception:
    winutil = None


@unittest.skipIf(winutil is None, "winutil 依赖 Windows 才能导入")
class TrayRegistryTest(unittest.TestCase):
    def test_normalize_windows_path(self):
        self.assertEqual(winutil._norm_exe_path(""), "")
        self.assertEqual(winutil._norm_exe_path("   "), "")
        self.assertEqual(winutil._norm_exe_path(r"\\?\C:\App\App.exe"),
                         os.path.normcase(os.path.abspath(r"C:\App\App.exe")))
        self.assertEqual(winutil._norm_exe_path('"C:\\App\\App.exe"'),
                         os.path.normcase(os.path.abspath(r"C:\App\App.exe")))

    def test_source_run_does_not_touch_python_tray_setting(self):
        self.assertEqual(winutil.set_tray_promoted(False), 0)

    def test_unknown_exe_path_changes_nothing(self):
        self.assertEqual(winutil.set_tray_promoted(False, r"C:\NoSuch\nope.exe"), 0)


if __name__ == "__main__":
    unittest.main()

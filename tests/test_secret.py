import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import winutil
except Exception:
    winutil = None


@unittest.skipIf(winutil is None, "winutil 依赖 Windows 才能导入")
class SecretTest(unittest.TestCase):
    def test_roundtrip_and_ciphertext(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cred.bin")
            winutil.save_secret(path, "test-password-123")
            self.assertEqual(winutil.load_secret(path), "test-password-123")
            with open(path, "rb") as fh:
                self.assertNotIn(b"test-password-123", fh.read())

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(winutil.load_secret(os.path.join(d, "none.bin")), "")


if __name__ == "__main__":
    unittest.main()

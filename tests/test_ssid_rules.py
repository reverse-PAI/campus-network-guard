import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ssid_rules import (MAX_SSID_ITEMS, is_wildcard, normalize_ssid_list,
                        ssid_key, ssid_matches, sync_legacy_ssid)


class SsidKeyTest(unittest.TestCase):
    def test_trims_and_casefolds(self):
        self.assertEqual(ssid_key("  Campus-WiFi "), "caMpus-WiFi".casefold())

    def test_non_string_is_empty(self):
        self.assertEqual(ssid_key(None), "")
        self.assertEqual(ssid_key(["x"]), "")


class NormalizeTest(unittest.TestCase):
    def test_single_string(self):
        self.assertEqual(normalize_ssid_list("  A  "), ["A"])

    def test_dedup_casefold_keeps_order(self):
        self.assertEqual(normalize_ssid_list(["Campus-WiFi", " campus-wifi ", "Campus-5G"]),
                         ["Campus-WiFi", "Campus-5G"])

    def test_drops_empty_and_non_strings(self):
        self.assertEqual(normalize_ssid_list(["", "  ", None, 3.5, [], "ok"]), ["3.5", "ok"])

    def test_truncates_length_and_count(self):
        self.assertEqual(len(normalize_ssid_list("x" * 80)[0]), 64)
        names = ["n%02d" % i for i in range(MAX_SSID_ITEMS + 8)]
        self.assertEqual(len(normalize_ssid_list(names)), MAX_SSID_ITEMS)

    def test_bad_container(self):
        self.assertEqual(normalize_ssid_list(None), [])
        self.assertEqual(normalize_ssid_list({"a": 1}), [])


class MatchTest(unittest.TestCase):
    def test_exact_case_insensitive(self):
        self.assertTrue(ssid_matches("Campus-WiFi", ["campus-wifi"]))
        self.assertFalse(ssid_matches("Campus", ["Campus-WiFi"]))
        self.assertFalse(ssid_matches("Campus-WiFi", ["Campus"]))
        self.assertFalse(ssid_matches("", ["Campus-*"]))
        self.assertFalse(ssid_matches("Campus-WiFi", []))

    def test_prefix_wildcard(self):
        self.assertTrue(ssid_matches("Campus-WiFi", ["Campus-*"]))
        self.assertTrue(ssid_matches("Campus-*", ["Campus-*"]))
        self.assertFalse(ssid_matches("WiFi-Campus", ["Campus-*"]))

    def test_fullwidth_star(self):
        self.assertTrue(ssid_matches("Campus-WiFi", ["Campus-\uff0a"]))
        self.assertTrue(is_wildcard("Campus-\uff0a"))
        self.assertFalse(is_wildcard("Campus-WiFi"))

    def test_star_alone_matches_any_non_empty(self):
        self.assertTrue(ssid_matches("anything", ["*"]))
        self.assertFalse(ssid_matches("  ", ["*"]))


class LegacyTest(unittest.TestCase):
    def test_sync_picks_first_non_wildcard(self):
        cfg = {"ssid_list": ["Campus-*", "Campus-WiFi"], "ssid": ""}
        sync_legacy_ssid(cfg)
        self.assertEqual(cfg["ssid"], "Campus-WiFi")

    def test_sync_wildcard_only(self):
        cfg = {"ssid_list": ["Campus-*"], "ssid": "old"}
        sync_legacy_ssid(cfg)
        self.assertEqual(cfg["ssid"], "")


if __name__ == "__main__":
    unittest.main()

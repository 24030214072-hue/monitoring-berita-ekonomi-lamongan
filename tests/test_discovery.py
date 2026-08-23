import unittest
from time import struct_time

from news_monitor.discovery import RSSDiscovery


class RSSDiscoveryTests(unittest.TestCase):
    def test_entry_outside_2026_is_rejected(self) -> None:
        entry = {
            "title": "Ekonomi Lamongan",
            "link": "https://example.com/news",
            "published_parsed": struct_time((2025, 12, 31, 0, 0, 0, 2, 365, -1)),
        }
        self.assertIsNone(RSSDiscovery()._candidate_from_entry(entry, "bing"))

    def test_2026_entry_is_normalized(self) -> None:
        entry = {
            "title": "Harga pasar Lamongan naik - Contoh Media",
            "link": "https://example.com/news?utm_source=test",
            "summary": "Harga komoditas naik.",
            "published_parsed": struct_time((2026, 2, 1, 0, 0, 0, 6, 32, -1)),
        }
        candidate = RSSDiscovery()._candidate_from_entry(entry, "google")
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.published_at.year, 2026)
        self.assertEqual(candidate.media, "Contoh Media")
        self.assertNotIn("utm_source", candidate.url)


if __name__ == "__main__":
    unittest.main()

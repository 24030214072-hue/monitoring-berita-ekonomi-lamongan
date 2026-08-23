import unittest
from datetime import date, datetime
from time import struct_time
from unittest.mock import patch

from news_monitor.discovery import RSSDiscovery
from news_monitor.models import NewsCandidate


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

    def test_discovery_uses_month_window_and_rejects_provider_leakage(self) -> None:
        discovery = RSSDiscovery()
        queries: list[str] = []

        def fake_search(provider: str, query: str) -> list[NewsCandidate]:
            queries.append(f"{provider}:{query}")
            return [
                NewsCandidate(datetime(2026, 2, 10), "Media", "Berita Februari", "https://example.com/feb"),
                NewsCandidate(datetime(2026, 3, 1), "Media", "Berita Maret", "https://example.com/mar"),
            ]

        saved_batches: list[tuple[int, int, int]] = []
        with (
            patch.object(discovery, "_search", side_effect=fake_search),
            patch("news_monitor.discovery.SEARCH_TOPICS", ["ekonomi"]),
        ):
            results = discovery.discover(
                [(date(2026, 2, 1), date(2026, 3, 1))],
                lambda batch, current, total: saved_batches.append(
                    (len(batch), current, total)
                ),
            )

        self.assertEqual([item.title for item in results], ["Berita Februari"])
        self.assertEqual(len(queries), 2)
        self.assertEqual(saved_batches[-1][1:], (2, 2))
        self.assertTrue(all(batch_size == 1 for batch_size, _, _ in saved_batches))
        self.assertTrue(all("after:2026-01-31" in query for query in queries))
        self.assertTrue(all("before:2026-03-01" in query for query in queries))


if __name__ == "__main__":
    unittest.main()

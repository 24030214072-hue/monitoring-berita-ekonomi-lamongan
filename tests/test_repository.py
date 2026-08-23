import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from news_monitor.models import NewsArticle, NewsCandidate
from news_monitor.repository import NewsRepository
from news_monitor.text import title_fingerprint


class NewsRepositoryTests(unittest.TestCase):
    def test_upsert_load_and_strict_year_filter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = NewsRepository(
                Path(directory) / "news.db",
                legacy_csv_path=None,
            )
            accepted = NewsArticle(
                datetime(2026, 3, 5),
                "Media A",
                "Ekonomi Lamongan tumbuh",
                "Aktivitas Ekonomi Daerah",
                "C - Industri Pengolahan",
                "Ringkasan",
                "https://example.com/2026",
                "Isi",
                "Alasan",
                "fingerprint-2026",
            )
            rejected_year = NewsArticle(
                datetime(2025, 12, 31),
                "Media B",
                "Berita lama",
                "Isu",
                "F - Konstruksi",
                "Ringkasan",
                "https://example.com/2025",
                "Isi",
                "Alasan",
                "fingerprint-2025",
            )

            self.assertEqual(repository.upsert([accepted, rejected_year]), 1)
            frame = repository.load_dataframe()
            self.assertEqual(len(frame), 1)
            self.assertEqual(frame.iloc[0]["Judul Berita"], accepted.title)

            updated = NewsArticle(
                accepted.published_at,
                accepted.media,
                accepted.title,
                "Isu diperbarui",
                accepted.sector,
                accepted.summary,
                accepted.url,
                accepted.content,
                accepted.reason,
                accepted.fingerprint,
            )
            repository.upsert([updated])
            frame = repository.load_dataframe()
            self.assertEqual(len(frame), 1)
            self.assertEqual(frame.iloc[0]["Isu Ekonomi"], "Isu diperbarui")

    def test_candidate_queue_persists_status_and_backfill_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = NewsRepository(Path(directory) / "news.db", legacy_csv_path=None)
            candidate = NewsCandidate(
                datetime(2026, 1, 10),
                "Media",
                "Harga beras Lamongan meningkat",
                "https://example.com/beras",
                "Ringkasan RSS",
            )
            february_candidate = NewsCandidate(
                datetime(2026, 2, 10),
                "Media",
                "Harga jagung Lamongan meningkat",
                "https://example.com/jagung",
                "Ringkasan RSS",
            )
            repository.upsert_candidates([candidate, february_candidate])
            january_pending = repository.pending_candidates(10, month=1)
            self.assertEqual(len(january_pending), 1)
            self.assertEqual(january_pending[0].title, candidate.title)
            self.assertEqual(repository.pending_count(month=2), 1)

            repository.mark_candidates({
                title_fingerprint(candidate.title): ("rejected", "Tidak relevan")
            })
            self.assertEqual(repository.pending_count(month=1), 0)
            self.assertEqual(repository.pending_count(month=2), 1)

            self.assertEqual(repository.discovery_month(8), 1)
            repository.advance_discovery_month(1, 8)
            self.assertEqual(repository.discovery_month(8), 2)


if __name__ == "__main__":
    unittest.main()

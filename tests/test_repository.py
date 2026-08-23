import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from news_monitor.models import NewsArticle
from news_monitor.repository import NewsRepository


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


if __name__ == "__main__":
    unittest.main()

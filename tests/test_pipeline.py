import tempfile
import unittest
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from news_monitor.classifier import NewsClassifier
from news_monitor.models import ExtractionResult, NewsArticle, NewsCandidate
from news_monitor.pipeline import NewsPipeline
from news_monitor.repository import NewsRepository


class PipelineTests(unittest.TestCase):
    def test_similar_titles_are_deduplicated(self) -> None:
        first = NewsArticle(
            datetime(2026, 1, 1), "A", "Harga cabai Lamongan naik tajam", "Isu", "Sektor",
            "Ringkasan", "https://a.example", "Isi artikel yang lebih lengkap", "Alasan", "one",
        )
        second = NewsArticle(
            datetime(2026, 1, 2), "B", "Harga cabai Lamongan naik", "Isu", "Sektor",
            "Ringkasan", "https://b.example", "Isi", "Alasan", "two",
        )
        result = NewsPipeline._deduplicate_similar([first, second])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].url, first.url)

    def test_pipeline_queues_candidates_and_does_not_repeat_accepted_article(self) -> None:
        candidate = NewsCandidate(
            datetime(2026, 1, 10),
            "Media A",
            "Harga cabai di pasar Lamongan meningkat",
            "https://example.com/cabai",
        )
        content = (
            "Harga cabai di pasar Lamongan meningkat karena pasokan dari petani menurun. "
            "Pedagang menyesuaikan harga penjualan kepada konsumen dan mencatat perubahan omzet. "
            "Distribusi komoditas pertanian tetap berjalan dari sentra produksi menuju pasar daerah. "
        )

        searched_windows: list[tuple[date, date]] = []

        class FakeDiscovery:
            def discover(
                self,
                windows: list[tuple[date, date]],
                on_batch: Callable[[list[NewsCandidate], int, int], None] | None = None,
            ) -> list[NewsCandidate]:
                searched_windows.extend(windows)
                return [candidate]

        class FakeExtractor:
            def extract(self, candidate: NewsCandidate) -> ExtractionResult:
                return ExtractionResult(candidate.url, content, True)

        with tempfile.TemporaryDirectory() as directory:
            repository = NewsRepository(Path(directory) / "news.db", legacy_csv_path=None)
            pipeline = NewsPipeline(
                repository,
                NewsClassifier(),
                discovery=FakeDiscovery(),  # type: ignore[arg-type]
                extractor=FakeExtractor(),  # type: ignore[arg-type]
            )
            first_report = pipeline.run(search_month=1)
            second_report = pipeline.run(search_month=1)

            self.assertEqual(first_report.saved, 1)
            self.assertEqual(second_report.processing, 0)
            self.assertEqual(len(repository.load_dataframe()), 1)
            self.assertTrue(
                all(
                    start == date(2026, 1, 1) and end == date(2026, 2, 1)
                    for start, end in searched_windows
                )
            )


if __name__ == "__main__":
    unittest.main()

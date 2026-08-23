import unittest
from datetime import datetime

from news_monitor.models import NewsArticle
from news_monitor.pipeline import NewsPipeline


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


if __name__ == "__main__":
    unittest.main()

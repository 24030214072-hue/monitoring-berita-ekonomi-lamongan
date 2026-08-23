import unittest

from news_monitor.classifier import NewsClassifier
from news_monitor.config import SEKTOR_BPS


class NewsClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = NewsClassifier()

    def test_accepts_lamongan_economic_news_without_gemini(self) -> None:
        result = self.classifier.classify(
            "Harga cabai di Lamongan naik",
            "Harga cabai di pasar Lamongan meningkat karena pasokan petani menurun. Pedagang menyesuaikan harga penjualan.",
        )
        self.assertTrue(result.is_economic)
        self.assertEqual(result.sector, SEKTOR_BPS[6])
        self.assertTrue(result.issue)
        self.assertTrue(result.summary)

    def test_rejects_news_without_lamongan_context(self) -> None:
        result = self.classifier.classify(
            "Harga beras nasional naik",
            "Pedagang di Jakarta menaikkan harga beras akibat distribusi yang terganggu.",
        )
        self.assertFalse(result.is_economic)

    def test_rejects_non_economic_lamongan_news(self) -> None:
        result = self.classifier.classify(
            "Pertandingan persahabatan digelar di Lamongan",
            "Para pemain mengikuti pertandingan dan latihan bersama di stadion.",
        )
        self.assertFalse(result.is_economic)


if __name__ == "__main__":
    unittest.main()

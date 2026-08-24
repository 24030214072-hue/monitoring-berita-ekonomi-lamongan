import unittest

from news_monitor.classifier import NewsClassifier
from news_monitor.config import SEKTOR_BPS


class NewsClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = NewsClassifier()

    def test_accepts_lamongan_agriculture_news_without_gemini(self) -> None:
        result = self.classifier.classify(
            "Harga cabai di Lamongan naik",
            "Harga cabai di pasar Lamongan meningkat karena pasokan petani menurun. "
            "Pedagang menyesuaikan harga penjualan.",
        )

        self.assertTrue(result.is_economic)
        self.assertEqual(result.sector, SEKTOR_BPS[0])
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

    def test_pmi_accident_is_not_agriculture(self) -> None:
        result = self.classifier.classify(
            "PMI Asal Lamongan Korban Kecelakaan Kerja Dipulangkan dari Malaysia",
            "Pekerja migran asal Lamongan menjadi korban kecelakaan kerja di Malaysia "
            "dan dipulangkan ke daerah asal dengan pendampingan pihak terkait.",
        )

        self.assertTrue(result.is_economic)
        self.assertNotEqual(
            result.sector,
            SEKTOR_BPS[0]
        )


if __name__ == "__main__":
    unittest.main()

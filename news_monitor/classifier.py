import json
import logging
import re
import time
from typing import Any, Protocol, cast

from google import genai

from .config import GEMINI_MODEL, SEKTOR_BPS
from .models import AnalysisResult
from .text import clean_text, extractive_summary, normalize_text, truncate_words

logger = logging.getLogger(__name__)


class _InteractionResponse(Protocol):
    output_text: str | None


SECTOR_RULES = {
    SEKTOR_BPS[0]: ("pertanian", "petani", "padi", "jagung", "panen", "pupuk", "perikanan", "nelayan", "ikan", "tambak", "peternakan", "ternak", "sapi"),
    SEKTOR_BPS[1]: ("tambang", "pertambangan", "galian", "mineral"),
    SEKTOR_BPS[2]: ("industri", "pabrik", "manufaktur", "pengolahan", "produksi"),
    SEKTOR_BPS[3]: ("listrik", "gas", "pln", "energi"),
    SEKTOR_BPS[4]: ("air bersih", "sampah", "limbah", "daur ulang"),
    SEKTOR_BPS[5]: ("konstruksi", "proyek", "infrastruktur", "jalan", "jembatan", "bangunan"),
    SEKTOR_BPS[6]: ("perdagangan", "pedagang", "pasar", "harga", "ritel", "penjualan", "umkm"),
    SEKTOR_BPS[7]: ("transportasi", "angkutan", "logistik", "pelabuhan", "terminal", "kereta"),
    SEKTOR_BPS[8]: ("hotel", "penginapan", "restoran", "kuliner", "wisata", "pariwisata"),
    SEKTOR_BPS[9]: ("informasi", "komunikasi", "internet", "digital", "telekomunikasi"),
    SEKTOR_BPS[10]: ("bank", "kredit", "keuangan", "asuransi", "pinjaman", "pembiayaan"),
    SEKTOR_BPS[11]: ("properti", "real estat", "perumahan"),
    SEKTOR_BPS[12]: ("jasa perusahaan", "konsultan", "persewaan"),
    SEKTOR_BPS[13]: ("pemerintah", "pemkab", "anggaran", "apbd", "pelayanan publik"),
    SEKTOR_BPS[14]: ("pendidikan", "sekolah", "kampus", "guru"),
    SEKTOR_BPS[15]: ("kesehatan", "rumah sakit", "puskesmas", "tenaga medis"),
    SEKTOR_BPS[16]: ("jasa", "hiburan", "seni", "olahraga"),
}

ISSUE_RULES = {
    "Perkembangan Harga dan Inflasi": ("harga", "inflasi", "deflasi", "mahal", "murah"),
    "Produksi dan Produktivitas": ("produksi", "produktivitas", "panen", "hasil"),
    "UMKM dan Koperasi": ("umkm", "koperasi", "usaha mikro"),
    "Investasi dan Pembangunan": ("investasi", "pembangunan", "proyek", "infrastruktur"),
    "Ketenagakerjaan": ("tenaga kerja", "pekerja", "upah", "pengangguran", "lowongan"),
    "Perdagangan dan Distribusi": ("perdagangan", "pedagang", "pasar", "distribusi", "logistik"),
    "Pertanian, Perikanan, dan Peternakan": ("pertanian", "petani", "perikanan", "nelayan", "peternakan", "ternak"),
    "Pariwisata dan Ekonomi Kreatif": ("pariwisata", "wisata", "hotel", "kuliner", "ekonomi kreatif"),
}

ECONOMIC_TERMS = {term for terms in SECTOR_RULES.values() for term in terms} | {
    "ekonomi", "pendapatan", "omzet", "ekspor", "impor", "investasi", "lapangan kerja", "daya beli"
}


class NewsClassifier:
    """Gemini enrichment with deterministic Lamongan-economic fallback."""

    def __init__(self, api_key: str | None = None, model: str = GEMINI_MODEL) -> None:
        self.model = model
        self.client = genai.Client(api_key=api_key) if api_key else None
        self.last_error = ""
        self._ai_disabled = False

    @property
    def configured(self) -> bool:
        return self.client is not None

    @property
    def ai_available(self) -> bool:
        return self.configured and not self._ai_disabled

    def classify_rules(self, title: str, content: str) -> AnalysisResult:
        return self._rules_classify(title, content)

    def classify(self, title: str, content: str) -> AnalysisResult:
        fallback = self._rules_classify(title, content)
        if not fallback.is_economic or not self.ai_available:
            return fallback
        try:
            return self._gemini_classify(title, content, fallback)
        except Exception as exc:
            self.last_error = str(exc)
            self._ai_disabled = True
            logger.warning("Gemini disabled for this run after an API error: %s", exc)
            fallback.reason = f"Klasifikasi aturan digunakan karena Gemini gagal: {exc}"
            return fallback

    def classify_many(
        self,
        articles: list[tuple[str, str]],
        batch_size: int = 8,
    ) -> list[AnalysisResult]:
        results = [
            self._rules_classify(title, content)
            for title, content in articles
        ]
        if not self.ai_available:
            return results

        eligible = [
            index
            for index, result in enumerate(results)
            if result.is_economic
        ]
        for start in range(0, len(eligible), batch_size):
            indexes = eligible[start:start + batch_size]
            try:
                batch_results = self._gemini_batch_with_retry(
                    [articles[index] for index in indexes],
                    [results[index] for index in indexes],
                )
                for index, analysis in zip(indexes, batch_results):
                    results[index] = analysis
            except Exception as exc:
                self.last_error = str(exc)
                logger.warning("Gemini batch failed; using extractive summaries: %s", exc)
                normalized_error = str(exc).casefold()
                if any(marker in normalized_error for marker in ("401", "403", "429", "quota", "rate limit")):
                    self._ai_disabled = True
                    break
        return results

    def _gemini_batch_with_retry(
        self,
        articles: list[tuple[str, str]],
        fallbacks: list[AnalysisResult],
    ) -> list[AnalysisResult]:
        for attempt in range(3):
            try:
                return self._gemini_classify_batch(articles, fallbacks)
            except Exception as exc:
                if attempt < 2 and "429" in str(exc):
                    match = re.search(r"retry in ([0-9.]+)s", str(exc), re.IGNORECASE)
                    delay = float(match.group(1)) + 1 if match else 15.0
                    logger.info("Gemini quota reached; retrying in %.1f seconds", delay)
                    time.sleep(min(delay, 65.0))
                    continue
                raise
        return fallbacks

    def _rules_classify(self, title: str, content: str) -> AnalysisResult:
        text = normalize_text(f"{title} {content}")
        if "lamongan" not in text:
            return AnalysisResult(False, reason="Berita tidak memiliki konteks Kabupaten Lamongan.")

        sector_scores = {
            sector: sum(1 for term in terms if term in text)
            for sector, terms in SECTOR_RULES.items()
        }
        sector, score = max(sector_scores.items(), key=lambda item: item[1])
        economic_hits = {term for term in ECONOMIC_TERMS if term in text}
        title_hits = {term for term in ECONOMIC_TERMS if term in normalize_text(title)}
        is_economic = score > 0 and (len(economic_hits) >= 2 or bool(title_hits))
        if not is_economic:
            return AnalysisResult(False, reason="Keterkaitan dengan kegiatan ekonomi Lamongan tidak cukup kuat.")

        issue_scores = {
            issue: sum(1 for term in terms if term in text)
            for issue, terms in ISSUE_RULES.items()
        }
        issue, issue_score = max(issue_scores.items(), key=lambda item: item[1])
        if issue_score == 0:
            issue = "Aktivitas Ekonomi Daerah"
        return AnalysisResult(
            True,
            issue=issue,
            sector=sector,
            summary=extractive_summary(title, content, 80),
            reason="Terdeteksi konteks Lamongan dan indikator aktivitas ekonomi yang relevan.",
            source="rules",
        )

    def _gemini_classify_batch(
        self,
        articles: list[tuple[str, str]],
        fallbacks: list[AnalysisResult],
    ) -> list[AnalysisResult]:
        if self.client is None:
            return fallbacks

        article_payload = [
            {
                "id": index,
                "judul": clean_text(title),
                "isi": clean_text(content)[:6000],
            }
            for index, (title, content) in enumerate(articles)
        ]
        prompt = f"""
Anda adalah analis berita ekonomi Kabupaten Lamongan. Analisis setiap artikel secara terpisah. Tentukan relevansi ekonomi, satu isu utama, tepat satu sektor resmi, dan buat ringkasan faktual 2-3 kalimat maksimal 80 kata. Ringkasan bukan salinan judul dan tidak boleh menambah fakta.

Daftar sektor:
{json.dumps(SEKTOR_BPS, ensure_ascii=False)}

Artikel:
{json.dumps(article_payload, ensure_ascii=False)}
"""
        item_schema = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "ekonomi": {"type": "boolean"},
                "isu_ekonomi": {"type": "string"},
                "sektor": {"type": "string", "enum": SEKTOR_BPS},
                "ringkasan": {"type": "string"},
                "alasan": {"type": "string"},
            },
            "required": ["id", "ekonomi", "isu_ekonomi", "sektor", "ringkasan", "alasan"],
        }
        response = self.client.interactions.create(
            model=self.model,
            input=prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": {"type": "array", "items": item_schema},
            },
        )
        payload = json.loads(cast(_InteractionResponse, response).output_text or "[]")
        by_id = {
            int(item.get("id", -1)): item
            for item in payload
            if isinstance(item, dict)
        }
        return [
            self._analysis_from_data(by_id[index], fallback)
            if index in by_id else fallback
            for index, fallback in enumerate(fallbacks)
        ]

    @staticmethod
    def _analysis_from_data(
        data: dict[str, Any],
        fallback: AnalysisResult,
    ) -> AnalysisResult:
        is_economic = data.get("ekonomi") is True
        if not is_economic:
            return AnalysisResult(
                False,
                reason=clean_text(data.get("alasan", "Ditolak oleh Gemini.")),
                source="gemini",
            )
        sector = clean_text(data.get("sektor"))
        if sector not in SEKTOR_BPS:
            sector = fallback.sector
        return AnalysisResult(
            True,
            issue=clean_text(data.get("isu_ekonomi")) or fallback.issue,
            sector=sector,
            summary=truncate_words(
                clean_text(data.get("ringkasan")) or fallback.summary,
                80,
            ),
            reason=clean_text(data.get("alasan")),
            source="gemini",
        )

    def _gemini_classify(self, title: str, content: str, fallback: AnalysisResult) -> AnalysisResult:
        prompt = f"""
Anda adalah analis berita ekonomi Kabupaten Lamongan. Tentukan apakah artikel benar-benar membahas aktivitas ekonomi Lamongan, pilih satu isu ekonomi utama, pilih tepat satu sektor dari daftar resmi, dan ringkas dalam 2-3 kalimat maksimal 80 kata. Jangan membuat fakta baru.

Daftar sektor:
{json.dumps(SEKTOR_BPS, ensure_ascii=False)}

Judul: {clean_text(title)}
Isi: {clean_text(content)[:7000]}
"""
        schema = {
            "type": "object",
            "properties": {
                "ekonomi": {"type": "boolean"},
                "isu_ekonomi": {"type": "string"},
                "sektor": {"type": "string", "enum": SEKTOR_BPS},
                "ringkasan": {"type": "string"},
                "alasan": {"type": "string"},
            },
            "required": ["ekonomi", "isu_ekonomi", "sektor", "ringkasan", "alasan"],
        }
        if self.client is None:
            return fallback

        response = self.client.interactions.create(
            model=self.model,
            input=prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": schema,
            },
        )
        data: dict[str, Any] = json.loads(
            cast(_InteractionResponse, response).output_text or "{}"
        )
        return self._analysis_from_data(data, fallback)

    def test(self, title: str, content: str) -> dict[str, object]:
        result = self.classify(title, content)
        return {
            "ekonomi": result.is_economic,
            "isu_ekonomi": result.issue,
            "sektor": result.sector,
            "ringkasan": result.summary,
            "alasan": result.reason,
            "sumber_klasifikasi": result.source,
        }

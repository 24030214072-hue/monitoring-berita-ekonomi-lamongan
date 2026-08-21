import re
import json
import time
import logging
import sqlite3
from pathlib import Path
from datetime import datetime
from urllib.parse import quote, urlparse
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor, as_completed

import streamlit as st
import pandas as pd
import requests
import feedparser
from bs4 import BeautifulSoup
import plotly.express as px

try:
    from google import genai
except ImportError:
    genai = None


# ============================================================
# PATH
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "berita_lamongan.db"
LOG_FILE = BASE_DIR / "app.log"
LOGO_FILE = BASE_DIR / "logo_bps.png"

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================
# STREAMLIT
# ============================================================

st.set_page_config(
    page_title="Monitoring Berita Ekonomi Lamongan - BPS",
    page_icon=str(LOGO_FILE) if LOGO_FILE.exists() else "📰",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
.stApp {
    background: #f6f9fc;
}

.block-container {
    padding-top: 1.2rem;
    padding-bottom: 2rem;
}

.dashboard-header {
    background: linear-gradient(135deg, #0f3b68, #1976b8);
    padding: 22px 28px;
    border-radius: 16px;
    color: white;
    margin-bottom: 20px;
    box-shadow: 0 4px 15px rgba(15,59,104,.15);
}

.dashboard-title {
    font-size: 29px;
    font-weight: 800;
    margin: 0;
}

.dashboard-subtitle {
    margin-top: 5px;
    font-size: 14px;
    color: #e7f3fb;
}

.section-header {
    font-size: 20px;
    font-weight: 750;
    color: #17324d;
    margin-top: 22px;
    margin-bottom: 12px;
    border-left: 5px solid #1976b8;
    padding-left: 10px;
}

.news-card {
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    padding: 17px;
    margin-bottom: 10px;
    box-shadow: 0 2px 7px rgba(0,0,0,.035);
}

.news-title {
    font-size: 17px;
    font-weight: 750;
    color: #102a43;
}

.news-meta {
    font-size: 12px;
    color: #64748b;
    margin-top: 5px;
}

.news-summary {
    color: #334155;
    font-size: 14px;
    line-height: 1.55;
    margin-top: 10px;
}

.small-note {
    color: #64748b;
    font-size: 12px;
}

.status-box {
    background: white;
    border: 1px solid #dbeafe;
    border-radius: 12px;
    padding: 12px;
}
</style>
""", unsafe_allow_html=True)


# ============================================================
# MASTER 17 SEKTOR BPS
# ============================================================

SECTOR_MAP = {
    "A": "A - Pertanian, Kehutanan, dan Perikanan",
    "B": "B - Pertambangan dan Penggalian",
    "C": "C - Industri Pengolahan",
    "D": "D - Pengadaan Listrik dan Gas",
    "E": "E - Pengadaan Air, Pengelolaan Sampah, Limbah dan Daur Ulang",
    "F": "F - Konstruksi",
    "G": "G - Perdagangan Besar dan Eceran; Reparasi Mobil dan Sepeda Motor",
    "H": "H - Transportasi dan Pergudangan",
    "I": "I - Penyediaan Akomodasi dan Makan Minum",
    "J": "J - Informasi dan Komunikasi",
    "K": "K - Jasa Keuangan dan Asuransi",
    "L": "L - Real Estat",
    "MN": "M,N - Jasa Perusahaan",
    "O": "O - Administrasi Pemerintahan, Pertahanan dan Jaminan Sosial Wajib",
    "P": "P - Jasa Pendidikan",
    "Q": "Q - Jasa Kesehatan dan Kegiatan Sosial",
    "RSTU": "R,S,T,U - Jasa Lainnya"
}

SEKTOR_BPS = list(SECTOR_MAP.values())


# ============================================================
# SUMBER MEDIA
# ============================================================

MEDIA_DOMAINS = {
    "ANTARA": ["antaranews.com"],
    "ANTARA Jatim": ["jatim.antaranews.com"],
    "Radar Lamongan": [
        "radarlamongan.jawapos.com",
        "radarlamongan.com"
    ],
    "Jawa Pos": ["jawapos.com"],
    "KOMPAS.com": ["kompas.com"],
    "detikJatim": ["detik.com"],
    "KlikJatim": ["klikjatim.com"],
    "BeritaJatim": ["beritajatim.com"],
    "Tribun Jatim": ["surabaya.tribunnews.com", "tribunnews.com"],
    "Jatim Times": ["jatimtimes.com"],
    "Bangsa Online": ["bangsaonline.com"],
    "Suara Surabaya": ["suarasurabaya.net"],
}

SEARCH_TOPICS = [
    "Lamongan ekonomi",
    "Kabupaten Lamongan ekonomi",
    "Lamongan UMKM",
    "Lamongan pertanian",
    "Lamongan perikanan",
    "Lamongan perdagangan",
    "Lamongan industri",
    "Lamongan investasi",
    "Lamongan pasar",
    "Lamongan harga pangan",
    "Lamongan pariwisata",
    "Lamongan peternakan",
    "Lamongan koperasi",
    "Lamongan pembangunan ekonomi",
    "Lamongan transportasi",
    "Lamongan keuangan",
    "Lamongan bisnis"
]


# ============================================================
# KONFIGURASI
# ============================================================

MAX_RESULTS_PER_TOPIC = 12
MAX_TOTAL_CANDIDATES = 150
SCRAPE_WORKERS = 8
SCRAPE_TIMEOUT = 15
MAX_CONTENT_FOR_AI = 9000

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
GEMINI_MODEL = st.secrets.get(
    "GEMINI_MODEL",
    "gemini-2.5-flash"
)

gemini_client = None

if genai is not None and GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as exc:
        logger.exception("Gemini initialization failed: %s", exc)
        gemini_client = None


# ============================================================
# HTTP SESSION
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0 Safari/537.36"
    ),
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8"
}


def make_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


# ============================================================
# DATABASE
# ============================================================

def get_connection():
    return sqlite3.connect(
        str(DB_FILE),
        check_same_thread=False,
        timeout=30
    )


def create_database():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS berita (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tanggal TEXT,
            media TEXT,
            judul TEXT,
            isu_ekonomi TEXT,
            sektor_kode TEXT,
            sektor TEXT,
            ringkasan TEXT,
            isi_berita TEXT,
            link TEXT UNIQUE,
            relevan INTEGER DEFAULT 0,
            sumber_pencarian TEXT,
            created_at TEXT
        )
    """)

    # Migrasi aman untuk database lama
    existing = {
        row[1]
        for row in cur.execute("PRAGMA table_info(berita)").fetchall()
    }

    columns = {
        "sektor_kode": "TEXT",
        "sumber_pencarian": "TEXT"
    }

    for col, dtype in columns.items():
        if col not in existing:
            cur.execute(
                f"ALTER TABLE berita ADD COLUMN {col} {dtype}"
            )

    conn.commit()
    conn.close()


create_database()


# ============================================================
# TEXT UTILITY
# ============================================================

def clean_text(text):
    if not text:
        return ""

    text = BeautifulSoup(
        str(text),
        "html.parser"
    ).get_text(" ")

    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_text(text):
    text = clean_text(text).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def title_similarity(a, b):
    a = normalize_text(a)
    b = normalize_text(b)

    if not a or not b:
        return 0.0

    return SequenceMatcher(None, a, b).ratio()


def is_lamongan_related(text):
    text = normalize_text(text)
    return "lamongan" in text


# ============================================================
# MEDIA IDENTIFICATION
# ============================================================

def identify_media(url="", source_title=""):
    """
    Media diprioritaskan dari URL artikel asli.
    Jika URL masih news.google.com, gunakan source.title dari RSS.
    """

    domain = urlparse(url).netloc.lower().replace("www.", "")

    for media, domains in MEDIA_DOMAINS.items():
        for d in domains:
            if d in domain:
                return media

    source_title = clean_text(source_title)

    if source_title:
        source_lower = source_title.lower()

        if "antara" in source_lower:
            return "ANTARA"
        if "radar lamongan" in source_lower:
            return "Radar Lamongan"
        if "kompas" in source_lower:
            return "KOMPAS.com"
        if "detik" in source_lower:
            return "detikJatim"
        if "klikjatim" in source_lower:
            return "KlikJatim"
        if "beritajatim" in source_lower:
            return "BeritaJatim"
        if "tribun" in source_lower:
            return "Tribun Jatim"
        if "jawapos" in source_lower:
            return "Jawa Pos"

        return source_title

    return "Media tidak teridentifikasi"


# ============================================================
# TANGGAL
# ============================================================

MONTHS_ID = {
    "januari": "01",
    "februari": "02",
    "maret": "03",
    "april": "04",
    "mei": "05",
    "juni": "06",
    "juli": "07",
    "agustus": "08",
    "september": "09",
    "oktober": "10",
    "november": "11",
    "desember": "12"
}


def parse_date(value):
    if not value:
        return ""

    value = clean_text(value)

    for month, number in MONTHS_ID.items():
        value = re.sub(
            rf"(\d{{1,2}})\s+{month}\s+(\d{{4}})",
            rf"\1-{number}-\2",
            value,
            flags=re.I
        )

    dt = pd.to_datetime(
        value,
        errors="coerce",
        dayfirst=True
    )

    if pd.isna(dt):
        return ""

    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# GOOGLE NEWS RSS DISCOVERY
# ============================================================

def google_news_search(query):
    url = (
        "https://news.google.com/rss/search?"
        f"q={quote(query)}"
        "&hl=id&gl=ID&ceid=ID:id"
    )

    try:
        session = make_session()
        response = session.get(
            url,
            timeout=15
        )
        response.raise_for_status()

        feed = feedparser.parse(response.content)
        results = []

        for item in feed.entries[:MAX_RESULTS_PER_TOPIC]:

            source = item.get("source", {})
            source_title = ""

            if isinstance(source, dict):
                source_title = source.get("title", "")
            else:
                source_title = getattr(
                    source,
                    "title",
                    ""
                )

            results.append({
                "rss_title": clean_text(
                    item.get("title", "")
                ),
                "rss_link": item.get(
                    "link",
                    ""
                ),
                "rss_date": item.get(
                    "published",
                    ""
                ),
                "rss_summary": clean_text(
                    item.get("summary", "")
                ),
                "source_title": clean_text(
                    source_title
                ),
                "query": query
            })

        return results

    except Exception as exc:
        logger.exception(
            "Google RSS failed for %s: %s",
            query,
            exc
        )
        return []


def collect_candidates():
    all_items = []

    with ThreadPoolExecutor(
        max_workers=8
    ) as executor:

        futures = {
            executor.submit(
                google_news_search,
                query
            ): query
            for query in SEARCH_TOPICS
        }

        for future in as_completed(futures):

            query = futures[future]

            try:
                items = future.result()
                all_items.extend(items)
            except Exception as exc:
                logger.exception(
                    "Candidate collection failed: %s",
                    exc
                )

    # Deduplicate RSS link / title
    unique = {}
    for item in all_items:

        key = (
            normalize_text(item["rss_title"]),
            item["source_title"]
        )

        if key not in unique:
            unique[key] = item

    candidates = list(unique.values())

    # Batasi total
    return candidates[:MAX_TOTAL_CANDIDATES]


# ============================================================
# RESOLVE URL GOOGLE NEWS -> ARTIKEL ASLI
# ============================================================

def resolve_article_url(rss_link):
    if not rss_link:
        return ""

    try:
        # Jika bukan Google News, langsung gunakan
        domain = urlparse(
            rss_link
        ).netloc.lower()

        if "news.google.com" not in domain:
            return rss_link

        session = make_session()

        response = session.get(
            rss_link,
            timeout=12,
            allow_redirects=True
        )

        final_url = response.url

        final_domain = urlparse(
            final_url
        ).netloc.lower()

        if (
            final_url
            and "news.google.com" not in final_domain
        ):
            return final_url

        # Beberapa URL Google News mengandung parameter url
        parsed = urlparse(rss_link)
        params = parse_qs(parsed.query)

        for key in ("url", "u"):
            if key in params:
                possible = params[key][0]
                if possible.startswith("http"):
                    return unquote(possible)

    except Exception as exc:
        logger.warning(
            "Resolve URL failed: %s",
            exc
        )

    return rss_link


# ============================================================
# EXTRACT ARTICLE
# ============================================================

def extract_jsonld_article(soup):
    texts = []

    for script in soup.find_all(
        "script",
        type="application/ld+json"
    ):

        raw = script.string or script.get_text()

        try:
            data = json.loads(raw)
        except Exception:
            continue

        objects = data if isinstance(data, list) else [data]

        for obj in objects:

            if not isinstance(obj, dict):
                continue

            graph = obj.get("@graph")

            if isinstance(graph, list):
                objects.extend(
                    x for x in graph
                    if isinstance(x, dict)
                )

            article_type = str(
                obj.get("@type", "")
            ).lower()

            if (
                "article" in article_type
                or "newsarticle" in article_type
            ):

                body = obj.get("articleBody", "")

                if body:
                    texts.append(
                        clean_text(body)
                    )

    return " ".join(texts)


def extract_article(url):
    """
    Ekstraksi dibuat berlapis:
    1. JSON-LD articleBody
    2. <article>
    3. <main>
    4. paragraf
    5. meta description
    """

    result = {
        "url": url,
        "judul": "",
        "tanggal": "",
        "isi": "",
        "description": ""
    }

    if not url:
        return result

    try:
        session = make_session()

        response = session.get(
            url,
            timeout=SCRAPE_TIMEOUT,
            allow_redirects=True
        )

        response.raise_for_status()

        final_url = response.url
        result["url"] = final_url

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # Hapus elemen yang bukan isi artikel
        for tag in soup.find_all([
            "script",
            "style",
            "noscript",
            "nav",
            "footer",
            "header",
            "aside",
            "form"
        ]):
            tag.decompose()

        # Judul
        og_title = soup.find(
            "meta",
            property="og:title"
        )

        h1 = soup.find("h1")

        title = ""

        if og_title and og_title.get("content"):
            title = og_title["content"]
        elif h1:
            title = h1.get_text(" ")
        elif soup.title:
            title = soup.title.get_text(" ")

        result["judul"] = clean_text(title)

        # Description
        description = ""

        meta_desc = soup.find(
            "meta",
            attrs={"name": "description"}
        )

        og_desc = soup.find(
            "meta",
            property="og:description"
        )

        if meta_desc:
            description = meta_desc.get("content", "")
        elif og_desc:
            description = og_desc.get("content", "")

        result["description"] = clean_text(
            description
        )

        # Tanggal
        date_candidates = [
            soup.find(
                "meta",
                property="article:published_time"
            ),
            soup.find(
                "meta",
                property="article:modified_time"
            ),
            soup.find(
                "meta",
                attrs={"name": "date"}
            ),
            soup.find(
                "meta",
                attrs={"name": "pubdate"}
            ),
            soup.find(
                "time"
            )
        ]

        for tag in date_candidates:

            if not tag:
                continue

            value = (
                tag.get("content")
                or tag.get("datetime")
                or tag.get_text(" ")
            )

            parsed = parse_date(value)

            if parsed:
                result["tanggal"] = parsed
                break

        # JSON-LD
        jsonld_text = extract_jsonld_article(
            soup
        )

        # Article tag
        article_text = ""

        article = soup.find("article")

        if article:
            article_text = clean_text(
                article.get_text(" ")
            )

        # Main
        main_text = ""

        main = soup.find("main")

        if main:
            main_text = clean_text(
                main.get_text(" ")
            )

        # Paragraphs
        paragraphs = []

        for p in soup.find_all("p"):

            text = clean_text(
                p.get_text(" ")
            )

            if len(text) >= 35:
                paragraphs.append(text)

        # Remove duplicate paragraphs
        seen = set()
        unique_paragraphs = []

        for p in paragraphs:

            key = normalize_text(p)

            if key and key not in seen:
                seen.add(key)
                unique_paragraphs.append(p)

        paragraph_text = " ".join(
            unique_paragraphs
        )

        # Pilih teks paling kaya
        candidates = [
            jsonld_text,
            article_text,
            main_text,
            paragraph_text
        ]

        candidates = [
            x for x in candidates
            if len(x) > 100
        ]

        if candidates:
            content = max(
                candidates,
                key=len
            )
        else:
            content = result["description"]

        # Buang bagian terlalu umum jika perlu
        content = re.sub(
            r"\s+",
            " ",
            content
        ).strip()

        result["isi"] = content[:20000]

        # Jika judul kosong, gunakan RSS nantinya
        return result

    except Exception as exc:

        logger.warning(
            "Article extraction failed %s: %s",
            url,
            exc
        )

        return result


# ============================================================
# AI PROMPT
# ============================================================

def build_ai_prompt(
    title,
    media,
    content
):

    sectors = "\n".join(
        f"- {code}: {name}"
        for code, name in SECTOR_MAP.items()
    )

    return f"""
Kamu adalah analis berita ekonomi BPS Kabupaten Lamongan.

Baca dan pahami ISI BERITA secara keseluruhan.
JANGAN menentukan hasil hanya dari judul.

JUDUL:
{title}

MEDIA:
{media}

ISI BERITA:
{content[:MAX_CONTENT_FOR_AI]}

TUGAS:

1. Tentukan apakah berita berkaitan dengan ekonomi,
   pembangunan ekonomi, kegiatan usaha, perdagangan,
   pertanian, perikanan, industri, investasi,
   UMKM, jasa, transportasi, keuangan, pariwisata,
   atau aktivitas ekonomi lain yang terjadi di
   Kabupaten Lamongan.

2. Jika bukan berita ekonomi Kabupaten Lamongan,
   "relevan" = false.

3. Jika relevan, tentukan ISU EKONOMI yang spesifik
   sesuai pokok isi berita.

   JANGAN selalu menggunakan "Ekonomi Umum".
   Buat isu yang benar-benar menggambarkan isi berita.

   Contoh:
   - Perkembangan UMKM
   - Produksi pertanian
   - Harga pangan
   - Distribusi hasil pertanian
   - Perdagangan dan pasar
   - Investasi daerah
   - Industri pengolahan
   - Perikanan
   - Peternakan
   - Pariwisata
   - Ketenagakerjaan
   - Infrastruktur ekonomi
   - Pendapatan daerah
   - Keuangan daerah
   - Transportasi dan logistik
   - Koperasi
   - Pembangunan ekonomi daerah

4. Tentukan TEPAT SATU sektor lapangan usaha BPS
   berdasarkan ISI BERITA.

SEKTOR:

{sectors}

5. Keluarkan kode sektor yang tepat.

6. Buat ringkasan 2-3 kalimat berdasarkan ISI BERITA.
   Jangan hanya mengulang judul.
   Jika tersedia, pertahankan angka, lokasi,
   pelaku, nilai transaksi, produksi, kebijakan,
   atau dampak ekonomi penting.

7. Jika bukan ekonomi, berikan alasan singkat.

KELUARKAN HANYA JSON VALID:

{{
    "relevan": true,
    "isu_ekonomi": "isu yang spesifik",
    "sektor_kode": "G",
    "sektor": "G - Perdagangan Besar dan Eceran; Reparasi Mobil dan Sepeda Motor",
    "ringkasan": "Ringkasan berdasarkan isi berita.",
    "alasan": "Alasan klasifikasi."
}}
"""


# ============================================================
# GEMINI ANALYSIS
# ============================================================

def normalize_sector(result):
    code = clean_text(
        result.get("sektor_kode", "")
    ).upper()

    sector_text = clean_text(
        result.get("sektor", "")
    )

    # 1. Kode paling diutamakan
    if code in SECTOR_MAP:
        return code, SECTOR_MAP[code]

    # 2. Coba ambil kode dari sektor
    upper_text = sector_text.upper()

    for valid_code, valid_name in SECTOR_MAP.items():

        if upper_text.startswith(
            valid_code + " -"
        ) or upper_text.startswith(
            valid_code + ","
        ):

            return valid_code, valid_name

    # 3. Cocokkan nama
    for valid_code, valid_name in SECTOR_MAP.items():

        if (
            normalize_text(valid_name)
            == normalize_text(sector_text)
        ):
            return valid_code, valid_name

    return "", "Tidak teridentifikasi"


def analyze_with_gemini(
    title,
    media,
    content
):

    if not content or len(content) < 80:

        return {
            "relevan": False,
            "isu_ekonomi": "Isi berita tidak cukup",
            "sektor_kode": "",
            "sektor": "Tidak teridentifikasi",
            "ringkasan": "",
            "alasan": "Isi artikel tidak berhasil diperoleh."
        }

    if gemini_client is None:

        return {
            "relevan": False,
            "isu_ekonomi": "Gemini belum terkonfigurasi",
            "sektor_kode": "",
            "sektor": "Tidak teridentifikasi",
            "ringkasan": "",
            "alasan": "GEMINI_API_KEY belum tersedia."
        }

    prompt = build_ai_prompt(
        title,
        media,
        content
    )

    try:

        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )

        text = (
            response.text
            if response and response.text
            else ""
        ).strip()

        # Bersihkan code fence
        text = re.sub(
            r"^```json\s*",
            "",
            text,
            flags=re.I
        )

        text = re.sub(
            r"^```\s*",
            "",
            text
        )

        text = re.sub(
            r"\s*```$",
            "",
            text
        ).strip()

        # Ambil blok JSON jika ada teks tambahan
        match = re.search(
            r"\{.*\}",
            text,
            flags=re.S
        )

        if match:
            text = match.group(0)

        result = json.loads(text)

        sector_code, sector_name = normalize_sector(
            result
        )

        relevant = bool(
            result.get(
                "relevan",
                False
            )
        )

        issue = clean_text(
            result.get(
                "isu_ekonomi",
                ""
            )
        )

        summary = clean_text(
            result.get(
                "ringkasan",
                ""
            )
        )

        reason = clean_text(
            result.get(
                "alasan",
                ""
            )
        )

        # Jangan biarkan isu menjadi ekonomi umum
        if (
            relevant
            and (
                not issue
                or normalize_text(issue)
                in {
                    "ekonomi umum",
                    "ekonomi",
                    "aktivitas ekonomi"
                }
            )
        ):
            issue = "Isu ekonomi belum teridentifikasi secara spesifik"

        return {
            "relevan": relevant,
            "isu_ekonomi": issue,
            "sektor_kode": sector_code,
            "sektor": sector_name,
            "ringkasan": summary,
            "alasan": reason
        }

    except Exception as exc:

        logger.exception(
            "Gemini analysis failed: %s",
            exc
        )

        return {
            "relevan": False,
            "isu_ekonomi": "Analisis AI gagal",
            "sektor_kode": "",
            "sektor": "Tidak teridentifikasi",
            "ringkasan": "",
            "alasan": str(exc)
        }


# ============================================================
# DEDUPLICATION
# ============================================================

def is_duplicate_against_db(
    title,
    content,
    link
):

    conn = get_connection()

    rows = conn.execute(
        """
        SELECT judul, isi_berita, link
        FROM berita
        """
    ).fetchall()

    conn.close()

    norm_title = normalize_text(title)

    for old_title, old_content, old_link in rows:

        if link and old_link == link:
            return True

        if (
            norm_title
            and title_similarity(
                title,
                old_title
            ) >= 0.93
        ):
            return True

        if content and old_content:

            a = normalize_text(content[:5000])
            b = normalize_text(old_content[:5000])

            if (
                len(a) > 200
                and len(b) > 200
                and SequenceMatcher(
                    None,
                    a,
                    b
                ).ratio() >= 0.88
            ):
                return True

    return False


def deduplicate_batch(items):

    kept = []

    for item in items:

        duplicate = False

        for old in kept:

            if (
                title_similarity(
                    item["judul"],
                    old["judul"]
                ) >= 0.93
            ):
                duplicate = True
                break

            a = normalize_text(
                item["isi_berita"][:4000]
            )

            b = normalize_text(
                old["isi_berita"][:4000]
            )

            if (
                len(a) > 250
                and len(b) > 250
                and SequenceMatcher(
                    None,
                    a,
                    b
                ).ratio() >= 0.88
            ):
                duplicate = True
                break

        if not duplicate:
            kept.append(item)

    return kept


# ============================================================
# SAVE
# ============================================================

def save_news(news):

    conn = get_connection()

    try:

        conn.execute(
            """
            INSERT OR IGNORE INTO berita
            (
                tanggal,
                media,
                judul,
                isu_ekonomi,
                sektor_kode,
                sektor,
                ringkasan,
                isi_berita,
                link,
                relevan,
                sumber_pencarian,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                news.get("tanggal", ""),
                news.get("media", ""),
                news.get("judul", ""),
                news.get("isu_ekonomi", ""),
                news.get("sektor_kode", ""),
                news.get("sektor", ""),
                news.get("ringkasan", ""),
                news.get("isi_berita", ""),
                news.get("link", ""),
                1 if news.get("relevan") else 0,
                news.get("sumber_pencarian", ""),
                datetime.now().isoformat()
            )
        )

        conn.commit()

    except Exception as exc:
        logger.exception(
            "Database save failed: %s",
            exc
        )

    finally:
        conn.close()


# ============================================================
# LOAD DATABASE
# ============================================================

def load_database():

    conn = get_connection()

    df = pd.read_sql_query(
        """
        SELECT
            id,
            tanggal,
            media,
            judul,
            isu_ekonomi,
            sektor_kode,
            sektor,
            ringkasan,
            link,
            sumber_pencarian,
            created_at
        FROM berita
        WHERE relevan = 1
        ORDER BY id DESC
        """,
        conn
    )

    conn.close()

    # Pastikan nama kolom dashboard konsisten
    rename_map = {
        "tanggal": "Tanggal Berita",
        "media": "Media",
        "judul": "Judul Berita",
        "isu_ekonomi": "Isu Ekonomi",
        "sektor_kode": "Kode Sektor",
        "sektor": "Sektor",
        "ringkasan": "Ringkasan Berita",
        "link": "Link Berita",
        "sumber_pencarian": "Kata Kunci"
    }

    df = df.rename(
        columns=rename_map
    )

    if "Tanggal Berita" in df.columns:
        df["Tanggal Berita"] = pd.to_datetime(
            df["Tanggal Berita"],
            errors="coerce"
        )

    return df


# ============================================================
# PROCESS ONE CANDIDATE
# ============================================================

def process_candidate(item):

    rss_title = item.get(
        "rss_title",
        ""
    )

    rss_link = item.get(
        "rss_link",
        ""
    )

    source_title = item.get(
        "source_title",
        ""
    )

    rss_date = item.get(
        "rss_date",
        ""
    )

    rss_summary = item.get(
        "rss_summary",
        ""
    )

    query = item.get(
        "query",
        ""
    )

    # Resolve Google News -> URL asli
    original_url = resolve_article_url(
        rss_link
    )

    article = extract_article(
        original_url
    )

    final_url = article.get(
        "url",
        ""
    ) or original_url

    # Media dari URL asli, fallback source RSS
    media = identify_media(
        final_url,
        source_title
    )

    title = (
        article.get("judul", "")
        or rss_title
    )

    content = (
        article.get("isi", "")
        or rss_summary
    )

    date = (
        article.get("tanggal", "")
        or parse_date(rss_date)
    )

    # Hanya target Lamongan
    combined = (
        f"{title} {content}"
    )

    if not is_lamongan_related(
        combined
    ):
        return None

    # Jangan menyimpan link Google News
    final_domain = urlparse(
        final_url
    ).netloc.lower()

    if (
        "news.google.com" in final_domain
        and media == "Media tidak teridentifikasi"
    ):
        return None

    # Analisis Gemini
    ai = analyze_with_gemini(
        title,
        media,
        content
    )

    if not ai["relevan"]:
        return None

    if not ai["sektor"]:
        return None

    if not ai["ringkasan"]:
        # Ringkasan kosong tidak boleh membuat
        # berita ekonomi dibuang.
        ai["ringkasan"] = (
            content[:500]
            if content
            else title
        )

    return {
        "tanggal": date,
        "media": media,
        "judul": title,
        "isu_ekonomi": ai["isu_ekonomi"],
        "sektor_kode": ai["sektor_kode"],
        "sektor": ai["sektor"],
        "ringkasan": ai["ringkasan"],
        "isi_berita": content,
        "link": final_url,
        "relevan": True,
        "sumber_pencarian": query
    }


# ============================================================
# FULL SCRAPING + AI PIPELINE
# ============================================================

def run_collection():

    if gemini_client is None:

        st.error(
            "Gemini API belum aktif. "
            "Tambahkan GEMINI_API_KEY di Streamlit Secrets."
        )

        return

    st.info(
        "🔎 Tahap 1/4 — mencari kandidat berita..."
    )

    candidates = collect_candidates()

    if not candidates:

        st.error(
            "Tidak ada kandidat berita yang ditemukan. "
            "Periksa koneksi atau sumber pencarian."
        )

        return

    st.success(
        f"Berhasil menemukan {len(candidates)} kandidat berita."
    )

    st.info(
        "🌐 Tahap 2/4 — membuka artikel dari media asli..."
    )

    results = []
    failed_scrape = 0
    progress = st.progress(0)

    total = len(candidates)

    with ThreadPoolExecutor(
        max_workers=SCRAPE_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                process_candidate,
                item
            )
            for item in candidates
        ]

        for i, future in enumerate(
            as_completed(futures),
            start=1
        ):

            try:

                result = future.result()

                if result:
                    results.append(result)
                else:
                    failed_scrape += 1

            except Exception as exc:

                failed_scrape += 1

                logger.exception(
                    "Candidate processing failed: %s",
                    exc
                )

            progress.progress(
                i / total
            )

    progress.empty()

    st.info(
        "🧹 Tahap 3/4 — menghapus berita duplikat..."
    )

    results = deduplicate_batch(
        results
    )

    saved = 0

    st.info(
        "💾 Tahap 4/4 — menyimpan hasil ke SQLite..."
    )

    for result in results:

        try:

            if not is_duplicate_against_db(
                result["judul"],
                result["isi_berita"],
                result["link"]
            ):
                save_news(result)
                saved += 1

        except Exception as exc:
            logger.exception(
                "Save pipeline failed: %s",
                exc
            )

    st.success(
        f"✅ Selesai. {saved} berita ekonomi baru disimpan."
    )

    st.caption(
        f"Kandidat: {len(candidates)} | "
        f"Lolos analisis: {len(results)} | "
        f"Gagal/tidak relevan: {failed_scrape}"
    )


# ============================================================
# HEADER
# ============================================================

logo_html = ""

if LOGO_FILE.exists():

    import base64

    encoded = base64.b64encode(
        LOGO_FILE.read_bytes()
    ).decode()

    logo_html = (
        f'<img src="data:image/png;base64,{encoded}" '
        'style="height:65px;float:left;margin-right:18px;">'
    )

st.markdown(
    f"""
    <div class="dashboard-header">
        {logo_html}
        <div>
            <div class="dashboard-title">
                MONITORING BERITA EKONOMI
                KABUPATEN LAMONGAN
            </div>
            <div class="dashboard-subtitle">
                Pemantauan berita • Web Scraping • Gemini AI • SQLite
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True
)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.markdown("## ⚙️ Pengaturan")

    if st.button(
        "🔄 Ambil Berita Terbaru",
        use_container_width=True
    ):

        run_collection()
        st.rerun()

    st.divider()

    st.markdown("### 🔐 Status Gemini")

    if gemini_client is not None:
        st.success("Gemini API aktif")
    else:
        st.error("Gemini API belum aktif")

    st.markdown(
        '<div class="small-note">'
        'Google News hanya digunakan sebagai mesin pencari kandidat. '
        'Media dan artikel diprioritaskan dari sumber asli.'
        '</div>',
        unsafe_allow_html=True
    )

    st.divider()

    conn = get_connection()

    total_db = conn.execute(
        "SELECT COUNT(*) FROM berita"
    ).fetchone()[0]

    total_economy = conn.execute(
        "SELECT COUNT(*) FROM berita WHERE relevan=1"
    ).fetchone()[0]

    conn.close()

    st.metric(
        "📰 Database",
        f"{total_db:,}"
    )

    st.metric(
        "📊 Berita Ekonomi",
        f"{total_economy:,}"
    )


# ============================================================
# LOAD DATA
# ============================================================

df = load_database()


if df.empty:

    st.info(
        "📭 Database belum memiliki berita ekonomi. "
        "Klik **Ambil Berita Terbaru**."
    )

    st.stop()


# ============================================================
# DATE NORMALIZATION
# ============================================================

df["Tanggal Berita"] = pd.to_datetime(
    df["Tanggal Berita"],
    errors="coerce"
)

# Salinan untuk grafik
df_chart = df.dropna(
    subset=["Tanggal Berita"]
).copy()


# ============================================================
# KPI
# ============================================================

today = pd.Timestamp(
    datetime.now().date()
)

today_count = int(
    (
        df["Tanggal Berita"]
        .dt.normalize()
        == today
    ).sum()
)

media_count = df["Media"].nunique()

sector_count = df["Sektor"].nunique()

issue_count = df["Isu Ekonomi"].nunique()


k1, k2, k3, k4 = st.columns(4)

k1.metric(
    "📰 Total Berita",
    f"{len(df):,}"
)

k2.metric(
    "📅 Berita Hari Ini",
    f"{today_count:,}"
)

k3.metric(
    "🌐 Media",
    f"{media_count:,}"
)

k4.metric(
    "🏭 Sektor",
    f"{sector_count:,}"
)


# ============================================================
# FILTER
# ============================================================

st.markdown(
    '<div class="section-header">🔎 Filter Berita</div>',
    unsafe_allow_html=True
)

f1, f2, f3 = st.columns(3)

with f1:

    media_options = [
        "Semua Media"
    ] + sorted(
        df["Media"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    selected_media = st.selectbox(
        "Media",
        media_options
    )


with f2:

    sector_options = [
        "Semua Sektor"
    ] + [
        x for x in SEKTOR_BPS
        if x in set(
            df["Sektor"].dropna()
        )
    ]

    selected_sector = st.selectbox(
        "Sektor Lapangan Usaha",
        sector_options
    )


with f3:

    keyword = st.text_input(
        "Kata kunci",
        placeholder="Contoh: UMKM, padi, pasar, investasi..."
    )


f4, f5 = st.columns(2)

with f4:

    date_min = (
        df["Tanggal Berita"]
        .min()
    )

    date_max = (
        df["Tanggal Berita"]
        .max()
    )

    if pd.notna(date_min) and pd.notna(date_max):

        date_range = st.date_input(
            "Rentang tanggal",
            value=(
                date_min.date(),
                date_max.date()
            )
        )

    else:

        date_range = None


with f5:

    issue_options = [
        "Semua Isu"
    ] + sorted(
        df["Isu Ekonomi"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    selected_issue = st.selectbox(
        "Isu Ekonomi",
        issue_options
    )


# ============================================================
# APPLY FILTER
# ============================================================

filtered = df.copy()

if selected_media != "Semua Media":

    filtered = filtered[
        filtered["Media"]
        == selected_media
    ]

if selected_sector != "Semua Sektor":

    filtered = filtered[
        filtered["Sektor"]
        == selected_sector
    ]

if selected_issue != "Semua Isu":

    filtered = filtered[
        filtered["Isu Ekonomi"]
        == selected_issue
    ]

if keyword:

    search_cols = [
        "Judul Berita",
        "Ringkasan Berita",
        "Isu Ekonomi",
        "Media",
        "Sektor"
    ]

    mask = pd.Series(
        False,
        index=filtered.index
    )

    for col in search_cols:

        mask = (
            mask
            | filtered[col]
            .fillna("")
            .astype(str)
            .str.contains(
                keyword,
                case=False,
                na=False
            )
        )

    filtered = filtered[mask]

if (
    date_range
    and isinstance(date_range, tuple)
    and len(date_range) == 2
):

    start_date = pd.Timestamp(
        date_range[0]
    )

    end_date = (
        pd.Timestamp(date_range[1])
        + pd.Timedelta(days=1)
        - pd.Timedelta(seconds=1)
    )

    filtered = filtered[
        (
            filtered["Tanggal Berita"]
            >= start_date
        )
        &
        (
            filtered["Tanggal Berita"]
            <= end_date
        )
    ]


# ============================================================
# TREN
# ============================================================

st.markdown(
    '<div class="section-header">📈 Tren Monitoring Berita</div>',
    unsafe_allow_html=True
)

if not df_chart.empty:

    daily = (
        df_chart
        .assign(
            Tanggal=df_chart[
                "Tanggal Berita"
            ].dt.date
        )
        .groupby("Tanggal")
        .size()
        .reset_index(
            name="Jumlah Berita"
        )
    )

    fig_daily = px.line(
        daily,
        x="Tanggal",
        y="Jumlah Berita",
        markers=True,
        title="Tren Jumlah Berita Ekonomi Harian"
    )

    fig_daily.update_layout(
        margin=dict(l=20, r=20, t=50, b=20)
    )

    st.plotly_chart(
        fig_daily,
        use_container_width=True
    )


    weekly = (
        df_chart
        .set_index("Tanggal Berita")
        .resample("W")
        .size()
        .reset_index(
            name="Jumlah Berita"
        )
    )

    fig_weekly = px.bar(
        weekly,
        x="Tanggal Berita",
        y="Jumlah Berita",
        title="Tren Berita Ekonomi Mingguan"
    )

    st.plotly_chart(
        fig_weekly,
        use_container_width=True
    )


    monthly = (
        df_chart
        .set_index("Tanggal Berita")
        .resample("MS")
        .size()
        .reset_index(
            name="Jumlah Berita"
        )
    )

    fig_monthly = px.line(
        monthly,
        x="Tanggal Berita",
        y="Jumlah Berita",
        markers=True,
        title="Tren Berita Ekonomi Bulanan"
    )

    st.plotly_chart(
        fig_monthly,
        use_container_width=True
    )


# ============================================================
# DISTRIBUSI MEDIA + SEKTOR
# ============================================================

c1, c2 = st.columns(2)

with c1:

    media_count_df = (
        filtered
        .groupby("Media")
        .size()
        .reset_index(
            name="Jumlah"
        )
        .sort_values(
            "Jumlah",
            ascending=False
        )
    )

    fig_media = px.bar(
        media_count_df,
        x="Jumlah",
        y="Media",
        orientation="h",
        title="Berita Berdasarkan Media"
    )

    st.plotly_chart(
        fig_media,
        use_container_width=True
    )


with c2:

    sector_count_df = (
        filtered
        .groupby("Sektor")
        .size()
        .reset_index(
            name="Jumlah"
        )
        .sort_values(
            "Jumlah",
            ascending=False
        )
    )

    fig_sector = px.bar(
        sector_count_df,
        x="Jumlah",
        y="Sektor",
        orientation="h",
        title="Berita Berdasarkan Sektor Lapangan Usaha"
    )

    st.plotly_chart(
        fig_sector,
        use_container_width=True
    )


# ============================================================
# ISU EKONOMI
# ============================================================

issue_count_df = (
    filtered
    .groupby("Isu Ekonomi")
    .size()
    .reset_index(
        name="Jumlah"
    )
    .sort_values(
        "Jumlah",
        ascending=False
    )
    .head(15)
)

fig_issue = px.bar(
    issue_count_df,
    x="Jumlah",
    y="Isu Ekonomi",
    orientation="h",
    title="15 Isu Ekonomi yang Paling Banyak Diberitakan"
)

st.plotly_chart(
    fig_issue,
    use_container_width=True
)


# ============================================================
# DAFTAR BERITA
# ============================================================

st.markdown(
    f"""
    <div class="section-header">
        📰 Berita Ekonomi ({len(filtered):,})
    </div>
    """,
    unsafe_allow_html=True
)

if filtered.empty:

    st.warning(
        "Tidak ada berita yang sesuai dengan filter."
    )

else:

    for _, row in filtered.iterrows():

        tanggal = row["Tanggal Berita"]

        if pd.notna(tanggal):
            tanggal_text = tanggal.strftime(
                "%d-%m-%Y"
            )
        else:
            tanggal_text = "-"

        st.markdown(
            f"""
            <div class="news-card">

                <div class="news-title">
                    {row["Judul Berita"]}
                </div>

                <div class="news-meta">
                    📅 {tanggal_text}
                    &nbsp; | &nbsp;
                    🌐 {row["Media"]}
                </div>

                <div class="news-meta">
                    🏭 {row["Sektor"]}
                </div>

                <div class="news-meta">
                    💡 <b>Isu:</b>
                    {row["Isu Ekonomi"]}
                </div>

                <div class="news-summary">
                    {row["Ringkasan Berita"]}
                </div>

            </div>
            """,
            unsafe_allow_html=True
        )

        if row["Link Berita"]:

            st.link_button(
                "🔗 Baca Artikel Asli",
                row["Link Berita"]
            )

        st.divider()


# ============================================================
# EXPORT
# ============================================================

st.markdown(
    '<div class="section-header">📥 Ekspor Data</div>',
    unsafe_allow_html=True
)

export_df = filtered.copy()

export_df["Tanggal Berita"] = (
    export_df["Tanggal Berita"]
    .dt.strftime("%Y-%m-%d")
)

export_cols = [
    "Tanggal Berita",
    "Media",
    "Judul Berita",
    "Isu Ekonomi",
    "Kode Sektor",
    "Sektor",
    "Ringkasan Berita",
    "Link Berita"
]

export_df = export_df[
    [
        c for c in export_cols
        if c in export_df.columns
    ]
]

csv_data = export_df.to_csv(
    index=False,
    encoding="utf-8-sig"
)

st.download_button(
    "⬇️ Download Data CSV",
    data=csv_data,
    file_name="monitoring_berita_ekonomi_lamongan.csv",
    mime="text/csv",
    use_container_width=True
)


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Dashboard Monitoring Berita Ekonomi Kabupaten Lamongan | "
    "Web Scraping + Gemini AI + SQLite"
)

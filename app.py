import re
import time
import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from urllib.parse import quote, urlparse, urljoin
from difflib import SequenceMatcher
import io
import base64

import streamlit as st
import pandas as pd
import sqlite3
import feedparser
import requests
from bs4 import BeautifulSoup
import plotly.express as px
from google import genai
from concurrent.futures import ThreadPoolExecutor, as_completed
import os

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"


# ============================================================
# 📌 SETUP FILE PATHS & LOGO BPS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "berita_lamongan.csv"
REJECTED_FILE = BASE_DIR / "berita_ditolak.csv"
LOG_FILE = BASE_DIR / "app.log"

BPS_LOGO = BASE_DIR / "logo_bps.png"
BPS_LOGO_URL = str(BPS_LOGO)

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ============================================================
# ⚙️ KONFIGURASI STREAMLIT
# ============================================================

st.set_page_config(
    page_title="Monitoring Berita Ekonomi Lamongan - BPS",
    page_icon=BPS_LOGO_URL if BPS_LOGO.exists() else "📰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
main { background-color: #f8fafc; }
.block-container { padding-top: 1.5rem; padding-bottom: 2rem; }

[data-testid="stElementToolbar"] button[title="Download as CSV"],
[data-testid="stElementToolbar"] button[aria-label="Download as CSV"],
[data-testid="stElementToolbar"] button:has(svg path[d*="M19 9h-4V3H9v6H5l7 7 7-7"]) {
    display: none !important;
}

.dashboard-header {
    background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
    padding: 22px 28px;
    border-radius: 16px;
    color: white;
    margin-bottom: 25px;
    box-shadow: 0 4px 12px rgba(30, 58, 138, 0.15);
    display: flex;
    align-items: center;
    gap: 20px;
}
.dashboard-logo {
    width: 75px;
    height: 75px;
    object-fit: contain;
    background: white;
    padding: 8px;
    border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    flex-shrink: 0;
}
.dashboard-title { font-size: 26px; font-weight: 800; margin: 0; color: white; }
.dashboard-subtitle { font-size: 14px; color: #e0f2fe; margin-top: 7px; }

.section-header {
    font-size: 18px;
    font-weight: 700;
    color: #1e293b;
    margin-top: 15px;
    margin-bottom: 15px;
    border-left: 4px solid #2563eb;
    padding-left: 10px;
}
</style>
""", unsafe_allow_html=True)

# ============================================================
# DATABASE
# ============================================================

DB_NAME = "berita_lamongan.db"


def get_connection():

    conn = sqlite3.connect(
        DB_NAME,
        check_same_thread=False
    )

    return conn


def create_database():

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS berita (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            tanggal TEXT,
            media TEXT,
            judul TEXT,
            isu_ekonomi TEXT,
            sektor TEXT,
            ringkasan TEXT,
            isi_berita TEXT,
            link TEXT UNIQUE,

            relevan INTEGER DEFAULT 0,

            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


create_database()

# ============================================================
# SUMBER BERITA
# ============================================================

NEWS_SOURCES = [
    {
        "nama": "KlikJatim",
        "domain": "klikjatim.com"
    },
    {
        "nama": "Kompas",
        "domain": "kompas.com"
    },
    {
        "nama": "Radar Lamongan",
        "domain": "radarlamongan.jawapos.com"
    },
    {
        "nama": "ANTARA Jatim",
        "domain": "jatim.antaranews.com"
    },
    {
        "nama": "Detik Jatim",
        "domain": "detik.com"
    }
]

# ============================================================
# TOPIK PENCARIAN BERITA
# ============================================================

SEARCH_TOPICS = [
    "Lamongan ekonomi",
    "Kabupaten Lamongan ekonomi",
    "Pemkab Lamongan ekonomi",
    "Lamongan pertanian",
    "Lamongan perikanan",
    "Lamongan peternakan",
    "Lamongan industri",
    "Lamongan perdagangan",
    "Lamongan UMKM",
    "Lamongan investasi",
    "Lamongan pariwisata",
    "Lamongan konstruksi",
    "Lamongan transportasi",
    "Lamongan energi",
    "Lamongan koperasi",
    "Lamongan tenaga kerja",
    "Lamongan pembangunan"
]

# ============================================================
# 17 SEKTOR LAPANGAN USAHA
# ============================================================

SEKTOR_BPS = [
    "A - Pertanian, Kehutanan, dan Perikanan",
    "B - Pertambangan dan Penggalian",
    "C - Industri Pengolahan",
    "D - Pengadaan Listrik dan Gas",
    "E - Pengadaan Air, Pengelolaan Sampah, Limbah dan Daur Ulang",
    "F - Konstruksi",
    "G - Perdagangan Besar dan Eceran; Reparasi Mobil dan Sepeda Motor",
    "H - Transportasi dan Pergudangan",
    "I - Penyediaan Akomodasi dan Makan Minum",
    "J - Informasi dan Komunikasi",
    "K - Jasa Keuangan dan Asuransi",
    "L - Real Estat",
    "M,N - Jasa Perusahaan",
    "O - Administrasi Pemerintahan, Pertahanan dan Jaminan Sosial Wajib",
    "P - Jasa Pendidikan",
    "Q - Jasa Kesehatan dan Kegiatan Sosial",
    "R,S,T,U - Jasa Lainnya"
]

# ============================================================
# STRUKTUR DATA BERITA
# ============================================================

NEWS_COLUMNS = [
    "Tanggal Berita",
    "Media",
    "Judul Berita",
    "Isu Ekonomi",
    "Sektor",
    "Ringkasan Berita",
    "Link Berita"
]
# ============================================================
# DATA AWAL
# ============================================================

def create_empty_data():

    return pd.DataFrame(
        columns=NEWS_COLUMNS
    )
if DATA_FILE.exists():

    try:
        data = pd.read_csv(
            DATA_FILE
        )

    except Exception:
        data = create_empty_data()

else:

    data = create_empty_data()
# ============================================================
# SESSION STATE
# ============================================================

if "data" not in st.session_state:

    st.session_state.data = data
# ============================================================
# STRUKTUR DATA KANDIDAT BERITA
# ============================================================

CANDIDATE_COLUMNS = [
    "Tanggal Berita",
    "Media",
    "Judul Berita",
    "Link Berita",
    "Isi Artikel"
]
# ============================================================
# KONFIGURASI SCRAPING
# ============================================================

MAX_RESULTS_PER_TOPIC = 8

MAX_TOTAL_CANDIDATES = 60

ARTICLE_TIMEOUT = 15

MAX_CONTENT_LENGTH = 12000
# ============================================================
# CLEAN TEXT
# ============================================================

def clean_text(text):

    if text is None:
        return ""

    text = str(text)

    # Hapus HTML
    text = BeautifulSoup(
        text,
        "html.parser"
    ).get_text(" ")

    # Hilangkan spasi berlebihan
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()
# ============================================================
# NORMALIZE TEXT
# ============================================================

def normalize_text(text):

    text = clean_text(text)

    text = text.lower()

    text = re.sub(
        r"[^a-z0-9\s]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()
# ============================================================
# SIMILARITY
# ============================================================

def calculate_similarity(text1, text2):

    words1 = set(
        normalize_text(text1).split()
    )

    words2 = set(
        normalize_text(text2).split()
    )

    if not words1 or not words2:
        return 0.0

    intersection = words1.intersection(
        words2
    )

    union = words1.union(
        words2
    )

    return len(intersection) / len(union)
# ============================================================
# PILIH ARTIKEL TERLENGKAP
# ============================================================

def choose_more_complete_article(
    article1,
    article2
):

    content1 = str(
        article1.get(
            "Isi Artikel",
            ""
        )
    )

    content2 = str(
        article2.get(
            "Isi Artikel",
            ""
        )
    )

    if len(content2) > len(content1):
        return article2

    return article1
# ============================================================
# REMOVE DUPLICATE NEWS
# ============================================================

def remove_duplicate_news(
    df,
    similarity_threshold=0.75
):

    if df.empty:
        return df

    df = df.copy()

    # -----------------------------------------
    # NORMALISASI JUDUL
    # -----------------------------------------

    df["_judul_normalized"] = (
        df["Judul Berita"]
        .apply(normalize_text)
    )

    # -----------------------------------------
    # PRIORITASKAN ARTIKEL TERLENGKAP
    # -----------------------------------------

    df["_content_length"] = (
        df["Isi Artikel"]
        .fillna("")
        .astype(str)
        .str.len()
    )

    df = df.sort_values(
        "_content_length",
        ascending=False
    )

    # -----------------------------------------
    # DUPLIKAT JUDUL
    # -----------------------------------------

    df = df.drop_duplicates(
        subset="_judul_normalized",
        keep="first"
    )

    # -----------------------------------------
    # DUPLIKAT ISI / BERITA MIRIP
    # -----------------------------------------

    keep_indices = []

    selected_texts = []

    for idx, row in df.iterrows():

        current_text = row[
            "Isi Artikel"
        ]

        is_duplicate = False

        for previous_text in selected_texts:

            similarity = calculate_similarity(
                current_text,
                previous_text
            )

            if similarity >= similarity_threshold:

                is_duplicate = True

                break

        if not is_duplicate:

            keep_indices.append(idx)

            selected_texts.append(
                current_text
            )

    df = df.loc[
        keep_indices
    ].copy()

    # -----------------------------------------
    # HAPUS KOLOM BANTU
    # -----------------------------------------

    df.drop(
        columns=[
            "_judul_normalized",
            "_content_length"
        ],
        errors="ignore",
        inplace=True
    )

    return df.reset_index(
        drop=True
    )
# ============================================================
# STRUKTUR DATA HASIL AKHIR
# ============================================================

NEWS_COLUMNS = [
    "Tanggal Berita",
    "Media",
    "Judul Berita",
    "Isu Ekonomi",
    "Sektor",
    "Ringkasan Berita",
    "Link Berita"
]
# ============================================================
# DATA STORAGE
# ============================================================

DATA_DIR = Path("data")

DATA_DIR.mkdir(
    exist_ok=True
)

DATA_FILE = (
    DATA_DIR /
    "berita_lamongan.csv"
)
# ============================================================
# SAVE DATA
# ============================================================

def save_news_data(df):

    if df is None or df.empty:
        return False

    try:

        df.to_csv(
            DATA_FILE,
            index=False,
            encoding="utf-8-sig"
        )

        return True

    except Exception as e:

        print(
            f"Gagal menyimpan data: {e}"
        )

        return False
# ============================================================
# LOAD DATA
# ============================================================

def load_news_data():

    if not DATA_FILE.exists():

        return pd.DataFrame(
            columns=NEWS_COLUMNS
        )

    try:

        df = pd.read_csv(
            DATA_FILE
        )

        for col in NEWS_COLUMNS:

            if col not in df.columns:
                df[col] = ""

        return df[
            NEWS_COLUMNS
        ]

    except Exception as e:

        print(
            f"Gagal membaca data: {e}"
        )

        return pd.DataFrame(
            columns=NEWS_COLUMNS
        )
# ============================================================
# GOOGLE NEWS RSS
# ============================================================

def search_news_rss(topic, max_results=8):

    articles = []

    try:

        encoded_topic = quote(
            topic
        )

        rss_url = (
            "https://news.google.com/rss/search?"
            f"q={encoded_topic}"
            "&hl=id"
            "&gl=ID"
            "&ceid=ID:id"
        )

        feed = feedparser.parse(
            rss_url
        )

        for entry in feed.entries[:max_results]:

            title = entry.get(
                "title",
                ""
            )

            link = entry.get(
                "link",
                ""
            )

            published = entry.get(
                "published",
                ""
            )

            # Google News biasanya memiliki
            # source pada bagian source
            source = ""

            if hasattr(
                entry,
                "source"
            ):
                source = entry.source.get(
                    "title",
                    ""
                )

            articles.append({
                "Tanggal Berita": published,
                "Media": source,
                "Judul Berita": title,
                "Link Berita": link,
                "Isi Artikel": ""
            })

    except Exception as e:

        print(
            f"RSS error untuk '{topic}': {e}"
        )

    return articles
# ============================================================
# AMBIL SEMUA KANDIDAT BERITA
# ============================================================

def collect_news_candidates():

    all_articles = []

    progress = st.progress(0)

    total_topics = len(
        SEARCH_TOPICS
    )

    for i, topic in enumerate(
        SEARCH_TOPICS
    ):

        try:

            articles = search_news_rss(
                topic,
                max_results=MAX_RESULTS_PER_TOPIC
            )

            all_articles.extend(
                articles
            )

        except Exception as e:

            print(
                f"Gagal topic {topic}: {e}"
            )

        progress.progress(
            (i + 1) / total_topics
        )

        # Jangan terlalu cepat melakukan request
        time.sleep(0.2)

        # Batasi kandidat
        if len(all_articles) >= MAX_TOTAL_CANDIDATES:

            all_articles = (
                all_articles[
                    :MAX_TOTAL_CANDIDATES
                ]
            )

            break

    progress.empty()

    return all_articles
# ============================================================
# CLEAN CANDIDATE DATA
# ============================================================

def clean_candidate_data(
    articles
):

    if not articles:

        return pd.DataFrame(
            columns=CANDIDATE_COLUMNS
        )

    df = pd.DataFrame(
        articles
    )

    # Pastikan semua kolom tersedia
    for col in CANDIDATE_COLUMNS:

        if col not in df.columns:
            df[col] = ""

    # Cleaning
    df["Judul Berita"] = (
        df["Judul Berita"]
        .fillna("")
        .astype(str)
        .apply(clean_text)
    )

    df["Link Berita"] = (
        df["Link Berita"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    df["Media"] = (
        df["Media"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    # Buang judul kosong
    df = df[
        df["Judul Berita"] != ""
    ].copy()

    # Buang URL kosong
    df = df[
        df["Link Berita"] != ""
    ].copy()

    # Hapus URL sama
    df = df.drop_duplicates(
        subset=["Link Berita"],
        keep="first"
    )

    return df.reset_index(
        drop=True
    )
# ============================================================
# RESOLVE GOOGLE NEWS URL
# ============================================================

def resolve_google_news_url(url):

    if not url:
        return ""

    # Kalau sudah URL media asli,
    # langsung gunakan
    if "news.google.com" not in url:
        return url

    try:

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:

            browser = p.chromium.launch(
                headless=True
            )

            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/151.0 Safari/537.36"
                )
            )

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=20000
            )

            # Tunggu proses redirect
            page.wait_for_timeout(3000)

            final_url = page.url

            browser.close()

            # Pastikan bukan masih Google News
            if (
                final_url
                and "news.google.com" not in final_url
            ):
                return final_url

    except Exception as e:

        print(
            f"Gagal resolve Google News URL: {e}"
        )

    return ""
# ============================================================
# EXTRACT ARTICLE CONTENT
# ============================================================

def extract_article_content(url):

    if not url:
        return ""

    try:

# ============================================================
# RESOLVE GOOGLE NEWS URL
# ============================================================

def resolve_google_news_url(url):

    if not url:
        return ""

    # Jika URL bukan dari Google News,
    # langsung gunakan URL tersebut
    if "news.google.com" not in url:
        return url

    try:

        from gnews.utils.utils import resolve_url

        real_url = resolve_url(url)

        if (
            real_url
            and "news.google.com" not in real_url
        ):
            return real_url

    except Exception as e:

        print(
            f"Gagal resolve Google News URL: {e}"
        )

    return ""
        # ----------------------------------------------------
        # 2. REQUEST ARTIKEL ASLI
        # ----------------------------------------------------

        headers = {
            "User-Agent":
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/151.0 Safari/537.36"
        }

        response = requests.get(
            real_url,
            headers=headers,
            timeout=ARTICLE_TIMEOUT
        )

        if response.status_code != 200:

            print(
                f"Status HTTP: "
                f"{response.status_code}"
            )

            return ""

        # ----------------------------------------------------
        # 3. PARSE HTML
        # ----------------------------------------------------

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # ----------------------------------------------------
        # 4. HAPUS ELEMEN TIDAK PERLU
        # ----------------------------------------------------

        for tag in soup([
            "script",
            "style",
            "nav",
            "footer",
            "header",
            "aside",
            "form",
            "noscript"
        ]):

            tag.decompose()

        # ----------------------------------------------------
        # 5. PRIORITAS ARTICLE
        # ----------------------------------------------------

        article = soup.find(
            "article"
        )

        if article:

            text = article.get_text(
                " ",
                strip=True
            )

        else:

            paragraphs = soup.find_all(
                "p"
            )

            text = " ".join(
                p.get_text(
                    " ",
                    strip=True
                )
                for p in paragraphs
            )

        # ----------------------------------------------------
        # 6. CLEAN TEXT
        # ----------------------------------------------------

        text = clean_text(
            text
        )

        # ----------------------------------------------------
        # 7. BATASI PANJANG
        # ----------------------------------------------------

        return text[
            :MAX_CONTENT_LENGTH
        ]

    except Exception as e:

        print(
            f"Gagal mengambil artikel: {e}"
        )

        return ""
if st.button(
    "🧪 Test Google News URL"
):

    test_articles = search_news_rss(
        "Lamongan ekonomi",
        max_results=1
    )

    if test_articles:

        google_url = test_articles[0][
            "Link Berita"
        ]

        st.write(
            "### URL Google News"
        )

        st.code(
            google_url
        )

        with st.spinner(
            "Resolving URL..."
        ):

            real_url = (
                resolve_google_news_url(
                    google_url
                )
            )

        if real_url:

            st.success(
                "✅ URL artikel asli ditemukan!"
            )

            st.write(
                "### URL Artikel Asli"
            )

            st.code(
                real_url
            )

        else:

            st.error(
                "❌ URL artikel asli tidak ditemukan."
            )

    else:

        st.warning(
            "⚠️ Tidak ada berita ditemukan."
        )
    
# ============================================================
# KONFIGURASI GEMINI AI
# ============================================================

try:
    from google import genai
except ImportError:
    genai = None

GEMINI_API_KEY = st.secrets.get(
    "GEMINI_API_KEY",
    ""
)

gemini_client = None

if genai and GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(
            api_key=GEMINI_API_KEY
        )
    except Exception as e:
        gemini_client = None

# ============================================================
# FUNGSI CLEAN TEXT
# ============================================================

def clean_text(text):

    if not text:
        return ""

    soup = BeautifulSoup(
        str(text),
        "html.parser"
    )

    text = soup.get_text(" ")

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# SCRAPING GOOGLE NEWS RSS
# ============================================================

SEARCH_TOPICS = [

    "Lamongan ekonomi",

    "Kabupaten Lamongan ekonomi",

    "Pemkab Lamongan ekonomi",

    "Lamongan pertanian",

    "Lamongan perikanan",

    "Lamongan UMKM",

    "Lamongan perdagangan",

    "Lamongan industri",

    "Lamongan investasi",

    "Lamongan pembangunan",

    "Lamongan pasar",

    "Lamongan harga pangan",

    "Lamongan bisnis",

    "Lamongan koperasi",

    "Lamongan pariwisata",

    "Lamongan peternakan",

    "Lamongan nelayan"
]


def get_google_news_rss(keyword):

    url = (
        "https://news.google.com/rss/search?"
        f"q={quote(keyword)}"
        "&hl=id"
        "&gl=ID"
        "&ceid=ID:id"
    )

    try:

        response = requests.get(
            url,
            timeout=10,
            headers={
                "User-Agent":
                "Mozilla/5.0"
            }
        )

        response.raise_for_status()

        feed = feedparser.parse(
            response.content
        )

        results = []

        for item in feed.entries:

            title = clean_text(
                item.get("title", "")
            )

            link = item.get(
                "link",
                ""
            )

            published = item.get(
                "published",
                ""
            )

            description = clean_text(
                item.get(
                    "summary",
                    ""
                )
            )

            if title and link:

                results.append({

                    "judul_awal": title,

                    "link": link,

                    "tanggal_awal":
                        published,

                    "deskripsi_awal":
                        description

                })

        return results

    except Exception:

        return []


# ============================================================
# SCRAPE SEMUA TOPIK
# ============================================================

def scrape_news():

    all_news = []

    progress = st.progress(0)

    total = len(SEARCH_TOPICS)

    for i, topic in enumerate(
        SEARCH_TOPICS
    ):

        results = get_google_news_rss(
            topic
        )

        all_news.extend(
            results
        )

        progress.progress(
            (i + 1) / total
        )

    progress.empty()

    # Deduplicate berdasarkan URL
    unique = {}

    for item in all_news:

        link = item["link"]

        if link not in unique:

            unique[link] = item

    return list(
        unique.values()
    )


# ============================================================
# EKSTRAK MEDIA
# ============================================================

def get_media_from_url(url):

    try:

        domain = urlparse(
            url
        ).netloc.lower()

        domain = domain.replace(
            "www.",
            ""
        )

        media_mapping = {

            "kompas.com":
                "KOMPAS.com",

            "detik.com":
                "detik.com",

            "jawapos.com":
                "Jawa Pos",

            "radarlamongan.jawapos.com":
                "Radar Lamongan",

            "antaranews.com":
                "ANTARA",

            "jatim.antaranews.com":
                "ANTARA Jatim",

            "klikjatim.com":
                "KlikJatim",

            "beritajatim.com":
                "BeritaJatim",

            "surabaya.tribunnews.com":
                "Tribun Jatim"

        }

        for domain_key, name in media_mapping.items():

            if domain_key in domain:

                return name

        return domain

    except Exception:

        return "Media tidak diketahui"


# ============================================================
# EKSTRAK ISI ARTIKEL
# ============================================================

def extract_article(url):

    try:

        response = requests.get(
            url,
            timeout=10,
            headers={
                "User-Agent":
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            }
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # Hapus elemen yang tidak diperlukan

        for element in soup(
            [
                "script",
                "style",
                "nav",
                "footer",
                "header",
                "aside",
                "form"
            ]
        ):

            element.decompose()

        # Cari paragraf

        paragraphs = []

        for p in soup.find_all(
            "p"
        ):

            text = clean_text(
                p.get_text(" ")
            )

            if len(text) >= 40:

                paragraphs.append(
                    text
                )

        # Hilangkan duplikasi

        unique_paragraphs = []

        seen = set()

        for p in paragraphs:

            key = p.lower()

            if key not in seen:

                seen.add(key)

                unique_paragraphs.append(
                    p
                )

        content = " ".join(
            unique_paragraphs
        )

        # Batasi panjang
        content = content[:12000]

        # Cari tanggal meta

        date = ""

        meta_candidates = [

            soup.find(
                "meta",
                attrs={
                    "property":
                    "article:published_time"
                }
            ),

            soup.find(
                "meta",
                attrs={
                    "name":
                    "date"
                }
            ),

            soup.find(
                "meta",
                attrs={
                    "name":
                    "pubdate"
                }
            )

        ]

        for meta in meta_candidates:

            if meta and meta.get(
                "content"
            ):

                date = meta[
                    "content"
                ]

                break

        return {

            "isi_berita":
                content,

            "tanggal":
                date

        }

    except Exception:

        return {

            "isi_berita":
                "",

            "tanggal":
                ""

        }


# ============================================================
# ANALISIS GEMINI AI
# ============================================================

def analyze_with_gemini(
    title,
    content
):

    if not content:

        return {

            "relevan": False,

            "isu_ekonomi":
                "Tidak dapat dianalisis",

            "sektor":
                "Tidak teridentifikasi",

            "ringkasan":
                "Isi berita tidak berhasil diambil."

        }

    # Jika Gemini belum dikonfigurasi

    if gemini_client is None:

        return {

            "relevan": True,

            "isu_ekonomi":
                "Belum dianalisis AI",

            "sektor":
                "Belum dianalisis AI",

            "ringkasan":
                content[:400]

        }

    sector_text = "\n".join(
        [
            f"- {x}"
            for x in SEKTOR_BPS
        ]
    )

    prompt = f"""
Kamu adalah analis ekonomi BPS Kabupaten Lamongan.

Baca ISI BERITA, jangan hanya membaca judul.

Tentukan apakah berita tersebut berkaitan
dengan ekonomi, pembangunan, kesejahteraan,
usaha, perdagangan, pertanian, industri,
jasa, investasi, atau aktivitas ekonomi
di Kabupaten Lamongan.

JUDUL:
{title}

ISI BERITA:
{content[:9000]}

PILIH SALAH SATU SEKTOR BERIKUT:

{sector_text}

ATURAN:

1. Gunakan isi berita sebagai dasar utama.
2. Jangan menentukan sektor hanya berdasarkan judul.
3. Jika berita bukan ekonomi, relevan = false.
4. Jika berita ekonomi, relevan = true.
5. Pilih tepat SATU sektor.
6. Buat isu ekonomi yang spesifik.
7. Ringkasan harus berdasarkan isi berita.
8. Jangan hanya mengulang judul.
9. Ringkasan maksimal 80 kata.
10. Jangan membuat informasi yang tidak ada dalam berita.

Keluarkan HANYA JSON:

{{
    "relevan": true,
    "isu_ekonomi": "...",
    "sektor": "...",
    "ringkasan": "..."
}}
"""

    try:

        response = gemini_client.models.generate_content(

            model="gemini-2.5-flash",

            contents=prompt

        )

        text = response.text.strip()

        # Bersihkan markdown JSON

        text = re.sub(
            r"```json",
            "",
            text,
            flags=re.I
        )

        text = text.replace(
            "```",
            ""
        ).strip()

        result = json.loads(
            text
        )

        # Validasi sektor

        sector = result.get(
            "sektor",
            ""
        )

        matched_sector = None

        for valid_sector in SEKTOR_BPS:

            if (
                sector.lower()
                == valid_sector.lower()
            ):

                matched_sector = (
                    valid_sector
                )

                break

        if not matched_sector:

            # Coba berdasarkan kode sektor

            for valid_sector in SEKTOR_BPS:

                code = valid_sector.split(
                    " - "
                )[0]

                if sector.upper().startswith(
                    code
                ):

                    matched_sector = (
                        valid_sector
                    )

                    break

        if not matched_sector:

            matched_sector = (
                "Tidak teridentifikasi"
            )

        return {

            "relevan":
                bool(
                    result.get(
                        "relevan",
                        False
                    )
                ),

            "isu_ekonomi":
                result.get(
                    "isu_ekonomi",
                    "Ekonomi Umum"
                ),

            "sektor":
                matched_sector,

            "ringkasan":
                result.get(
                    "ringkasan",
                    ""
                )

        }

    except Exception as e:

        return {

            "relevan":
                True,

            "isu_ekonomi":
                "Ekonomi Umum",

            "sektor":
                "Tidak teridentifikasi",

            "ringkasan":
                content[:500]

        }


# ============================================================
# SIMPAN DATABASE
# ============================================================

def save_news(news):

    conn = get_connection()

    cursor = conn.cursor()

    try:

        cursor.execute("""
            INSERT OR IGNORE INTO berita
            (
                tanggal,
                media,
                judul,
                isu_ekonomi,
                sektor,
                ringkasan,
                isi_berita,
                link,
                relevan,
                created_at
            )

            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (

            news["tanggal"],

            news["media"],

            news["judul"],

            news["isu_ekonomi"],

            news["sektor"],

            news["ringkasan"],

            news["isi_berita"],

            news["link"],

            1 if news["relevan"]
            else 0,

            datetime.now().isoformat()

        ))

        conn.commit()

    except Exception:

        pass

    finally:

        conn.close()


# ============================================================
# AMBIL DATA DARI DATABASE
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
            sektor,
            ringkasan,
            link
        FROM berita
        WHERE relevan = 1
        ORDER BY id DESC
        """,
        conn
    )

    conn.close()

    return df


# ============================================================
# PROSES BERITA
# ============================================================

def process_news():

    st.info(
        "🔎 Mengambil berita terbaru..."
    )

    candidates = scrape_news()

    if not candidates:

        st.warning(
            "Tidak ditemukan kandidat berita."
        )

        return

    st.success(
        f"Berhasil menemukan "
        f"{len(candidates)} kandidat berita."
    )

    progress = st.progress(0)

    total = len(candidates)

    processed = 0

    # ========================================================
    # EKSTRAK ARTIKEL
    # ========================================================

    def worker(item):

        article = extract_article(
            item["link"]
        )

        title = item[
            "judul_awal"
        ]

        content = article[
            "isi_berita"
        ]

        media = get_media_from_url(
            item["link"]
        )

        analysis = analyze_with_gemini(
            title,
            content
        )

        tanggal = (
            article["tanggal"]
            or item["tanggal_awal"]
        )

        return {

            "tanggal":
                tanggal,

            "media":
                media,

            "judul":
                title,

            "isu_ekonomi":
                analysis[
                    "isu_ekonomi"
                ],

            "sektor":
                analysis[
                    "sektor"
                ],

            "ringkasan":
                analysis[
                    "ringkasan"
                ],

            "isi_berita":
                content,

            "link":
                item["link"],

            "relevan":
                analysis[
                    "relevan"
                ]

        }

    # ========================================================
    # PARALLEL PROCESSING
    # ========================================================

    with ThreadPoolExecutor(
        max_workers=5
    ) as executor:

        futures = [
            executor.submit(
                worker,
                item
            )
            for item in candidates
        ]

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                # Hanya simpan berita ekonomi

                if result["relevan"]:

                    save_news(
                        result
                    )

            except Exception:

                pass

            processed += 1

            progress.progress(
                processed / total
            )

    progress.empty()

    st.success(
        "✅ Proses pengambilan dan analisis berita selesai."
    )


# ============================================================
# 📌 LOAD DATA & SIDEBAR CONTROL (SG KOMPONEN)
# ============================================================

if "data" not in st.session_state:
    if DATA_FILE.exists():
        try:
            st.session_state.data = pd.read_csv(DATA_FILE)
        except Exception:
            st.session_state.data = create_sample_data()
    else:
        st.session_state.data = create_sample_data()

with st.sidebar:
    if BPS_LOGO.exists():
        st.image(BPS_LOGO_URL, width=120)

    st.title("Dashboard Control")

    # ========================================================
# STATUS GEMINI AI
# ========================================================

if gemini_client is not None:
    st.success("🟢 Gemini AI: Active")
else:
    st.error("🔴 Gemini AI: Offline (Cek Secrets)")

st.divider()

st.subheader("⚙️ Aksi")

# ============================================================
# FETCH AND PROCESS NEWS
# ============================================================

def fetch_and_process_news():
    """
    Mengambil, memproses, menganalisis, dan mengembalikan
    berita ekonomi dalam bentuk DataFrame.
    """

    import pandas as pd

    all_news = []

    try:
        # ----------------------------------------------------
        # 1. AMBIL BERITA
        # ----------------------------------------------------

        st.info("🔎 Mengambil berita terbaru...")

        for topic in SEARCH_TOPICS:

            try:
                articles = get_news_from_rss(topic)

                if articles:
                    all_news.extend(articles)

            except Exception as e:
                print(
                    f"Gagal mengambil berita untuk "
                    f"{topic}: {e}"
                )

        # ----------------------------------------------------
        # 2. JIKA TIDAK ADA BERITA
        # ----------------------------------------------------

        if not all_news:
            st.warning(
                "⚠️ Tidak ada berita yang berhasil ditemukan."
            )

            return pd.DataFrame()

        # ----------------------------------------------------
        # 3. BUAT DATAFRAME
        # ----------------------------------------------------

        df = pd.DataFrame(all_news)

        if df.empty:
            return pd.DataFrame()

        # ----------------------------------------------------
        # 4. NORMALISASI KOLOM
        # ----------------------------------------------------

        rename_map = {
            "title": "Judul Berita",
            "judul": "Judul Berita",
            "headline": "Judul Berita",

            "link": "Link Berita",
            "url": "Link Berita",

            "source": "Media",
            "media": "Media",

            "published": "Tanggal Berita",
            "date": "Tanggal Berita",

            "summary": "Ringkasan Berita",
            "description": "Ringkasan Berita"
        }

        df.rename(
            columns=rename_map,
            inplace=True
        )

        # ----------------------------------------------------
        # 5. PASTIKAN KOLOM ADA
        # ----------------------------------------------------

        for col in [
            "Judul Berita",
            "Link Berita",
            "Media",
            "Tanggal Berita"
        ]:
            if col not in df.columns:
                df[col] = ""

        # ----------------------------------------------------
        # 6. BERSIHKAN DATA
        # ----------------------------------------------------

        df["Judul Berita"] = (
            df["Judul Berita"]
            .fillna("")
            .astype(str)
            .str.strip()
        )

        df["Link Berita"] = (
            df["Link Berita"]
            .fillna("")
            .astype(str)
            .str.strip()
        )

        df["Media"] = (
            df["Media"]
            .fillna("")
            .astype(str)
            .str.strip()
        )

        df = df[
            df["Judul Berita"] != ""
        ].copy()

        # ----------------------------------------------------
        # 7. HAPUS URL DUPLIKAT
        # ----------------------------------------------------

        df = df.drop_duplicates(
            subset=["Link Berita"],
            keep="first"
        )

        # ----------------------------------------------------
        # 8. AMBIL ISI ARTIKEL
        # ----------------------------------------------------

        contents = []

        progress = st.progress(0)

        total = len(df)

        for i, (_, row) in enumerate(
            df.iterrows()
        ):

            url = row["Link Berita"]

            try:

                content = extract_article_content(
                    url
                )

            except Exception as e:

                print(
                    f"Gagal mengambil isi artikel: {e}"
                )

                content = ""

            if not content:

                content = str(
                    row.get(
                        "Ringkasan Berita",
                        ""
                    )
                )

            contents.append(
                clean_text(content)
            )

            progress.progress(
                (i + 1) / total
            )

        progress.empty()

        df["Isi Artikel"] = contents

        # ----------------------------------------------------
        # 9. BUANG ARTIKEL TANPA ISI
        # ----------------------------------------------------

        df = df[
            df["Isi Artikel"].str.len() >= 100
        ].copy()

        if df.empty:

            st.warning(
                "⚠️ Isi artikel tidak berhasil diperoleh."
            )

            return pd.DataFrame()

        # ----------------------------------------------------
        # 10. ANALISIS GEMINI
        # ----------------------------------------------------

        if gemini_client is None:

            st.error(
                "🔴 Gemini AI tidak aktif."
            )

            return pd.DataFrame()

        hasil_ai = []

        progress_ai = st.progress(0)

        total_ai = len(df)

        for i, (_, row) in enumerate(
            df.iterrows()
        ):

            try:

                hasil = analyze_news_with_ai(
                    row["Judul Berita"],
                    row["Isi Artikel"][:MAX_CONTENT_FOR_AI]
                )

                if not isinstance(
                    hasil,
                    dict
                ):
                    hasil = {}

                ekonomi = hasil.get(
                    "ekonomi",
                    False
                )

                if isinstance(
                    ekonomi,
                    str
                ):
                    ekonomi = (
                        ekonomi.lower()
                        in [
                            "true",
                            "ya",
                            "yes",
                            "1"
                        ]
                    )

                hasil_ai.append({
                    "ekonomi": bool(
                        ekonomi
                    ),

                    "isu_ekonomi": str(
                        hasil.get(
                            "isu_ekonomi",
                            ""
                        )
                    ).strip(),

                    "sektor": str(
                        hasil.get(
                            "sektor",
                            ""
                        )
                    ).strip(),

                    "ringkasan": str(
                        hasil.get(
                            "ringkasan",
                            ""
                        )
                    ).strip()
                })

            except Exception as e:

                print(
                    f"Gemini error: {e}"
                )

                hasil_ai.append({
                    "ekonomi": False,
                    "isu_ekonomi": "",
                    "sektor": "",
                    "ringkasan": ""
                })

            progress_ai.progress(
                (i + 1) / total_ai
            )

        progress_ai.empty()

        # ----------------------------------------------------
        # 11. MASUKKAN HASIL GEMINI
        # ----------------------------------------------------

        ai_df = pd.DataFrame(
            hasil_ai,
            index=df.index
        )

        df["Ekonomi"] = ai_df[
            "ekonomi"
        ]

        df["Isu Ekonomi"] = ai_df[
            "isu_ekonomi"
        ]

        df["Sektor"] = ai_df[
            "sektor"
        ]

        df["Ringkasan Berita"] = ai_df[
            "ringkasan"
        ]

        # ----------------------------------------------------
        # 12. HANYA BERITA EKONOMI
        # ----------------------------------------------------

        df = df[
            df["Ekonomi"] == True
        ].copy()

        if df.empty:

            st.warning(
                "⚠️ Tidak ditemukan berita ekonomi."
            )

            return pd.DataFrame()

        # ----------------------------------------------------
        # 13. DEDUPLIKASI BERDASARKAN JUDUL
        # ----------------------------------------------------

        df["_judul_normalized"] = (
            df["Judul Berita"]
            .apply(normalize_text)
        )

        # Artikel yang lebih panjang
        # dianggap lebih lengkap
        df["_panjang"] = (
            df["Isi Artikel"]
            .str.len()
        )

        df = df.sort_values(
            "_panjang",
            ascending=False
        )

        df = df.drop_duplicates(
            subset="_judul_normalized",
            keep="first"
        )

        # ----------------------------------------------------
        # 14. TANGGAL
        # ----------------------------------------------------

        df["Tanggal Berita"] = pd.to_datetime(
            df["Tanggal Berita"],
            errors="coerce"
        )

        # ----------------------------------------------------
        # 15. KOLOM AKHIR
        # ----------------------------------------------------

        final_columns = [
            "Tanggal Berita",
            "Media",
            "Judul Berita",
            "Isu Ekonomi",
            "Sektor",
            "Ringkasan Berita",
            "Link Berita"
        ]

        for col in final_columns:

            if col not in df.columns:
                df[col] = ""

        df = df[
            final_columns
        ].copy()

        # ----------------------------------------------------
        # 16. URUTKAN
        # ----------------------------------------------------

        df = df.sort_values(
            "Tanggal Berita",
            ascending=False
        )

        df.reset_index(
            drop=True,
            inplace=True
        )

        st.success(
            f"✅ Berhasil memproses "
            f"{len(df)} berita ekonomi."
        )

        return df

    except Exception as e:

        st.error(
            "❌ Gagal memproses berita."
        )

        st.exception(e)

        return pd.DataFrame()
if st.button(
    "🔄 Ambil Berita Terbaru",
    use_container_width=True
):
    new_data = fetch_and_process_news()

    if new_data is not None and not new_data.empty:
        st.session_state.data = new_data.copy()

        new_data.to_csv(
            DATA_FILE,
            index=False,
            encoding="utf-8-sig"
        )

        st.success(
            f"✅ {len(new_data)} berita berhasil diperbarui!"
        )

        st.rerun()

    else:
        st.warning(
            "⚠️ Tidak ada berita baru yang berhasil diproses."
        )


# ========================================================
# RESET & BERSIHKAN DATA
# ========================================================

if st.button(
    "🗑️ Reset & Bersihkan Data",
    use_container_width=True
):
    try:
        st.session_state.data = create_sample_data()

        if DATA_FILE.exists():
            DATA_FILE.unlink()

        st.success("🗑️ Data berhasil direset.")

        st.rerun()

    except Exception as e:
        st.error("❌ Gagal mereset data.")
        st.exception(e)

    st.divider()
    st.subheader("🔎 Filter Data")

df = st.session_state.data.copy()
df["Tanggal Berita"] = pd.to_datetime(df["Tanggal Berita"], errors="coerce")

with st.sidebar:
    if not df.empty and "Tanggal Berita" in df.columns:
        valid_dates = df["Tanggal Berita"].dropna()
        min_date = valid_dates.min().date()
        max_date = valid_dates.max().date()
    else:
        min_date = datetime.now().date()
        max_date = datetime.now().date()

    date_range = st.date_input("📅 Periode Berita", value=(min_date, max_date))
    selected_media = st.multiselect("🌐 Media", sorted(df["Media"].dropna().unique()))
    selected_sector = st.multiselect("🏭 Sektor Lapangan Usaha", sorted(df["Sektor"].dropna().unique()))
    selected_issue = st.multiselect("📊 Isu Ekonomi", sorted(df["Isu Ekonomi"].dropna().unique()))
    keyword = st.text_input("🔎 Cari kata kunci", placeholder="Ketik kata kunci...")

filtered = df.copy()
if len(date_range) == 2:
    filtered = filtered[(filtered["Tanggal Berita"].dt.date >= date_range[0]) & (filtered["Tanggal Berita"].dt.date <= date_range[1])]
if selected_media: filtered = filtered[filtered["Media"].isin(selected_media)]
if selected_sector: filtered = filtered[filtered["Sektor"].isin(selected_sector)]
if selected_issue: filtered = filtered[filtered["Isu Ekonomi"].isin(selected_issue)]
if keyword:
    search_text = keyword.lower()
    filtered = filtered[filtered[["Judul Berita", "Isu Ekonomi", "Sektor", "Ringkasan Berita"]].fillna("").astype(str).apply(lambda row: row.str.lower().str.contains(search_text, regex=False).any(), axis=1)]

# ============================================================
# 📌 TAMPILAN DASHBOARD UTAMA
# ============================================================

logo_base64 = ""
if BPS_LOGO.exists():
    with open(BPS_LOGO, "rb") as f:
        logo_base64 = base64.b64encode(f.read()).decode("utf-8")

header_img_tag = f'<img src="data:image/png;base64,{logo_base64}" class="dashboard-logo" alt="Logo BPS">' if logo_base64 else ''

st.markdown(f"""
<div class="dashboard-header">
    {header_img_tag}
    <div>
        <div class="dashboard-title">MONITORING BERITA EKONOMI LAMONGAN</div>
        <div class="dashboard-subtitle">Sistem pemantauan media otomatis berbasis AI untuk 17 Sektor Lapangan Usaha BPS Kabupaten Lamongan</div>
    </div>
</div>
""", unsafe_allow_html=True)

k1, k2, k3, k4 = st.columns(4)
k1.metric("📰 Total Berita", f"{len(filtered):,}")
k2.metric("📅 Berita Hari Ini", f"{len(filtered[filtered['Tanggal Berita'].dt.date == datetime.now().date()]):,}")
k3.metric("🌐 Sumber Media", f"{filtered['Media'].nunique():,}")
k4.metric("🏭 Sektor Terpantau", f"{filtered['Sektor'].nunique():,}")

st.markdown("<br>", unsafe_allow_html=True)

if not filtered.empty:
    st.markdown('<div class="section-header">📊 Ringkasan Visual & Grafik</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        sector_df = filtered["Sektor"].value_counts().reset_index()
        sector_df.columns = ["Sektor", "Jumlah"]
        fig_sector = px.bar(sector_df, x="Jumlah", y="Sektor", orientation="h", text="Jumlah", color="Jumlah", color_continuous_scale="Blues", title="Sebaran 17 Sektor Lapangan Usaha BPS")
        fig_sector.update_layout(height=450, showlegend=False, yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig_sector, use_container_width=True)

    with col2:
        media_df = filtered["Media"].value_counts().reset_index()
        media_df.columns = ["Media", "Jumlah"]
        fig_media = px.pie(media_df, names="Media", values="Jumlah", hole=0.4, title="Proporsi Berita Per Media")
        fig_media.update_layout(height=450)
        st.plotly_chart(fig_media, use_container_width=True)

    trend_df = filtered.groupby("Tanggal Berita").size().reset_index(name="Jumlah Berita")
    fig_trend = px.area(trend_df, x="Tanggal Berita", y="Jumlah Berita", title="📈 Tren Volume Berita Ekonomi", color_discrete_sequence=["#2563eb"])
    fig_trend.update_layout(height=300)
    st.plotly_chart(fig_trend, use_container_width=True)

st.markdown('<div class="section-header">📋 Tabel Berita Terfilter</div>', unsafe_allow_html=True)

if not filtered.empty:
    display_df = filtered.copy()
    display_df["Tanggal Berita"] = display_df["Tanggal Berita"].dt.strftime("%Y-%m-%d")
    st.dataframe(
        display_df[["Tanggal Berita", "Media", "Judul Berita", "Isu Ekonomi", "Sektor", "Ringkasan Berita", "Link Berita"]],
        column_config={
            "Link Berita": st.column_config.LinkColumn("Link Berita", display_text="🔗 Baca Artikel"),
            "Ringkasan Berita": st.column_config.TextColumn("Ringkasan Berita", width="large")
        },
        use_container_width=True,
        hide_index=True
    )
else:
    st.warning("Tidak ada data berita yang cocok dengan filter.")

st.markdown('<div class="section-header">📥 Ekspor Laporan Excel</div>', unsafe_allow_html=True)

if not filtered.empty:
    exp_df = filtered.copy()
    exp_df["Tanggal Berita"] = exp_df["Tanggal Berita"].dt.strftime("%Y-%m-%d")
    exp_df = exp_df[["Tanggal Berita", "Media", "Judul Berita", "Isu Ekonomi", "Sektor", "Ringkasan Berita", "Link Berita"]]

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            exp_df.to_excel(writer, index=False, sheet_name='Monitoring Berita')
            worksheet = writer.sheets['Monitoring Berita']

            header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
            header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

            for col_num in range(1, len(exp_df.columns) + 1):
                cell = worksheet.cell(row=1, column=col_num)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

            col_widths = {'A': 18, 'B': 20, 'C': 35, 'D': 22, 'E': 38, 'F': 50, 'G': 30}
            for col_letter, width in col_widths.items():
                worksheet.column_dimensions[col_letter].width = width

            body_alignment = Alignment(vertical="top", wrap_text=True)
            for row in worksheet.iter_rows(min_row=2, max_row=len(exp_df) + 1, min_col=1, max_col=len(exp_df.columns)):
                for cell in row:
                    cell.alignment = body_alignment

        buffer.seek(0)
        st.download_button(
            label="📊 Download Laporan Excel (.xlsx)",
            data=buffer,
            file_name=f"Laporan_Berita_Ekonomi_Lamongan_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    except Exception as e:
        st.info("💡 Pastikan 'openpyxl' sudah ada di requirements.txt")

st.divider()
st.caption("Dashboard Monitoring Berita Ekonomi Kabupaten Lamongan | BPS Kabupaten Lamongan")

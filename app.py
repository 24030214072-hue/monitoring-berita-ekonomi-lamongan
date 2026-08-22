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
# GOOGLE NEWS SEARCH
# ============================================================

def search_news_rss(topic, max_results=8):

    articles = []

    try:

        from gnews import GNews

        google_news = GNews(
            language="id",
            country="ID",
            max_results=max_results
        )

        results = google_news.get_news(
            topic
        )

        for item in results:

            title = item.get(
                "title",
                ""
            )

            url = item.get(
                "url",
                ""
            )

            published = item.get(
                "published date",
                ""
            )

            publisher = item.get(
                "publisher",
                ""
            )

            # --------------------------------------------
            # HANYA TERIMA URL ASLI
            # --------------------------------------------

            if (
                not url
                or "news.google.com" in url
            ):
                continue

            articles.append({

                "Tanggal Berita":
                    published,

                "Media":
                    publisher,

                "Judul Berita":
                    title,

                "Link Berita":
                    url,

                "Isi Artikel":
                    ""
            })

    except Exception as e:

        print(
            f"Gagal mengambil berita "
            f"untuk '{topic}': {e}"
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
# DOMAIN MEDIA
# ============================================================

MEDIA_DOMAIN_MAP = {

    "unesa.ac.id":
        "unesa.ac.id",

    "KlikJatim":
        "klikjatim.com",

    "klikjatim":
        "klikjatim.com",

    "LintasJatimNews.com":
        "lintasjatimnews.com",

    "LintasJatimNews":
        "lintasjatimnews.com",

    "Radar Lamongan":
        "radarlamongan.jawapos.com",

    "Radar Lamongan (Jawa Pos)":
        "radarlamongan.jawapos.com",

    "ANTARAJATIM":
        "jatim.antaranews.com",

    "detikjatim":
        "detik.com"
}


# ============================================================
# NORMALISASI DOMAIN MEDIA
# ============================================================

def get_media_domain(media):

    if not media:
        return ""

    media_clean = (
        str(media)
        .strip()
        .lower()
    )

    # Cek mapping
    for key, domain in MEDIA_DOMAIN_MAP.items():

        if key.lower() in media_clean:

            return domain

    # Jika sudah berupa domain
    media_clean = (
        media_clean
        .replace("https://", "")
        .replace("http://", "")
        .replace("www.", "")
        .strip("/")
    )

    if "." in media_clean:

        return media_clean

    return ""



# ============================================================
# CARI URL ARTIKEL DARI DUCKDUCKGO
# ============================================================

def search_article_url(
    title,
    media=""
):

    if not title:
        return ""

    try:

        import requests
        from bs4 import BeautifulSoup
        from urllib.parse import quote_plus

        # --------------------------------------------
        # Bersihkan judul
        # --------------------------------------------

        clean_title_value = clean_text(
            title
        )

        # Buang nama media setelah " - "
        if " - " in clean_title_value:

            clean_title_value = (
                clean_title_value
                .rsplit("-", 1)[0]
                .strip()
            )

        # --------------------------------------------
        # Domain
        # --------------------------------------------

        domain = get_media_domain(
            media
        )

        # --------------------------------------------
        # Query
        # --------------------------------------------

        if domain:

            query = (
                f'"{clean_title_value}" '
                f'site:{domain}'
            )

        else:

            query = (
                f'"{clean_title_value}"'
            )

        search_url = (
            "https://html.duckduckgo.com/html/?q="
            + quote_plus(query)
        )

        headers = {

            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/151.0 Safari/537.36"
            )
        }

        response = requests.get(
            search_url,
            headers=headers,
            timeout=20
        )

        print(
            "DuckDuckGo HTTP:",
            response.status_code
        )

        if response.status_code != 200:

            return ""

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # --------------------------------------------
        # Ambil hasil pencarian
        # --------------------------------------------

        for result in soup.select(
            ".result"
        ):

            link = result.select_one(
                "a.result__a"
            )

            if not link:
                continue

            href = link.get(
                "href",
                ""
            )

            if not href:
                continue

            # ----------------------------------------
            # Prioritaskan domain media
            # ----------------------------------------

            if domain:

                if domain.lower() in (
                    href.lower()
                ):

                    print(
                        "URL ditemukan melalui search:",
                        href
                    )

                    return href

            else:

                return href

    except Exception as e:

        print(
            "Search URL gagal:",
            e
        )

    return ""
# ============================================================
# DOMAIN MEDIA
# ============================================================

MEDIA_DOMAIN_MAP = {
    "unesa.ac.id": "unesa.ac.id",
    "KlikJatim": "klikjatim.com",
    "KlikJatim.com": "klikjatim.com",
    "LintasJatimNews": "lintasjatimnews.com",
    "LintasJatimNews.com": "lintasjatimnews.com",
    "Radar Lamongan": "radarlamongan.jawapos.com",
    "ANTARAJATIM": "jatim.antaranews.com",
    "detikjatim": "detik.com",
}


# ============================================================
# DAPATKAN DOMAIN MEDIA
# ============================================================

def get_media_domain(media):

    if not media:
        return ""

    media = str(media).strip()

    # Cek mapping
    for name, domain in MEDIA_DOMAIN_MAP.items():

        if name.lower() in media.lower():
            return domain

    # Kalau media sudah berupa URL/domain
    domain = (
        media.lower()
        .replace("https://", "")
        .replace("http://", "")
        .replace("www.", "")
        .strip("/")
    )

    if "." in domain:
        return domain

    return ""


# ============================================================
# CARI URL ARTIKEL ASLI BERDASARKAN JUDUL
# ============================================================

def find_article_from_title(title, media=""):

    if not title:
        return ""

    try:

        import requests
        from bs4 import BeautifulSoup
        from urllib.parse import quote_plus

        # ----------------------------------------------------
        # BERSIHKAN JUDUL
        # ----------------------------------------------------

        clean_title_value = clean_text(title)

        # Hilangkan nama media di belakang judul
        if " - " in clean_title_value:

            clean_title_value = (
                clean_title_value
                .rsplit(" - ", 1)[0]
                .strip()
            )

        domain = get_media_domain(media)

        print("====================================")
        print("MENCARI ARTIKEL ASLI")
        print("Judul :", clean_title_value)
        print("Media :", media)
        print("Domain:", domain)

        # ----------------------------------------------------
        # QUERY
        # ----------------------------------------------------

        if domain:

            query = (
                f'site:{domain} '
                f'"{clean_title_value}"'
            )

        else:

            query = (
                f'"{clean_title_value}"'
            )

        print("Query:", query)

        # ----------------------------------------------------
        # GOOGLE SEARCH
        # ----------------------------------------------------

        google_url = (
            "https://www.google.com/search?q="
            + quote_plus(query)
        )

        headers = {

            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/151.0 Safari/537.36"
            ),

            "Accept-Language":
                "id-ID,id;q=0.9,en-US;q=0.8"
        }

        response = requests.get(
            google_url,
            headers=headers,
            timeout=20
        )

        print(
            "Google Search status:",
            response.status_code
        )

        if response.status_code != 200:

            return ""

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # ----------------------------------------------------
        # CARI SEMUA LINK
        # ----------------------------------------------------

        candidates = []

        for a in soup.find_all(
            "a",
            href=True
        ):

            href = a.get("href")

            if not href:
                continue

            # Hanya URL
            if not href.startswith("http"):
                continue

            href_lower = href.lower()

            # Jangan ambil Google
            if (
                "google.com" in href_lower
                or "googleusercontent.com"
                in href_lower
                or "news.google.com"
                in href_lower
            ):
                continue

            # ------------------------------------------------
            # PRIORITAS DOMAIN MEDIA
            # ------------------------------------------------

            if domain:

                if domain.lower() in href_lower:

                    print(
                        "✅ URL ARTIKEL DITEMUKAN:"
                    )

                    print(href)

                    return href

            candidates.append(href)

        # ----------------------------------------------------
        # FALLBACK
        # ----------------------------------------------------

        if candidates:

            print(
                "⚠️ Domain media tidak ditemukan."
            )

            print(
                "Menggunakan kandidat pertama:"
            )

            print(
                candidates[0]
            )

            return candidates[0]

    except Exception as e:

        print(
            "❌ ERROR find_article_from_title:",
            repr(e)
        )

    return ""


# ============================================================
# AMBIL ISI ARTIKEL
# ============================================================

def get_article_content(
    title,
    media,
    google_url=""
):

    if not title:
        return "", ""

    try:

        import requests
        from bs4 import BeautifulSoup

        # ====================================================
        # JANGAN PAKAI URL GOOGLE NEWS UNTUK SCRAPING
        # ====================================================

        real_url = ""

        # Kalau URL sudah bukan Google News
        if (
            google_url
            and "news.google.com"
            not in google_url.lower()
        ):

            real_url = google_url

        # ====================================================
        # CARI BERDASARKAN JUDUL
        # ====================================================

        if not real_url:

            print(
                "🔎 Mencari URL artikel berdasarkan judul..."
            )

            real_url = find_article_from_title(
                title,
                media
            )

        # ====================================================
        # URL GAGAL
        # ====================================================

        if not real_url:

            print(
                "❌ URL artikel asli tidak ditemukan."
            )

            return "", ""

        # ====================================================
        # VALIDASI
        # ====================================================

        if (
            "news.google.com"
            in real_url.lower()
        ):

            print(
                "❌ URL masih Google News."
            )

            return "", ""

        print(
            "✅ URL ARTIKEL ASLI:",
            real_url
        )

        # ====================================================
        # REQUEST ARTIKEL
        # ====================================================

        headers = {

            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/151.0 Safari/537.36"
            ),

            "Accept-Language":
                "id-ID,id;q=0.9,en;q=0.8",

            "Accept":
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
        }

        response = requests.get(
            real_url,
            headers=headers,
            timeout=30,
            allow_redirects=True
        )

        print(
            "Artikel HTTP:",
            response.status_code
        )

        if response.status_code != 200:

            return real_url, ""

        # ====================================================
        # PARSE
        # ====================================================

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # ====================================================
        # HAPUS ELEMENT
        # ====================================================

        for tag in soup.find_all([
            "script",
            "style",
            "nav",
            "footer",
            "header",
            "aside",
            "form",
            "noscript",
            "iframe"
        ]):

            tag.decompose()

        # ====================================================
        # CARI ARTICLE
        # ====================================================

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

        # ====================================================
        # CLEAN
        # ====================================================

        text = clean_text(
            text
        )

        # ====================================================
        # VALIDASI ISI
        # ====================================================

        if len(text) < 100:

            print(
                "⚠️ Isi terlalu pendek:",
                len(text)
            )

            return real_url, ""

        print(
            "✅ ISI ARTIKEL BERHASIL:",
            len(text),
            "karakter"
        )

        return (
            real_url,
            text[:MAX_CONTENT_LENGTH]
        )

    except Exception as e:

        print(
            "❌ ERROR get_article_content:",
            repr(e)
        )

        return "", ""


# ============================================================
# SEARCH NEWS
# ============================================================

def search_news_rss(topic, max_results=8):

    articles = []

    try:

        import feedparser

        query = requests.utils.quote(
            topic
        )

        rss_url = (
            "https://news.google.com/rss/search?"
            f"q={query}"
            "&hl=id"
            "&gl=ID"
            "&ceid=ID:id"
        )

        response = requests.get(
            rss_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "Chrome/151.0 Safari/537.36"
                )
            },
            timeout=15
        )

        response.raise_for_status()

        feed = feedparser.parse(
            response.content
        )

        for entry in feed.entries[
            :max_results
        ]:

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

            summary = entry.get(
                "summary",
                ""
            )

            # --------------------------------------------
            # Ambil nama media
            # --------------------------------------------

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

                "Tanggal Berita":
                    published,

                "Media":
                    source,

                "Judul Berita":
                    clean_text(
                        title
                    ),

                "Link Berita":
                    link,

                "Ringkasan":
                    clean_text(
                        summary
                    )
            })

    except Exception as e:

        print(
            f"ERROR search_news_rss: {e}"
        )

    return articles


# ============================================================
# TEST NEWS PIPELINE
# ============================================================

if st.button(
    "🧪 Test News Pipeline",
    use_container_width=True
):

    with st.spinner(
        "🔎 Mencari berita..."
    ):

        test_articles = search_news_rss(
            "Lamongan ekonomi",
            max_results=3
        )

    if not test_articles:

        st.error(
            "❌ Google News tidak menemukan berita."
        )

    else:

        st.success(
            f"✅ Google News menemukan "
            f"{len(test_articles)} berita."
        )

        for i, item in enumerate(
            test_articles
        ):

            st.markdown(
                f"## 📰 Berita {i + 1}"
            )

            title = item.get(
                "Judul Berita",
                ""
            )

            media = item.get(
                "Media",
                ""
            )

            google_url = item.get(
                "Link Berita",
                ""
            )

            st.write(
                f"**Judul:** {title}"
            )

            st.write(
                f"**Media:** {media}"
            )

            st.write(
                "**URL Google News:**"
            )

            st.code(
                google_url
            )

            # =================================================
            # AMBIL ARTIKEL
            # =================================================

            with st.spinner(
                "🔎 Mencari URL artikel asli..."
            ):

                real_url, content = get_article_content(
                    title=title,
                    media=media,
                    google_url=google_url
                )
            )

            # =================================================
            # URL ASLI
            # =================================================

            if real_url:

                st.success(
                    "✅ URL artikel asli ditemukan!"
                )

                st.write(
                    "**URL Artikel Asli:**"
                )

                st.code(
                    real_url
                )

            else:

                st.error(
                    "❌ URL artikel asli tidak ditemukan."
                )

            # =================================================
            # ISI ARTIKEL
            # =================================================

            if content:

                st.success(
                    f"✅ Isi artikel berhasil "
                    f"diambil "
                    f"({len(content):,} karakter)"
                )

                st.text_area(
                    f"📄 Isi Artikel {i + 1}",
                    content,
                    height=300,
                    key=f"article_{i}"
                )

            else:

                st.warning(
                    "⚠️ URL ditemukan atau dicari, "
                    "tetapi isi artikel gagal diambil."
                )

            st.divider()
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

import os
import re
import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from urllib.parse import quote
from difflib import SequenceMatcher
import io
import base64

import streamlit as st
import pandas as pd
import feedparser
import requests
from bs4 import BeautifulSoup
import plotly.express as px
from google import genai

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
# GEMINI
# ============================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

if not GEMINI_API_KEY:
    try:
        GEMINI_API_KEY = st.secrets.get(
            "GEMINI_API_KEY",
            ""
        )
    except Exception:
        GEMINI_API_KEY = ""


client = None

if GEMINI_API_KEY:

    try:

        client = genai.Client(
            api_key=GEMINI_API_KEY
        )

    except Exception as e:

        logger.error(
            f"Gagal membuat Gemini client: {e}"
        )

        client = None


# ============================================================
# MODEL GEMINI
# ============================================================

GEMINI_MODEL = "gemini-2.5-flash"


# ============================================================
# PARAMETER SCRAPING
# ============================================================

REQUEST_TIMEOUT = 12

MAX_ARTICLES_PER_SITE = 20

MAX_TOTAL_ARTICLES = 80

ARTICLE_WORKERS = 8

MIN_CONTENT_LENGTH = 250


# ============================================================
# MASTER SEKTOR BPS
# ============================================================

SEKTOR_BPS = {

    "A":
        "A - Pertanian, Kehutanan, dan Perikanan",

    "B":
        "B - Pertambangan dan Penggalian",

    "C":
        "C - Industri Pengolahan",

    "D":
        "D - Pengadaan Listrik dan Gas",

    "E":
        "E - Pengadaan Air, Pengelolaan Sampah, Limbah dan Daur Ulang",

    "F":
        "F - Konstruksi",

    "G":
        "G - Perdagangan Besar dan Eceran; Reparasi Mobil dan Sepeda Motor",

    "H":
        "H - Transportasi dan Pergudangan",

    "I":
        "I - Penyediaan Akomodasi dan Makan Minum",

    "J":
        "J - Informasi dan Komunikasi",

    "K":
        "K - Jasa Keuangan dan Asuransi",

    "L":
        "L - Real Estat",

    "MN":
        "M,N - Jasa Perusahaan",

    "O":
        "O - Administrasi Pemerintahan, Pertahanan dan Jaminan Sosial Wajib",

    "P":
        "P - Jasa Pendidikan",

    "Q":
        "Q - Jasa Kesehatan dan Kegiatan Sosial",

    "RSTU":
        "R,S,T,U - Jasa Lainnya"
}


# ============================================================
# DAFTAR MEDIA
# ============================================================

MEDIA_SOURCES = [

    {
        "name": "ANTARA Jatim",
        "domain": "jatim.antaranews.com",
        "search_urls": [
            "https://jatim.antaranews.com/search?q=Lamongan"
        ]
    },

    {
        "name": "Radar Lamongan",
        "domain": "radarlamongan.jawapos.com",
        "search_urls": [
            "https://radarlamongan.jawapos.com/"
        ]
    },

    {
        "name": "KlikJatim",
        "domain": "klikjatim.com",
        "search_urls": [
            "https://klikjatim.com/?s=Lamongan"
        ]
    },

    {
        "name": "Detik Jatim",
        "domain": "detik.com",
        "search_urls": [
            "https://www.detik.com/jatim/search/searchall?query=Lamongan"
        ]
    },

    {
        "name": "Kompas",
        "domain": "kompas.com",
        "search_urls": [
            "https://search.kompas.com/search/?q=Lamongan"
        ]
    }
]


# ============================================================
# USER AGENT
# ============================================================

HEADERS = {

    "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36",

    "Accept":
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8",

    "Accept-Language":
        "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7"
}


# ============================================================
# CSS
# ============================================================

st.markdown(
r"""
<style>

.stApp {
    background:
        linear-gradient(
            180deg,
            #F7FBFE 0%,
            #EEF7FC 100%
        );
}

.block-container {
    padding-top: 1.5rem;
    padding-bottom: 3rem;
}

.dashboard-title {
    font-size: 32px;
    font-weight: 800;
    color: #075985;
    margin-bottom: 2px;
}

.dashboard-subtitle {
    color: #64748B;
    font-size: 15px;
    margin-bottom: 20px;
}

.kpi-card {
    background: white;
    border: 1px solid #DCEAF3;
    border-radius: 15px;
    padding: 20px;
    box-shadow: 0 4px 15px rgba(15, 23, 42, 0.05);
}

.kpi-title {
    color: #64748B;
    font-size: 13px;
}

.kpi-value {
    color: #075985;
    font-size: 28px;
    font-weight: 800;
}

.news-card {
    background: white;
    border: 1px solid #DCEAF3;
    border-radius: 15px;
    padding: 18px;
    margin-bottom: 14px;
    box-shadow: 0 3px 12px rgba(15, 23, 42, 0.04);
}

.news-title {
    color: #0F172A;
    font-size: 18px;
    font-weight: 750;
}

.news-meta {
    color: #64748B;
    font-size: 13px;
    margin-top: 5px;
}

.news-summary {
    color: #334155;
    font-size: 14px;
    line-height: 1.6;
    margin-top: 10px;
}

.badge {
    display: inline-block;
    padding: 4px 9px;
    border-radius: 20px;
    background: #E0F2FE;
    color: #0369A1;
    font-size: 12px;
    margin-right: 5px;
}

.section-title {
    color: #075985;
    font-size: 21px;
    font-weight: 750;
    margin-top: 20px;
    margin-bottom: 12px;
}

</style>
""",
unsafe_allow_html=True
)


# ============================================================
# UTILITY
# ============================================================

def clean_text(text):

    if text is None:
        return ""

    text = str(text)

    text = BeautifulSoup(
        text,
        "html.parser"
    ).get_text(" ")

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

    text = clean_text(text).lower()

    text = re.sub(
        r"http\S+|www\S+",
        " ",
        text
    )

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
# NORMALIZE URL
# ============================================================

def normalize_url(url):

    if not url:
        return ""

    url = str(url).strip()

    parsed = urlparse(url)

    clean = (
        parsed.scheme
        + "://"
        + parsed.netloc
        + parsed.path
    )

    return clean.rstrip("/")


# ============================================================
# ID ARTIKEL
# ============================================================

def make_id(title, url):

    value = (
        normalize_text(title)
        + "|"
        + normalize_url(url)
    )

    return hashlib.md5(
        value.encode("utf-8")
    ).hexdigest()[:16]


# ============================================================
# REQUEST WEB
# ============================================================

def request_page(url):

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:

            logger.warning(
                f"HTTP {response.status_code}: {url}"
            )

            return ""

        return response.text

    except Exception as e:

        logger.warning(
            f"Gagal mengambil {url}: {e}"
        )

        return ""


# ============================================================
# CEK URL BERITA
# ============================================================

def looks_like_article_url(url):

    if not url:
        return False

    url_low = url.lower()

    blocked = [

        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        "/tag/",
        "/category/",
        "/author/",
        "/video/",
        "/foto/",
        "/login",
        "/search"

    ]

    for item in blocked:

        if item in url_low:

            return False

    return True


# ============================================================
# EKSTRAK LINK DARI HALAMAN
# ============================================================

def extract_links(
    html,
    base_url,
    domain
):

    if not html:
        return []

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    links = []

    for a in soup.find_all("a", href=True):

        href = a.get("href", "")

        title = clean_text(
            a.get_text(" ")
        )

        if not href:
            continue

        url = urljoin(
            base_url,
            href
        )

        parsed = urlparse(url)

        if domain not in parsed.netloc:
            continue

        if not looks_like_article_url(url):
            continue

        if len(title) < 20:
            continue

        links.append(
            {
                "url": normalize_url(url),
                "title_hint": title
            }
        )

    # deduplicate

    seen = set()

    result = []

    for item in links:

        if item["url"] in seen:
            continue

        seen.add(
            item["url"]
        )

        result.append(item)

    return result


# ============================================================
# SCRAPE HALAMAN ARTIKEL
# ============================================================

def scrape_article(
    url,
    media
):

    html = request_page(url)

    if not html:

        return None

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    title = ""

    meta_title = soup.find(
        "meta",
        property="og:title"
    )

    if meta_title:

        title = meta_title.get(
            "content",
            ""
        )

    if not title and soup.title:

        title = soup.title.get_text(
            " ",
            strip=True
        )

    if not title:

        h1 = soup.find("h1")

        if h1:

            title = h1.get_text(
                " ",
                strip=True
            )

    title = clean_text(
        title
    )


    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    date_value = ""

    meta_dates = [

        ("meta", {"property": "article:published_time"}),

        ("meta", {"property": "datePublished"}),

        ("meta", {"name": "date"}),

        ("meta", {"name": "publish-date"}),

        ("meta", {"itemprop": "datePublished"})

    ]

    for tag_name, attrs in meta_dates:

        tag = soup.find(
            tag_name,
            attrs
        )

        if tag:

            date_value = (
                tag.get("content")
                or
                tag.get("datetime")
                or
                ""
            )

            if date_value:
                break


    if not date_value:

        time_tag = soup.find(
            "time"
        )

        if time_tag:

            date_value = (
                time_tag.get("datetime")
                or
                time_tag.get_text(" ", strip=True)
            )


    # --------------------------------------------------------
    # CONTENT
    # --------------------------------------------------------

    content_candidates = [

        "article",

        '[itemprop="articleBody"]',

        ".article-content",

        ".article__content",

        ".content-detail",

        ".detail-content",

        ".read-page--content",

        ".post-content",

        ".entry-content",

        ".article-body"

    ]


    content_node = None


    for selector in content_candidates:

        try:

            node = soup.select_one(
                selector
            )

            if node:

                text = clean_text(
                    node.get_text(" ")
                )

                if len(text) > 300:

                    content_node = node

                    break

        except Exception:

            continue


    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------

    if content_node is None:

        paragraphs = soup.find_all(
            "p"
        )

        paragraph_texts = []

        for p in paragraphs:

            txt = clean_text(
                p.get_text(" ")
            )

            if len(txt) >= 40:

                paragraph_texts.append(
                    txt
                )

        content = " ".join(
            paragraph_texts
        )

    else:

        # hapus elemen yang tidak dibutuhkan

        for unwanted in content_node.find_all(
            [
                "script",
                "style",
                "nav",
                "footer",
                "aside",
                "form",
                "figure"
            ]
        ):

            unwanted.decompose()

        content = clean_text(
            content_node.get_text(" ")
        )


    # --------------------------------------------------------
    # BERSIHKAN
    # --------------------------------------------------------

    content = re.sub(
        r"\s+",
        " ",
        content
    ).strip()


    # --------------------------------------------------------
    # VALIDASI
    # --------------------------------------------------------

    if len(content) < MIN_CONTENT_LENGTH:

        logger.info(
            f"Isi terlalu pendek: {url}"
        )

        return None


    if not title:

        return None


    return {

        "id":
            make_id(
                title,
                url
            ),

        "title":
            title,

        "url":
            normalize_url(url),

        "source":
            media,

        "date":
            date_value,

        "content":
            content

    }


# ============================================================
# SCRAPE SATU MEDIA
# ============================================================

def scrape_media(
    media_config
):

    media_name = media_config[
        "name"
    ]

    domain = media_config[
        "domain"
    ]

    all_links = []


    for search_url in media_config[
        "search_urls"
    ]:

        html = request_page(
            search_url
        )

        if not html:
            continue

        links = extract_links(
            html,
            search_url,
            domain
        )

        all_links.extend(
            links
        )


    # deduplicate

    seen = set()

    unique_links = []

    for item in all_links:

        url = item["url"]

        if url in seen:
            continue

        seen.add(url)

        unique_links.append(
            item
        )


    unique_links = unique_links[
        :MAX_ARTICLES_PER_SITE
    ]


    articles = []


    for item in unique_links:

        article = scrape_article(

            item["url"],

            media_name

        )

        if article:

            articles.append(
                article
            )


    return articles


# ============================================================
# SCRAPING SEMUA MEDIA
# ============================================================

def scrape_all_media():

    all_articles = []


    progress = st.progress(
        0
    )

    status = st.empty()


    total_media = len(
        MEDIA_SOURCES
    )


    with ThreadPoolExecutor(
        max_workers=5
    ) as executor:

        futures = {

            executor.submit(
                scrape_media,
                media
            ):
            media["name"]

            for media
            in MEDIA_SOURCES

        }


        completed = 0


        for future in as_completed(
            futures
        ):

            media_name = futures[
                future
            ]

            try:

                result = future.result()

                all_articles.extend(
                    result
                )

                logger.info(
                    f"{media_name}: "
                    f"{len(result)} artikel"
                )

            except Exception as e:

                logger.error(
                    f"{media_name}: {e}"
                )

            completed += 1

            progress.progress(
                completed
                /
                total_media
            )

            status.info(
                f"🌐 Scraping {media_name} "
                f"({completed}/{total_media})..."
            )


    progress.empty()

    status.empty()


    # URL deduplication

    unique = {}

    for article in all_articles:

        url = article["url"]

        if url not in unique:

            unique[url] = article


    articles = list(
        unique.values()
    )


    # batasi total

    articles = articles[
        :MAX_TOTAL_ARTICLES
    ]


    return articles


# ============================================================
# SIMILARITAS JUDUL
# ============================================================

def title_similarity(
    a,
    b
):

    a = normalize_text(a)

    b = normalize_text(b)

    if not a or not b:

        return 0

    return SequenceMatcher(
        None,
        a,
        b
    ).ratio()


# ============================================================
# SIMILARITAS ISI
# ============================================================

def content_similarity(
    a,
    b
):

    a = normalize_text(a)[:5000]

    b = normalize_text(b)[:5000]

    if len(a) < 200 or len(b) < 200:

        return 0

    return SequenceMatcher(
        None,
        a,
        b
    ).ratio()


# ============================================================
# SKOR ARTIKEL
# ============================================================

def article_quality_score(
    article
):

    content = article.get(
        "content",
        ""
    )

    score = len(
        content
    )

    # bonus jika memiliki angka

    numbers = re.findall(
        r"\b\d+(?:[.,]\d+)?\b",
        content
    )

    score += (
        len(numbers)
        *
        20
    )

    # bonus jika ada kutipan

    if (
        '"'
        in
        content
    ):

        score += 100


    return score


# ============================================================
# DEDUPLIKASI ANTAR MEDIA
# ============================================================

def deduplicate_articles(
    articles
):

    if not articles:

        return []


    articles = sorted(

        articles,

        key=article_quality_score,

        reverse=True

    )


    selected = []


    for article in articles:

        duplicate = False


        for existing in selected:

            title_sim = title_similarity(

                article["title"],

                existing["title"]

            )


            content_sim = content_similarity(

                article["content"],

                existing["content"]

            )


            # Judul hampir sama

            if title_sim >= 0.90:

                duplicate = True

                break


            # Isi sangat sama

            if content_sim >= 0.82:

                duplicate = True

                break


            # Judul cukup mirip + isi mirip

            if (
                title_sim >= 0.72
                and
                content_sim >= 0.55
            ):

                duplicate = True

                break


        if not duplicate:

            selected.append(
                article
            )


    return selected


# ============================================================
# LOAD DATA LAMA
# ============================================================

def load_existing_data():

    if not os.path.exists(
        DATA_FILE
    ):

        return pd.DataFrame(
            columns=[
                "ID",
                "Tanggal Berita",
                "Media",
                "Judul Berita",
                "Isu Ekonomi",
                "Sektor",
                "Ringkasan Berita",
                "Link Berita"
            ]
        )


    try:

        df = pd.read_csv(
            DATA_FILE,
            encoding="utf-8-sig"
        )

        return df

    except Exception as e:

        logger.error(
            f"Gagal membaca CSV: {e}"
        )

        return pd.DataFrame()


# ============================================================
# SIMPAN DATA
# ============================================================

def save_data(df):

    try:

        df.to_csv(
            DATA_FILE,
            index=False,
            encoding="utf-8-sig"
        )

        return True

    except Exception as e:

        logger.error(
            f"Gagal menyimpan data: {e}"
        )

        return False


# ============================================================
# FILTER ARTIKEL LAMA
# ============================================================

def filter_existing_articles(
    articles,
    existing_df
):

    if existing_df.empty:

        return articles


    old_urls = set()

    old_titles = []


    if "Link Berita" in existing_df.columns:

        old_urls = {

            normalize_url(x)

            for x in existing_df[
                "Link Berita"
            ]
            .dropna()
            .astype(str)

        }


    if "Judul Berita" in existing_df.columns:

        old_titles = [

            normalize_text(x)

            for x in existing_df[
                "Judul Berita"
            ]
            .dropna()
            .astype(str)

        ]


    result = []


    for article in articles:

        url = normalize_url(
            article["url"]
        )

        title = normalize_text(
            article["title"]
        )


        if url in old_urls:

            continue


        duplicate = False


        for old_title in old_titles:

            if SequenceMatcher(
                None,
                title,
                old_title
            ).ratio() >= 0.92:

                duplicate = True

                break


        if not duplicate:

            result.append(
                article
            )


    return result


# ============================================================
# GEMINI PROMPT
# ============================================================

def create_gemini_prompt(
    articles
):

    text_blocks = []


    for article in articles:

        content = clean_text(
            article["content"]
        )

        # jangan terlalu besar
        content = content[:9000]


        text_blocks.append(

            f"""
ID: {article["id"]}

MEDIA:
{article["source"]}

JUDUL:
{article["title"]}

ISI ARTIKEL:
{content}

URL:
{article["url"]}

------------------------------------------------------------
"""

        )


    sector_text = "\n".join(

        [
            f"{k} = {v}"
            for k, v
            in SEKTOR_BPS.items()
        ]

    )


    prompt = f"""
Anda adalah analis berita ekonomi
BPS Kabupaten Lamongan.

TUGAS ANDA:

Baca ISI ARTIKEL secara menyeluruh.

JANGAN menentukan klasifikasi hanya dari judul.

Untuk setiap artikel:

1. Tentukan apakah berita tersebut benar-benar berkaitan
   dengan aktivitas ekonomi atau sektor lapangan usaha
   di Kabupaten Lamongan.

2. Jika ekonomi=true:
   pilih tepat SATU sektor BPS.

3. Tentukan satu isu ekonomi utama.

4. Buat ringkasan berdasarkan ISI ARTIKEL.

5. Jangan mengarang fakta.

6. Jangan menggunakan informasi dari luar artikel.

7. Ringkasan harus berbeda dari judul.

8. Ringkasan 2-3 kalimat.

9. Maksimal 100 kata.

10. Jika ada angka, nilai transaksi, produksi,
    jumlah pelaku usaha, luas lahan, harga,
    pendapatan, investasi atau data penting lainnya,
    masukkan jika relevan.

============================================================
SEKTOR BPS
============================================================

{sector_text}

============================================================
ATURAN PEMILIHAN SEKTOR
============================================================

A:
pertanian, sawah, padi, jagung, petani,
perkebunan, kehutanan, perikanan,
nelayan, tambak, budidaya ikan.

B:
pertambangan dan penggalian.

C:
pabrik, industri pengolahan,
manufaktur, produksi barang.

D:
listrik dan gas.

E:
air, sampah, limbah, daur ulang.

F:
jalan, jembatan, gedung,
proyek konstruksi, pembangunan fisik.

G:
pasar, perdagangan, pedagang,
toko, jual beli, grosir, eceran,
UMKM yang fokus pada aktivitas perdagangan.

H:
angkutan, transportasi,
logistik, ekspedisi, pergudangan.

I:
hotel, restoran, rumah makan,
kuliner, penginapan.

J:
internet, telekomunikasi,
teknologi informasi, media,
komunikasi digital.

K:
bank, kredit, pembiayaan,
asuransi, jasa keuangan.

L:
properti, perumahan,
real estate.

MN:
konsultan dan jasa perusahaan.

O:
administrasi pemerintahan sebagai
aktivitas ekonomi utama.

P:
sekolah, universitas,
jasa pendidikan.

Q:
rumah sakit, klinik,
puskesmas, jasa kesehatan.

RSTU:
wisata, hiburan, olahraga profesional,
dan jasa lainnya.

============================================================
ATURAN PENTING
============================================================

Jangan otomatis memilih O hanya karena
berita menyebut Bupati, Pemkab, Dinas atau Pemerintah.

Contoh:

"Pemerintah memperbaiki jalan untuk mendukung
akses distribusi hasil pertanian."

→ sektor F jika fokus utama adalah konstruksi jalan.

"Pemerintah memberikan bantuan kepada petani
untuk meningkatkan produksi padi."

→ sektor A.

"Festival melibatkan 155 UMKM dan menghasilkan
transaksi Rp210 juta."

→ sektor G jika fokus pada aktivitas perdagangan UMKM.

"Festival wisata meningkatkan kunjungan wisatawan
dan aktivitas hotel/restoran."

→ sektor I atau RSTU berdasarkan aktivitas utama
yang paling dominan dalam isi berita.

============================================================
RINGKASAN
============================================================

Jangan menulis:

"Berita ini membahas..."

Jangan hanya mengubah judul.

Ringkasan harus menjelaskan:

- apa yang terjadi
- siapa yang terlibat
- lokasi
- angka/data penting
- tujuan/dampak jika tersedia

============================================================
BERITA
============================================================

{"".join(text_blocks)}
"""

    return prompt


# ============================================================
# GEMINI ANALYSIS
# ============================================================

def analyze_with_gemini(
    articles
):

    if not articles:

        return []


    if client is None:

        logger.error(
            "Gemini tidak aktif."
        )

        return []


    prompt = create_gemini_prompt(
        articles
    )


    schema = {

        "type": "array",

        "items": {

            "type": "object",

            "properties": {

                "id": {
                    "type": "string"
                },

                "ekonomi": {
                    "type": "boolean"
                },

                "sektor_kode": {
                    "type": "string",
                    "enum": [
                        "A",
                        "B",
                        "C",
                        "D",
                        "E",
                        "F",
                        "G",
                        "H",
                        "I",
                        "J",
                        "K",
                        "L",
                        "MN",
                        "O",
                        "P",
                        "Q",
                        "RSTU",
                        ""
                    ]
                },

                "isu_ekonomi": {
                    "type": "string"
                },

                "ringkasan": {
                    "type": "string"
                }

            },

            "required": [
                "id",
                "ekonomi",
                "sektor_kode",
                "isu_ekonomi",
                "ringkasan"
            ]

        }

    }


    try:

        response = client.models.generate_content(

            model=GEMINI_MODEL,

            contents=prompt,

            config={

                "response_mime_type":
                    "application/json",

                "response_json_schema":
                    schema,

                "temperature":
                    0.15,

                "max_output_tokens":
                    12000

            }

        )


        raw = (
            response.text
            or
            ""
        ).strip()


        if not raw:

            return []


        results = json.loads(
            raw
        )


        if isinstance(
            results,
            list
        ):

            return results


        return []


    except Exception as e:

        logger.error(
            f"Gemini error: {e}"
        )

        return []


# ============================================================
# CEK SEKTOR
# ============================================================

def valid_sector(
    code
):

    if not code:

        return ""

    code = str(
        code
    ).strip().upper()

    if code in SEKTOR_BPS:

        return code

    return ""


# ============================================================
# FALLBACK SEKTOR
# ============================================================

def fallback_sector(
    article
):

    text = normalize_text(

        article.get(
            "content",
            ""
        )

    )


    mapping = {

        "padi": "A",
        "jagung": "A",
        "petani": "A",
        "sawah": "A",
        "panen": "A",
        "nelayan": "A",
        "tambak": "A",
        "perikanan": "A",
        "ikan": "A",
        "pertanian": "A",

        "tambang": "B",
        "pertambangan": "B",

        "pabrik": "C",
        "industri": "C",
        "manufaktur": "C",

        "listrik": "D",
        "gas": "D",

        "sampah": "E",
        "limbah": "E",

        "jalan": "F",
        "jembatan": "F",
        "gedung": "F",
        "konstruksi": "F",

        "perdagangan": "G",
        "pedagang": "G",
        "pasar": "G",
        "toko": "G",
        "umkm": "G",
        "transaksi": "G",

        "transportasi": "H",
        "angkutan": "H",
        "logistik": "H",
        "ekspedisi": "H",
        "gudang": "H",

        "hotel": "I",
        "restoran": "I",
        "rumah makan": "I",
        "kuliner": "I",
        "penginapan": "I",

        "internet": "J",
        "telekomunikasi": "J",
        "digital": "J",

        "bank": "K",
        "kredit": "K",
        "asuransi": "K",
        "keuangan": "K",

        "properti": "L",
        "perumahan": "L",
        "real estate": "L",

        "konsultan": "MN",

        "pemerintah": "O",

        "sekolah": "P",
        "universitas": "P",
        "pendidikan": "P",

        "rumah sakit": "Q",
        "puskesmas": "Q",
        "klinik": "Q",
        "kesehatan": "Q",

        "wisata": "RSTU",
        "hiburan": "RSTU",
        "olahraga": "RSTU"
    }


    # frasa panjang dulu

    mapping_sorted = sorted(

        mapping.items(),

        key=lambda x: len(x[0]),

        reverse=True

    )


    for keyword, code in mapping_sorted:

        if keyword in text:

            return code


    return ""


# ============================================================
# VALIDASI RINGKASAN
# ============================================================

def summary_is_bad(
    title,
    summary
):

    title_n = normalize_text(
        title
    )

    summary_n = normalize_text(
        summary
    )


    if len(summary_n) < 80:

        return True


    similarity = SequenceMatcher(
        None,
        title_n,
        summary_n
    ).ratio()


    title_words = set(
        title_n.split()
    )

    summary_words = set(
        summary_n.split()
    )


    overlap = 0


    if title_words:

        overlap = len(
            title_words
            &
            summary_words
        ) / len(
            title_words
        )


    if similarity >= 0.70:

        return True


    if overlap >= 0.80:

        return True


    return False


# ============================================================
# REGENERATE SUMMARY
# ============================================================

def regenerate_summary(
    article
):

    if client is None:

        return ""


    prompt = f"""
Buat ringkasan berita berdasarkan ISI ARTIKEL.

JANGAN menggunakan judul sebagai sumber utama.

JUDUL:
{article["title"]}

ISI:
{article["content"][:9000]}

ATURAN:

- 2 sampai 3 kalimat.
- Maksimal 100 kata.
- Jelaskan fakta dari isi artikel.
- Sebutkan pelaku/pihak terkait.
- Masukkan angka penting jika ada.
- Sebutkan lokasi jika tersedia.
- Jangan mengarang.
- Jangan menggunakan kalimat:
  "Berita ini membahas..."
  "Artikel ini membahas..."
- Jangan hanya mengulang judul.

Hanya berikan ringkasan.
"""


    try:

        response = client.models.generate_content(

            model=GEMINI_MODEL,

            contents=prompt,

            config={
                "temperature": 0.2,
                "max_output_tokens": 500
            }

        )


        return clean_text(
            response.text
        )


    except Exception as e:

        logger.warning(
            f"Regenerate summary gagal: {e}"
        )

        return ""


# ============================================================
# PROSES HASIL AI
# ============================================================

def process_ai_result(
    article,
    result
):

    ekonomi = result.get(
        "ekonomi",
        False
    )


    if ekonomi is not True:

        return None


    sector_code = valid_sector(

        result.get(
            "sektor_kode",
            ""
        )

    )


    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------

    if not sector_code:

        sector_code = fallback_sector(
            article
        )


    # --------------------------------------------------------
    # JIKA TETAP KOSONG
    # --------------------------------------------------------

    if not sector_code:

        logger.warning(
            "Sektor tidak ditemukan: "
            + article["title"]
        )

        # Jangan tampilkan sebagai sektor kosong.
        # Tandai perlu review.

        sector_name = "Perlu Review"

    else:

        sector_name = SEKTOR_BPS[
            sector_code
        ]


    issue = clean_text(

        result.get(
            "isu_ekonomi",
            ""
        )

    )


    if not issue:

        issue = "Ekonomi Daerah"


    summary = clean_text(

        result.get(
            "ringkasan",
            ""
        )

    )


    # --------------------------------------------------------
    # PERBAIKI RINGKASAN
    # --------------------------------------------------------

    if summary_is_bad(

        article["title"],

        summary

    ):

        new_summary = regenerate_summary(
            article
        )

        if new_summary:

            summary = new_summary


    return {

        "ID":
            article["id"],

        "Tanggal Berita":
            article.get(
                "date",
                ""
            ),

        "Media":
            article["source"],

        "Judul Berita":
            article["title"],

        "Isu Ekonomi":
            issue,

        "Sektor":
            sector_name,

        "Ringkasan Berita":
            summary,

        "Link Berita":
            article["url"]

    }


# ============================================================
# TANGGAL
# ============================================================

def clean_date(
    value
):

    if not value:

        return ""


    try:

        dt = pd.to_datetime(
            value,
            errors="coerce"
        )

        if pd.isna(dt):

            return ""

        return dt.strftime(
            "%Y-%m-%d"
        )

    except Exception:

        return ""


# ============================================================
# FETCH + PROCESS
# ============================================================

def fetch_and_process_news():

    if client is None:

        st.error(
            "❌ Gemini API belum aktif. "
            "Tambahkan GEMINI_API_KEY di Streamlit Secrets."
        )

        return load_existing_data()


    existing_df = load_existing_data()


    # ========================================================
    # SCRAPING
    # ========================================================

    st.markdown(
        "### 🌐 1. Scraping berita dari web"
    )


    articles = scrape_all_media()


    st.info(
        f"📰 {len(articles)} kandidat artikel ditemukan."
    )


    if not articles:

        st.warning(
            "Tidak ada artikel yang berhasil di-scrape. "
            "Kemungkinan beberapa website memblokir scraping "
            "atau struktur websitenya berubah."
        )

        return existing_df


    # ========================================================
    # FILTER DATA LAMA
    # ========================================================

    articles = filter_existing_articles(

        articles,

        existing_df

    )


    st.info(
        f"🆕 {len(articles)} artikel baru setelah "
        "dibandingkan dengan database."
    )


    if not articles:

        st.success(
            "✅ Tidak ada berita baru."
        )

        return existing_df


    # ========================================================
    # DEDUPLIKASI
    # ========================================================

    st.markdown(
        "### 🔄 2. Menghapus berita duplikat"
    )


    before = len(
        articles
    )


    articles = deduplicate_articles(
        articles
    )


    removed = (
        before
        -
        len(articles)
    )


    st.info(
        f"♻️ {removed} artikel duplikat "
        "dihapus."
    )


    if not articles:

        return existing_df


    # ========================================================
    # GEMINI
    # ========================================================

    st.markdown(
        "### 🤖 3. Gemini AI menganalisis berita"
    )


    all_results = []


    # batch kecil supaya request tidak terlalu besar

    batch_size = 5


    progress = st.progress(
        0
    )


    total_batches = (
        len(articles)
        +
        batch_size
        -
        1
    ) // batch_size


    for start in range(
        0,
        len(articles),
        batch_size
    ):

        batch = articles[
            start:
            start + batch_size
        ]


        batch_number = (
            start // batch_size
        ) + 1


        st.write(
            f"🤖 Menganalisis batch "
            f"{batch_number}/{total_batches}..."
        )


        results = analyze_with_gemini(
            batch
        )


        result_map = {

            str(
                item.get(
                    "id",
                    ""
                )
            ):
            item

            for item
            in results

        }


        for article in batch:

            ai_result = result_map.get(

                article["id"],

                {

                    "ekonomi":
                        False,

                    "sektor_kode":
                        "",

                    "isu_ekonomi":
                        "",

                    "ringkasan":
                        ""

                }

            )


            processed = process_ai_result(

                article,

                ai_result

            )


            if processed:

                processed[
                    "Tanggal Berita"
                ] = clean_date(

                    processed[
                        "Tanggal Berita"
                    ]

                )

                all_results.append(
                    processed
                )


        progress.progress(

            min(

                1.0,

                (
                    start
                    +
                    len(batch)
                )
                /
                len(articles)

            )

        )


    progress.empty()


    # ========================================================
    # DATA BARU
    # ========================================================

    new_df = pd.DataFrame(
        all_results
    )


    # ========================================================
    # GABUNG DATA
    # ========================================================

    if (
        not existing_df.empty
        and
        not new_df.empty
    ):

        combined_df = pd.concat(

            [
                existing_df,
                new_df
            ],

            ignore_index=True

        )

    elif not existing_df.empty:

        combined_df = existing_df

    else:

        combined_df = new_df


    if combined_df.empty:

        return pd.DataFrame()


    # ========================================================
    # NORMALISASI KOLOM
    # ========================================================

    required_columns = [

        "ID",
        "Tanggal Berita",
        "Media",
        "Judul Berita",
        "Isu Ekonomi",
        "Sektor",
        "Ringkasan Berita",
        "Link Berita"

    ]


    for col in required_columns:

        if col not in combined_df.columns:

            combined_df[col] = ""


    combined_df = combined_df[
        required_columns
    ]


    # ========================================================
    # URL DEDUPLICATION
    # ========================================================

    combined_df[
        "_url"
    ] = combined_df[
        "Link Berita"
    ].apply(
        normalize_url
    )


    combined_df = (
        combined_df
        .drop_duplicates(
            subset="_url",
            keep="first"
        )
        .drop(
            columns="_url"
        )
    )


    # ========================================================
    # TITLE DEDUPLICATION
    # ========================================================

    combined_df[
        "_title"
    ] = combined_df[
        "Judul Berita"
    ].apply(
        normalize_text
    )


    combined_df = (
        combined_df
        .drop_duplicates(
            subset="_title",
            keep="first"
        )
        .drop(
            columns="_title"
        )
    )


    # ========================================================
    # SORTING
    # ========================================================

    combined_df[
        "Tanggal Berita"
    ] = pd.to_datetime(

        combined_df[
            "Tanggal Berita"
        ],

        errors="coerce"

    )


    combined_df = (
        combined_df
        .sort_values(
            "Tanggal Berita",
            ascending=False
        )
    )


    combined_df[
        "Tanggal Berita"
    ] = combined_df[
        "Tanggal Berita"
    ].dt.strftime(
        "%Y-%m-%d"
    )


    # ========================================================
    # SIMPAN
    # ========================================================

    save_data(
        combined_df
    )


    st.success(
        f"✅ Selesai. {len(all_results)} "
        "berita ekonomi berhasil dianalisis."
    )


    return combined_df
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
    # 1. Logo BPS Paling Atas
    if BPS_LOGO.exists():
        st.image(BPS_LOGO_URL, width=120)
    
    st.title("Dashboard Control")

    # 2. STATUS GEMINI AI (SG KOMPONEN)
    if client:
        st.success("🟢 Gemini AI: Active")
    else:
        st.error("🔴 Gemini AI: Offline (Cek Secrets)")

    st.divider()
    st.subheader("⚙️ Aksi")
    
    if st.button("🔄 Ambil Berita Terbaru", use_container_width=True):
        new_data = fetch_and_process_news()
        if not new_data.empty:
            st.session_state.data = new_data
            new_data.to_csv(DATA_FILE, index=False, encoding="utf-8-sig")
            st.success("Data berhasil diperbarui!")
            st.rerun()

    if st.button("🗑️ Reset & Bersihkan Data", use_container_width=True):
        st.session_state.data = create_sample_data()
        if DATA_FILE.exists(): DATA_FILE.unlink()
        st.rerun()

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

# FIX BUG 2: Pengecekan aman membaca file logo BPS base64
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

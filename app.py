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

import streamlit as st
import pandas as pd
import feedparser
import requests
from bs4 import BeautifulSoup
import base64
import plotly.express as px
from google import genai
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 📁 LOKASI FILE
# ============================================================

# Mengambil lokasi folder tempat file app.py berada
BASE_DIR = Path(__file__).resolve().parent


# ============================================================
# 🏛️ LOGO BPS
# ============================================================

# Pastikan nama file logo di GitHub adalah:
# logo_bps.png
#
# Jika nama file kamu berbeda, ubah bagian ini.

BPS_LOGO = BASE_DIR / "logo_bps.png"


# ============================================================
# 🔄 KOMPATIBILITAS DENGAN CODING LAMA
# ============================================================

# Variabel ini sengaja tetap dibuat karena kemungkinan
# masih digunakan di bagian lain coding, misalnya:
#
# st.image(BPS_LOGO_URL, width=120)
#
# Dengan begitu kamu tidak perlu mengubah semua bagian
# coding yang sudah menggunakan BPS_LOGO_URL.

BPS_LOGO_URL = str(BPS_LOGO)


# ============================================================
# 🔍 CEK LOGO
# ============================================================

# Jika logo tidak ditemukan, tampilkan peringatan
# tetapi aplikasi tetap bisa berjalan.

if not BPS_LOGO.exists():
    st.warning(
        f"⚠️ File logo BPS tidak ditemukan: {BPS_LOGO.name}"
    )


# ============================================================
# ⚙️ KONFIGURASI STREAMLIT
# ============================================================

st.set_page_config(
    page_title="Monitoring Berita Ekonomi Lamongan - BPS",

    # Logo sebagai icon tab browser
    page_icon=BPS_LOGO_URL,

    layout="wide",

    initial_sidebar_state="expanded"
)


# ============================================================
# 🎨 CUSTOM CSS STYLING
# ============================================================

st.markdown(
"""
<style>

/* ============================================================
   BACKGROUND UTAMA
   ============================================================ */

main {
    background-color: #f8fafc;
}

.block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
}


/* ============================================================
   SEMBUNYIKAN DOWNLOAD CSV BAWAAN STREAMLIT
   ============================================================ */

[data-testid="stElementToolbar"] button[title="Download as CSV"],
[data-testid="stElementToolbar"] button[aria-label="Download as CSV"],
[data-testid="stElementToolbar"] button:has(
    svg path[d*="M19 9h-4V3H9v6H5l7 7 7-7"]
) {
    display: none !important;
}


/* ============================================================
   HEADER DASHBOARD
   ============================================================ */

.dashboard-header {
    background: linear-gradient(
        135deg,
        #1e3a8a 0%,
        #3b82f6 100%
    );

    padding: 24px;

    border-radius: 16px;

    color: white;

    margin-bottom: 25px;

    box-shadow:
        0 4px 12px rgba(30, 58, 138, 0.15);

    display: flex;

    align-items: center;

    gap: 20px;
}


/* ============================================================
   LOGO DASHBOARD
   ============================================================ */

.dashboard-logo {
    width: 75px;

    height: auto;

    background: white;

    padding: 8px;

    border-radius: 12px;

    box-shadow:
        0 2px 8px rgba(0, 0, 0, 0.2);
}


/* ============================================================
   JUDUL DASHBOARD
   ============================================================ */

.dashboard-title {
    font-size: 26px;

    font-weight: 800;

    margin: 0;

    color: #ffffff;
}


/* ============================================================
   SUBJUDUL DASHBOARD
   ============================================================ */

.dashboard-subtitle {
    font-size: 14px;

    color: #e0f2fe;

    margin-top: 4px;
}


/* ============================================================
   JUDUL SECTION
   ============================================================ */

.section-header {
    font-size: 18px;

    font-weight: 700;

    color: #1e293b;

    margin-top: 15px;

    margin-bottom: 15px;

    border-left: 4px solid #2563eb;

    padding-left: 10px;
}


/* ============================================================
   SIDEBAR
   ============================================================ */

[data-testid="stSidebar"] {
    background-color: #f8fafc;
}


/* ============================================================
   TOMBOL
   ============================================================ */

.stButton > button {
    border-radius: 8px;

    font-weight: 600;
}


/* ============================================================
   SELECTBOX
   ============================================================ */

.stSelectbox > div > div {
    border-radius: 8px;
}


/* ============================================================
   DATAFRAME
   ============================================================ */

[data-testid="stDataFrame"] {
    border-radius: 10px;
}


/* ============================================================
   LINK BERITA
   ============================================================ */

a {
    color: #2563eb;
}

</style>
""",
unsafe_allow_html=True
)

# ============================================================
# 📌 SETUP FILE PATHS & GEMINI AI CLIENT
# ============================================================
BASE_DIR = Path(__file__).resolve().parent

DATA_FILE = BASE_DIR / "berita_lamongan.csv"

# Menyimpan berita yang sudah ditolak Gemini
# supaya tidak dianalisis ulang terus-menerus
REJECTED_FILE = BASE_DIR / "berita_ditolak.csv"

LOG_FILE = BASE_DIR / "app.log"


# ============================================================
# 📝 LOGGING
# ============================================================

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s"
)

logger = logging.getLogger(__name__)


# ============================================================
# 🤖 GEMINI AI
# ============================================================

GEMINI_API_KEY = st.secrets.get(
    "GEMINI_API_KEY",
    os.getenv("GEMINI_API_KEY", "")
)

client = None

if GEMINI_API_KEY:

    try:

        client = genai.Client(
            api_key=GEMINI_API_KEY
        )

        logger.info(
            "Gemini AI berhasil diinisialisasi."
        )

    except Exception as e:

        logger.error(
            f"Gagal inisialisasi Gemini Client: {e}"
        )

        client = None


# ============================================================
# 📊 MASTER 17 SEKTOR LAPANGAN USAHA BPS
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
# ⚙️ PENGATURAN KECEPATAN
# ============================================================

# Maksimal berita yang diambil dari setiap pencarian
MAX_RESULTS_PER_TOPIC = 8

# Maksimal total kandidat berita yang diproses
MAX_TOTAL_CANDIDATES = 60

# Jumlah thread untuk mengambil RSS
RSS_WORKERS = 8

# Jumlah thread untuk membuka halaman berita
ARTICLE_WORKERS = 10

# Timeout membuka halaman berita
ARTICLE_TIMEOUT = 6

# Jumlah berita dalam satu request Gemini
AI_BATCH_SIZE = 6

# Panjang isi artikel yang dikirim ke Gemini
MAX_CONTENT_FOR_AI = 7000


# ============================================================
# 🔎 TOPIK PENCARIAN
# ============================================================
#
# Jangan terlalu banyak.
# Terlalu banyak topik = loading lama.
#
# Topik dibuat cukup luas supaya Gemini yang menentukan
# apakah berita tersebut benar-benar ekonomi atau bukan.
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

    "Lamongan pembangunan"

]


# ============================================================
# 🧠 PROMPT GEMINI
# ============================================================
#
# PERATURAN PENTING:
#
# Gemini adalah penentu utama:
# 1. Ekonomi / bukan ekonomi
# 2. Sektor
# 3. Isu ekonomi
# 4. Ringkasan isi artikel
#
# Tidak ada lagi pemaksaan menggunakan keyword.
# ============================================================

AI_CLASSIFICATION_PROMPT = """
Anda adalah analis berita ekonomi untuk
Badan Pusat Statistik Kabupaten Lamongan.

Anda bertugas membaca ISI ARTIKEL yang diberikan
dan menentukan apakah berita tersebut merupakan
BERITA EKONOMI KABUPATEN LAMONGAN atau BUKAN.

============================================================
ATURAN UTAMA
============================================================

JANGAN menentukan berita hanya berdasarkan judul.

JANGAN hanya mencari kata "ekonomi".

Baca dan pahami isi artikel.

Keputusan ekonomi=true atau ekonomi=false
HARUS berdasarkan isi artikel.

============================================================
1. TENTUKAN APAKAH BERITA EKONOMI
============================================================

Berikan:

ekonomi = true

jika isi artikel membahas aktivitas ekonomi,
pembangunan ekonomi, kesejahteraan ekonomi,
usaha, produksi, distribusi, konsumsi, perdagangan,
pertanian, perikanan, industri, UMKM, investasi,
harga, tenaga kerja, keuangan, pariwisata,
infrastruktur ekonomi, pendapatan daerah,
atau kegiatan ekonomi lainnya yang berkaitan
dengan Kabupaten Lamongan.

Berikan:

ekonomi = false

jika berita hanya membahas:

- olahraga
- sepak bola
- Persela
- kriminalitas
- kecelakaan
- kasus polisi
- hukum murni
- politik murni
- pilkada
- konflik politik
- kegiatan seremonial tanpa dampak ekonomi
- hiburan murni
- kegiatan sosial yang tidak memiliki aspek ekonomi
- berita daerah lain yang tidak berkaitan dengan Lamongan

============================================================
2. JANGAN MEMAKSA BERITA MENJADI EKONOMI
============================================================

Jika Anda ragu apakah berita merupakan berita ekonomi,
pilih:

ekonomi = false

Jangan mengubah false menjadi true hanya karena
judul memiliki kata:

- pasar
- harga
- pembangunan
- pemerintah
- UMKM
- petani
- ekonomi

Konteks isi artikel harus mendukung.

============================================================
3. TENTUKAN ISU EKONOMI
============================================================

Jika ekonomi=true, tentukan SATU isu ekonomi utama.

Contoh:

- Pertanian dan Produksi Pangan
- Perikanan
- UMKM
- Perdagangan
- Harga Pangan
- Inflasi
- Industri
- Investasi
- Tenaga Kerja
- Infrastruktur Ekonomi
- Pariwisata
- Keuangan
- Pendapatan Daerah
- Koperasi
- Ekonomi Desa
- Distribusi Barang
- Pembangunan Ekonomi

Pilih isu yang paling menggambarkan isi utama artikel.

============================================================
4. TENTUKAN SEKTOR LAPANGAN USAHA
============================================================

Pilih TEPAT SATU dari 17 sektor berikut:

A - Pertanian, Kehutanan, dan Perikanan

B - Pertambangan dan Penggalian

C - Industri Pengolahan

D - Pengadaan Listrik dan Gas

E - Pengadaan Air, Pengelolaan Sampah, Limbah dan Daur Ulang

F - Konstruksi

G - Perdagangan Besar dan Eceran; Reparasi Mobil dan Sepeda Motor

H - Transportasi dan Pergudangan

I - Penyediaan Akomodasi dan Makan Minum

J - Informasi dan Komunikasi

K - Jasa Keuangan dan Asuransi

L - Real Estat

M,N - Jasa Perusahaan

O - Administrasi Pemerintahan, Pertahanan dan Jaminan Sosial Wajib

P - Jasa Pendidikan

Q - Jasa Kesehatan dan Kegiatan Sosial

R,S,T,U - Jasa Lainnya

============================================================
5. ATURAN PEMILIHAN SEKTOR
============================================================

Pilih berdasarkan AKTIVITAS EKONOMI UTAMA dalam
isi artikel, bukan berdasarkan satu kata.

Contoh:

Petani, padi, sawah, panen, nelayan, tambak,
budidaya ikan, hasil pertanian:

→ A - Pertanian, Kehutanan, dan Perikanan

Pabrik, manufaktur, proses produksi barang:

→ C - Industri Pengolahan

Pembangunan jalan, jembatan, gedung, konstruksi:

→ F - Konstruksi

Pasar, pedagang, toko, transaksi, jual beli,
UMKM, omzet perdagangan:

→ G - Perdagangan Besar dan Eceran;
   Reparasi Mobil dan Sepeda Motor

Hotel, restoran, rumah makan, penginapan:

→ I - Penyediaan Akomodasi dan Makan Minum

Bank, kredit, pembiayaan, asuransi:

→ K - Jasa Keuangan dan Asuransi

============================================================
6. RINGKASAN BERITA
============================================================

Ringkasan WAJIB dibuat berdasarkan ISI ARTIKEL.

JANGAN hanya mengulang judul.

JANGAN membuat fakta baru.

JANGAN menggunakan informasi dari luar artikel.

Ringkasan harus:

- menjelaskan kejadian utama
- menjelaskan kegiatan atau kebijakan yang dilakukan
- mencantumkan angka penting jika tersedia
- mencantumkan dampak/tujuan jika disebutkan
- menggunakan bahasa Indonesia yang jelas
- sekitar 2-3 kalimat
- maksimal 80 kata

Jangan menggunakan pembuka generik seperti:

"Pemberitaan ini mengulas..."

Lebih baik langsung menjelaskan informasi utama.

============================================================
DATA BERITA
============================================================

ID:
{article_id}

MEDIA:
{source}

JUDUL:
{title}

ISI ARTIKEL:
{content}

URL:
{url}

============================================================
FORMAT OUTPUT
============================================================

Jawab HANYA JSON ARRAY.

Contoh:

[
    {{
        "id": "123",
        "ekonomi": true,
        "sektor": "A - Pertanian, Kehutanan, dan Perikanan",
        "isu_ekonomi": "Pertanian dan Produksi Pangan",
        "ringkasan": "Pemerintah Kabupaten Lamongan meningkatkan pengelolaan irigasi untuk menjaga ketersediaan air bagi petani selama musim tanam."
    }}
]

Jika bukan ekonomi:

[
    {{
        "id": "123",
        "ekonomi": false,
        "sektor": "Tidak Relevan",
        "isu_ekonomi": "Tidak Relevan",
        "ringkasan": ""
    }}
]
"""


# ============================================================
# 🧹 CLEAN TEXT
# ============================================================

def clean_text(text):

    if not text:
        return ""

    text = BeautifulSoup(
        str(text),
        "html.parser"
    ).get_text(" ")

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


# ============================================================
# 🔤 NORMALISASI TEKS
# ============================================================

def normalize_text(text):

    if not text:
        return ""

    text = str(text).lower()

    text = re.sub(
        r"http\S+|www\S+",
        "",
        text
    )

    text = re.sub(
        r"[^a-z0-9\s]",
        " ",
        text
    )

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


# ============================================================
# 🔤 TOKEN TEKS
# ============================================================

def text_tokens(text):

    normalized = normalize_text(
        text
    )

    return set(
        normalized.split()
    )


# ============================================================
# 📊 JACCARD SIMILARITY
# ============================================================

def jaccard_similarity(text_a, text_b):

    a = text_tokens(text_a)
    b = text_tokens(text_b)

    if not a or not b:
        return 0

    intersection = len(
        a.intersection(b)
    )

    union = len(
        a.union(b)
    )

    if union == 0:
        return 0

    return intersection / union


# ============================================================
# 🆔 ID BERITA
# ============================================================

def make_id(title, link):

    return hashlib.md5(
        (
            str(title) +
            str(link)
        ).encode("utf-8")
    ).hexdigest()


# ============================================================
# 🔗 NORMALISASI URL
# ============================================================

def normalize_url(url):

    if not url:
        return ""

    url = str(url).strip()

    url = url.split("#")[0]

    return url.rstrip("/")


# ============================================================
# 📰 EKSTRAK ISI ARTIKEL
# ============================================================
#
# Tidak menggunakan trafilatura.
#
# Prioritas:
# 1. JSON-LD articleBody
# 2. <article>
# 3. paragraf <p>
# 4. meta description
# 5. RSS summary
# ============================================================

def extract_article_content(
    url,
    fallback_summary=""
):

    if not url:

        return {
            "content": clean_text(
                fallback_summary
            ),

            "canonical_url": ""
        }


    headers = {

        "User-Agent":
        (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/120.0.0.0 "
            "Safari/537.36"
        )

    }


    try:

        response = requests.get(

            url,

            headers=headers,

            timeout=ARTICLE_TIMEOUT,

            allow_redirects=True

        )


        if response.status_code != 200:

            return {

                "content":
                    clean_text(
                        fallback_summary
                    ),

                "canonical_url":
                    normalize_url(
                        response.url
                    )

            }


        soup = BeautifulSoup(

            response.text,

            "html.parser"

        )


        # ====================================================
        # CANONICAL URL
        # ====================================================

        canonical_url = ""

        canonical_tag = soup.find(
            "link",
            rel="canonical"
        )

        if canonical_tag:

            canonical_url = normalize_url(
                canonical_tag.get(
                    "href",
                    ""
                )
            )


        if not canonical_url:

            canonical_url = normalize_url(
                response.url
            )


        # ====================================================
        # HAPUS ELEMENT YANG TIDAK DIBUTUHKAN
        # ====================================================

        for tag in soup.find_all(
            [
                "script",
                "style",
                "nav",
                "header",
                "footer",
                "aside",
                "form",
                "noscript",
                "iframe",
                "svg"
            ]
        ):

            tag.decompose()


        # ====================================================
        # 1. JSON-LD ARTICLE BODY
        # ====================================================

        article_body = ""


        # Parse script JSON-LD dari halaman asli.
        # Karena sebelumnya script dihapus, ambil ulang dari
        # response jika diperlukan.

        original_soup = BeautifulSoup(
            response.text,
            "html.parser"
        )


        for script in original_soup.find_all(
            "script",
            type="application/ld+json"
        ):

            try:

                data = json.loads(
                    script.string or
                    script.get_text()
                )


                objects = []

                if isinstance(
                    data,
                    list
                ):

                    objects = data

                elif isinstance(
                    data,
                    dict
                ):

                    if "@graph" in data:

                        objects = data["@graph"]

                    else:

                        objects = [data]


                for obj in objects:

                    if not isinstance(
                        obj,
                        dict
                    ):

                        continue


                    body = obj.get(
                        "articleBody",
                        ""
                    )


                    if body:

                        article_body = clean_text(
                            body
                        )

                        break


                if len(article_body) >= 300:

                    break


            except Exception:

                continue


        if len(article_body) >= 300:

            return {

                "content":
                    article_body,

                "canonical_url":
                    canonical_url

            }


        # ====================================================
        # 2. TAG ARTICLE
        # ====================================================

        article_tag = soup.find(
            "article"
        )


        if article_tag:

            article_text = clean_text(
                article_tag.get_text(
                    separator=" ",
                    strip=True
                )
            )

            if len(article_text) >= 300:

                return {

                    "content":
                        article_text,

                    "canonical_url":
                        canonical_url

                }


        # ====================================================
        # 3. PARAGRAF
        # ====================================================

        paragraphs = soup.find_all(
            "p"
        )


        paragraph_list = []


        for p in paragraphs:

            text_p = clean_text(
                p.get_text(
                    separator=" ",
                    strip=True
                )
            )


            if len(text_p) >= 40:

                paragraph_list.append(
                    text_p
                )


        article_text = " ".join(
            paragraph_list
        )


        if len(article_text) >= 300:

            return {

                "content":
                    article_text,

                "canonical_url":
                    canonical_url

            }


        # ====================================================
        # 4. META DESCRIPTION
        # ====================================================

        meta = soup.find(
            "meta",
            attrs={
                "name": "description"
            }
        )


        if meta:

            meta_text = clean_text(
                meta.get(
                    "content",
                    ""
                )
            )


            if len(meta_text) >= 100:

                return {

                    "content":
                        meta_text,

                    "canonical_url":
                        canonical_url

                }


        # ====================================================
        # 5. FALLBACK RSS
        # ====================================================

        return {

            "content":
                clean_text(
                    fallback_summary
                ),

            "canonical_url":
                canonical_url

        }


    except Exception as e:

        logger.warning(
            f"Gagal membaca artikel {url}: {e}"
        )


        return {

            "content":
                clean_text(
                    fallback_summary
                ),

            "canonical_url":
                ""

        }


# ============================================================
# 📥 LOAD DATA LAMA
# ============================================================

def load_existing_data():

    if not DATA_FILE.exists():

        return pd.DataFrame()


    try:

        df = pd.read_csv(
            DATA_FILE,
            encoding="utf-8-sig"
        )


        if df.empty:

            return pd.DataFrame()


        return df


    except Exception as e:

        logger.error(
            f"Gagal membaca data lama: {e}"
        )

        return pd.DataFrame()


# ============================================================
# 🚫 LOAD BERITA YANG SUDAH DITOLAK
# ============================================================

def load_rejected_data():

    if not REJECTED_FILE.exists():

        return pd.DataFrame()


    try:

        return pd.read_csv(
            REJECTED_FILE,
            encoding="utf-8-sig"
        )

    except Exception:

        return pd.DataFrame()


# ============================================================
# 💾 SIMPAN BERITA YANG DITOLAK
# ============================================================

def save_rejected_data(
    rejected_articles
):

    if not rejected_articles:

        return


    new_df = pd.DataFrame(
        rejected_articles
    )


    old_df = load_rejected_data()


    if not old_df.empty:

        combined = pd.concat(
            [
                old_df,
                new_df
            ],
            ignore_index=True
        )

    else:

        combined = new_df


    if "URL" in combined.columns:

        combined = combined.drop_duplicates(
            subset=["URL"],
            keep="first"
        )


    try:

        combined.to_csv(
            REJECTED_FILE,
            index=False,
            encoding="utf-8-sig"
        )

    except Exception as e:

        logger.error(
            f"Gagal menyimpan berita ditolak: {e}"
        )


# ============================================================
# 🔎 CEK APAKAH ARTIKEL SUDAH ADA
# ============================================================

def is_already_exists(
    article,
    existing_df,
    rejected_urls
):

    url = normalize_url(
        article.get(
            "url",
            ""
        )
    )


    # --------------------------------------------------------
    # URL yang sama
    # --------------------------------------------------------

    if url in rejected_urls:

        return True


    if not existing_df.empty:

        if "Link Berita" in existing_df.columns:

            existing_urls = set(

                normalize_url(x)

                for x in
                existing_df[
                    "Link Berita"
                ]
                .dropna()
                .astype(str)

            )


            if url in existing_urls:

                return True


    # --------------------------------------------------------
    # Judul yang sama persis
    # --------------------------------------------------------

    title = normalize_text(
        article.get(
            "title",
            ""
        )
    )


    if not title:

        return False


    if not existing_df.empty:

        if "Judul Berita" in existing_df.columns:

            for old_title in (

                existing_df[
                    "Judul Berita"
                ]
                .dropna()
                .astype(str)
                .tolist()

            ):

                old_normalized = normalize_text(
                    old_title
                )


                if (
                    title == old_normalized
                ):

                    return True


    return False


# ============================================================
# 📰 AMBIL SATU RSS
# ============================================================

def fetch_single_rss(
    topic
):

    headers = {

        "User-Agent":
        (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/120.0.0.0 "
            "Safari/537.36"
        )

    }


    try:

        rss_url = (

            "https://news.google.com/rss/search?"

            f"q={quote(topic)}"

            "&hl=id"

            "&gl=ID"

            "&ceid=ID:id"

        )


        response = requests.get(

            rss_url,

            timeout=8,

            headers=headers

        )


        feed = feedparser.parse(
            response.content
        )


        articles = []


        for entry in feed.entries[
            :MAX_RESULTS_PER_TOPIC
        ]:

            title = clean_text(
                entry.get(
                    "title",
                    ""
                )
            )


            link = normalize_url(
                entry.get(
                    "link",
                    ""
                )
            )


            summary = clean_text(
                entry.get(
                    "summary",
                    ""
                )
            )


            if (
                not title
                or
                not link
                or
                len(title) < 10
            ):

                continue


            source_name = (
                "Berita Online"
            )


            if (
                entry.get("source")
                and
                entry.source.get("title")
            ):

                source_name = clean_text(
                    entry.source.get(
                        "title"
                    )
                )


            pub_date = datetime.now().strftime(
                "%Y-%m-%d"
            )


            if entry.get(
                "published_parsed"
            ):

                try:

                    pub_date = datetime(
                        *entry.published_parsed[
                            :6
                        ]
                    ).strftime(
                        "%Y-%m-%d"
                    )

                except Exception:

                    pass


            articles.append({

                "title":
                    title,

                "content":
                    summary,

                "source":
                    source_name,

                "date":
                    pub_date,

                "url":
                    link

            })


        return articles


    except Exception as e:

        logger.error(
            f"RSS error {topic}: {e}"
        )

        return []


# ============================================================
# 📰 AMBIL RSS SECARA PARALEL
# ============================================================
#
# Ini salah satu bagian utama agar loading lebih cepat.
#
# Sebelumnya:
#
# topik 1 → tunggu
# topik 2 → tunggu
# topik 3 → tunggu
#
# Sekarang:
#
# topik 1 ┐
# topik 2 ├── berjalan bersamaan
# topik 3 ┤
# topik 4 ┘
# ============================================================

def fetch_all_rss():

    all_articles = []


    with ThreadPoolExecutor(
        max_workers=RSS_WORKERS
    ) as executor:


        futures = {

            executor.submit(
                fetch_single_rss,
                topic
            ):
                topic

            for topic in SEARCH_TOPICS

        }


        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                all_articles.extend(
                    result
                )

            except Exception as e:

                logger.error(
                    f"RSS worker error: {e}"
                )


    # ========================================================
    # Hilangkan URL duplikat
    # ========================================================

    unique = {}

    for article in all_articles:

        key = normalize_url(
            article["url"]
        )

        if key:

            unique[key] = article


    return list(
        unique.values()
    )


# ============================================================
# 📰 AMBIL ISI ARTIKEL SECARA PARALEL
# ============================================================

def enrich_article(article):

    result = extract_article_content(

        article["url"],

        article.get(
            "content",
            ""
        )

    )


    article["content"] = result.get(
        "content",
        ""
    )


    article["canonical_url"] = result.get(
        "canonical_url",
        ""
    )


    return article


# ============================================================
# 📰 ENRICH SEMUA ARTIKEL
# ============================================================

def enrich_articles_parallel(
    articles,
    progress=None,
    status=None
):

    results = []


    total = len(
        articles
    )


    if total == 0:

        return []


    with ThreadPoolExecutor(
        max_workers=ARTICLE_WORKERS
    ) as executor:


        futures = [

            executor.submit(
                enrich_article,
                article
            )

            for article in articles

        ]


        for i, future in enumerate(
            as_completed(futures),
            start=1
        ):

            try:

                article = future.result()

                results.append(
                    article
                )


            except Exception as e:

                logger.warning(
                    f"Article worker error: {e}"
                )


            if progress:

                progress.progress(
                    min(
                        1.0,
                        i / total
                    )
                )


            if status:

                status.info(
                    f"📖 Membaca isi berita "
                    f"{i}/{total}..."
                )


    return results


# ============================================================
# 🔍 DUPLIKAT BERDASARKAN JUDUL
# ============================================================

def title_similarity(
    title_a,
    title_b
):

    a = normalize_text(
        title_a
    )

    b = normalize_text(
        title_b
    )


    if not a or not b:

        return 0


    if a == b:

        return 1.0


    return SequenceMatcher(
        None,
        a,
        b
    ).ratio()


# ============================================================
# 🔍 DUPLIKAT BERDASARKAN ISI
# ============================================================

def content_similarity(
    content_a,
    content_b
):

    if (
        len(content_a) < 200
        or
        len(content_b) < 200
    ):

        return 0


    # Ambil bagian awal artikel.
    # Bagian awal biasanya berisi inti berita.
    a = normalize_text(
        content_a[:5000]
    )

    b = normalize_text(
        content_b[:5000]
    )


    # Jaccard lebih cepat daripada membandingkan
    # seluruh artikel menggunakan SequenceMatcher.
    jaccard = jaccard_similarity(
        a,
        b
    )


    # SequenceMatcher hanya digunakan jika
    # sudah terlihat cukup mirip.
    if jaccard >= 0.60:

        seq = SequenceMatcher(
            None,
            a[:3000],
            b[:3000]
        ).ratio()

        return max(
            jaccard,
            seq
        )


    return jaccard


# ============================================================
# 🏆 SKOR KELENGKAPAN ARTIKEL
# ============================================================
#
# Jika berita yang sama berasal dari:
#
# Media A = 500 kata
# Media B = 1.200 kata
#
# Media B lebih diprioritaskan.
# ============================================================

def article_quality_score(
    article
):

    content = article.get(
        "content",
        ""
    )


    score = 0


    # Panjang isi
    score += min(
        len(content) / 1000,
        10
    )


    # Jumlah kata
    score += min(
        len(content.split()) / 150,
        10
    )


    # Ada angka/data
    if re.search(
        r"\d",
        content
    ):

        score += 2


    # Ada tanda kutip / pernyataan
    if '"' in content:

        score += 1


    # Ada banyak paragraf
    paragraph_count = len(
        re.findall(
            r"\.",
            content
        )
    )


    score += min(
        paragraph_count / 10,
        5
    )


    return score


# ============================================================
# 🧹 PILIH BERITA TERBAIK DARI DUPLIKAT
# ============================================================
#
# Dua berita dianggap duplikat jika:
#
# 1. Judul sangat mirip
# ATAU
# 2. Isi sangat mirip
#
# Jika duplikat:
#
# → pilih artikel dengan isi paling lengkap.
# ============================================================

def remove_similar_articles(
    articles
):

    selected = []


    # Urutkan dari artikel paling lengkap
    # sehingga artikel berkualitas tinggi
    # menjadi kandidat utama.

    articles = sorted(

        articles,

        key=article_quality_score,

        reverse=True

    )


    for article in articles:

        duplicate = False


        for existing in selected:

            title_sim = title_similarity(

                article["title"],

                existing["title"]

            )


            # Jika judul hampir sama
            if title_sim >= 0.88:

                duplicate = True

                break


            # Jika isi sangat mirip
            content_sim = content_similarity(

                article.get(
                    "content",
                    ""
                ),

                existing.get(
                    "content",
                    ""
                )

            )


            if content_sim >= 0.82:

                duplicate = True

                break


        if not duplicate:

            selected.append(
                article
            )


    return selected


# ============================================================
# 🔎 CEK DUPLIKAT DENGAN DATA LAMA
# ============================================================

def filter_against_existing(
    articles,
    existing_df
):

    if existing_df.empty:

        return articles


    old_titles = []

    old_urls = set()


    if "Judul Berita" in existing_df.columns:

        old_titles = [

            normalize_text(x)

            for x in
            existing_df[
                "Judul Berita"
            ]
            .dropna()
            .astype(str)
            .tolist()

        ]


    if "Link Berita" in existing_df.columns:

        old_urls = {

            normalize_url(x)

            for x in
            existing_df[
                "Link Berita"
            ]
            .dropna()
            .astype(str)
            .tolist()

        }


    result = []


    for article in articles:

        url = normalize_url(
            article["url"]
        )


        if url in old_urls:

            continue


        title = normalize_text(
            article["title"]
        )


        # Judul sama persis
        if title in old_titles:

            continue


        # Judul sangat mirip dengan data lama
        is_old_story = False


        for old_title in old_titles:

            if (
                SequenceMatcher(
                    None,
                    title,
                    old_title
                ).ratio()
                >= 0.92
            ):

                is_old_story = True

                break


        if not is_old_story:

            result.append(
                article
            )


    return result


# ============================================================
# 🤖 ANALISIS GEMINI DALAM BATCH
# ============================================================
#
# Ini membuat loading jauh lebih cepat.
#
# SEBELUM:
#
# berita 1 → Gemini
# berita 2 → Gemini
# berita 3 → Gemini
#
# SEKARANG:
#
# berita 1
# berita 2
# berita 3
# berita 4
# berita 5
# berita 6
#      ↓
# satu request Gemini
# ============================================================

def analyze_batch_with_gemini(
    articles
):

    if not articles:

        return []


    if not client:

        logger.error(
            "Gemini API tidak tersedia."
        )

        return [

            {
                "id":
                    make_id(
                        a["title"],
                        a["url"]
                    ),

                "ekonomi":
                    False,

                "sektor":
                    "Tidak Relevan",

                "isu_ekonomi":
                    "Gemini tidak tersedia",

                "ringkasan":
                    ""

            }

            for a in articles

        ]


    news_blocks = []


    for article in articles:

        article_id = make_id(
            article["title"],
            article["url"]
        )


        content = clean_text(
            article.get(
                "content",
                ""
            )
        )


        # Potong isi agar request cepat
        content = content[
            :MAX_CONTENT_FOR_AI
        ]


        news_blocks.append(

            f"""
--- BERITA ID: {article_id} ---

MEDIA:
{article.get("source", "")}

JUDUL:
{article.get("title", "")}

ISI ARTIKEL:
{content}

URL:
{article.get("url", "")}
"""

        )


    prompt = """

Anda adalah analis berita ekonomi
Badan Pusat Statistik Kabupaten Lamongan.

Analisis SEMUA berita yang diberikan.

Untuk SETIAP berita:

1. Tentukan apakah ekonomi Lamongan atau bukan.
2. Jika ekonomi=true, tentukan isu ekonomi.
3. Pilih tepat satu dari 17 sektor BPS.
4. Buat ringkasan berdasarkan ISI ARTIKEL.

ATURAN SANGAT PENTING:

- Jangan hanya membaca judul.
- Baca isi artikel.
- Jangan membuat fakta baru.
- Jangan menggunakan informasi dari luar artikel.
- Jika bukan ekonomi, ekonomi=false.
- Jangan memaksa berita menjadi ekonomi.
- Berita olahraga murni = false.
- Berita kriminal murni = false.
- Berita politik murni = false.
- Berita hukum murni = false.
- Seremonial tanpa aspek ekonomi = false.
- Berita harus berkaitan dengan Kabupaten Lamongan.

17 SEKTOR:

A - Pertanian, Kehutanan, dan Perikanan
B - Pertambangan dan Penggalian
C - Industri Pengolahan
D - Pengadaan Listrik dan Gas
E - Pengadaan Air, Pengelolaan Sampah, Limbah dan Daur Ulang
F - Konstruksi
G - Perdagangan Besar dan Eceran; Reparasi Mobil dan Sepeda Motor
H - Transportasi dan Pergudangan
I - Penyediaan Akomodasi dan Makan Minum
J - Informasi dan Komunikasi
K - Jasa Keuangan dan Asuransi
L - Real Estat
M,N - Jasa Perusahaan
O - Administrasi Pemerintahan, Pertahanan dan Jaminan Sosial Wajib
P - Jasa Pendidikan
Q - Jasa Kesehatan dan Kegiatan Sosial
R,S,T,U - Jasa Lainnya

RINGKASAN:

- Berdasarkan isi artikel.
- 2-3 kalimat.
- Maksimal 80 kata.
- Jangan hanya mengulang judul.
- Masukkan angka/data penting jika tersedia.
- Jelaskan kejadian utama dan dampaknya jika disebutkan.

Jawab HANYA JSON ARRAY seperti:

[
  {
    "id": "ID",
    "ekonomi": true,
    "sektor": "A - Pertanian, Kehutanan, dan Perikanan",
    "isu_ekonomi": "Pertanian dan Produksi Pangan",
    "ringkasan": "Ringkasan berdasarkan isi artikel."
  }
]

Jika bukan ekonomi:

[
  {
    "id": "ID",
    "ekonomi": false,
    "sektor": "Tidak Relevan",
    "isu_ekonomi": "Tidak Relevan",
    "ringkasan": ""
  }
]

""" + "\n".join(
        news_blocks
    )


    try:

        response = client.models.generate_content(

            model="gemini-2.5-flash",

            contents=prompt

        )


        text_resp = (
            response.text or ""
        ).strip()


        # ====================================================
        # BERSIHKAN MARKDOWN JSON
        # ====================================================

        if "```json" in text_resp:

            text_resp = (
                text_resp
                .split(
                    "```json",
                    1
                )[1]
                .split(
                    "```",
                    1
                )[0]
                .strip()
            )

        elif "```" in text_resp:

            text_resp = (
                text_resp
                .split(
                    "```",
                    1
                )[1]
                .split(
                    "```",
                    1
                )[0]
                .strip()
            )


        results = json.loads(
            text_resp
        )


        if not isinstance(
            results,
            list
        ):

            raise ValueError(
                "Output Gemini bukan JSON array."
            )


        return results


    except Exception as e:

        logger.error(
            f"Gemini batch error: {e}"
        )


        # Jika batch gagal, jangan mengarang hasil.
        return [

            {
                "id":
                    make_id(
                        a["title"],
                        a["url"]
                    ),

                "ekonomi":
                    False,

                "sektor":
                    "Tidak Relevan",

                "isu_ekonomi":
                    "Analisis gagal",

                "ringkasan":
                    ""

            }

            for a in articles

        ]


# ============================================================
# 🧠 VALIDASI HASIL GEMINI
# ============================================================

def validate_ai_result(
    article,
    result
):

    ekonomi = result.get(
        "ekonomi",
        False
    )


    # ========================================================
    # GEMINI MENYATAKAN BUKAN EKONOMI
    # ========================================================

    if ekonomi is not True:

        return {

            "ekonomi":
                False,

            "sektor":
                "Tidak Relevan",

            "isu_ekonomi":
                "Tidak Relevan",

            "ringkasan":
                ""

        }


    # ========================================================
    # VALIDASI SEKTOR
    # ========================================================

    sektor = clean_text(
        result.get(
            "sektor",
            ""
        )
    )


    if sektor not in SEKTOR_BPS:

        logger.warning(
            f"Sektor AI tidak valid: "
            f"{sektor}"
        )


        return {

            "ekonomi":
                False,

            "sektor":
                "Tidak Relevan",

            "isu_ekonomi":
                "Sektor AI tidak valid",

            "ringkasan":
                ""

        }


    # ========================================================
    # ISU
    # ========================================================

    isu = clean_text(
        result.get(
            "isu_ekonomi",
            ""
        )
    )


    if not isu:

        isu = "Ekonomi Daerah"


    # ========================================================
    # RINGKASAN
    # ========================================================

    ringkasan = clean_text(
        result.get(
            "ringkasan",
            ""
        )
    )


    if len(ringkasan) < 30:

        return {

            "ekonomi":
                False,

            "sektor":
                "Tidak Relevan",

            "isu_ekonomi":
                "Ringkasan tidak valid",

            "ringkasan":
                ""

        }


    # ========================================================
    # CEK RINGKASAN TERLALU MIRIP JUDUL
    # ========================================================

    title = normalize_text(
        article.get(
            "title",
            ""
        )
    )


    summary = normalize_text(
        ringkasan
    )


    similarity = SequenceMatcher(
        None,
        title,
        summary
    ).ratio()


    if similarity >= 0.75:

        logger.warning(
            "Ringkasan terlalu mirip judul."
        )


        return {

            "ekonomi":
                False,

            "sektor":
                "Tidak Relevan",

            "isu_ekonomi":
                "Ringkasan terlalu mirip judul",

            "ringkasan":
                ""

        }


    return {

        "ekonomi":
            True,

        "sektor":
            sektor,

        "isu_ekonomi":
            isu,

        "ringkasan":
            ringkasan

    }


# ============================================================
# 📥 FUNGSI UTAMA AMBIL BERITA
# ============================================================

def fetch_and_process_news():

    # ========================================================
    # CEK GEMINI
    # ========================================================

    if not client:

        st.error(
            "❌ Gemini AI belum aktif. "
            "Periksa GEMINI_API_KEY di Streamlit Secrets."
        )

        return pd.DataFrame()


    # ========================================================
    # LOAD DATA LAMA
    # ========================================================

    existing_df = load_existing_data()

    rejected_df = load_rejected_data()


    rejected_urls = set()


    if (
        not rejected_df.empty
        and
        "URL" in rejected_df.columns
    ):

        rejected_urls = {

            normalize_url(x)

            for x in rejected_df[
                "URL"
            ]
            .dropna()
            .astype(str)

        }


    # ========================================================
    # UI PROGRESS
    # ========================================================

    progress = st.progress(
        0
    )

    status = st.empty()


    # ========================================================
    # TAHAP 1
    # AMBIL RSS SECARA PARALEL
    # ========================================================

    status.info(
        "🔎 Mencari berita terbaru dari berbagai media..."
    )


    raw_articles = fetch_all_rss()


    status.info(
        f"📰 Ditemukan {len(raw_articles)} "
        "kandidat berita."
    )


    # ========================================================
    # BATASI TOTAL
    # ========================================================

    raw_articles = raw_articles[
        :MAX_TOTAL_CANDIDATES
    ]


    # ========================================================
    # TAHAP 2
    # LEWATI BERITA YANG SUDAH ADA
    # ========================================================

    new_articles = []


    for article in raw_articles:

        if is_already_exists(
            article,
            existing_df,
            rejected_urls
        ):

            continue


        new_articles.append(
            article
        )


    status.info(
        f"🆕 Ada {len(new_articles)} "
        "berita baru yang perlu diperiksa."
    )


    # ========================================================
    # JIKA TIDAK ADA BERITA BARU
    # ========================================================

    if not new_articles:

        progress.progress(
            1.0
        )

        status.success(
            "✅ Tidak ada berita baru. "
            "Data dashboard sudah terbaru."
        )

        progress.empty()

        return existing_df


    # ========================================================
    # TAHAP 3
    # AMBIL ISI ARTIKEL SECARA PARALEL
    # ========================================================

    progress.progress(
        0.25
    )


    status.info(
        "📖 Membaca isi artikel secara paralel..."
    )


    enriched_articles = (
        enrich_articles_parallel(
            new_articles,
            progress=None,
            status=status
        )
    )


    # ========================================================
    # HANYA ARTIKEL YANG MEMILIKI ISI CUKUP
    # ========================================================

    enriched_articles = [

        article

        for article
        in enriched_articles

        if len(
            article.get(
                "content",
                ""
            )
        ) >= 100

    ]


    status.info(
        f"📚 Berhasil membaca "
        f"{len(enriched_articles)} artikel."
    )


    # ========================================================
    # TAHAP 4
    # HILANGKAN DUPLIKAT BERITA
    # ========================================================

    status.info(
        "🔄 Membandingkan judul dan isi "
        "untuk menghapus berita yang sama..."
    )


    before_dedup = len(
        enriched_articles
    )


    unique_articles = (
        remove_similar_articles(
            enriched_articles
        )
    )


    duplicate_count = (
        before_dedup
        -
        len(unique_articles)
    )


    status.info(
        f"♻️ {duplicate_count} berita duplikat "
        "dihapus. Dipilih artikel dengan isi "
        "paling lengkap."
    )


    # ========================================================
    # TAHAP 5
    # GEMINI BATCH
    # ========================================================

    total_unique = len(
        unique_articles
    )


    if total_unique == 0:

        status.warning(
            "Tidak ada artikel unik yang dapat dianalisis."
        )

        progress.empty()

        return existing_df


    all_ai_results = []


    total_batches = (
        (
            total_unique
            +
            AI_BATCH_SIZE
            -
            1
        )
        //
        AI_BATCH_SIZE
    )


    for batch_number, start in enumerate(

        range(
            0,
            total_unique,
            AI_BATCH_SIZE
        ),

        start=1

    ):

        batch = unique_articles[
            start:
            start + AI_BATCH_SIZE
        ]


        status.info(
            f"🤖 Gemini menganalisis "
            f"batch {batch_number}/{total_batches} "
            f"({len(batch)} berita)..."
        )


        batch_results = (
            analyze_batch_with_gemini(
                batch
            )
        )


        all_ai_results.extend(
            batch_results
        )


        progress.progress(

            0.40
            +
            (
                0.50
                *
                batch_number
                /
                total_batches
            )

        )


    # ========================================================
    # INDEX HASIL AI
    # ========================================================

    ai_by_id = {}


    for result in all_ai_results:

        result_id = str(
            result.get(
                "id",
                ""
            )
        )


        if result_id:

            ai_by_id[
                result_id
            ] = result


    # ========================================================
    # HASIL AKHIR
    # ========================================================

    final_records = []

    rejected_articles = []


    for article in unique_articles:

        article_id = make_id(
            article["title"],
            article["url"]
        )


        ai_raw = ai_by_id.get(

            article_id,

            {

                "ekonomi":
                    False,

                "sektor":
                    "Tidak Relevan",

                "isu_ekonomi":
                    "Tidak Relevan",

                "ringkasan":
                    ""

            }

        )


        ai_result = validate_ai_result(
            article,
            ai_raw
        )


        # ====================================================
        # EKONOMI
        # ====================================================

        if ai_result["ekonomi"]:

            final_records.append({

                "ID":
                    article_id,

                "Tanggal Berita":
                    article["date"],

                "Media":
                    article["source"],

                "Judul Berita":
                    article["title"],

                "Isu Ekonomi":
                    ai_result[
                        "isu_ekonomi"
                    ],

                "Sektor":
                    ai_result[
                        "sektor"
                    ],

                "Ringkasan Berita":
                    ai_result[
                        "ringkasan"
                    ],

                "Link Berita":
                    article["url"]

            })


        # ====================================================
        # BUKAN EKONOMI
        # ====================================================

        else:

            rejected_articles.append({

                "Tanggal":
                    article["date"],

                "Media":
                    article["source"],

                "Judul":
                    article["title"],

                "URL":
                    article["url"]

            })


    # ========================================================
    # SIMPAN BERITA NON-EKONOMI
    # ========================================================

    save_rejected_data(
        rejected_articles
    )


    # ========================================================
    # DATAFRAME BERITA BARU
    # ========================================================

    new_df = pd.DataFrame(
        final_records
    )


    # ========================================================
    # GABUNG DATA LAMA + BARU
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


    # ========================================================
    # JIKA MASIH KOSONG
    # ========================================================

    if combined_df.empty:

        status.warning(
            "⚠️ Tidak ditemukan berita ekonomi "
            "yang lolos analisis Gemini."
        )

        progress.progress(
            1.0
        )

        progress.empty()

        return pd.DataFrame()


    # ========================================================
    # HAPUS DUPLIKAT URL
    # ========================================================

    if "Link Berita" in combined_df.columns:

        combined_df[
            "Link Berita"
        ] = combined_df[
            "Link Berita"
        ].apply(
            normalize_url
        )


        combined_df = (
            combined_df
            .drop_duplicates(
                subset=[
                    "Link Berita"
                ],
                keep="first"
            )
        )


    # ========================================================
    # HAPUS DUPLIKAT JUDUL
    # ========================================================

    if "Judul Berita" in combined_df.columns:

        combined_df = (
            combined_df
            .drop_duplicates(
                subset=[
                    "Judul Berita"
                ],
                keep="first"
            )
        )


    # ========================================================
    # SORTING
    # ========================================================

    if "Tanggal Berita" in combined_df.columns:

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
    # SIMPAN CSV
    # ========================================================

    try:

        combined_df.to_csv(

            DATA_FILE,

            index=False,

            encoding="utf-8-sig"

        )


        logger.info(
            f"Data berhasil disimpan: "
            f"{len(combined_df)} berita."
        )


    except Exception as e:

        logger.error(
            f"Gagal menyimpan CSV: {e}"
        )


    # ========================================================
    # SELESAI
    # ========================================================

    progress.progress(
        1.0
    )


    status.success(

        f"✅ Selesai! "
        f"{len(final_records)} berita baru lolos "
        f"analisis Gemini. "
        f"{duplicate_count} berita duplikat dihapus."

    )


    progress.empty()


    return combined_df


# ============================================================
# 📦 DATA CONTOH
# ============================================================

def create_sample_data():

    return pd.DataFrame([

        {

            "ID":
                "1",

            "Tanggal Berita":
                "2026-08-17",

            "Media":
                "ANTARAJATIM",

            "Judul Berita":
                "Pertumbuhan Ekonomi Pesisir Lamongan Meningkat",

            "Isu Ekonomi":
                "Perikanan",

            "Sektor":
                "A - Pertanian, Kehutanan, dan Perikanan",

            "Ringkasan Berita":
                "Aktivitas perikanan tangkap dan budidaya memberikan kontribusi terhadap pendapatan masyarakat pesisir Lamongan.",

            "Link Berita":
                "https://jatim.antaranews.com/"

        },

        {

            "ID":
                "2",

            "Tanggal Berita":
                "2026-08-16",

            "Media":
                "Radar Lamongan",

            "Judul Berita":
                "Pasar Tradisional Lamongan Siap Digitalisasi UMKM",

            "Isu Ekonomi":
                "UMKM dan Perdagangan",

            "Sektor":
                "G - Perdagangan Besar dan Eceran; Reparasi Mobil dan Sepeda Motor",

            "Ringkasan Berita":
                "Pedagang UMKM mendapatkan dukungan digitalisasi transaksi dan pemasaran untuk meningkatkan aktivitas perdagangan di pasar daerah.",

            "Link Berita":
                "https://radarlamongan.jawapos.com/"

        }

    ])
# ============================================================
# 📌 MEMUAT DATA & PENGATURAN SIDEBAR CONTROL
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
    st.image(BPS_LOGO_URL, width=120)  # Logo BPS di Sidebar
    st.title("Dashboard Control")
    if client:
        st.success("🟢 Gemini AI: Active")
    else:
        st.error("🔴 Gemini AI: Offline (Cek Secrets)")

    st.divider()
    st.subheader("⚙️ Aksi")
    
    # Tombol Ambil Berita Terbaru
    if st.button("🔄 Ambil Berita Terbaru", use_container_width=True):
        new_data = fetch_and_process_news()
        if not new_data.empty:
            st.session_state.data = new_data
            new_data.to_csv(DATA_FILE, index=False, encoding="utf-8-sig")
            st.success("Data berhasil diperbarui!")

    # Tombol Reset Data
    if st.button("🗑️ Reset & Bersihkan Data", use_container_width=True):
        st.session_state.data = create_sample_data()
        if DATA_FILE.exists(): DATA_FILE.unlink()

    st.divider()
    st.subheader("🔎 Filter Data")

df = st.session_state.data.copy()
df["Tanggal Berita"] = pd.to_datetime(df["Tanggal Berita"], errors="coerce")

# 💡 DIBERSIHKAN: Rentang tanggal otomatis menyesuaikan isi data ter-update
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

# Logika Filter Tampilan
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
# Lokasi file logo
BASE_DIR = Path(__file__).resolve().parent
BPS_LOGO = BASE_DIR / "logo_bps.png"


# ============================================================
# 📷 MEMBACA LOGO BPS
# ============================================================

with open(BPS_LOGO, "rb") as f:
    logo_base64 = base64.b64encode(f.read()).decode("utf-8")


# ============================================================
# 🎨 CSS HEADER
# ============================================================

st.markdown("""
<style>
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
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.20);
    flex-shrink: 0;
}

.dashboard-title {
    font-size: 26px;
    font-weight: 800;
    margin: 0;
    color: white;
    line-height: 1.2;
}

.dashboard-subtitle {
    font-size: 14px;
    color: #e0f2fe;
    margin-top: 7px;
    line-height: 1.5;
}

</style>
""", unsafe_allow_html=True)


# ============================================================
# 🏛️ HEADER
# ============================================================

st.markdown(
    f'<div class="dashboard-header">'
    f'<img src="data:image/png;base64,{logo_base64}" '
    f'class="dashboard-logo" alt="Logo BPS">'
    f'<div>'
    f'<div class="dashboard-title">'
    f'MONITORING BERITA EKONOMI LAMONGAN'
    f'</div>'
    f'<div class="dashboard-subtitle">'
    f'Sistem pemantauan media otomatis berbasis AI untuk '
    f'17 Sektor Lapangan Usaha BPS Kabupaten Lamongan'
    f'</div>'
    f'</div>'
    f'</div>',
    unsafe_allow_html=True
)

# 4 Kartu Metrik Utama
k1, k2, k3, k4 = st.columns(4)
k1.metric("📰 Total Berita", f"{len(filtered):,}")
k2.metric("📅 Berita Hari Ini", f"{len(filtered[filtered['Tanggal Berita'].dt.date == datetime.now().date()]):,}")
k3.metric("🌐 Sumber Media", f"{filtered['Media'].nunique():,}")
k4.metric("🏭 Sektor Terpantau", f"{filtered['Sektor'].nunique():,}")

st.markdown("<br>", unsafe_allow_html=True)

# Ringkasan Visual Grafik
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

# Tabel Data Utama
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

# Ekspor Laporan Excel Resmi
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

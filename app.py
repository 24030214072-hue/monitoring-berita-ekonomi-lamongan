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
import trafilatura
from bs4 import BeautifulSoup
import base64
import plotly.express as px
from google import genai

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

        logger.info("Gemini AI berhasil diinisialisasi.")

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
# 🔎 TOPIK PENCARIAN BERITA
# ============================================================
#
# Tujuan:
# Mencari berita Lamongan dari berbagai media.
#
# Gemini TIDAK digunakan untuk mencari berita.
# Gemini hanya menganalisis berita yang sudah diperoleh.
# ============================================================

SEARCH_TOPICS = [

    "Lamongan ekonomi",

    "Kabupaten Lamongan ekonomi",

    "Pemkab Lamongan ekonomi",

    "Lamongan pertanian",

    "Lamongan petani",

    "Lamongan padi",

    "Lamongan panen",

    "Lamongan perikanan",

    "Lamongan nelayan",

    "Lamongan tambak",

    "Lamongan UMKM",

    "Lamongan perdagangan",

    "Lamongan pasar",

    "Lamongan harga pangan",

    "Lamongan industri",

    "Lamongan pabrik",

    "Lamongan investasi",

    "Lamongan bisnis",

    "Lamongan koperasi",

    "Lamongan tenaga kerja",

    "Lamongan pariwisata",

    "Lamongan wisata",

    "Lamongan hotel",

    "Lamongan restoran",

    "Lamongan konstruksi",

    "Lamongan pembangunan",

    "Lamongan transportasi",

    "Lamongan keuangan",

    "Lamongan pajak",

    "Lamongan pendapatan daerah",

    "Lamongan infrastruktur",

    "Lamongan ekonomi desa"

]


# ============================================================
# 🧹 MEMBERSIHKAN TEKS
# ============================================================

def clean_text(text):

    if not text:
        return ""

    text = BeautifulSoup(
        str(text),
        "html.parser"
    ).get_text(" ")

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


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
# 🆔 MEMBUAT ID UNIK BERITA
# ============================================================

def make_id(title, link):

    return hashlib.md5(
        (
            str(title) +
            str(link)
        ).encode("utf-8")
    ).hexdigest()


# ============================================================
# 📰 MENGAMBIL ISI ARTIKEL ASLI
# ============================================================
#
# Google News RSS hanya memberikan ringkasan pendek.
#
# Karena itu:
#
# Google News
#      ↓
# URL berita
#      ↓
# requests
#      ↓
# trafilatura
#      ↓
# isi artikel
#
# Jika halaman media tidak dapat dibaca,
# RSS summary digunakan sebagai CADANGAN.
# ============================================================

def extract_article_content(
    url,
    fallback_summary=""
):

    if not url:
        return clean_text(
            fallback_summary
        )

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

        # ----------------------------------------------------
        # Ambil halaman berita
        # ----------------------------------------------------

        response = requests.get(
            url,
            headers=headers,
            timeout=15,
            allow_redirects=True
        )

        if response.status_code != 200:

            logger.warning(
                f"URL berita gagal dibuka: "
                f"{response.status_code} - {url}"
            )

            return clean_text(
                fallback_summary
            )


        # ----------------------------------------------------
        # Ekstrak isi artikel
        # ----------------------------------------------------

        article_text = trafilatura.extract(
            response.text,

            include_comments=False,

            include_tables=False,

            include_links=False,

            include_images=False,

            favor_precision=True
        )


        article_text = clean_text(
            article_text
        )


        # ----------------------------------------------------
        # Pastikan isi benar-benar cukup
        # ----------------------------------------------------

        if len(article_text) >= 300:

            return article_text


        # ----------------------------------------------------
        # Jika isi terlalu pendek
        # gunakan RSS summary
        # ----------------------------------------------------

        logger.warning(
            f"Isi artikel terlalu pendek: {url}"
        )

        return clean_text(
            fallback_summary
        )


    except Exception as e:

        logger.warning(
            f"Gagal mengambil isi artikel "
            f"{url}: {e}"
        )

        return clean_text(
            fallback_summary
        )


# ============================================================
# 🧠 FALLBACK SEKTOR
# ============================================================
#
# Fungsi ini HANYA digunakan jika Gemini gagal memberikan
# sektor yang valid.
#
# Bukan sebagai metode utama klasifikasi.
# ============================================================

def match_fallback_sector(text):

    text_lower = clean_text(
        text
    ).lower()


    # --------------------------------------------------------
    # A - Pertanian
    # --------------------------------------------------------

    if any(
        word in text_lower
        for word in [

            "tani",
            "petani",
            "padi",
            "panen",
            "sawah",
            "pertanian",
            "pupuk",
            "jagung",
            "kedelai",
            "nelayan",
            "ikan",
            "tambak",
            "udang",
            "budidaya",
            "ternak",
            "peternakan",
            "perkebunan"

        ]
    ):

        return (
            "A - Pertanian, Kehutanan, dan Perikanan"
        )


    # --------------------------------------------------------
    # C - Industri
    # --------------------------------------------------------

    if any(
        word in text_lower
        for word in [

            "pabrik",
            "industri",
            "manufaktur",
            "produksi",
            "pengolahan",
            "produksi barang"

        ]
    ):

        return (
            "C - Industri Pengolahan"
        )


    # --------------------------------------------------------
    # D - Listrik dan Gas
    # --------------------------------------------------------

    if any(
        word in text_lower
        for word in [

            "listrik",
            "energi",
            "gas",
            "kelistrikan"

        ]
    ):

        return (
            "D - Pengadaan Listrik dan Gas"
        )


    # --------------------------------------------------------
    # E - Air / Sampah
    # --------------------------------------------------------

    if any(
        word in text_lower
        for word in [

            "air bersih",
            "sampah",
            "limbah",
            "daur ulang"

        ]
    ):

        return (
            "E - Pengadaan Air, Pengelolaan Sampah, "
            "Limbah dan Daur Ulang"
        )


    # --------------------------------------------------------
    # F - Konstruksi
    # --------------------------------------------------------

    if any(
        word in text_lower
        for word in [

            "konstruksi",
            "jalan",
            "jembatan",
            "gedung",
            "proyek pembangunan",
            "pembangunan infrastruktur"

        ]
    ):

        return (
            "F - Konstruksi"
        )


    # --------------------------------------------------------
    # G - Perdagangan
    # --------------------------------------------------------

    if any(
        word in text_lower
        for word in [

            "pasar",
            "pedagang",
            "perdagangan",
            "toko",
            "jual",
            "beli",
            "umkm",
            "eceran",
            "omzet",
            "transaksi",
            "harga barang",
            "sembako",
            "distributor"

        ]
    ):

        return (
            "G - Perdagangan Besar dan Eceran; "
            "Reparasi Mobil dan Sepeda Motor"
        )


    # --------------------------------------------------------
    # H - Transportasi
    # --------------------------------------------------------

    if any(
        word in text_lower
        for word in [

            "transportasi",
            "angkutan",
            "bus",
            "truk",
            "pelabuhan",
            "logistik",
            "pergudangan",
            "distribusi barang"

        ]
    ):

        return (
            "H - Transportasi dan Pergudangan"
        )


    # --------------------------------------------------------
    # I - Akomodasi dan Makan Minum
    # --------------------------------------------------------

    if any(
        word in text_lower
        for word in [

            "hotel",
            "restoran",
            "rumah makan",
            "kuliner",
            "warung",
            "penginapan",
            "akomodasi"

        ]
    ):

        return (
            "I - Penyediaan Akomodasi dan Makan Minum"
        )


    # --------------------------------------------------------
    # J - Informasi dan Komunikasi
    # --------------------------------------------------------

    if any(
        word in text_lower
        for word in [

            "digital",
            "internet",
            "telekomunikasi",
            "aplikasi",
            "teknologi informasi",
            "komunikasi"

        ]
    ):

        return (
            "J - Informasi dan Komunikasi"
        )


    # --------------------------------------------------------
    # K - Keuangan
    # --------------------------------------------------------

    if any(
        word in text_lower
        for word in [

            "bank",
            "kredit",
            "pinjaman",
            "pembiayaan",
            "asuransi",
            "keuangan",
            "perbankan"

        ]
    ):

        return (
            "K - Jasa Keuangan dan Asuransi"
        )


    # --------------------------------------------------------
    # L - Real Estat
    # --------------------------------------------------------

    if any(
        word in text_lower
        for word in [

            "properti",
            "perumahan",
            "real estat",
            "perumahan rakyat",
            "tanah"

        ]
    ):

        return (
            "L - Real Estat"
        )


    # --------------------------------------------------------
    # Default
    # --------------------------------------------------------

    return (
        "O - Administrasi Pemerintahan, "
        "Pertahanan dan Jaminan Sosial Wajib"
    )


# ============================================================
# 🤖 ANALISIS BERITA DENGAN GEMINI AI
# ============================================================
#
# Gemini TIDAK mencari berita.
#
# Gemini hanya menerima berita yang sudah ditemukan program.
#
# Gemini bertugas:
#
# 1. Menentukan apakah berita relevan dengan ekonomi Lamongan
# 2. Menentukan isu ekonomi
# 3. Menentukan 1 dari 17 sektor BPS
# 4. Meringkas ISI artikel
#
# Ringkasan WAJIB berdasarkan isi artikel.
# ============================================================

def analyze_with_gemini(article):

    title = clean_text(
        article.get("title", "")
    )

    content = clean_text(
        article.get("content", "")
    )

    source = clean_text(
        article.get("source", "")
    )

    url = article.get(
        "url",
        ""
    )


    # ========================================================
    # Jika isi artikel tidak tersedia
    # ========================================================

    if len(content) < 100:

        logger.warning(
            f"Isi artikel tidak cukup untuk dianalisis: "
            f"{title}"
        )

        return {
            "ekonomi": False,
            "sektor": "Tidak Relevan",
            "isu_ekonomi": "Tidak dapat ditentukan",
            "ringkasan": ""
        }


    # ========================================================
    # Jika Gemini tidak aktif
    # ========================================================

    if not client:

        logger.warning(
            "Gemini tidak aktif."
        )

        return {
            "ekonomi": False,
            "sektor": "Tidak Relevan",
            "isu_ekonomi": "Gemini tidak aktif",
            "ringkasan": ""
        }


    # ========================================================
    # PROMPT GEMINI
    # ========================================================

    prompt = f"""
Anda adalah analis berita ekonomi untuk
Badan Pusat Statistik Kabupaten Lamongan.

Anda HANYA bertugas menganalisis berita yang diberikan
oleh sistem.

JANGAN mencari berita lain.
JANGAN menggunakan informasi dari luar artikel.
JANGAN membuat fakta baru.
JANGAN menebak isi artikel.

Yang paling penting:
SEMUA hasil analisis harus berdasarkan ISI ARTIKEL.

============================================================
TUGAS 1 — RELEVANSI BERITA
============================================================

Tentukan apakah berita ini merupakan berita ekonomi
yang berkaitan dengan Kabupaten Lamongan.

Berita dianggap relevan jika isi artikelnya membahas
aktivitas ekonomi, pembangunan ekonomi, kesejahteraan
ekonomi, usaha, produksi, perdagangan, pertanian,
perikanan, industri, harga, investasi, tenaga kerja,
infrastruktur ekonomi, keuangan, pariwisata, atau
aktivitas ekonomi lainnya yang berkaitan dengan
Kabupaten Lamongan.

Tolak jika berita hanya membahas:

- olahraga murni
- sepak bola
- kriminalitas murni
- politik murni
- hukum murni
- seremonial tanpa aspek ekonomi
- hiburan tanpa aspek ekonomi

============================================================
TUGAS 2 — ISU EKONOMI
============================================================

Jika relevan, tentukan SATU isu ekonomi utama.

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

Isu harus menggambarkan isi utama berita.

============================================================
TUGAS 3 — SEKTOR LAPANGAN USAHA BPS
============================================================

Pilih TEPAT SATU sektor dari 17 sektor berikut:

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
ATURAN PEMILIHAN SEKTOR
============================================================

Pilih sektor berdasarkan AKTIVITAS EKONOMI UTAMA
yang benar-benar dibahas dalam isi berita.

Jangan memilih sektor hanya berdasarkan satu kata.

Contoh:

Jika isi utama membahas petani, sawah, padi,
panen, nelayan, tambak atau produksi ikan:

→ A - Pertanian, Kehutanan, dan Perikanan

Jika isi utama membahas pasar, pedagang, toko,
UMKM, transaksi, omzet atau kegiatan jual beli:

→ G - Perdagangan Besar dan Eceran;
  Reparasi Mobil dan Sepeda Motor

Jika isi utama membahas pabrik atau proses manufaktur:

→ C - Industri Pengolahan

Jika isi utama membahas pembangunan jalan,
jembatan, gedung atau proyek konstruksi:

→ F - Konstruksi

Jika isi utama membahas hotel, restoran,
rumah makan atau kegiatan akomodasi:

→ I - Penyediaan Akomodasi dan Makan Minum

Jika isi utama membahas bank, kredit,
pembiayaan atau asuransi:

→ K - Jasa Keuangan dan Asuransi

============================================================
TUGAS 4 — RINGKASAN ISI BERITA
============================================================

Buat ringkasan berdasarkan ISI ARTIKEL.

JANGAN hanya mengulang judul.

Ringkasan harus:

1. Mengambil informasi utama dari isi artikel.
2. Menjelaskan apa yang terjadi atau dilakukan.
3. Menjelaskan dampak atau tujuan jika memang disebutkan.
4. Memasukkan angka atau data penting jika ada.
5. Tidak membuat informasi baru.
6. Menggunakan bahasa Indonesia yang jelas.
7. Panjang sekitar 2–3 kalimat.
8. Maksimal 80 kata.
9. Jangan memulai dengan kalimat generik seperti:
   "Pemberitaan ini mengulas..."
   jika dapat langsung menjelaskan isi berita.

============================================================
DATA BERITA
============================================================

MEDIA:
{source}

JUDUL:
{title}

ISI ARTIKEL:
{content}

URL:
{url}

============================================================
FORMAT JAWABAN
============================================================

Jawab HANYA JSON valid.

Jika berita ekonomi:

{{
    "ekonomi": true,
    "sektor": "KODE - Nama sektor",
    "isu_ekonomi": "Isu ekonomi utama",
    "ringkasan": "Ringkasan berdasarkan isi artikel."
}}

Jika bukan berita ekonomi:

{{
    "ekonomi": false,
    "sektor": "Tidak Relevan",
    "isu_ekonomi": "Tidak Relevan",
    "ringkasan": ""
}}
"""


    # ========================================================
    # PANGGIL GEMINI
    # ========================================================

    try:

        response = client.models.generate_content(

            model="gemini-2.5-flash",

            contents=prompt

        )


        text_response = (
            response.text or ""
        ).strip()


        # ====================================================
        # BERSIHKAN FORMAT JSON
        # ====================================================

        if "```json" in text_response:

            text_response = (
                text_response
                .split("```json", 1)[1]
                .split("```", 1)[0]
                .strip()
            )

        elif "```" in text_response:

            text_response = (
                text_response
                .split("```", 1)[1]
                .split("```", 1)[0]
                .strip()
            )


        # ====================================================
        # PARSE JSON
        # ====================================================

        result = json.loads(
            text_response
        )


        # ====================================================
        # CEK RELEVANSI
        # ====================================================

        ekonomi = result.get(
            "ekonomi",
            False
        )


        if ekonomi is not True:

            return {
                "ekonomi": False,
                "sektor": "Tidak Relevan",
                "isu_ekonomi": "Tidak Relevan",
                "ringkasan": ""
            }


        # ====================================================
        # VALIDASI SEKTOR
        # ====================================================

        sektor = clean_text(
            result.get(
                "sektor",
                ""
            )
        )


        if sektor not in SEKTOR_BPS:

            sektor = match_fallback_sector(
                title + " " + content
            )


        # ====================================================
        # ISU EKONOMI
        # ====================================================

        isu = clean_text(
            result.get(
                "isu_ekonomi",
                "Ekonomi Daerah"
            )
        )


        if not isu:

            isu = "Ekonomi Daerah"


        # ====================================================
        # RINGKASAN
        # ====================================================

        ringkasan = clean_text(
            result.get(
                "ringkasan",
                ""
            )
        )


        # ====================================================
        # VALIDASI RINGKASAN
        # ====================================================

        if len(ringkasan) < 30:

            logger.warning(
                f"Ringkasan AI terlalu pendek: {title}"
            )

            return {
                "ekonomi": False,
                "sektor": "Tidak Relevan",
                "isu_ekonomi": "Ringkasan tidak tersedia",
                "ringkasan": ""
            }


        # ----------------------------------------------------
        # Pastikan ringkasan tidak hanya mengulang judul
        # ----------------------------------------------------

        normalized_title = normalize_text(
            title
        )

        normalized_summary = normalize_text(
            ringkasan
        )


        similarity = SequenceMatcher(
            None,
            normalized_title,
            normalized_summary
        ).ratio()


        if (
            normalized_title
            and
            similarity > 0.70
        ):

            logger.warning(
                f"Ringkasan terlalu mirip judul: {title}"
            )

            return {
                "ekonomi": False,
                "sektor": "Tidak Relevan",
                "isu_ekonomi": "Ringkasan tidak valid",
                "ringkasan": ""
            }


        # ====================================================
        # HASIL AKHIR
        # ====================================================

        return {

            "ekonomi": True,

            "sektor": sektor,

            "isu_ekonomi": isu,

            "ringkasan": ringkasan

        }


    except Exception as e:

        logger.error(
            f"Gemini API Error: {e}"
        )

        return {

            "ekonomi": False,

            "sektor": "Tidak Relevan",

            "isu_ekonomi": "Analisis gagal",

            "ringkasan": ""

        }


# ============================================================
# 📰 PENGAMBILAN BERITA DARI GOOGLE NEWS RSS
# ============================================================

def fetch_and_process_news():

    raw_articles = []

    progress = st.progress(0)

    status = st.empty()


    total = len(
        SEARCH_TOPICS
    )


    # ========================================================
    # USER AGENT
    # ========================================================

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


    # ========================================================
    # LOOP TOPIK PENCARIAN
    # ========================================================

    for i, topic in enumerate(
        SEARCH_TOPICS
    ):

        status.info(
            f"🔎 Mencari berita: {topic}"
        )


        try:

            # ------------------------------------------------
            # Google News RSS
            # ------------------------------------------------

            rss_url = (
                "https://news.google.com/rss/search?"
                f"q={quote(topic)}"
                "&hl=id"
                "&gl=ID"
                "&ceid=ID:id"
            )


            response = requests.get(

                rss_url,

                timeout=15,

                headers=headers

            )


            feed = feedparser.parse(
                response.content
            )


            # ------------------------------------------------
            # Ambil berita
            # ------------------------------------------------

            for entry in feed.entries:

                title = clean_text(
                    entry.get(
                        "title",
                        ""
                    )
                )


                link = entry.get(
                    "link",
                    ""
                )


                rss_summary = clean_text(
                    entry.get(
                        "summary",
                        ""
                    )
                )


                # ------------------------------------------------
                # Validasi dasar
                # ------------------------------------------------

                if (
                    not title
                    or
                    not link
                    or
                    len(title) < 10
                ):

                    continue


                # ------------------------------------------------
                # Nama media
                # ------------------------------------------------

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


                # ------------------------------------------------
                # Tanggal berita
                # ------------------------------------------------

                pub_date = (
                    datetime.now()
                    .strftime("%Y-%m-%d")
                )


                if entry.get(
                    "published_parsed"
                ):

                    try:

                        pub_date = (
                            datetime(
                                *entry.published_parsed[:6]
                            )
                            .strftime("%Y-%m-%d")
                        )

                    except Exception:

                        pass


                # ------------------------------------------------
                # Ambil ISI ARTIKEL ASLI
                # ------------------------------------------------

                status.info(
                    f"📰 Membaca isi: {title[:80]}"
                )


                article_content = (
                    extract_article_content(
                        link,
                        rss_summary
                    )
                )


                # ------------------------------------------------
                # Simpan artikel
                # ------------------------------------------------

                raw_articles.append({

                    "title": title,

                    "content": article_content,

                    "source": source_name,

                    "date": pub_date,

                    "url": link

                })


        except Exception as e:

            logger.error(
                f"Error topic {topic}: {e}"
            )


        progress.progress(
            (i + 1) / total
        )


    # ========================================================
    # HILANGKAN DUPLIKAT
    # ========================================================

    status.info(
        "🔄 Menghapus berita duplikat..."
    )


    unique_articles = {}

    for article in raw_articles:

        article_id = make_id(
            article["title"],
            article["url"]
        )

        unique_articles[
            article_id
        ] = article


    unique_articles = list(
        unique_articles.values()
    )


    # ========================================================
    # GEMINI ANALISIS
    # ========================================================

    status.info(
        "🤖 Gemini AI sedang membaca isi berita "
        "dan mengidentifikasi sektor serta isu ekonomi..."
    )


    final_records = []


    total_articles = len(
        unique_articles
    )


    for index, article in enumerate(
        unique_articles
    ):

        # ----------------------------------------------------
        # Progress AI
        # ----------------------------------------------------

        if total_articles > 0:

            progress.progress(
                min(
                    1.0,
                    (
                        (index + 1)
                        /
                        total_articles
                    )
                )
            )


        status.info(
            f"🤖 Menganalisis berita "
            f"{index + 1}/{total_articles}: "
            f"{article['title'][:80]}"
        )


        # ----------------------------------------------------
        # Analisis Gemini
        # ----------------------------------------------------

        ai_result = analyze_with_gemini(
            article
        )


        # ----------------------------------------------------
        # Hanya simpan berita ekonomi
        # ----------------------------------------------------

        if ai_result.get(
            "ekonomi"
        ) is True:


            final_records.append({

                "ID": make_id(
                    article["title"],
                    article["url"]
                ),

                "Tanggal Berita":
                    article["date"],

                "Media":
                    article["source"],

                "Judul Berita":
                    article["title"],

                "Isu Ekonomi":
                    ai_result["isu_ekonomi"],

                "Sektor":
                    ai_result["sektor"],

                "Ringkasan Berita":
                    ai_result["ringkasan"],

                "Link Berita":
                    article["url"]

            })


    # ========================================================
    # SELESAI
    # ========================================================

    status.success(
        "✅ Selesai! "
        f"Ditemukan {len(final_records)} "
        "berita ekonomi Lamongan."
    )


    progress.empty()


    # ========================================================
    # JIKA TIDAK ADA DATA
    # ========================================================

    if not final_records:

        return pd.DataFrame()


    # ========================================================
    # DATAFRAME
    # ========================================================

    df = pd.DataFrame(
        final_records
    )


    # --------------------------------------------------------
    # Hapus duplikat
    # --------------------------------------------------------

    df = df.drop_duplicates(
        subset=["ID"]
    )


    # --------------------------------------------------------
    # Urutkan tanggal
    # --------------------------------------------------------

    df = df.sort_values(
        "Tanggal Berita",
        ascending=False
    )


    # ========================================================
    # SIMPAN CSV
    # ========================================================

    try:

        df.to_csv(
            DATA_FILE,
            index=False,
            encoding="utf-8-sig"
        )

        logger.info(
            f"Data berita berhasil disimpan: "
            f"{len(df)} berita"
        )

    except Exception as e:

        logger.error(
            f"Gagal menyimpan CSV: {e}"
        )


    return df


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
                "UMKM dan Digitalisasi Perdagangan",

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

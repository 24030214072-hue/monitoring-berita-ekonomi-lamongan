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
# 🧠 SISTEM ANALISIS BERITA GEMINI AI - VERSI PERBAIKAN
# ============================================================
#
# PERBAIKAN UTAMA:
#
# 1. Gemini WAJIB memilih sektor berdasarkan isi.
# 2. Sektor menggunakan KODE agar tidak mudah gagal:
#       A, B, C, D, E, F, G, H, I, J, K, L,
#       MN, O, P, Q, RSTU
#
# 3. Jika nama sektor Gemini tidak persis sama,
#    program akan memperbaikinya berdasarkan kode.
#
# 4. Berita ekonomi TIDAK akan dibuang hanya karena
#    ringkasannya kurang bagus.
#
# 5. Jika ringkasan terlalu mirip judul,
#    Gemini diminta membuat ulang ringkasan.
#
# 6. Deduplicasi dilakukan berdasarkan:
#       - judul sama
#       - judul sangat mirip
#       - isi sangat mirip
#
# 7. Jika berita sama dari beberapa media,
#    dipilih artikel dengan isi paling lengkap.
#
# 8. Ringkasan WAJIB berdasarkan isi artikel,
#    bukan judul.
# ============================================================


# ============================================================
# 📊 MASTER 17 SEKTOR BPS
# ============================================================

SEKTOR_BPS = {

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


# ============================================================
# 🔤 NORMALISASI TEKS
# ============================================================

def normalize_text(text):

    if not text:
        return ""

    text = str(text).lower()

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
# 🔤 TOKEN
# ============================================================

def text_tokens(text):

    return set(
        normalize_text(text).split()
    )


# ============================================================
# 📊 JACCARD
# ============================================================

def jaccard_similarity(
    text_a,
    text_b
):

    a = text_tokens(text_a)
    b = text_tokens(text_b)

    if not a or not b:
        return 0.0

    intersection = len(
        a.intersection(b)
    )

    union = len(
        a.union(b)
    )

    if union == 0:
        return 0.0

    return intersection / union


# ============================================================
# 🔍 SIMILARITAS JUDUL
# ============================================================

def title_similarity(
    title_a,
    title_b
):

    a = normalize_text(title_a)
    b = normalize_text(title_b)

    if not a or not b:
        return 0.0

    if a == b:
        return 1.0

    return SequenceMatcher(
        None,
        a,
        b
    ).ratio()


# ============================================================
# 🔍 SIMILARITAS ISI
# ============================================================

def content_similarity(
    content_a,
    content_b
):

    if not content_a or not content_b:
        return 0.0

    if (
        len(content_a) < 200
        or
        len(content_b) < 200
    ):
        return 0.0

    a = normalize_text(
        content_a[:6000]
    )

    b = normalize_text(
        content_b[:6000]
    )

    jac = jaccard_similarity(
        a,
        b
    )

    # SequenceMatcher hanya dipakai
    # kalau sudah terlihat mirip
    if jac >= 0.35:

        seq = SequenceMatcher(
            None,
            a[:3500],
            b[:3500]
        ).ratio()

        return max(
            jac,
            seq
        )

    return jac


# ============================================================
# 🧠 CEK APAKAH DUA BERITA ADALAH PERISTIWA YANG SAMA
# ============================================================

def is_same_news(
    article_a,
    article_b
):

    title_a = article_a.get(
        "title",
        ""
    )

    title_b = article_b.get(
        "title",
        ""
    )

    content_a = article_a.get(
        "content",
        ""
    )

    content_b = article_b.get(
        "content",
        ""
    )


    # --------------------------------------------------------
    # 1. JUDUL SAMA PERSIS
    # --------------------------------------------------------

    if (
        normalize_text(title_a)
        ==
        normalize_text(title_b)
    ):

        return True


    # --------------------------------------------------------
    # 2. JUDUL SANGAT MIRIP
    # --------------------------------------------------------

    title_sim = title_similarity(
        title_a,
        title_b
    )

    if title_sim >= 0.90:

        return True


    # --------------------------------------------------------
    # 3. ISI SANGAT MIRIP
    # --------------------------------------------------------

    content_sim = content_similarity(
        content_a,
        content_b
    )

    if content_sim >= 0.78:

        return True


    # --------------------------------------------------------
    # 4. JUDUL MIRIP + ISI CUKUP MIRIP
    # --------------------------------------------------------

    if (
        title_sim >= 0.75
        and
        content_sim >= 0.50
    ):

        return True


    return False


# ============================================================
# 🏆 SKOR KUALITAS ARTIKEL
# ============================================================

def article_quality_score(
    article
):

    title = clean_text(
        article.get(
            "title",
            ""
        )
    )

    content = clean_text(
        article.get(
            "content",
            ""
        )
    )


    score = 0.0


    # --------------------------------------------------------
    # PANJANG ISI
    # --------------------------------------------------------

    word_count = len(
        content.split()
    )

    score += min(
        word_count / 100,
        20
    )


    # --------------------------------------------------------
    # JUMLAH PARAGRAF / KALIMAT
    # --------------------------------------------------------

    sentence_count = len(
        re.findall(
            r"[.!?]",
            content
        )
    )

    score += min(
        sentence_count / 5,
        10
    )


    # --------------------------------------------------------
    # ADA ANGKA / DATA
    # --------------------------------------------------------

    numbers = re.findall(
        r"\b\d+(?:[.,]\d+)?\b",
        content
    )

    score += min(
        len(numbers) * 0.5,
        8
    )


    # --------------------------------------------------------
    # ADA INDIKATOR DATA EKONOMI
    # --------------------------------------------------------

    economic_words = [

        "rp",
        "rupiah",
        "persen",
        "%",
        "ton",
        "kg",
        "juta",
        "miliar",
        "triliun",
        "produksi",
        "pendapatan",
        "omzet",
        "transaksi",
        "harga",
        "investasi",
        "petani",
        "nelayan",
        "umkm",
        "perdagangan",
        "industri",
        "usaha",
        "ekonomi"

    ]


    lower_content = content.lower()


    for word in economic_words:

        if word in lower_content:

            score += 1


    # --------------------------------------------------------
    # ADA QUOTE / PERNYATAAN
    # --------------------------------------------------------

    if (
        '"' in content
        or
        "ujar" in lower_content
        or
        "kata" in lower_content
        or
        "menurut" in lower_content
    ):

        score += 3


    # --------------------------------------------------------
    # ISI TERLALU PENDEK
    # --------------------------------------------------------

    if word_count < 80:

        score -= 15


    return score


# ============================================================
# 🏆 PILIH ARTIKEL TERBAIK DARI BERITA YANG SAMA
# ============================================================

def remove_similar_articles(
    articles
):

    if not articles:

        return []


    # --------------------------------------------------------
    # Urutkan artikel berdasarkan kualitas
    # --------------------------------------------------------

    sorted_articles = sorted(

        articles,

        key=article_quality_score,

        reverse=True

    )


    selected = []


    for article in sorted_articles:

        duplicate = False


        for existing in selected:

            if is_same_news(
                article,
                existing
            ):

                duplicate = True

                logger.info(
                    "Duplikat ditemukan: "
                    f"{article.get('title', '')} "
                    "→ mempertahankan artikel "
                    "dengan isi lebih lengkap."
                )

                break


        if not duplicate:

            selected.append(
                article
            )


    return selected


# ============================================================
# 🔤 NORMALISASI KODE SEKTOR
# ============================================================

def normalize_sector_code(
    code
):

    if not code:

        return ""


    code = str(
        code
    ).strip().upper()


    # Hilangkan karakter yang tidak perlu

    code = code.replace(
        "SEKTOR",
        ""
    )

    code = code.replace(
        "SEKTOR:",
        ""
    )

    code = code.strip()


    # Variasi sektor M,N

    if code in [
        "M,N",
        "M N",
        "MN",
        "M-N",
        "M & N"
    ]:

        return "MN"


    # Variasi RSTU

    if code in [
        "R,S,T,U",
        "R S T U",
        "RSTU",
        "R-U",
        "R,S,T,U"
    ]:

        return "RSTU"


    if code in SEKTOR_BPS:

        return code


    # Cari kode di dalam teks

    for key in SEKTOR_BPS:

        if re.search(
            rf"\b{re.escape(key)}\b",
            code
        ):

            return key


    return ""


# ============================================================
# 🧠 PERBAIKAN SEKTOR DARI NAMA SEKTOR
# ============================================================

def detect_sector_from_text(
    sector_text
):

    if not sector_text:

        return ""


    text = normalize_text(
        sector_text
    )


    mapping = {

        "pertanian": "A",
        "kehutanan": "A",
        "perikanan": "A",
        "petani": "A",
        "nelayan": "A",
        "tambak": "A",
        "padi": "A",
        "jagung": "A",
        "perkebunan": "A",

        "pertambangan": "B",
        "tambang": "B",
        "galian": "B",
        "pasir": "B",

        "industri": "C",
        "pabrik": "C",
        "manufaktur": "C",
        "produksi barang": "C",

        "listrik": "D",
        "gas": "D",
        "energi listrik": "D",

        "air bersih": "E",
        "sampah": "E",
        "limbah": "E",
        "daur ulang": "E",

        "konstruksi": "F",
        "jalan": "F",
        "jembatan": "F",
        "gedung": "F",
        "pembangunan fisik": "F",

        "perdagangan": "G",
        "pedagang": "G",
        "pasar": "G",
        "toko": "G",
        "jual beli": "G",
        "eceran": "G",
        "grosir": "G",
        "umkm": "G",

        "transportasi": "H",
        "angkutan": "H",
        "logistik": "H",
        "pergudangan": "H",
        "distribusi barang": "H",

        "hotel": "I",
        "restoran": "I",
        "rumah makan": "I",
        "penginapan": "I",
        "kuliner": "I",
        "akomodasi": "I",

        "informasi": "J",
        "komunikasi": "J",
        "telekomunikasi": "J",
        "digital": "J",
        "internet": "J",
        "media": "J",

        "bank": "K",
        "perbankan": "K",
        "keuangan": "K",
        "asuransi": "K",
        "kredit": "K",
        "pembiayaan": "K",

        "real estat": "L",
        "properti": "L",
        "perumahan": "L",
        "real estate": "L",

        "jasa perusahaan": "MN",
        "konsultan": "MN",
        "profesional": "MN",

        "pemerintah": "O",
        "pemerintahan": "O",
        "administrasi pemerintahan": "O",
        "pertahanan": "O",

        "pendidikan": "P",
        "sekolah": "P",
        "universitas": "P",
        "kampus": "P",

        "kesehatan": "Q",
        "rumah sakit": "Q",
        "puskesmas": "Q",
        "klinik": "Q",
        "sosial": "Q",

        "pariwisata": "RSTU",
        "wisata": "RSTU",
        "hiburan": "RSTU",
        "olahraga": "RSTU",
        "jasa lainnya": "RSTU"

    }


    # Cari frasa paling panjang dahulu

    sorted_mapping = sorted(

        mapping.items(),

        key=lambda x: len(x[0]),

        reverse=True

    )


    for keyword, code in sorted_mapping:

        if keyword in text:

            return code


    return ""


# ============================================================
# 🤖 PROMPT GEMINI UTAMA
# ============================================================

def build_gemini_prompt(
    articles
):

    blocks = []


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


        content = content[
            :MAX_CONTENT_FOR_AI
        ]


        blocks.append(

            f"""
============================================================
BERITA ID: {article_id}
============================================================

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

Anda HARUS membaca ISI ARTIKEL, bukan hanya judul.

Tujuan Anda adalah mengidentifikasi berita ekonomi
Kabupaten Lamongan secara akurat.

============================================================
ATURAN 1 — EKONOMI ATAU BUKAN
============================================================

ekonomi=true jika isi artikel benar-benar membahas
aktivitas ekonomi atau aktivitas sektor lapangan usaha
yang terjadi di Kabupaten Lamongan.

Contohnya:

- pertanian
- perikanan
- perdagangan
- UMKM
- industri
- produksi
- harga
- investasi
- tenaga kerja
- konstruksi
- transportasi
- perbankan
- pariwisata
- jasa
- pendapatan daerah
- distribusi
- kegiatan usaha
- pembangunan yang memiliki aktivitas ekonomi

ekonomi=false jika hanya:

- kriminal
- kecelakaan
- olahraga murni
- Persela
- politik murni
- hukum murni
- konflik
- hiburan murni
- kegiatan seremonial tanpa aspek ekonomi
- berita daerah lain yang tidak berkaitan dengan Lamongan

Jangan menjadikan berita ekonomi hanya karena judul
mengandung kata "ekonomi", "UMKM", "pasar",
"pembangunan", "harga", atau "pemerintah".

Baca konteks keseluruhan.

============================================================
ATURAN 2 — SEKTOR
============================================================

Jika ekonomi=true, WAJIB memilih tepat SATU kode sektor.

Gunakan kode berikut:

A = Pertanian, Kehutanan, dan Perikanan

B = Pertambangan dan Penggalian

C = Industri Pengolahan

D = Pengadaan Listrik dan Gas

E = Pengadaan Air, Pengelolaan Sampah, Limbah dan Daur Ulang

F = Konstruksi

G = Perdagangan Besar dan Eceran; Reparasi Mobil dan Sepeda Motor

H = Transportasi dan Pergudangan

I = Penyediaan Akomodasi dan Makan Minum

J = Informasi dan Komunikasi

K = Jasa Keuangan dan Asuransi

L = Real Estat

MN = Jasa Perusahaan

O = Administrasi Pemerintahan, Pertahanan dan Jaminan Sosial Wajib

P = Jasa Pendidikan

Q = Jasa Kesehatan dan Kegiatan Sosial

RSTU = Jasa Lainnya

============================================================
ATURAN SEKTOR YANG SANGAT PENTING
============================================================

Pilih sektor berdasarkan AKTIVITAS EKONOMI UTAMA.

Contoh:

padi, jagung, petani, sawah, panen, nelayan,
tambak, budidaya ikan
→ A

pabrik, manufaktur, pengolahan hasil menjadi barang
→ C

jalan, jembatan, gedung, proyek konstruksi
→ F

pasar, toko, perdagangan, jual beli, pedagang
→ G

hotel, restoran, rumah makan, penginapan
→ I

bank, kredit, pembiayaan, asuransi
→ K

angkutan, ekspedisi, logistik, gudang
→ H

internet, telekomunikasi, teknologi informasi
→ J

sekolah atau aktivitas pendidikan sebagai kegiatan jasa
→ P

rumah sakit, klinik, puskesmas
→ Q

wisata, hiburan, olahraga profesional, jasa lainnya
→ RSTU

PENTING:

Jika berita membahas pemerintah tetapi kegiatan utamanya
adalah pembangunan jalan, sektor utamanya F.

Jika pemerintah memberikan bantuan kepada petani,
aktivitas ekonomi utamanya pertanian, maka A.

Jika pemerintah mengadakan pelatihan UMKM,
lihat aktivitas utamanya. Jika fokus pada usaha/perdagangan
UMKM, gunakan G.

Jangan otomatis menggunakan O hanya karena ada
kata "Pemkab", "Bupati", "Dinas", atau "Pemerintah".

============================================================
ATURAN 3 — ISU EKONOMI
============================================================

Pilih SATU isu ekonomi utama.

Contoh:

Pertanian dan Produksi Pangan
Perikanan
Perdagangan
UMKM
Harga Pangan
Inflasi
Industri
Investasi
Tenaga Kerja
Konstruksi
Transportasi
Keuangan
Pendapatan Daerah
Pariwisata
Ekonomi Desa
Distribusi Barang
Pembangunan Ekonomi
Jasa

============================================================
ATURAN 4 — RINGKASAN
============================================================

INI SANGAT PENTING.

Ringkasan TIDAK BOLEH hanya mengubah sedikit kata
dari judul.

Ringkasan HARUS menjelaskan isi berita.

Gunakan struktur:

1. Apa yang terjadi?
2. Siapa yang melakukan/terlibat?
3. Apa angka/data pentingnya?
4. Apa tujuan atau dampaknya jika tersedia?

Gunakan 2–3 kalimat.

Maksimal 100 kata.

Jangan menggunakan kalimat:

"Pemberitaan ini membahas..."
"Berita ini membahas..."
"Artikel ini membahas..."

Langsung jelaskan fakta.

Contoh:

JUDUL:
"Festival Dayung Tejoasri Catat Transaksi UMKM Rp210 Juta"

RINGKASAN YANG BENAR:
"Festival Dayung Tejoasri 2026 di Desa Tejoasri,
Kecamatan Laren, melibatkan 155 pelaku UMKM.
Kegiatan tersebut mencatat estimasi perputaran ekonomi
sekitar Rp210 juta yang berasal dari aktivitas perdagangan
selama pelaksanaan festival."

Jangan membuat fakta yang tidak terdapat dalam artikel.

============================================================
ATURAN 5 — GUNAKAN ISI ARTIKEL
============================================================

Jika judul mengatakan sesuatu tetapi isi artikel
memberikan informasi yang lebih lengkap, gunakan
informasi dari isi artikel.

Jangan mengarang.

============================================================
FORMAT OUTPUT
============================================================

Jawab HANYA JSON ARRAY.

Format:

[
  {
    "id": "ID",
    "ekonomi": true,
    "sektor_kode": "A",
    "sektor": "A - Pertanian, Kehutanan, dan Perikanan",
    "isu_ekonomi": "Pertanian dan Produksi Pangan",
    "ringkasan": "Penjelasan berdasarkan isi artikel."
  }
]

Jika bukan ekonomi:

[
  {
    "id": "ID",
    "ekonomi": false,
    "sektor_kode": "",
    "sektor": "Tidak Relevan",
    "isu_ekonomi": "Tidak Relevan",
    "ringkasan": ""
  }
]

"""

    return prompt + "\n".join(
        blocks
    )


# ============================================================
# 🤖 ANALISIS GEMINI BATCH
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

        return []


    prompt = build_gemini_prompt(
        articles
    )


    try:

        response = client.models.generate_content(

            model="gemini-2.5-flash",

            contents=prompt

        )


        text_resp = (
            response.text or ""
        ).strip()


        # ----------------------------------------------------
        # Bersihkan markdown
        # ----------------------------------------------------

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
                "Output Gemini bukan array."
            )


        return results


    except Exception as e:

        logger.error(
            f"Gemini batch error: {e}"
        )

        return []


# ============================================================
# ✍️ PROMPT KHUSUS MEMPERBAIKI RINGKASAN
# ============================================================

def regenerate_summary(
    article
):

    if not client:

        return ""


    content = clean_text(
        article.get(
            "content",
            ""
        )
    )


    content = content[
        :MAX_CONTENT_FOR_AI
    ]


    prompt = f"""
Anda adalah editor berita untuk
Badan Pusat Statistik Kabupaten Lamongan.

Buat ringkasan berita berdasarkan ISI ARTIKEL,
bukan berdasarkan judul.

JUDUL:
{article.get("title", "")}

ISI ARTIKEL:
{content}

ATURAN:

1. Ringkasan 2-3 kalimat.
2. Maksimal 100 kata.
3. Jelaskan kejadian utama.
4. Jelaskan siapa yang terlibat.
5. Masukkan angka/data penting jika tersedia.
6. Jelaskan tujuan atau dampak jika tersedia.
7. Jangan membuat fakta baru.
8. Jangan menggunakan informasi dari luar artikel.
9. Jangan mengulang judul.
10. Jangan menggunakan kalimat "Berita ini membahas..."
11. Langsung tuliskan fakta.

HASILKAN HANYA RINGKASAN.
"""


    try:

        response = client.models.generate_content(

            model="gemini-2.5-flash",

            contents=prompt

        )


        summary = clean_text(
            response.text or ""
        )


        if (
            "```" in summary
        ):

            summary = re.sub(
                r"```.*?```",
                "",
                summary,
                flags=re.S
            ).strip()


        return summary


    except Exception as e:

        logger.warning(
            f"Gagal membuat ulang ringkasan: {e}"
        )

        return ""


# ============================================================
# 🧠 VALIDASI + PERBAIKAN SEKTOR
# ============================================================

def validate_ai_result(
    article,
    result
):

    ekonomi = result.get(
        "ekonomi",
        False
    )


    # --------------------------------------------------------
    # BUKAN EKONOMI
    # --------------------------------------------------------

    if ekonomi is not True:

        return {

            "ekonomi": False,

            "sektor": "Tidak Relevan",

            "isu_ekonomi": "Tidak Relevan",

            "ringkasan": ""

        }


    # --------------------------------------------------------
    # SEKTOR
    # --------------------------------------------------------

    sector_code = normalize_sector_code(

        result.get(
            "sektor_kode",
            ""
        )

    )


    # Jika kode gagal, coba baca nama sektor

    if not sector_code:

        sector_code = normalize_sector_code(

            result.get(
                "sektor",
                ""
            )

        )


    # Jika masih gagal,
    # coba identifikasi dari nama sektor / konteks

    if not sector_code:

        sector_code = detect_sector_from_text(

            result.get(
                "sektor",
                ""
            )

        )


    # --------------------------------------------------------
    # JIKA SEKTOR MASIH KOSONG
    # JANGAN LANGSUNG MEMBUANG BERITA
    # --------------------------------------------------------

    if not sector_code:

        logger.warning(
            "Sektor Gemini tidak valid. "
            f"Judul: {article.get('title', '')}"
        )

        return {

            "ekonomi": True,

            "sektor": "Perlu Review",

            "isu_ekonomi":
                clean_text(
                    result.get(
                        "isu_ekonomi",
                        "Ekonomi Daerah"
                    )
                ),

            "ringkasan":
                clean_text(
                    result.get(
                        "ringkasan",
                        ""
                    )
                )

        }


    sector_name = SEKTOR_BPS[
        sector_code
    ]


    # --------------------------------------------------------
    # ISU
    # --------------------------------------------------------

    issue = clean_text(

        result.get(
            "isu_ekonomi",
            ""
        )

    )


    if not issue:

        issue = "Ekonomi Daerah"


    # --------------------------------------------------------
    # RINGKASAN
    # --------------------------------------------------------

    summary = clean_text(

        result.get(
            "ringkasan",
            ""
        )

    )


    title = normalize_text(
        article.get(
            "title",
            ""
        )
    )


    summary_normalized = normalize_text(
        summary
    )


    # --------------------------------------------------------
    # CEK RINGKASAN
    # --------------------------------------------------------

    summary_too_short = (
        len(summary) < 50
    )


    summary_too_similar = False


    if (
        title
        and
        summary_normalized
    ):

        similarity = SequenceMatcher(

            None,

            title,

            summary_normalized

        ).ratio()


        # Juga cek apakah sebagian besar kata judul
        # hanya diulang di ringkasan

        title_words = set(
            title.split()
        )

        summary_words = set(
            summary_normalized.split()
        )


        if title_words:

            overlap = (
                len(
                    title_words
                    &
                    summary_words
                )
                /
                len(title_words)
            )

        else:

            overlap = 0


        if (
            similarity >= 0.72
            or
            overlap >= 0.85
        ):

            summary_too_similar = True


    # --------------------------------------------------------
    # JIKA RINGKASAN BURUK
    # BUAT ULANG
    # --------------------------------------------------------

    if (
        summary_too_short
        or
        summary_too_similar
    ):

        logger.info(
            "Ringkasan perlu diperbaiki: "
            f"{article.get('title', '')}"
        )


        new_summary = regenerate_summary(
            article
        )


        if new_summary:

            summary = new_summary


    # --------------------------------------------------------
    # JIKA MASIH TERLALU PENDEK
    # TETAP PERTAHANKAN BERITA
    # --------------------------------------------------------

    if len(summary) < 30:

        logger.warning(
            "Ringkasan Gemini masih pendek: "
            f"{article.get('title', '')}"
        )


    return {

        "ekonomi": True,

        "sektor":
            sector_name,

        "isu_ekonomi":
            issue,

        "ringkasan":
            summary

    }


# ============================================================
# 🔎 CEK DATA LAMA BERDASARKAN JUDUL
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

        }


    result = []


    for article in articles:

        url = normalize_url(
            article.get(
                "url",
                ""
            )
        )


        if url in old_urls:

            continue


        title = normalize_text(
            article.get(
                "title",
                ""
            )
        )


        # Judul sama persis

        if title in old_titles:

            continue


        # Judul sangat mirip

        duplicate = False


        for old_title in old_titles:

            similarity = SequenceMatcher(

                None,

                title,

                old_title

            ).ratio()


            if similarity >= 0.92:

                duplicate = True

                break


        if not duplicate:

            result.append(
                article
            )


    return result


# ============================================================
# 📥 FUNGSI UTAMA
# ============================================================

def fetch_and_process_news():

    if not client:

        st.error(
            "❌ Gemini AI belum aktif. "
            "Periksa GEMINI_API_KEY."
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


    progress = st.progress(
        0
    )

    status = st.empty()


    # ========================================================
    # 1. AMBIL RSS
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
    # 2. URL DUPLIKAT
    # ========================================================

    unique_url = {}

    for article in raw_articles:

        url = normalize_url(
            article.get(
                "url",
                ""
            )
        )


        if not url:

            continue


        if url not in unique_url:

            unique_url[
                url
            ] = article


    raw_articles = list(
        unique_url.values()
    )


    # Jangan potong terlalu awal.
    #
    # Sebelumnya MAX_TOTAL_CANDIDATES = 60
    # bisa membuat salah satu media dari berita
    # yang sama tidak ikut dibandingkan.
    #
    # Ambil lebih banyak kandidat.

    raw_articles = raw_articles[
        :100
    ]


    # ========================================================
    # 3. FILTER DATA LAMA
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
        f"🆕 {len(new_articles)} "
        "berita baru ditemukan."
    )


    if not new_articles:

        progress.progress(
            1.0
        )

        status.success(
            "✅ Tidak ada berita baru."
        )

        progress.empty()

        return existing_df


    # ========================================================
    # 4. BACA ISI ARTIKEL
    # ========================================================

    status.info(
        "📖 Membaca isi berita..."
    )


    enriched_articles = (
        enrich_articles_parallel(
            new_articles,
            progress=None,
            status=status
        )
    )


    # Hanya buang jika isi benar-benar terlalu sedikit

    enriched_articles = [

        article

        for article
        in enriched_articles

        if len(
            clean_text(
                article.get(
                    "content",
                    ""
                )
            )
        ) >= 100

    ]


    status.info(
        f"📚 {len(enriched_articles)} "
        "artikel berhasil dibaca."
    )


    # ========================================================
    # 5. DEDUPLIKASI ANTAR MEDIA
    # ========================================================

    status.info(
        "🔄 Membandingkan berita dari berbagai media..."
    )


    before = len(
        enriched_articles
    )


    unique_articles = (
        remove_similar_articles(
            enriched_articles
        )
    )


    removed = (
        before
        -
        len(unique_articles)
    )


    status.info(
        f"♻️ {removed} berita yang sama "
        "dihapus. Artikel dengan isi paling lengkap "
        "dipertahankan."
    )


    # ========================================================
    # 6. GEMINI
    # ========================================================

    total = len(
        unique_articles
    )


    if total == 0:

        progress.empty()

        return existing_df


    all_ai_results = []


    for start in range(
        0,
        total,
        AI_BATCH_SIZE
    ):

        batch = unique_articles[
            start:
            start + AI_BATCH_SIZE
        ]


        batch_number = (
            start // AI_BATCH_SIZE
        ) + 1


        total_batches = (
            total
            +
            AI_BATCH_SIZE
            -
            1
        ) // AI_BATCH_SIZE


        status.info(
            f"🤖 Gemini menganalisis "
            f"batch {batch_number}/{total_batches}..."
        )


        results = analyze_batch_with_gemini(
            batch
        )


        all_ai_results.extend(
            results
        )


        progress.progress(

            0.4
            +
            (
                0.45
                *
                (
                    start
                    +
                    len(batch)
                )
                /
                total
            )

        )


    # ========================================================
    # 7. INDEX HASIL GEMINI
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
    # 8. HASIL AKHIR
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

                "ekonomi": False,

                "sektor_kode": "",

                "sektor": "",

                "isu_ekonomi": "",

                "ringkasan": ""

            }

        )


        ai_result = validate_ai_result(

            article,

            ai_raw

        )


        # ----------------------------------------------------
        # EKONOMI
        # ----------------------------------------------------

        if ai_result["ekonomi"]:

            final_records.append({

                "ID":
                    article_id,

                "Tanggal Berita":
                    article.get(
                        "date",
                        ""
                    ),

                "Media":
                    article.get(
                        "source",
                        ""
                    ),

                "Judul Berita":
                    article.get(
                        "title",
                        ""
                    ),

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
                    normalize_url(
                        article.get(
                            "url",
                            ""
                        )
                    )

            })


        # ----------------------------------------------------
        # BUKAN EKONOMI
        # ----------------------------------------------------

        else:

            rejected_articles.append({

                "Tanggal":
                    article.get(
                        "date",
                        ""
                    ),

                "Media":
                    article.get(
                        "source",
                        ""
                    ),

                "Judul":
                    article.get(
                        "title",
                        ""
                    ),

                "URL":
                    article.get(
                        "url",
                        ""
                    )

            })


    # ========================================================
    # 9. SIMPAN NON-EKONOMI
    # ========================================================

    save_rejected_data(
        rejected_articles
    )


    new_df = pd.DataFrame(
        final_records
    )


    # ========================================================
    # 10. GABUNG DATA LAMA
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

        status.warning(
            "⚠️ Belum ada berita ekonomi "
            "yang tersimpan."
        )

        progress.progress(
            1.0
        )

        progress.empty()

        return pd.DataFrame()


    # ========================================================
    # 11. NORMALISASI URL
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
    # 12. HAPUS JUDUL SAMA
    # ========================================================

    if "Judul Berita" in combined_df.columns:

        combined_df[
            "_judul_normal"
        ] = combined_df[
            "Judul Berita"
        ].apply(
            normalize_text
        )


        combined_df = (
            combined_df
            .drop_duplicates(
                subset=[
                    "_judul_normal"
                ],
                keep="first"
            )
            .drop(
                columns=[
                    "_judul_normal"
                ],
                errors="ignore"
            )
        )


    # ========================================================
    # 13. SORTING
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
    # 14. SIMPAN
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
    # 15. SELESAI
    # ========================================================

    progress.progress(
        1.0
    )


    status.success(

        f"✅ Selesai! "
        f"{len(final_records)} berita ekonomi baru "
        f"berhasil dianalisis. "
        f"{removed} berita duplikat dihapus."

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

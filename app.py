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
# 📊 MASTER 17 SEKTOR LAPANGAN USAHA BPS
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
# ⚙️ PENGATURAN
# ============================================================

MAX_RESULTS_PER_TOPIC = 10

MAX_TOTAL_CANDIDATES = 80

RSS_WORKERS = 8

ARTICLE_WORKERS = 10

ARTICLE_TIMEOUT = 8

AI_BATCH_SIZE = 5

MAX_CONTENT_FOR_AI = 9000


# ============================================================
# 🔎 TOPIK PENCARIAN
# ============================================================

SEARCH_TOPICS = [

    "Lamongan ekonomi",

    "Kabupaten Lamongan ekonomi",

    "Pemkab Lamongan ekonomi",

    "Lamongan pertanian",

    "Lamongan perikanan",

    "Lamongan petani",

    "Lamongan tambak",

    "Lamongan UMKM",

    "Lamongan perdagangan",

    "Lamongan pasar",

    "Lamongan industri",

    "Lamongan investasi",

    "Lamongan tenaga kerja",

    "Lamongan harga pangan",

    "Lamongan pembangunan",

    "Lamongan infrastruktur",

    "Lamongan pariwisata",

    "Lamongan keuangan",

    "Lamongan APBD",

    "Lamongan PAD"

]


# ============================================================
# 🧠 PROMPT GEMINI
# ============================================================

AI_CLASSIFICATION_PROMPT = """

Anda adalah analis berita ekonomi untuk
Badan Pusat Statistik Kabupaten Lamongan.

Tugas Anda adalah membaca dan memahami ISI ARTIKEL,
kemudian menentukan:

1. Apakah berita tersebut merupakan berita ekonomi
   yang berkaitan dengan Kabupaten Lamongan.
2. Apa aktivitas ekonomi utama dalam berita.
3. Apa isu ekonomi utamanya.
4. Apa sektor lapangan usaha BPS yang paling sesuai.
5. Membuat ringkasan berdasarkan ISI ARTIKEL,
   bukan berdasarkan judul.

============================================================
ATURAN PALING PENTING
============================================================

JANGAN menentukan klasifikasi hanya berdasarkan judul.

WAJIB membaca isi artikel.

Judul hanya digunakan sebagai konteks.

Jika judul mengandung kata ekonomi, pasar, harga,
UMKM, pemerintah, pembangunan atau petani,
tetapi isi sebenarnya bukan berita ekonomi,
maka ekonomi = false.

Isi artikel adalah sumber utama keputusan.

============================================================
1. TENTUKAN BERITA EKONOMI
============================================================

ekonomi = true jika isi artikel membahas aktivitas
ekonomi yang terjadi di Kabupaten Lamongan atau
berdampak langsung terhadap aktivitas ekonomi Lamongan.

Contoh:

- pertanian
- perkebunan
- kehutanan
- perikanan
- tambak
- peternakan
- produksi
- industri
- perdagangan
- pasar
- UMKM
- koperasi
- investasi
- tenaga kerja
- upah
- harga barang
- distribusi barang
- transportasi
- pergudangan
- konstruksi
- pembangunan infrastruktur ekonomi
- hotel
- restoran
- kuliner
- pariwisata
- perbankan
- kredit
- pembiayaan
- asuransi
- real estat
- teknologi dan komunikasi
- pendidikan
- kesehatan
- jasa perusahaan
- administrasi pemerintah yang berkaitan dengan
  aktivitas ekonomi, anggaran, pendapatan, belanja,
  pajak atau kebijakan ekonomi.

============================================================
2. BUKAN EKONOMI
============================================================

ekonomi = false jika isi artikel hanya membahas:

- kriminalitas
- pencurian
- pembunuhan
- kecelakaan
- olahraga
- Persela
- politik murni
- pilkada
- konflik politik
- hukum murni
- kegiatan keagamaan murni
- hiburan murni
- kegiatan sosial murni
- seremoni tanpa dampak ekonomi
- berita daerah lain yang tidak berkaitan dengan Lamongan.

Jangan memaksakan berita menjadi ekonomi.

============================================================
3. AKTIVITAS EKONOMI UTAMA
============================================================

Sebelum menentukan sektor, tentukan:

"Apa kegiatan utama yang sebenarnya dibahas
dalam isi berita?"

Contoh:

Petani meningkatkan produksi padi
→ produksi pertanian

Pedagang meningkatkan transaksi
→ perdagangan

Pabrik mengolah hasil pertanian
→ industri pengolahan

Pemerintah meningkatkan PAD
→ administrasi pemerintahan

Bank memberikan kredit UMKM
→ jasa keuangan

Hotel meningkatkan okupansi
→ akomodasi

============================================================
4. 17 SEKTOR BPS
============================================================

A
Pertanian, Kehutanan, dan Perikanan

B
Pertambangan dan Penggalian

C
Industri Pengolahan

D
Pengadaan Listrik dan Gas

E
Pengadaan Air, Pengelolaan Sampah,
Limbah dan Daur Ulang

F
Konstruksi

G
Perdagangan Besar dan Eceran;
Reparasi Mobil dan Sepeda Motor

H
Transportasi dan Pergudangan

I
Penyediaan Akomodasi dan Makan Minum

J
Informasi dan Komunikasi

K
Jasa Keuangan dan Asuransi

L
Real Estat

MN
Jasa Perusahaan

O
Administrasi Pemerintahan, Pertahanan
dan Jaminan Sosial Wajib

P
Jasa Pendidikan

Q
Jasa Kesehatan dan Kegiatan Sosial

RSTU
Jasa Lainnya

============================================================
5. PEMETAAN SEKTOR
============================================================

A = Pertanian, Kehutanan, dan Perikanan

Gunakan A untuk:

- padi
- jagung
- tebu
- tembakau
- kedelai
- hortikultura
- sayuran
- buah
- perkebunan
- petani
- sawah
- panen
- bibit
- pupuk
- irigasi pertanian
- peternakan
- sapi
- kambing
- ayam
- telur
- susu
- nelayan
- ikan
- tambak
- budidaya ikan
- perikanan tangkap
- hasil laut
- kehutanan

Jika inti berita adalah produksi pertanian,
peternakan, kehutanan atau perikanan,
gunakan A.

------------------------------------------------------------

B = Pertambangan dan Penggalian

Gunakan B untuk:

- tambang
- pasir
- batu
- mineral
- galian
- eksplorasi tambang
- produksi bahan tambang

------------------------------------------------------------

C = Industri Pengolahan

Gunakan C jika inti kegiatan adalah
mengolah bahan menjadi produk.

Contoh:

- pabrik
- manufaktur
- industri makanan
- industri minuman
- industri tekstil
- industri mebel
- industri pengolahan hasil pertanian
- industri pengolahan ikan
- produksi barang di pabrik

Jika hanya menjual produk → G.

Jika mengolah produk menjadi barang → C.

------------------------------------------------------------

D = Pengadaan Listrik dan Gas

Gunakan D untuk:

- pembangkit listrik
- distribusi listrik
- penyediaan listrik
- jaringan listrik
- gas
- energi

------------------------------------------------------------

E = Pengadaan Air, Pengelolaan Sampah,
Limbah dan Daur Ulang

Gunakan E untuk:

- air bersih
- pengelolaan sampah
- limbah
- daur ulang
- pengelolaan air
- sanitasi yang berkaitan dengan pengelolaan lingkungan

------------------------------------------------------------

F = Konstruksi

Gunakan F untuk:

- pembangunan jalan
- pembangunan jembatan
- pembangunan gedung
- pembangunan pasar
- pembangunan irigasi
- pembangunan infrastruktur
- proyek konstruksi
- rehabilitasi bangunan
- pekerjaan konstruksi

------------------------------------------------------------

G = Perdagangan Besar dan Eceran;
Reparasi Mobil dan Sepeda Motor

Gunakan G untuk:

- pasar
- pedagang
- toko
- jual beli
- transaksi perdagangan
- distribusi perdagangan
- UMKM yang aktivitas utamanya menjual barang
- perdagangan hasil pertanian
- perdagangan hasil perikanan
- grosir
- eceran
- pusat perdagangan
- dealer kendaraan
- bengkel
- reparasi kendaraan

UMKM TIDAK otomatis G.

Jika UMKM memproduksi barang → C.

Jika UMKM menjual barang → G.

Jika UMKM restoran → I.

Jika UMKM jasa → sektor jasa yang sesuai.

------------------------------------------------------------

H = Transportasi dan Pergudangan

Gunakan H untuk:

- angkutan
- transportasi
- logistik
- ekspedisi
- pengiriman
- pergudangan
- terminal
- distribusi logistik

------------------------------------------------------------

I = Penyediaan Akomodasi dan Makan Minum

Gunakan I untuk:

- hotel
- penginapan
- homestay
- restoran
- rumah makan
- warung makan
- katering
- usaha makanan dan minuman
- kuliner

------------------------------------------------------------

J = Informasi dan Komunikasi

Gunakan J untuk:

- telekomunikasi
- internet
- teknologi informasi
- aplikasi
- platform digital
- media
- penyiaran
- layanan komunikasi

------------------------------------------------------------

K = Jasa Keuangan dan Asuransi

Gunakan K untuk:

- bank
- perbankan
- kredit
- pinjaman
- pembiayaan
- fintech
- koperasi simpan pinjam
- asuransi
- lembaga keuangan

------------------------------------------------------------

L = Real Estat

Gunakan L untuk:

- properti
- perumahan
- real estat
- jual beli properti
- sewa properti
- kawasan perumahan

------------------------------------------------------------

MN = Jasa Perusahaan

Gunakan MN untuk:

- konsultasi bisnis
- akuntansi
- jasa profesional
- jasa perusahaan
- jasa administrasi bisnis
- jasa arsitektur
- jasa hukum bisnis

------------------------------------------------------------

O = Administrasi Pemerintahan,
Pertahanan dan Jaminan Sosial Wajib

Gunakan O jika inti kegiatan adalah:

- administrasi pemerintahan
- APBD
- PAD
- pajak daerah
- retribusi
- pendapatan pemerintah
- belanja pemerintah
- pengelolaan anggaran
- kebijakan administrasi pemerintah
- jaminan sosial wajib

CATATAN:

Jika pemerintah hanya menjadi pelaksana program,
tetapi kegiatan utama adalah pertanian,
perdagangan, konstruksi atau sektor lain,
pilih sektor aktivitas tersebut.

Contoh:

"Pemerintah memberikan bantuan pupuk kepada petani"

→ A

bukan O.

Contoh:

"Pemkab meningkatkan target PAD"

→ O.

------------------------------------------------------------

P = Jasa Pendidikan

Gunakan P untuk:

- sekolah
- perguruan tinggi
- pendidikan
- pelatihan
- lembaga pendidikan
- usaha pendidikan

------------------------------------------------------------

Q = Jasa Kesehatan dan Kegiatan Sosial

Gunakan Q untuk:

- rumah sakit
- klinik
- puskesmas
- layanan kesehatan
- tenaga kesehatan
- fasilitas kesehatan
- kegiatan sosial sebagai layanan sosial

------------------------------------------------------------

RSTU = Jasa Lainnya

Gunakan RSTU jika aktivitas utama termasuk
jasa lain yang tidak masuk A-Q.

Contoh:

- kesenian
- hiburan
- rekreasi
- jasa personal
- jasa lainnya

============================================================
6. JIKA BERITA MEMILIKI BEBERAPA SEKTOR
============================================================

Pilih HANYA SATU.

Pilih sektor yang:

1. paling dominan;
2. menjadi aktivitas ekonomi utama;
3. paling banyak dibahas;
4. paling berhubungan dengan inti peristiwa.

Jangan memilih sektor hanya karena kata tersebut
muncul satu kali.

============================================================
7. RINGKASAN
============================================================

Ringkasan WAJIB berdasarkan ISI ARTIKEL.

JANGAN hanya mengulang judul.

Ringkasan harus menjelaskan:

- apa yang terjadi;
- siapa yang terlibat;
- lokasi jika tersedia;
- angka penting jika tersedia;
- tujuan atau penyebab jika disebutkan;
- dampak atau hasil jika disebutkan.

Panjang 2-4 kalimat.

Sekitar 50-100 kata.

Masukkan angka/data penting jika tersedia.

Jangan membuat angka atau fakta baru.

Jangan mengambil informasi dari luar artikel.

============================================================
8. CONTOH RINGKASAN BURUK
============================================================

Judul:
Harga Cabai di Lamongan Naik

Ringkasan buruk:
"Harga cabai di Lamongan mengalami kenaikan."

Itu hanya mengulang judul.

============================================================
9. CONTOH RINGKASAN YANG BENAR
============================================================

Jika artikel menjelaskan harga sebelumnya,
harga sekarang dan penyebabnya:

"Harga cabai rawit di sejumlah pasar Lamongan meningkat
dari Rp60 ribu menjadi Rp75 ribu per kilogram. Pedagang
menyebut kenaikan tersebut dipengaruhi terbatasnya pasokan,
sementara permintaan masyarakat masih tinggi."

============================================================
10. OUTPUT
============================================================

Jawab HANYA JSON ARRAY.

Format:

[
    {
        "id": "123",
        "ekonomi": true,
        "aktivitas_utama": "produksi pertanian",
        "sektor_kode": "A",
        "isu_ekonomi": "Pertanian dan Produksi Pangan",
        "ringkasan": "Ringkasan berdasarkan isi artikel."
    }
]

Jika bukan ekonomi:

[
    {
        "id": "123",
        "ekonomi": false,
        "aktivitas_utama": "",
        "sektor_kode": "",
        "isu_ekonomi": "Tidak Relevan",
        "ringkasan": ""
    }
]

JANGAN memberikan markdown.

JANGAN memberikan penjelasan di luar JSON.
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

def jaccard_similarity(
    text_a,
    text_b
):

    a = text_tokens(
        text_a
    )

    b = text_tokens(
        text_b
    )

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

def make_id(
    title,
    link
):

    return hashlib.md5(
        (
            str(title)
            +
            str(link)
        ).encode("utf-8")
    ).hexdigest()


# ============================================================
# 🔗 NORMALISASI URL
# ============================================================

def normalize_url(url):

    if not url:
        return ""

    url = str(
        url
    ).strip()

    url = url.split(
        "#"
    )[0]

    return url.rstrip(
        "/"
    )


# ============================================================
# 📰 EKSTRAK ISI ARTIKEL
# ============================================================

def extract_article_content(
    url,
    fallback_summary=""
):

    if not url:

        return {

            "content":
                clean_text(
                    fallback_summary
                ),

            "canonical_url":
                ""

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


        original_soup = BeautifulSoup(
            response.text,
            "html.parser"
        )


        # ====================================================
        # CANONICAL
        # ====================================================

        canonical_url = ""

        canonical_tag = (
            original_soup.find(
                "link",
                rel="canonical"
            )
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
        # JSON-LD ARTICLE BODY
        # ====================================================

        article_body = ""


        for script in original_soup.find_all(
            "script",
            type="application/ld+json"
        ):

            try:

                raw_json = (
                    script.string
                    or
                    script.get_text()
                )


                data = json.loads(
                    raw_json
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

                        objects = data[
                            "@graph"
                        ]

                    else:

                        objects = [
                            data
                        ]


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


                if len(
                    article_body
                ) >= 300:

                    break


            except Exception:

                continue


        if len(
            article_body
        ) >= 300:

            return {

                "content":
                    article_body,

                "canonical_url":
                    canonical_url

            }


        # ====================================================
        # BUAT SOUP BERSIH
        # ====================================================

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )


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
        # ARTICLE
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


            if len(
                article_text
            ) >= 300:

                return {

                    "content":
                        article_text,

                    "canonical_url":
                        canonical_url

                }


        # ====================================================
        # PARAGRAF
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


            if len(
                text_p
            ) >= 40:

                paragraph_list.append(
                    text_p
                )


        article_text = " ".join(
            paragraph_list
        )


        if len(
            article_text
        ) >= 300:

            return {

                "content":
                    article_text,

                "canonical_url":
                    canonical_url

            }


        # ====================================================
        # META DESCRIPTION
        # ====================================================

        meta = soup.find(
            "meta",
            attrs={
                "name":
                    "description"
            }
        )


        if meta:

            meta_text = clean_text(
                meta.get(
                    "content",
                    ""
                )
            )


            if len(
                meta_text
            ) >= 100:

                return {

                    "content":
                        meta_text,

                    "canonical_url":
                        canonical_url

                }


        # ====================================================
        # FALLBACK RSS
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
            f"Gagal membaca artikel "
            f"{url}: {e}"
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
# 🚫 LOAD BERITA DITOLAK
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
# 💾 SIMPAN BERITA DITOLAK
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

        combined = (
            combined
            .drop_duplicates(
                subset=[
                    "URL"
                ],
                keep="first"
            )
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
# 🔤 NORMALISASI JUDUL
# ============================================================

def normalize_title_for_duplicate(
    title
):

    if not title:

        return ""


    text = normalize_text(
        title
    )


    # Kata pembuka yang sering berbeda
    # tetapi tidak mengubah inti berita.

    stop_phrases = [

        "breaking",

        "update",

        "terbaru",

        "simak",

        "cek",

        "begini",

        "ungkap",

        "fakta"

    ]


    words = [

        word

        for word
        in text.split()

        if word not in stop_phrases

    ]


    return " ".join(
        words
    )


# ============================================================
# 🆔 CEK ARTIKEL SUDAH ADA
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


    # ========================================================
    # URL DITOLAK
    # ========================================================

    if url in rejected_urls:

        return True


    if existing_df.empty:

        return False


    # ========================================================
    # URL LAMA
    # ========================================================

    if "Link Berita" in existing_df.columns:

        existing_urls = {

            normalize_url(x)

            for x in
            existing_df[
                "Link Berita"
            ]
            .dropna()
            .astype(str)

        }


        if url in existing_urls:

            return True


    # ========================================================
    # JUDUL LAMA
    # ========================================================

    title = normalize_title_for_duplicate(
        article.get(
            "title",
            ""
        )
    )


    if not title:

        return False


    if "Judul Berita" in existing_df.columns:

        for old_title in (

            existing_df[
                "Judul Berita"
            ]
            .dropna()
            .astype(str)

        ):

            old_normalized = (
                normalize_title_for_duplicate(
                    old_title
                )
            )


            if title == old_normalized:

                return True


    return False


# ============================================================
# 📰 AMBIL RSS
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


            source_name = "Berita Online"


            if (
                entry.get("source")
                and
                entry.source.get(
                    "title"
                )
            ):

                source_name = clean_text(
                    entry.source.get(
                        "title"
                    )
                )


            pub_date = (
                datetime.now()
                .strftime(
                    "%Y-%m-%d"
                )
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
# 📰 AMBIL SEMUA RSS PARALEL
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
    # HAPUS DUPLIKAT URL
    # ========================================================

    unique = {}


    for article in all_articles:

        key = normalize_url(
            article.get(
                "url",
                ""
            )
        )


        if key:

            unique[key] = article


    return list(
        unique.values()
    )


# ============================================================
# 📰 ENRICH ARTIKEL
# ============================================================

def enrich_article(
    article
):

    result = extract_article_content(

        article.get(
            "url",
            ""
        ),

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
# 📰 ENRICH PARALEL
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
# 🔍 SIMILARITY ISI
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


    a = normalize_text(
        content_a[:6000]
    )


    b = normalize_text(
        content_b[:6000]
    )


    if not a or not b:

        return 0


    jaccard = jaccard_similarity(
        a,
        b
    )


    if jaccard >= 0.55:

        seq = SequenceMatcher(
            None,
            a[:3500],
            b[:3500]
        ).ratio()


        return max(
            jaccard,
            seq
        )


    return jaccard


# ============================================================
# 🏆 SKOR KUALITAS ARTIKEL
# ============================================================

def article_quality_score(
    article
):

    content = clean_text(
        article.get(
            "content",
            ""
        )
    )


    if not content:

        return 0


    score = 0


    # --------------------------------------------------------
    # JUMLAH KATA
    # --------------------------------------------------------

    word_count = len(
        content.split()
    )


    score += min(
        word_count / 100,
        20
    )


    # --------------------------------------------------------
    # JUMLAH KALIMAT
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
    # DATA / ANGKA
    # --------------------------------------------------------

    numbers = re.findall(
        r"\b\d+(?:[.,]\d+)?\b",
        content
    )


    score += min(
        len(numbers),
        10
    )


    # --------------------------------------------------------
    # KUTIPAN
    # --------------------------------------------------------

    quotation_count = (
        content.count('"')
        +
        content.count("'")
    )


    if quotation_count >= 2:

        score += 3


    # --------------------------------------------------------
    # PERSENTASE
    # --------------------------------------------------------

    if "%" in content:

        score += 3


    # --------------------------------------------------------
    # TAHUN
    # --------------------------------------------------------

    if re.search(
        r"\b20\d{2}\b",
        content
    ):

        score += 2


    return score


# ============================================================
# 🔍 DETEKSI BERITA YANG SAMA
# ============================================================

def is_same_story(
    article_a,
    article_b
):

    title_a = normalize_title_for_duplicate(
        article_a.get(
            "title",
            ""
        )
    )


    title_b = normalize_title_for_duplicate(
        article_b.get(
            "title",
            ""
        )
    )


    if not title_a or not title_b:

        return False


    # ========================================================
    # JUDUL SAMA
    # ========================================================

    if title_a == title_b:

        return True


    # ========================================================
    # JUDUL HAMPIR SAMA
    # ========================================================

    title_sim = SequenceMatcher(
        None,
        title_a,
        title_b
    ).ratio()


    if title_sim >= 0.93:

        return True


    # ========================================================
    # ISI SANGAT MIRIP
    # ========================================================

    content_a = article_a.get(
        "content",
        ""
    )


    content_b = article_b.get(
        "content",
        ""
    )


    if (
        len(content_a) >= 300
        and
        len(content_b) >= 300
    ):

        content_sim = content_similarity(
            content_a,
            content_b
        )


        if content_sim >= 0.78:

            return True


    # ========================================================
    # JUDUL CUKUP MIRIP + ISI CUKUP MIRIP
    # ========================================================

    if title_sim >= 0.82:

        if (
            len(content_a) >= 200
            and
            len(content_b) >= 200
        ):

            content_sim = content_similarity(
                content_a,
                content_b
            )


            if content_sim >= 0.55:

                return True


    return False


# ============================================================
# 🧹 HAPUS DUPLIKAT & PILIH ARTIKEL TERLENGKAP
# ============================================================

def remove_similar_articles(
    articles
):

    if not articles:

        return []


    # ========================================================
    # ARTIKEL TERLENGKAP DIURUTKAN TERLEBIH DAHULU
    # ========================================================

    articles = sorted(

        articles,

        key=article_quality_score,

        reverse=True

    )


    selected = []


    for article in articles:

        duplicate = False


        for existing in selected:

            if is_same_story(
                article,
                existing
            ):

                duplicate = True


                logger.info(
                    "Duplikat ditemukan. "
                    f"Artikel dibuang: "
                    f"{article.get('title', '')} | "
                    f"Media: "
                    f"{article.get('source', '')}"
                )


                break


        if not duplicate:

            selected.append(
                article
            )


    return selected


# ============================================================
# 🧠 NORMALISASI KODE SEKTOR
# ============================================================

def normalize_sector_code(
    value
):

    if value is None:

        return ""


    value = str(
        value
    ).strip().upper()


    # Hilangkan karakter selain huruf
    value = re.sub(
        r"[^A-Z]",
        "",
        value
    )


    aliases = {

        "A": "A",

        "B": "B",

        "C": "C",

        "D": "D",

        "E": "E",

        "F": "F",

        "G": "G",

        "H": "H",

        "I": "I",

        "J": "J",

        "K": "K",

        "L": "L",

        "MN": "MN",

        "M": "MN",

        "N": "MN",

        "O": "O",

        "P": "P",

        "Q": "Q",

        "RSTU": "RSTU",

        "R": "RSTU",

        "S": "RSTU",

        "T": "RSTU",

        "U": "RSTU"

    }


    return aliases.get(
        value,
        ""
    )


# ============================================================
# 🧠 FALLBACK SEKTOR
# ============================================================
#
# Hanya digunakan jika Gemini gagal memberikan
# kode sektor yang valid.
#
# BUKAN untuk menentukan ekonomi/non-ekonomi.
# Gemini tetap menjadi penentu ekonomi.
# ============================================================

def fallback_sector_from_text(
    article
):

    text = normalize_text(
        (
            article.get(
                "title",
                ""
            )
            +
            " "
            +
            article.get(
                "content",
                ""
            )
        )
    )


    sector_keywords = {

        "A": [

            "padi",
            "jagung",
            "petani",
            "pertanian",
            "sawah",
            "panen",
            "tebu",
            "tembakau",
            "perkebunan",
            "nelayan",
            "perikanan",
            "tambak",
            "ikan",
            "budidaya",
            "peternakan",
            "sapi",
            "ayam",
            "kambing"

        ],


        "B": [

            "tambang",
            "pertambangan",
            "galian",
            "pasir",
            "mineral"

        ],


        "C": [

            "pabrik",
            "manufaktur",
            "industri",
            "produksi",
            "pengolahan",
            "diproduksi",
            "produksi barang"

        ],


        "D": [

            "listrik",
            "pembangkit",
            "energi",
            "gas"

        ],


        "E": [

            "sampah",
            "limbah",
            "daur ulang",
            "air bersih",
            "pengelolaan sampah"

        ],


        "F": [

            "konstruksi",
            "jalan",
            "jembatan",
            "gedung",
            "irigasi",
            "pembangunan infrastruktur"

        ],


        "G": [

            "pasar",
            "pedagang",
            "perdagangan",
            "jual beli",
            "toko",
            "transaksi",
            "eceran",
            "grosir",
            "omzet"

        ],


        "H": [

            "transportasi",
            "angkutan",
            "logistik",
            "ekspedisi",
            "pengiriman",
            "pergudangan"

        ],


        "I": [

            "hotel",
            "restoran",
            "rumah makan",
            "warung",
            "kuliner",
            "katering",
            "penginapan"

        ],


        "J": [

            "telekomunikasi",
            "internet",
            "aplikasi",
            "digital",
            "teknologi informasi",
            "platform"

        ],


        "K": [

            "bank",
            "kredit",
            "pinjaman",
            "pembiayaan",
            "asuransi",
            "perbankan",
            "keuangan"

        ],


        "L": [

            "properti",
            "perumahan",
            "real estat",
            "perumahan"

        ],


        "MN": [

            "konsultan",
            "akuntansi",
            "jasa perusahaan",
            "konsultasi bisnis"

        ],


        "O": [

            "apbd",
            "pad",
            "pendapatan daerah",
            "belanja daerah",
            "pajak daerah",
            "retribusi daerah"

        ],


        "P": [

            "sekolah",
            "pendidikan",
            "universitas",
            "perguruan tinggi",
            "pelatihan"

        ],


        "Q": [

            "rumah sakit",
            "puskesmas",
            "klinik",
            "kesehatan",
            "tenaga kesehatan"

        ],


        "RSTU": [

            "hiburan",
            "rekreasi",
            "kesenian",
            "jasa personal"

        ]

    }


    scores = {}


    for code, keywords in sector_keywords.items():

        score = 0


        for keyword in keywords:

            if keyword in text:

                score += 1


        scores[code] = score


    if not scores:

        return ""


    best_code = max(
        scores,
        key=scores.get
    )


    if scores[best_code] == 0:

        return ""


    return best_code


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
    # BUKAN EKONOMI
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
    # AMBIL KODE SEKTOR DARI GEMINI
    # ========================================================

    sektor_code = normalize_sector_code(
        result.get(
            "sektor_kode",
            ""
        )
    )


    # ========================================================
    # FALLBACK JIKA GEMINI TIDAK MEMBERIKAN KODE VALID
    # ========================================================

    if sektor_code not in SEKTOR_BPS:

        logger.warning(
            "Gemini tidak memberikan sektor valid. "
            "Menggunakan fallback sektor."
        )


        sektor_code = fallback_sector_from_text(
            article
        )


    # ========================================================
    # JIKA MASIH TIDAK DITEMUKAN
    # ========================================================

    if sektor_code not in SEKTOR_BPS:

        logger.warning(
            f"Sektor tidak dapat ditentukan: "
            f"{article.get('title', '')}"
        )


        return {

            "ekonomi":
                False,

            "sektor":
                "Tidak Relevan",

            "isu_ekonomi":
                "Sektor tidak dapat ditentukan",

            "ringkasan":
                ""

        }


    # ========================================================
    # KONVERSI KODE MENJADI NAMA SEKTOR
    # ========================================================

    sektor = SEKTOR_BPS[
        sektor_code
    ]


    # ========================================================
    # ISU EKONOMI
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


    if len(
        ringkasan
    ) < 40:

        logger.warning(
            "Ringkasan terlalu pendek."
        )


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


    if similarity >= 0.90:

        logger.warning(
            "Ringkasan terlalu mirip dengan judul."
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


    news_blocks = []


    for article in articles:

        article_id = make_id(
            article.get(
                "title",
                ""
            ),
            article.get(
                "url",
                ""
            )
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


        news_blocks.append(

            f"""
============================================================
BERITA
============================================================

ID:
{article_id}

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


    prompt = (
        AI_CLASSIFICATION_PROMPT
        +
        "\n\n"
        +
        "\n".join(
            news_blocks
        )
    )


    try:

        response = client.models.generate_content(

            model="gemini-2.5-flash",

            contents=prompt

        )


        text_resp = (
            response.text
            or
            ""
        ).strip()


        if not text_resp:

            raise ValueError(
                "Gemini tidak memberikan response."
            )


        # ====================================================
        # BERSIHKAN MARKDOWN
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


        # ====================================================
        # CARI JSON ARRAY
        # ====================================================

        start = text_resp.find(
            "["
        )

        end = text_resp.rfind(
            "]"
        )


        if (
            start == -1
            or
            end == -1
        ):

            raise ValueError(
                "Output Gemini bukan JSON ARRAY."
            )


        text_resp = text_resp[
            start:
            end + 1
        ]


        results = json.loads(
            text_resp
        )


        if not isinstance(
            results,
            list
        ):

            raise ValueError(
                "Output Gemini bukan list."
            )


        logger.info(
            f"Gemini berhasil menganalisis "
            f"{len(results)} berita."
        )


        return results


    except Exception as e:

        logger.error(
            f"Gemini batch error: {e}"
        )

        return []


# ============================================================
# 📥 FUNGSI UTAMA
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
    # LOAD DATA
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

            for x in
            rejected_df[
                "URL"
            ]
            .dropna()
            .astype(str)

        }


    # ========================================================
    # PROGRESS
    # ========================================================

    progress = st.progress(
        0
    )

    status = st.empty()


    # ========================================================
    # TAHAP 1
    # RSS
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
    # HAPUS URL DUPLIKAT
    # ========================================================

    raw_articles = list({

        normalize_url(
            a.get(
                "url",
                ""
            )
        ):
            a

        for a in raw_articles

        if normalize_url(
            a.get(
                "url",
                ""
            )
        )

    }.values())


    # ========================================================
    # BATASI KANDIDAT
    # ========================================================

    raw_articles = raw_articles[
        :MAX_TOTAL_CANDIDATES
    ]


    # ========================================================
    # TAHAP 2
    # CEK DATA LAMA
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
    # TAHAP 3
    # BACA ARTIKEL
    # ========================================================

    progress.progress(
        0.20
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
    # HANYA ARTIKEL DENGAN ISI CUKUP
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
        ) >= 150

    ]


    status.info(
        f"📚 Berhasil membaca "
        f"{len(enriched_articles)} artikel."
    )


    # ========================================================
    # TAHAP 4
    # DUPLIKAT ANTAR-MEDIA
    # ========================================================

    status.info(
        "🔄 Membandingkan judul dan isi berita "
        "antar-media..."
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
        f"♻️ {duplicate_count} berita yang sama "
        "dihapus. Artikel dengan isi paling lengkap "
        "dipertahankan."
    )


    # ========================================================
    # JIKA KOSONG
    # ========================================================

    if not unique_articles:

        status.warning(
            "⚠️ Tidak ada artikel unik."
        )


        progress.progress(
            1.0
        )


        progress.empty()


        return existing_df


    # ========================================================
    # TAHAP 5
    # GEMINI
    # ========================================================

    total_unique = len(
        unique_articles
    )


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
            f"batch {batch_number}/"
            f"{total_batches} "
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

            min(

                0.90,

                0.40
                +
                (
                    0.45
                    *
                    batch_number
                    /
                    total_batches
                )

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

            article.get(
                "title",
                ""
            ),

            article.get(
                "url",
                ""
            )

        )


        ai_raw = ai_by_id.get(

            article_id,

            {

                "ekonomi":
                    False,

                "sektor_kode":
                    "",

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

        if ai_result[
            "ekonomi"
        ]:

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
                        "Berita Online"
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


        # ====================================================
        # BUKAN EKONOMI
        # ====================================================

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
                    normalize_url(
                        article.get(
                            "url",
                            ""
                        )
                    )

            })


    # ========================================================
    # SIMPAN BERITA DITOLAK
    # ========================================================

    save_rejected_data(
        rejected_articles
    )


    # ========================================================
    # DATAFRAME BARU
    # ========================================================

    new_df = pd.DataFrame(
        final_records
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


    # ========================================================
    # JIKA KOSONG
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
    # NORMALISASI KOLOM
    # ========================================================

    if "Link Berita" in combined_df.columns:

        combined_df[
            "Link Berita"
        ] = combined_df[
            "Link Berita"
        ].apply(
            normalize_url
        )


    if "Judul Berita" in combined_df.columns:

        combined_df[
            "Judul Berita"
        ] = combined_df[
            "Judul Berita"
        ].apply(
            clean_text
        )


    # ========================================================
    # HAPUS DUPLIKAT URL
    # ========================================================

    if "Link Berita" in combined_df.columns:

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
    # HAPUS JUDUL SAMA
    # ========================================================

    if "Judul Berita" in combined_df.columns:

        combined_df[
            "_judul_normalized"
        ] = combined_df[
            "Judul Berita"
        ].apply(
            normalize_title_for_duplicate
        )


        combined_df = (
            combined_df
            .drop_duplicates(
                subset=[
                    "_judul_normalized"
                ],
                keep="first"
            )
        )


        combined_df = (
            combined_df
            .drop(
                columns=[
                    "_judul_normalized"
                ],
                errors="ignore"
            )
        )


    # ========================================================
    # HAPUS BARIS DENGAN JUDUL KOSONG
    # ========================================================

    if "Judul Berita" in combined_df.columns:

        combined_df = combined_df[
            combined_df[
                "Judul Berita"
            ]
            .fillna("")
            .astype(str)
            .str.strip()
            .ne("")
        ]


    # ========================================================
    # SORTING TANGGAL
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
        f"{duplicate_count} berita duplikat "
        f"antar-media dihapus."

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

import os
from google import genai

# Tempel API Key kamu di bawah ini (di dalam tanda kutip)
GEMINI_API_KEY = "PASTE_KUNCI_API_MU_DI_SINI"

# Inisialisasi Klien Gemini
client = genai.Client(api_key=GEMINI_API_KEY)
def classify_with_gemini(title, summary):
    prompt = f"""
    Kamu adalah pakar analisis ekonomi BPS.
    Analisis berita berikut:
    Judul: {title}
    Ringkasan: {summary}

    Tugas:
    1. Tentukan Sektor Lapangan Usaha (Pilih 1 dari 17 Sektor BPS).
    2. Tentukan Isu Ekonomi utama.

    Jawab HANYA dalam format JSON:
    {{
        "sektor": "Nama sektor BPS",
        "isu": "Nama isu"
    }}
    """
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text
    except Exception as e:
        return None
# ============================================================
# DASHBOARD STREAMLIT
# ============================================================

import streamlit as st
import pandas as pd
import feedparser
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
from datetime import datetime
import plotly.express as px
import re
import hashlib
import html
import logging
from pathlib import Path

# ============================================================
# KONFIGURASI
# ============================================================

st.set_page_config(
    page_title="Monitoring Berita Ekonomi Lamongan",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded"
)

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "berita_lamongan.csv"
LOG_FILE = BASE_DIR / "app.log"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ============================================================
# CSS / TAMPILAN
# ============================================================

st.markdown("""
<style>

.main {
    background-color: #f7f9fc;
}

.block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
}

.dashboard-title {
    font-size: 32px;
    font-weight: 700;
    color: #1f2937;
    margin-bottom: 0px;
}

.dashboard-subtitle {
    font-size: 15px;
    color: #6b7280;
    margin-bottom: 20px;
}

.kpi-card {
    background: white;
    padding: 20px;
    border-radius: 14px;
    border: 1px solid #e5e7eb;
    box-shadow: 0px 2px 8px rgba(0,0,0,0.04);
}

.kpi-title {
    font-size: 14px;
    color: #6b7280;
}

.kpi-value {
    font-size: 28px;
    font-weight: 700;
    color: #111827;
}

.section-title {
    font-size: 21px;
    font-weight: 650;
    margin-top: 20px;
    margin-bottom: 10px;
}

.news-card {
    background: white;
    padding: 16px;
    border-radius: 12px;
    border: 1px solid #e5e7eb;
    margin-bottom: 10px;
}

.news-title {
    font-size: 17px;
    font-weight: 650;
}

.news-meta {
    font-size: 13px;
    color: #6b7280;
}

.news-summary {
    font-size: 14px;
    color: #374151;
    line-height: 1.5;
}

.sidebar-title {
    font-size: 20px;
    font-weight: 700;
}

</style>
""", unsafe_allow_html=True)


# ============================================================
# 17 SEKTOR LAPANGAN USAHA
# ============================================================

SEKTOR = {
    "A": "Pertanian, Kehutanan, dan Perikanan",
    "B": "Pertambangan dan Penggalian",
    "C": "Industri Pengolahan",
    "D": "Pengadaan Listrik dan Gas",
    "E": "Pengadaan Air, Pengelolaan Sampah, Limbah dan Daur Ulang",
    "F": "Konstruksi",
    "G": "Perdagangan Besar dan Eceran; Reparasi Mobil dan Sepeda Motor",
    "H": "Transportasi dan Pergudangan",
    "I": "Penyediaan Akomodasi dan Makan Minum",
    "J": "Informasi dan Komunikasi",
    "K": "Jasa Keuangan dan Asuransi",
    "L": "Real Estat",
    "M,N": "Jasa Perusahaan",
    "O": "Administrasi Pemerintahan, Pertahanan dan Jaminan Sosial Wajib",
    "P": "Jasa Pendidikan",
    "Q": "Jasa Kesehatan dan Kegiatan Sosial",
    "R,S,T,U": "Jasa Lainnya"
}


# ============================================================
# KEYWORD SEKTOR
# ============================================================

SEKTOR_KEYWORDS = {

"A": [
    "pertanian","petani","sawah","padi","jagung","cabai",
    "cabe","bawang","tebu","perkebunan","perikanan","nelayan",
    "ikan","tambak","udang","rumput laut","peternakan",
    "sapi","kambing","ayam","panen","pupuk","benih",
    "hasil tani","pertanian lamongan"
],

"B": [
    "pertambangan","tambang","galian","pasir","batu",
    "mineral","galian c"
],

"C": [
    "industri","pabrik","manufaktur","produksi","pengolahan",
    "pabrikasi","industri pengolahan","sentra industri"
],

"D": [
    "listrik","pln","gas","energi","pembangkit",
    "kelistrikan"
],

"E": [
    "sampah","limbah","air bersih","daur ulang",
    "pengelolaan sampah","air minum","persampahan"
],

"F": [
    "konstruksi","pembangunan","gedung","jalan","jembatan",
    "infrastruktur","perumahan","renovasi","proyek",
    "pembangunan jalan","pembangunan gedung"
],

"G": [
    "perdagangan","pasar","pedagang","toko","ritel",
    "eceran","grosir","jual beli","harga","komoditas",
    "dealer","otomotif","kendaraan","pasar tradisional",
    "pasar modern","distributor"
],

"H": [
    "transportasi","angkutan","bus","truk","pelabuhan",
    "logistik","ekspedisi","pergudangan","terminal",
    "jasa pengiriman","kendaraan umum"
],

"I": [
    "hotel","penginapan","restoran","rumah makan","warung",
    "kuliner","cafe","kafe","pariwisata","wisata",
    "akomodasi","destinasi wisata"
],

"J": [
    "digital","internet","telekomunikasi","teknologi",
    "aplikasi","startup","online","e-commerce",
    "digitalisasi","marketplace","internet"
],

"K": [
    "bank","perbankan","kredit","pembiayaan","asuransi",
    "keuangan","pajak","investasi","bpr","pinjaman",
    "finansial","perbankan lamongan"
],

"L": [
    "properti","real estat","perumahan","rumah","tanah",
    "apartemen","developer","pengembang properti"
],

"M,N": [
    "jasa perusahaan","konsultan","jasa bisnis",
    "tenaga kerja","outsourcing","konsultan bisnis"
],

"O": [
    "pemerintah","pemkab","pemda","bupati","anggaran",
    "apbd","kebijakan pemerintah","program pemerintah",
    "dinas","pemerintahan","kebijakan ekonomi"
],

"P": [
    "sekolah","pendidikan","kampus","universitas","guru",
    "siswa","mahasiswa","beasiswa","pelatihan"
],

"Q": [
    "kesehatan","rumah sakit","rsud","puskesmas","dokter",
    "pasien","bpjs","obat","kesehatan masyarakat"
],

"R,S,T,U": [
    "jasa lainnya","hiburan","organisasi","sosial",
    "budaya","kesenian","olahraga","salon"
]

}


# ============================================================
# KEYWORD ISU EKONOMI
# ============================================================

ISU_KEYWORDS = {

"Harga dan Inflasi": [
    "harga","inflasi","deflasi","naik","turun",
    "mahal","murah","komoditas","kenaikan harga"
],

"Perdagangan": [
    "perdagangan","pasar","pedagang","jual","beli",
    "ritel","grosir","distributor"
],

"Pertanian": [
    "pertanian","petani","panen","padi","jagung",
    "cabai","tebu","pupuk","hasil pertanian"
],

"Perikanan": [
    "nelayan","ikan","tambak","perikanan","udang",
    "laut","hasil tangkapan"
],

"Industri": [
    "industri","pabrik","produksi","manufaktur",
    "pengolahan"
],

"UMKM": [
    "umkm","usaha mikro","usaha kecil",
    "usaha menengah","pelaku usaha"
],

"Investasi": [
    "investasi","investor","modal","penanaman modal"
],

"Ketenagakerjaan": [
    "tenaga kerja","pekerja","buruh","lowongan",
    "pengangguran","pekerjaan"
],

"Infrastruktur": [
    "jalan","jembatan","infrastruktur",
    "pembangunan","konstruksi"
],

"Keuangan": [
    "bank","kredit","pembiayaan","asuransi",
    "keuangan","pajak"
],

"Pariwisata": [
    "wisata","pariwisata","hotel","restoran","kuliner"
],

"Ekonomi Digital": [
    "digital","online","e-commerce","aplikasi",
    "teknologi","marketplace"
],

"Ekonomi Daerah": [
    "ekonomi lamongan","pertumbuhan ekonomi",
    "pdrb","ekonomi daerah","perekonomian"
]

}


# Gabungkan keyword isu dan sektor agar berita UMKM, investasi, dan isu
# ekonomi lain tidak terbuang sebelum proses klasifikasi.
ECONOMIC_KEYWORDS = sorted({
    keyword
    for keyword_list in list(SEKTOR_KEYWORDS.values()) + list(ISU_KEYWORDS.values())
    for keyword in keyword_list
})


# ============================================================
# MEDIA YANG DIMONITOR
# ============================================================

MEDIA_SEARCH = {

    "KlikJatim.com":
        "Lamongan ekonomi site:klikjatim.com",

    "KOMPAS.com":
        "Lamongan ekonomi site:kompas.com",

    "Radar Lamongan":
        "Lamongan ekonomi site:radarlamongan.jawapos.com",

    "ANTARAJATIM":
        "Lamongan ekonomi site:jatim.antaranews.com",

    "detikJatim":
        "Lamongan ekonomi site:detik.com",

    "BeritaJatim":
        "Lamongan ekonomi site:beritajatim.com",

    "Surya":
        "Lamongan ekonomi site:surya.co.id",

    "Jawa Pos":
        "Lamongan ekonomi site:jawapos.com",

    "Tribun":
        "Lamongan ekonomi site:tribunnews.com",

    "Times Indonesia":
        "Lamongan ekonomi site:timesindonesia.co.id",

    "Kumparan":
        "Lamongan ekonomi site:kumparan.com",

    "Media lainnya":
        "Lamongan ekonomi"
}


# ============================================================
# RSS GOOGLE NEWS
# ============================================================

# Membentuk URL RSS Google News berdasarkan kata kunci pencarian.
def google_news_rss(query):

    encoded = quote(query)

    return (
        "https://news.google.com/rss/search?"
        "q=" + encoded +
        "&hl=id&gl=ID&ceid=ID:id"
    )


# ============================================================
# MEMBERSIHKAN TEKS
# ============================================================

# Membersihkan teks dari tag HTML dan spasi berlebih agar siap dianalisis.
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


# Pencocokan berbasis kata utuh mengurangi salah deteksi substring,
# misalnya kata "ikan" yang muncul di dalam kata lain.
# Mengecek apakah keyword muncul sebagai kata utuh di dalam teks.
def contains_keyword(text, keyword):

    return re.search(
        r"(?<!\w)" + re.escape(keyword.lower()) + r"(?!\w)",
        str(text).lower()
    ) is not None


# ============================================================
# DETEKSI MEDIA
# ============================================================

# Menentukan nama media berdasarkan metadata RSS atau alamat tautan berita.
def detect_media(entry):

    try:

        source = entry.get("source")

        if source:

            title = source.get("title")

            if title:
                return title

    except (AttributeError, TypeError, KeyError):
        logger.debug("Metadata media tidak tersedia", exc_info=True)

    link = entry.get("link","").lower()

    if "klikjatim" in link:
        return "KlikJatim.com"

    if "kompas" in link:
        return "KOMPAS.com"

    if "radarlamongan" in link:
        return "Radar Lamongan"

    if "antaranews" in link:
        return "ANTARAJATIM"

    if "detik" in link:
        return "detikJatim"

    if "beritajatim" in link:
        return "BeritaJatim"

    if "surya" in link:
        return "Surya"

    if "jawapos" in link:
        return "Jawa Pos"

    if "tribunnews" in link:
        return "Tribun"

    if "timesindonesia" in link:
        return "Times Indonesia"

    return "Media lainnya"


# ============================================================
# KLASIFIKASI ISU
# ============================================================

# Mengelompokkan berita ke dalam isu ekonomi berdasarkan skor kata kunci.
def classify_issue(title, summary):

    text = (
        str(title) + " " +
        str(summary)
    ).lower()

    scores = {}

    for issue, keywords in ISU_KEYWORDS.items():

        score = 0

        for keyword in keywords:

            if contains_keyword(text, keyword):
                score += 1

        scores[issue] = score

    best = max(
        scores,
        key=scores.get
    )

    if scores[best] == 0:
        return "Ekonomi Umum"

    return best


# ============================================================
# KLASIFIKASI SEKTOR
# ============================================================

# Mengelompokkan berita ke dalam sektor lapangan usaha berdasarkan kata kunci.
def classify_sector(title, summary):

    text = (
        str(title) + " " +
        str(summary)
    ).lower()

    scores = {}

    for kode, keywords in SEKTOR_KEYWORDS.items():

        score = 0

        for keyword in keywords:

            if contains_keyword(text, keyword):
                score += 1

        scores[kode] = score

    best = max(
        scores,
        key=scores.get
    )

    if scores[best] == 0:

        return "Belum Teridentifikasi"

    return (
        best + " - " +
        SEKTOR[best]
    )


# ============================================================
# CEK APAKAH BERITA EKONOMI LAMONGAN
# ============================================================

# Memastikan berita berkaitan dengan wilayah Lamongan dan topik ekonomi.
def is_relevant(title, summary):

    text = (
        str(title) + " " +
        str(summary)
    ).lower()

    lamongan_words = [

        "lamongan",

        "babat",
        "brondong",
        "paciran",
        "solokuro",
        "pucuk",
        "mantup",
        "sugio",
        "ngimbang",
        "kembangbahu",
        "sambeng",
        "kedungpring",
        "bluluk",
        "sukodadi",
        "tikung",
        "karangbinangun",
        "glagah",
        "deket",
        "turi",
        "maduran",
        "sekaran",
        "laren",
        "karanggeneng",
        "kalitengah",
        "babat",
        "brondong"

    ]

    has_location = any(
        contains_keyword(text, word)
        for word in lamongan_words
    )

    has_economic = any(
        contains_keyword(text, word)
        for word in ECONOMIC_KEYWORDS
    )

    return (
        has_location and
        has_economic
    )


# ============================================================
# TANGGAL
# ============================================================

# Mengambil tanggal publikasi berita dari entri RSS dengan fallback ke tanggal hari ini.
def get_date(entry):

    try:

        if entry.get("published_parsed"):

            dt = datetime(
                *entry.published_parsed[:6]
            )

            return dt.strftime(
                "%Y-%m-%d"
            )

    except (AttributeError, TypeError, ValueError):
        logger.debug("Tanggal berita tidak valid", exc_info=True)

    return datetime.now().strftime(
        "%Y-%m-%d"
    )


# ============================================================
# RINGKASAN
# ============================================================

# Mengambil, membersihkan, dan membatasi panjang ringkasan berita.
def get_summary(entry):

    summary = ""

    if entry.get("summary"):
        summary = entry.get("summary")

    elif entry.get("description"):
        summary = entry.get("description")

    summary = clean_text(summary)

    if len(summary) > 450:
        summary = summary[:447] + "..."

    return summary


# ============================================================
# ID BERITA
# ============================================================

# Membuat ID unik berita dari gabungan judul dan tautan.
def make_id(title, link):

    raw = (
        str(title) +
        str(link)
    )

    return hashlib.md5(
        raw.encode("utf-8")
    ).hexdigest()


# ============================================================
# AMBIL BERITA
# ============================================================

# Mengambil berita dari seluruh media, memfilter, mengklasifikasi, dan menghapus duplikat.
def fetch_news():

    all_news = []
    fetch_errors = []

    progress = st.progress(
        0
    )

    status = st.empty()

    items = list(
        MEDIA_SEARCH.items()
    )

    total = len(items)

    for i, (media_name, query) in enumerate(items):

        status.info(
            "🔎 Mengambil berita dari "
            + media_name + "..."
        )

        try:

            rss_url = google_news_rss(
                query
            )

            response = requests.get(
                rss_url,
                timeout=20,
                headers={
                    "User-Agent":
                    "Mozilla/5.0"
                }
            )
            response.raise_for_status()

            feed = feedparser.parse(
                response.content
            )

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

                summary = get_summary(
                    entry
                )

                if not title or not link:
                    continue

                if not is_relevant(
                    title,
                    summary
                ):
                    continue

                detected_media = detect_media(
                    entry
                )

                # Jika hasil dari query tertentu,
                # gunakan media yang terdeteksi.
                if detected_media == "Media lainnya":

                    detected_media = media_name

                record = {

                    "ID":
                        make_id(
                            title,
                            link
                        ),

                    "Tanggal Berita":
                        get_date(
                            entry
                        ),

                    "Media":
                        detected_media,

                    "Judul Berita":
                        title,

                    "Isu Ekonomi":
                        classify_issue(
                            title,
                            summary
                        ),

                    "Sektor":
                        classify_sector(
                            title,
                            summary
                        ),

                    "Ringkasan Berita":
                        summary,

                    "Link Berita":
                        link

                }

                all_news.append(
                    record
                )

        except Exception:

            logger.exception(
                "Gagal mengambil berita dari %s",
                media_name
            )
            fetch_errors.append(media_name)

        progress.progress(
            (i + 1) / total
        )

    status.success(
        "✅ Pengambilan berita selesai."
    )

    progress.empty()

    if fetch_errors:
        st.warning(
            "Sebagian sumber berita gagal diakses: "
            + ", ".join(fetch_errors)
            + ". Detail tersimpan di app.log."
        )

    if len(all_news) == 0:
        return pd.DataFrame()

    df = pd.DataFrame(
        all_news
    )

    # Hapus duplikat
    df = df.drop_duplicates(
        subset=["ID"]
    )

    df = df.sort_values(
        "Tanggal Berita",
        ascending=False
    )

    return df


# ============================================================
# DATA SAMPLE JIKA RSS TIDAK MENGEMBALIKAN DATA
# ============================================================

# Menyediakan data contoh ketika belum ada data CSV atau RSS tidak menghasilkan berita.
def create_sample_data():

    sample = [

        {
            "ID":"1",
            "Tanggal Berita":"2026-08-04",
            "Media":"ANTARAJATIM",
            "Judul Berita":
                "Aktivitas Ekonomi Kabupaten Lamongan Terus Tumbuh",
            "Isu Ekonomi":
                "Ekonomi Daerah",
            "Sektor":
                "A - Pertanian, Kehutanan, dan Perikanan",
            "Ringkasan Berita":
                "Aktivitas ekonomi masyarakat Lamongan terus berkembang dengan dukungan sektor pertanian, perdagangan dan industri.",
            "Link Berita":
                "https://jatim.antaranews.com/"
        },

        {
            "ID":"2",
            "Tanggal Berita":"2026-08-03",
            "Media":"KlikJatim.com",
            "Judul Berita":
                "Harga Komoditas Pertanian di Lamongan Mengalami Perubahan",
            "Isu Ekonomi":
                "Harga dan Inflasi",
            "Sektor":
                "A - Pertanian, Kehutanan, dan Perikanan",
            "Ringkasan Berita":
                "Perubahan harga sejumlah komoditas pertanian menjadi perhatian masyarakat dan pelaku usaha di Kabupaten Lamongan.",
            "Link Berita":
                "https://klikjatim.com/"
        },

        {
            "ID":"3",
            "Tanggal Berita":"2026-08-02",
            "Media":"detikJatim",
            "Judul Berita":
                "Perdagangan dan UMKM Lamongan Terus Berkembang",
            "Isu Ekonomi":
                "UMKM",
            "Sektor":
                "G - Perdagangan Besar dan Eceran; Reparasi Mobil dan Sepeda Motor",
            "Ringkasan Berita":
                "Pelaku UMKM dan perdagangan menjadi salah satu penggerak aktivitas ekonomi masyarakat Kabupaten Lamongan.",
            "Link Berita":
                "https://www.detik.com/jatim/"
        },

        {
            "ID":"4",
            "Tanggal Berita":"2026-08-01",
            "Media":"KOMPAS.com",
            "Judul Berita":
                "Pembangunan Infrastruktur Dorong Aktivitas Ekonomi Lamongan",
            "Isu Ekonomi":
                "Infrastruktur",
            "Sektor":
                "F - Konstruksi",
            "Ringkasan Berita":
                "Pembangunan infrastruktur menjadi salah satu faktor pendukung aktivitas ekonomi di Kabupaten Lamongan.",
            "Link Berita":
                "https://www.kompas.com/"
        },

        {
            "ID":"5",
            "Tanggal Berita":"2026-07-31",
            "Media":"Radar Lamongan",
            "Judul Berita":
                "Potensi Industri Pengolahan Lamongan Terus Dikembangkan",
            "Isu Ekonomi":
                "Industri",
            "Sektor":
                "C - Industri Pengolahan",
            "Ringkasan Berita":
                "Potensi industri pengolahan di Kabupaten Lamongan terus dikembangkan untuk meningkatkan nilai tambah ekonomi daerah.",
            "Link Berita":
                "https://radarlamongan.jawapos.com/"
        },

        {
            "ID":"6",
            "Tanggal Berita":"2026-07-30",
            "Media":"BeritaJatim",
            "Judul Berita":
                "Investasi Menjadi Perhatian dalam Pengembangan Ekonomi Lamongan",
            "Isu Ekonomi":
                "Investasi",
            "Sektor":
                "K - Jasa Keuangan dan Asuransi",
            "Ringkasan Berita":
                "Peningkatan investasi menjadi salah satu upaya untuk mendorong pertumbuhan ekonomi Kabupaten Lamongan.",
            "Link Berita":
                "https://beritajatim.com/"
        },

        {
            "ID":"7",
            "Tanggal Berita":"2026-07-29",
            "Media":"Surya",
            "Judul Berita":
                "Sektor Pariwisata Lamongan Terus Dikembangkan",
            "Isu Ekonomi":
                "Pariwisata",
            "Sektor":
                "I - Penyediaan Akomodasi dan Makan Minum",
            "Ringkasan Berita":
                "Pengembangan destinasi wisata di Lamongan diharapkan dapat meningkatkan aktivitas ekonomi masyarakat.",
            "Link Berita":
                "https://surya.co.id/"
        }

    ]

    return pd.DataFrame(
        sample
    )


# ============================================================
# LOAD DATA
# ============================================================

if "data" not in st.session_state:

    if DATA_FILE.exists():

        try:

            st.session_state.data = pd.read_csv(
                DATA_FILE
            )

        except Exception:

            logger.exception("Gagal membaca %s", DATA_FILE)
            st.warning(
                "File data tidak dapat dibaca. Data contoh digunakan; "
                "detail tersimpan di app.log."
            )

            st.session_state.data = create_sample_data()

    else:

        st.session_state.data = create_sample_data()


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.markdown(
        '<div class="sidebar-title">📰 Monitoring Berita</div>',
        unsafe_allow_html=True
    )

    st.caption(
        "Ekonomi Kabupaten Lamongan"
    )

    st.divider()

    st.markdown(
        "### ⚙️ Pengaturan"
    )

    if st.button(
        "🔄 Ambil Berita Terbaru",
        use_container_width=True
    ):

        new_data = fetch_news()

        if not new_data.empty:

            old_data = st.session_state.data

            final = pd.concat(
                [
                    old_data,
                    new_data
                ],
                ignore_index=True
            )

            final = final.drop_duplicates(
                subset=["ID"]
            )

            final = final.sort_values(
                "Tanggal Berita",
                ascending=False
            )

            st.session_state.data = final

            try:
                final.to_csv(
                    DATA_FILE,
                    index=False,
                    encoding="utf-8-sig"
                )
                st.success(
                    "Data berita berhasil diperbarui."
                )
            except OSError:
                logger.exception("Gagal menyimpan %s", DATA_FILE)
                st.error(
                    "Data berhasil diambil, tetapi tidak dapat disimpan "
                    "ke file CSV. Detail tersimpan di app.log."
                )

        else:

            st.warning(
                "Tidak ada data baru dari sumber berita."
            )

        st.rerun()

    if st.button(
        "🗑️ Reset Data",
        use_container_width=True
    ):

        st.session_state.data = create_sample_data()

        if DATA_FILE.exists():
            try:
                DATA_FILE.unlink()
            except OSError:
                logger.exception("Gagal menghapus %s", DATA_FILE)
                st.error(
                    "File data tidak dapat dihapus. Tutup aplikasi lain "
                    "yang sedang membuka file tersebut lalu coba lagi."
                )

        st.rerun()

    st.divider()

    st.markdown(
        "### 🔎 Filter"
    )


# ============================================================
# DATAFRAME
# ============================================================

df = st.session_state.data.copy()

if df.empty:

    df = create_sample_data()


df["Tanggal Berita"] = pd.to_datetime(
    df["Tanggal Berita"],
    errors="coerce"
)


# ============================================================
# SIDEBAR FILTER
# ============================================================

with st.sidebar:

    min_date = df[
        "Tanggal Berita"
    ].min().date()

    max_date = df[
        "Tanggal Berita"
    ].max().date()

    date_range = st.date_input(
        "📅 Periode Berita",
        value=(
            min_date,
            max_date
        )
    )

    media_options = sorted(
        df["Media"].dropna().unique()
    )

    selected_media = st.multiselect(
        "🌐 Media",
        media_options
    )

    sector_options = sorted(
        df["Sektor"].dropna().unique()
    )

    selected_sector = st.multiselect(
        "🏭 Sektor Lapangan Usaha",
        sector_options
    )

    issue_options = sorted(
        df["Isu Ekonomi"].dropna().unique()
    )

    selected_issue = st.multiselect(
        "📊 Isu Ekonomi",
        issue_options
    )

    keyword = st.text_input(
        "🔎 Cari berita",
        placeholder="Judul, isu, kata kunci..."
    )


# ============================================================
# FILTER DATA
# ============================================================

filtered = df.copy()

if len(date_range) == 2:

    filtered = filtered[
        (
            filtered["Tanggal Berita"].dt.date
            >= date_range[0]
        )
        &
        (
            filtered["Tanggal Berita"].dt.date
            <= date_range[1]
        )
    ]


if selected_media:

    filtered = filtered[
        filtered["Media"].isin(
            selected_media
        )
    ]


if selected_sector:

    filtered = filtered[
        filtered["Sektor"].isin(
            selected_sector
        )
    ]


if selected_issue:

    filtered = filtered[
        filtered["Isu Ekonomi"].isin(
            selected_issue
        )
    ]


if keyword:

    search_text = keyword.lower()

    filtered = filtered[
        filtered[
            [
                "Judul Berita",
                "Isu Ekonomi",
                "Sektor",
                "Ringkasan Berita"
            ]
        ]
        .fillna("")
        .astype(str)
        .apply(
            lambda row:
            row.str.lower()
            .str.contains(
                search_text,
                regex=False
            )
            .any(),
            axis=1
        )
    ]


# ============================================================
# HEADER
# ============================================================

st.markdown(
    '<div class="dashboard-title">📰 MONITORING BERITA EKONOMI LAMONGAN</div>',
    unsafe_allow_html=True
)

st.markdown(
    '<div class="dashboard-subtitle">'
    'Dashboard monitoring pemberitaan ekonomi Kabupaten Lamongan '
    'berdasarkan isu ekonomi dan 17 lapangan usaha.'
    '</div>',
    unsafe_allow_html=True
)


# ============================================================
# UPDATE INFO
# ============================================================

st.info(
    "💡 Gunakan tombol **Ambil Berita Terbaru** pada sidebar "
    "untuk mengambil berita terbaru dari berbagai media."
)


# ============================================================
# KPI
# ============================================================

total_news = len(filtered)

today = datetime.now().date()

today_news = len(
    filtered[
        filtered["Tanggal Berita"].dt.date == today
    ]
)

media_count = filtered[
    "Media"
].nunique()

sector_count = filtered[
    "Sektor"
].nunique()


c1, c2, c3, c4 = st.columns(4)


with c1:

    st.metric(
        "📰 Total Berita",
        f"{total_news:,}"
    )


with c2:

    st.metric(
        "📅 Berita Hari Ini",
        f"{today_news:,}"
    )


with c3:

    st.metric(
        "🌐 Media",
        f"{media_count:,}"
    )


with c4:

    st.metric(
        "🏭 Sektor Terpantau",
        f"{sector_count:,}"
    )


st.divider()


# ============================================================
# GRAFIK
# ============================================================

if not filtered.empty:

    st.markdown(
        '<div class="section-title">📊 Ringkasan Monitoring</div>',
        unsafe_allow_html=True
    )

    col1, col2 = st.columns(2)


    # ========================================================
    # SEKTOR
    # ========================================================

    with col1:

        sector_df = (
            filtered[
                "Sektor"
            ]
            .value_counts()
            .reset_index()
        )

        sector_df.columns = [
            "Sektor",
            "Jumlah"
        ]

        fig_sector = px.bar(
            sector_df,
            x="Jumlah",
            y="Sektor",
            orientation="h",
            text="Jumlah",
            title="Berita Berdasarkan 17 Lapangan Usaha"
        )
        

        fig_sector.update_traces(
            textposition="outside"
        )

        fig_sector.update_layout(
            height=600,
            margin=dict(
                l=10,
                r=10,
                t=60,
                b=10
            ),
            yaxis={
                "categoryorder":
                "total ascending"
            }
        )

        st.plotly_chart(
            fig_sector,
            use_container_width=True
        )


    # ========================================================
    # MEDIA
    # ========================================================

    with col2:

        media_df = (
            filtered[
                "Media"
            ]
            .value_counts()
            .reset_index()
        )

        media_df.columns = [
            "Media",
            "Jumlah"
        ]

        fig_media = px.pie(
            media_df,
            names="Media",
            values="Jumlah",
            hole=0.45,
            title="Distribusi Berita Berdasarkan Media"
        )

        fig_media.update_layout(
            height=600
        )

        st.plotly_chart(
            fig_media,
            use_container_width=True
        )


    # ========================================================
    # TREND
    # ========================================================

    st.markdown(
        '<div class="section-title">📈 Tren Pemberitaan</div>',
        unsafe_allow_html=True
    )

    trend_df = (
        filtered
        .groupby(
            "Tanggal Berita"
        )
        .size()
        .reset_index(
            name="Jumlah Berita"
        )
    )

    fig_trend = px.line(
        trend_df,
        x="Tanggal Berita",
        y="Jumlah Berita",
        markers=True,
        title="Tren Jumlah Berita Ekonomi Lamongan"
    )

    fig_trend.update_layout(
        height=400
    )

    st.plotly_chart(
        fig_trend,
        use_container_width=True
    )


    # ========================================================
    # ISU EKONOMI
    # ========================================================

    col3, col4 = st.columns(2)


    with col3:

        issue_df = (
            filtered[
                "Isu Ekonomi"
            ]
            .value_counts()
            .reset_index()
        )

        issue_df.columns = [
            "Isu",
            "Jumlah"
        ]

        fig_issue = px.bar(
            issue_df,
            x="Isu",
            y="Jumlah",
            text="Jumlah",
            title="Distribusi Isu Ekonomi"
        )

        fig_issue.update_layout(
            height=450,
            xaxis_tickangle=-40
        )

        st.plotly_chart(
            fig_issue,
            use_container_width=True
        )


    with col4:

        # Top sektor
        top_sector = (
            filtered[
                "Sektor"
            ]
            .value_counts()
            .head(5)
            .reset_index()
        )

        top_sector.columns = [
            "Sektor",
            "Jumlah"
        ]

        fig_top = px.bar(
            top_sector,
            x="Jumlah",
            y="Sektor",
            orientation="h",
            text="Jumlah",
            title="5 Sektor Paling Banyak Diberitakan"
        )

        fig_top.update_layout(
            height=450,
            yaxis={
                "categoryorder":
                "total ascending"
            }
        )

        st.plotly_chart(
            fig_top,
            use_container_width=True
        )


# ============================================================
# TABEL BERITA
# ============================================================

st.divider()

st.markdown(
    '<div class="section-title">📋 Monitoring Berita</div>',
    unsafe_allow_html=True
)

st.caption(
    f"Menampilkan {len(filtered)} berita sesuai filter."
)


if not filtered.empty:

    table_df = filtered.copy()

    table_df[
        "Tanggal Berita"
    ] = table_df[
        "Tanggal Berita"
    ].dt.strftime(
        "%d-%m-%Y"
    )

    # Jangan tampilkan ID dan sanitasi isi RSS sebelum dirender sebagai HTML.
    table_df = table_df[
        [
            "Tanggal Berita",
            "Media",
            "Judul Berita",
            "Isu Ekonomi",
            "Sektor",
            "Ringkasan Berita",
            "Link Berita"
        ]
    ]

    for column in table_df.columns:
        table_df[column] = table_df[column].map(
            lambda value: html.escape(str(value))
        )

    table_df["Link Berita"] = table_df["Link Berita"].apply(
        lambda x: f'<a href="{x}" target="_blank" rel="noopener">🔗 Baca</a>'
    )

    st.markdown(
        table_df.to_html(
            escape=False,
            index=False
        ),
        unsafe_allow_html=True
    )

else:

    st.warning(
        "Tidak ada berita yang sesuai dengan filter."
    )


# ============================================================
# DOWNLOAD DATA
# ============================================================

st.divider()

st.markdown(
    '<div class="section-title">📥 Ekspor Data</div>',
    unsafe_allow_html=True
)


if not filtered.empty:

    export_df = filtered.copy()

    export_df[
        "Tanggal Berita"
    ] = export_df[
        "Tanggal Berita"
    ].dt.strftime(
        "%Y-%m-%d"
    )

    export_df = export_df[
        [
            "Tanggal Berita",
            "Media",
            "Judul Berita",
            "Isu Ekonomi",
            "Sektor",
            "Ringkasan Berita",
            "Link Berita"
        ]
    ]

    csv = export_df.to_csv(
        index=False,
        encoding="utf-8-sig"
    )

    st.download_button(
        "⬇️ Download Data CSV",
        data=csv,
        file_name=
        "monitoring_berita_ekonomi_lamongan.csv",
        mime="text/csv",
        use_container_width=True
    )


# ============================================================
# DAFTAR 17 SEKTOR
# ============================================================

st.divider()

with st.expander(
    "📚 Lihat 17 Lapangan Usaha"
):

    sector_display = pd.DataFrame(
        {
            "Kode": list(SEKTOR.keys()),
            "Lapangan Usaha": list(SEKTOR.values())
        }
    )

    st.dataframe(
        sector_display,
        use_container_width=True,
        hide_index=True
    )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Dashboard Monitoring Berita Ekonomi Kabupaten Lamongan | "
    "Prototype Miniproject Magang BPS Kabupaten Lamongan"
)

st.caption(
    "Klasifikasi sektor menggunakan pendekatan berbasis kata kunci "
    "dan perlu validasi sebelum digunakan sebagai data resmi."
)


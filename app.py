import os
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
import feedparser
import requests
from bs4 import BeautifulSoup
import plotly.express as px
from google import genai
from concurrent.futures import ThreadPoolExecutor, as_completed


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
# MASTER SEKTOR BPS
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

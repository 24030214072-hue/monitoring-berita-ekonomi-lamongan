import os
import re
import json
import hashlib
import html
import logging
from pathlib import Path
from datetime import datetime
from urllib.parse import quote
import io

import streamlit as st
import pandas as pd
import feedparser
import requests
from bs4 import BeautifulSoup
import plotly.express as px
from google import genai

# ============================================================
# KONFIGURASI HALAMAN & STYLING CSS
# ============================================================

st.set_page_config(
    page_title="Monitoring Berita Ekonomi Lamongan",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<meta name="google-site-verification" content="xrwK_BByxvJAfptvhoOoeWNHSvdb4vcGkTLxIz8k3ls" />
<style>
    main { background-color: #f8fafc; }
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    
    /* Header Styling */
    .dashboard-header {
        background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
        padding: 24px;
        border-radius: 16px;
        color: white;
        margin-bottom: 25px;
        box-shadow: 0 4px 12px rgba(30, 58, 138, 0.15);
    }
    .dashboard-title { font-size: 28px; font-weight: 800; margin: 0; color: #ffffff; }
    .dashboard-subtitle { font-size: 14px; color: #e0f2fe; margin-top: 6px; }

    /* Card Container */
    .css-card {
        background: white;
        padding: 18px;
        border-radius: 12px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02);
        margin-bottom: 15px;
    }
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
# INISIALISASI GEMINI AI
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "berita_lamongan.csv"
LOG_FILE = BASE_DIR / "app.log"

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))

client = None
if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        logger.error(f"Gagal inisialisasi Gemini Client: {e}")

# ============================================================
# MASTER SEKTOR BPS & MEDIA
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

MEDIA_SEARCH = {
    "KlikJatim.com": "Lamongan ekonomi site:klikjatim.com",
    "KOMPAS.com": "Lamongan ekonomi site:kompas.com",
    "Radar Lamongan": "Lamongan ekonomi site:radarlamongan.jawapos.com",
    "ANTARAJATIM": "Lamongan ekonomi site:jatim.antaranews.com",
    "detikJatim": "Lamongan ekonomi site:detik.com",
    "BeritaJatim": "Lamongan ekonomi site:beritajatim.com",
    "Surya": "Lamongan ekonomi site:surya.co.id",
    "Jawa Pos": "Lamongan ekonomi site:jawapos.com",
    "Tribun": "Lamongan ekonomi site:tribunnews.com",
    "Times Indonesia": "Lamongan ekonomi site:timesindonesia.co.id",
    "Kumparan": "Lamongan ekonomi site:kumparan.com",
    "Berita Umum": "Lamongan ekonomi"
}

# ============================================================
# ANALISIS CERDAS GEMINI AI
# ============================================================

def clean_text(text):
    if not text: return ""
    text = BeautifulSoup(str(text), "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()

def analyze_news_with_ai(title, raw_summary):
    if not client:
        return {
            "sektor": "A - Pertanian, Kehutanan, dan Perikanan",
            "isu": "Ekonomi Umum",
            "ringkasan": raw_summary if raw_summary else title,
            "relevan": True
        }

    prompt = f"""
    Kamu adalah pakar analis ekonomi BPS Kabupaten Lamongan.
    Analisis berita berikut:
    Judul Berita: {title}
    Deskripsi: {raw_summary}

    Tugas:
    1. Apakah berita ini berhubungan dengan topik EKONOMI / PEMBANGUNAN / KESEJAHTERAAN / BISNIS / PERTANIAN / USAHA di Kabupaten Lamongan? (Jawab true/false).
    2. Tentukan Sektor Lapangan Usaha BPS yang paling cocok. Pilihan WAJIB salah satu dari ini:
       - A - Pertanian, Kehutanan, dan Perikanan
       - B - Pertambangan dan Penggalian
       - C - Industri Pengolahan
       - D - Pengadaan Listrik dan Gas
       - E - Pengadaan Air, Pengelolaan Sampah, Limbah dan Daur Ulang
       - F - Konstruksi
       - G - Perdagangan Besar dan Eceran; Reparasi Mobil dan Sepeda Motor
       - H - Transportasi dan Pergudangan
       - I - Penyediaan Akomodasi dan Makan Minum
       - J - Informasi dan Komunikasi
       - K - Jasa Keuangan dan Asuransi
       - L - Real Estat
       - M,N - Jasa Perusahaan
       - O - Administrasi Pemerintahan, Pertahanan dan Jaminan Sosial Wajib
       - P - Jasa Pendidikan
       - Q - Jasa Kesehatan dan Kegiatan Sosial
       - R,S,T,U - Jasa Lainnya
    3. Tentukan Isu Ekonomi Utama (Misal: UMKM, Harga dan Inflasi, Pertanian, Perdagangan, Investasi, Ketenagakerjaan, Pariwisata, Infrastruktur, Ekonomi Daerah, dll).
    4. Buat RINGKASAN CERDAS 2-3 kalimat yang informatif.

    Balas HANYA JSON valid tanpa teks tambahan:
    {{
        "relevan": true,
        "sektor": "KODE - Nama Sektor",
        "isu": "Nama Isu",
        "ringkasan": "Isi ringkasan..."
    }}
    """
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        text_resp = response.text.strip()
        if "```json" in text_resp:
            text_resp = text_resp.split("```json")[1].split("```")[0].strip()
        elif "```" in text_resp:
            text_resp = text_resp.split("```")[1].split("```")[0].strip()
        
        data = json.loads(text_resp)
        return {
            "relevan": data.get("relevan", True),
            "sektor": data.get("sektor", "A - Pertanian, Kehutanan, dan Perikanan"),
            "isu": data.get("isu", "Ekonomi Umum"),
            "ringkasan": data.get("ringkasan", raw_summary)
        }
    except Exception as e:
        logger.error(f"Gemini API Error: {e}")
        return {
            "relevan": True,
            "sektor": "A - Pertanian, Kehutanan, dan Perikanan",
            "isu": "Ekonomi Umum",
            "ringkasan": raw_summary if raw_summary else title
        }

def make_id(title, link):
    return hashlib.md5((str(title) + str(link)).encode("utf-8")).hexdigest()

# ============================================================
# FETCHING NEWS
# ============================================================

def fetch_news():
    all_news = []
    progress = st.progress(0)
    status = st.empty()
    items = list(MEDIA_SEARCH.items())
    total = len(items)

    for i, (media_name, query) in enumerate(items):
        status.info(f"🔎 Mengambil & menganalisis berita dari {media_name}...")
        try:
            rss_url = f"https://news.google.com/rss/search?q={quote(query)}&hl=id&gl=ID&ceid=ID:id"
            response = requests.get(rss_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            feed = feedparser.parse(response.content)

            for entry in feed.entries:
                title = clean_text(entry.get("title", ""))
                link = entry.get("link", "")
                raw_summary = clean_text(entry.get("summary", ""))

                if not title or not link:
                    continue

                ai_res = analyze_news_with_ai(title, raw_summary)
                
                if not ai_res["relevan"]:
                    continue

                pub_date = datetime.now().strftime("%Y-%m-%d")
                if entry.get("published_parsed"):
                    pub_date = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d")

                record = {
                    "ID": make_id(title, link),
                    "Tanggal Berita": pub_date,
                    "Media": media_name,
                    "Judul Berita": title,
                    "Isu Ekonomi": ai_res["isu"],
                    "Sektor": ai_res["sektor"],
                    "Ringkasan Berita": ai_res["ringkasan"],
                    "Link Berita": link
                }
                all_news.append(record)
        except Exception as e:
            logger.error(f"Error media {media_name}: {e}")

        progress.progress((i + 1) / total)

    status.success("✅ Selesai mengambil berita terbaru!")
    progress.empty()

    if not all_news:
        return pd.DataFrame()

    df = pd.DataFrame(all_news).drop_duplicates(subset=["ID"]).sort_values("Tanggal Berita", ascending=False)
    return df

def create_sample_data():
    return pd.DataFrame([
        {"ID":"1","Tanggal Berita":"2026-08-17","Media":"ANTARAJATIM","Judul Berita":"Pertumbuhan Ekonomi Pesisir Lamongan Meningkat","Isu Ekonomi":"Ekonomi Daerah","Sektor":"A - Pertanian, Kehutanan, dan Perikanan","Ringkasan Berita":"Produktivitas sektor perikanan tangkap dan budidaya di Lamongan mencatatkan tren positif mendorong pendapatan nelayan lokal.","Link Berita":"https://jatim.antaranews.com/"},
        {"ID":"2","Tanggal Berita":"2026-08-16","Media":"Radar Lamongan","Judul Berita":"Pasar Tradisional Lamongan Siap Digitalisasi UMKM","Isu Ekonomi":"UMKM","Sektor":"G - Perdagangan Besar dan Eceran; Reparasi Mobil dan Sepeda Motor","Ringkasan Berita":"Pemerintah daerah memfasilitasi pembayaran QRIS dan pelatihan pemasaran digital bagi para pedagang UMKM di pasar daerah.","Link Berita":"https://radarlamongan.jawapos.com/"}
    ])

# ============================================================
# LOAD & CLEAN DATA
# ============================================================

if "data" not in st.session_state:
    if DATA_FILE.exists():
        try:
            df_loaded = pd.read_csv(DATA_FILE)
            df_loaded["Sektor"] = df_loaded["Sektor"].replace(["Belum Teridentifikasi", None, ""], "A - Pertanian, Kehutanan, dan Perikanan")
            df_loaded["Isu Ekonomi"] = df_loaded["Isu Ekonomi"].replace(["Belum Teridentifikasi", None, ""], "Ekonomi Umum")
            st.session_state.data = df_loaded
        except Exception:
            st.session_state.data = create_sample_data()
    else:
        st.session_state.data = create_sample_data()

# ============================================================
# SIDEBAR CONTROL
# ============================================================

with st.sidebar:
    st.title("📰 Dashboard Control")
    
    if client:
        st.success("🟢 Gemini AI: Active")
    else:
        st.error("🔴 Gemini AI: Offline (Cek Secrets)")

    st.divider()
    st.subheader("⚙️ Aksi")
    if st.button("🔄 Ambil Berita Terbaru", use_container_width=True):
        new_data = fetch_news()
        if not new_data.empty:
            final = pd.concat([st.session_state.data, new_data], ignore_index=True)
            final = final.drop_duplicates(subset=["ID"]).sort_values("Tanggal Berita", ascending=False)
            st.session_state.data = final
            final.to_csv(DATA_FILE, index=False, encoding="utf-8-sig")
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
    min_date = df["Tanggal Berita"].min().date() if not df.empty else datetime.now().date()
    max_date = df["Tanggal Berita"].max().date() if not df.empty else datetime.now().date()

    date_range = st.date_input("📅 Periode Berita", value=(min_date, max_date))
    selected_media = st.multiselect("🌐 Media", sorted(df["Media"].dropna().unique()))
    selected_sector = st.multiselect("🏭 Sektor Lapangan Usaha", sorted(df["Sektor"].dropna().unique()))
    selected_issue = st.multiselect("📊 Isu Ekonomi", sorted(df["Isu Ekonomi"].dropna().unique()))
    keyword = st.text_input("🔎 Cari kata kunci", placeholder="Ketik kata kunci...")

# FILTERING LOGIC
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
# TAMPILAN DASHBOARD UTAMA
# ============================================================

st.markdown("""
<div class="dashboard-header">
    <div class="dashboard-title">📰 MONITORING BERITA EKONOMI LAMONGAN</div>
    <div class="dashboard-subtitle">Sistem pemantauan media otomatis berbasis AI untuk 17 Sektor Lapangan Usaha BPS Kabupaten Lamongan</div>
</div>
""", unsafe_allow_html=True)

# KPI METRICS CARD
k1, k2, k3, k4 = st.columns(4)
k1.metric("📰 Total Berita", f"{len(filtered):,} artikel")
k2.metric("📅 Berita Hari Ini", f"{len(filtered[filtered['Tanggal Berita'].dt.date == datetime.now().date()]):,} artikel")
k3.metric("🌐 Sumber Media", f"{filtered['Media'].nunique():,} media")
k4.metric("🏭 Sektor Terpantau", f"{filtered['Sektor'].nunique():,} sektor")

st.markdown("<br>", unsafe_allow_html=True)

# GRAFIK ANALISIS
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

# TABEL MONITORING DATA
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

# ============================================================
# EKSPOR LAPORAN
# ============================================================

st.markdown('<div class="section-header">📥 Ekspor Laporan Excel / CSV</div>', unsafe_allow_html=True)

if not filtered.empty:
    exp_df = filtered.copy()
    exp_df["Tanggal Berita"] = exp_df["Tanggal Berita"].dt.strftime("%Y-%m-%d")
    exp_df = exp_df[["Tanggal Berita", "Media", "Judul Berita", "Isu Ekonomi", "Sektor", "Ringkasan Berita", "Link Berita"]]
    
    c_down1, c_down2 = st.columns(2)
    
    csv_data = exp_df.to_csv(index=False, encoding="utf-8-sig")
    c_down1.download_button(
        label="📄 Download Laporan Format CSV (Bisa Rapi di Excel)",
        data=csv_data,
        file_name=f"Laporan_Berita_Ekonomi_Lamongan_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True
    )
    
    try:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            exp_df.to_excel(writer, index=False, sheet_name='Monitoring Berita')
        buffer.seek(0)
        
        c_down2.download_button(
            label="📊 Download Laporan Format Excel (.xlsx)",
            data=buffer,
            file_name=f"Laporan_Berita_Ekonomi_Lamongan_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    except Exception:
        c_down2.info("💡 Untuk aktifkan tombol .xlsx, pastikan 'openpyxl' ada di requirements.txt")

st.divider()
st.caption("Dashboard Monitoring Berita Ekonomi Kabupaten Lamongan | BPS Kabupaten Lamongan")

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
import plotly.express as px
from google import genai

# ============================================================
# KONFIGURASI HALAMAN & LOGO BPS
# ============================================================

BPS_LOGO_URL = "https://www.bps.go.id/images/bps_logo.png"

st.set_page_config(
    page_title="Monitoring Berita Ekonomi Lamongan - BPS",
    page_icon=BPS_LOGO_URL,
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<meta name="google-site-verification" content="xrwK_BByxvJAfptvhoOoeWNHSvdb4vcGkTLxIz8k3ls" />
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
        padding: 24px;
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
        height: auto;
        background: white;
        padding: 8px;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    }
    .dashboard-title { font-size: 26px; font-weight: 800; margin: 0; color: #ffffff; }
    .dashboard-subtitle { font-size: 14px; color: #e0f2fe; margin-top: 4px; }

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

AI_CLASSIFICATION_PROMPT = """
Anda adalah analis berita ekonomi Badan Pusat Statistik (BPS) Kabupaten Lamongan.

TUGAS UTAMA: Tentukan apakah berita ini BENAR-BENAR BERITA EKONOMI KABUPATEN LAMONGAN atau BUKAN.

KRITERIA KETAT (ekonomi = true):
- Membahas aktivitas usaha, UMKM, pasar, perdagangan, pertanian, perikanan, produksi, harga barang, inflasi, industri, investasi, tenaga kerja, infrastruktur ekonomi, atau pendapatan daerah di Kabupaten Lamongan.

KRITERIA TOLAK (ekonomi = false):
- Berita Olahraga / Sepak Bola (Persela, Liga 2) -> WAJIB FALSE.
- Berita Kriminalitas Murni / Hukum / Kasus Polisi -> WAJIB FALSE.
- Berita Politik / Seremonial tanpa dampak ekonomi -> WAJIB FALSE.

ATURAN STRICT RINGKASAN:
1. DILARANG KERAS TULISAN SAMA DENGAN JUDUL BERITA!
2. Buat ulasan 1-2 kalimat (maksimal 25 kata) mengenai isi/dampak berita ini.
3. Mulailah ringkasan dengan penjelas seperti: "Laporan ini mengulas...", "Pemerintah daerah mendorong...", "Membahas tentang perkembangan...", dll.

Jika ekonomi = true, pilih TEPAT SATU sektor BPS berikut:
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

Jawab HANYA JSON valid:
{{
    "ekonomi": true,
    "sektor": "KODE - Nama Sektor",
    "isu_ekonomi": "Isu Utama Singkat",
    "ringkasan": "Ulasan deskriptif ringkas berita yang kata-katanya BERBEDA DENGAN JUDUL."
}}

Jika tidak relevan (ekonomi = false):
{{
    "ekonomi": false,
    "sektor": "Tidak Relevan",
    "isu_ekonomi": "Tidak Relevan",
    "ringkasan": ""
}}

DATA BERITA:
Judul Berita: {title}
Ringkasan Awal: {content}
Media: {source}
URL: {url}
"""

def clean_text(text):
    if not text: return ""
    text = BeautifulSoup(str(text), "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()

def normalize_text(text):
    if not text: return ""
    text = str(text).lower()
    text = re.sub(r"http\S+|www\S+", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def match_fallback_sector(text):
    text_lower = text.lower()
    if any(w in text_lower for w in ["tani", "padi", "panen", "nelayan", "ikan", "sawah", "pupuk", "ternak", "hutan"]):
        return "A - Pertanian, Kehutanan, dan Perikanan"
    elif any(w in text_lower for w in ["pabrik", "produksi", "olahan", "industri", "manufaktur"]):
        return "C - Industri Pengolahan"
    elif any(w in text_lower for w in ["pasar", "toko", "pedagang", "jual", "beli", "umkm", "eceran", "harga", "sembako"]):
        return "G - Perdagangan Besar dan Eceran; Reparasi Mobil dan Sepeda Motor"
    elif any(w in text_lower for w in ["jalan", "jembatan", "pembangunan", "gedung", "proyek", "konstruksi"]):
        return "F - Konstruksi"
    elif any(w in text_lower for w in ["bank", "kredit", "pinjaman", "pajak", "retribusi", "keuangan", "asuransi"]):
        return "K - Jasa Keuangan dan Asuransi"
    elif any(w in text_lower for w in ["wisata", "hotel", "kuliner", "resto", "warung", "makan"]):
        return "I - Penyediaan Akomodasi dan Makan Minum"
    elif any(w in text_lower for w in ["digital", "internet", "aplikasi", "komunikasi", "medsos"]):
        return "J - Informasi dan Komunikasi"
    elif any(w in text_lower for w in ["jalan raya", "pelabuhan", "angkutan", "bus", "kereta"]):
        return "H - Transportasi dan Pergudangan"
    return "O - Administrasi Pemerintahan, Pertahanan dan Jaminan Sosial Wajib"

def make_id(title, link):
    return hashlib.md5((str(title) + str(link)).encode("utf-8")).hexdigest()

def analyze_with_gemini(article):
    title_text = article.get("title", "")
    content_text = article.get("content", "")

    if not client:
        summary_text = f"Pemberitaan ini mengulas tentang {title_text.lower()} serta dampaknya terhadap perkembangan perekonomian di Kabupaten Lamongan."
        return {
            "ekonomi": True, 
            "sektor": match_fallback_sector(title_text + " " + content_text), 
            "isu_ekonomi": "Ekonomi Daerah", 
            "ringkasan": summary_text
        }

    prompt = AI_CLASSIFICATION_PROMPT.format(
        title=title_text,
        content=content_text if len(content_text) > 20 else title_text,
        source=article.get("source", ""),
        url=article.get("url", "")
    )

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

        res = json.loads(text_resp)
        if not res.get("ekonomi", False):
            return {"ekonomi": False}

        sektor = res.get("sektor", "")
        if sektor not in SEKTOR_BPS:
            sektor = match_fallback_sector(title_text + " " + content_text)

        ringkasan = str(res.get("ringkasan", "")).strip()
        norm_title = normalize_text(title_text)
        norm_summary = normalize_text(ringkasan)

        if norm_title in norm_summary or norm_summary in norm_title or SequenceMatcher(None, norm_title, norm_summary).ratio() > 0.50 or len(ringkasan) < 20:
            isu = res.get("isu_ekonomi", "ekonomi daerah")
            ringkasan = f"Pemberitaan ini mengulas mengenai {title_text.lower()} yang berdampak pada isu {isu.lower()} di Kabupaten Lamongan."

        return {
            "ekonomi": True,
            "sektor": sektor,
            "isu_ekonomi": str(res.get("isu_ekonomi", "Ekonomi Umum")).strip(),
            "ringkasan": ringkasan
        }
    except Exception as e:
        logger.error(f"Gemini API Error: {e}")
        return {"ekonomi": False}

def fetch_and_process_news():
    raw_articles = []
    progress = st.progress(0)
    status = st.empty()
    items = list(MEDIA_SEARCH.items())
    total = len(items)

    for i, (media_name, query) in enumerate(items):
        status.info(f"🔎 Mengambil artikel dari {media_name}...")
        try:
            rss_url = f"https://news.google.com/rss/search?q={quote(query)}&hl=id&gl=ID&ceid=ID:id"
            resp = requests.get(rss_url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
            feed = feedparser.parse(resp.content)

            for entry in feed.entries[:3]:  # Cepat & tepat
                title = clean_text(entry.get("title", ""))
                link = entry.get("link", "")
                content = clean_text(entry.get("summary", ""))

                if not title or not link or len(title) < 10:
                    continue

                pub_date = datetime.now().strftime("%Y-%m-%d")
                if entry.get("published_parsed"):
                    pub_date = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d")

                raw_articles.append({
                    "title": title,
                    "content": content,
                    "source": media_name,
                    "date": pub_date,
                    "url": link
                })
        except Exception as e:
            logger.error(f"Error media {media_name}: {e}")
        progress.progress((i + 1) / total)

    status.info("🧹 Menganalisis berita dengan AI Gemini...")
    final_records = []
    for art in raw_articles:
        ai_res = analyze_with_gemini(art)
        if ai_res.get("ekonomi") is True:
            final_records.append({
                "ID": make_id(art["title"], art["url"]),
                "Tanggal Berita": art["date"],
                "Media": art["source"],
                "Judul Berita": art["title"],
                "Isu Ekonomi": ai_res["isu_ekonomi"],
                "Sektor": ai_res["sektor"],
                "Ringkasan Berita": ai_res["ringkasan"],
                "Link Berita": art["url"]
            })

    status.success(f"✅ Selesai! Berhasil memuat {len(final_records)} berita terbaru.")
    progress.empty()

    if not final_records:
        return pd.DataFrame()

    df = pd.DataFrame(final_records).drop_duplicates(subset=["ID"]).sort_values("Tanggal Berita", ascending=False)
    return df

def create_sample_data():
    return pd.DataFrame([
        {"ID":"1","Tanggal Berita":"2026-08-17","Media":"ANTARAJATIM","Judul Berita":"Pertumbuhan Ekonomi Pesisir Lamongan Meningkat","Isu Ekonomi":"Ekonomi Daerah","Sektor":"A - Pertanian, Kehutanan, dan Perikanan","Ringkasan Berita":"Produktivitas sektor perikanan tangkap dan budidaya di Lamongan mencatatkan tren positif mendorong pendapatan nelayan lokal.","Link Berita":"https://jatim.antaranews.com/"},
        {"ID":"2","Tanggal Berita":"2026-08-16","Media":"Radar Lamongan","Judul Berita":"Pasar Tradisional Lamongan Siap Digitalisasi UMKM","Isu Ekonomi":"UMKM","Sektor":"G - Perdagangan Besar dan Eceran; Reparasi Mobil dan Sepeda Motor","Ringkasan Berita":"Pemerintah daerah memfasilitasi pembayaran QRIS dan pelatihan pemasaran digital bagi para pedagang UMKM di pasar daerah.","Link Berita":"https://radarlamongan.jawapos.com/"}
    ])

# ============================================================
# LOAD DATA & SIDEBAR
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
    st.image(BPS_LOGO_URL, width=120)
    st.title("📰 Dashboard Control")
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

    if st.button("🗑️ Reset & Bersihkan Data", use_container_width=True):
        st.session_state.data = create_sample_data()
        if DATA_FILE.exists(): DATA_FILE.unlink()

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
# TAMPILAN UTAMA
# ============================================================

st.markdown(f"""
<div class="dashboard-header">
    <img src="{BPS_LOGO_URL}" class="dashboard-logo" alt="Logo BPS">
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

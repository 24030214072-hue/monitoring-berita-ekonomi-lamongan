import os
import re
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
# 🤖 GEMINI AI CLIENT
# ============================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
if not GEMINI_API_KEY:
    try:
        GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        GEMINI_API_KEY = ""

client = None
if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        logger.error(f"Gagal inisialisasi Gemini Client: {e}")

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
# 🛠️ UTILITY HELPER
# ============================================================

def clean_text(text):
    if not text: return ""
    text = BeautifulSoup(str(text), "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()

def normalize_text(text):
    if not text: return ""
    text = str(text).lower()
    text = re.sub(r"http\S+|www\S+", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def normalize_url(url):
    if not url: return ""
    url = str(url).strip()
    parsed = urlparse(url)
    clean = parsed.scheme + "://" + parsed.netloc + parsed.path if parsed.scheme else url
    return clean.rstrip("/")

def make_id(title, url):
    return hashlib.md5((normalize_text(title) + "|" + normalize_url(url)).encode("utf-8")).hexdigest()[:16]

def fallback_sector(text):
    text_lower = text.lower()
    if any(w in text_lower for w in ["tani", "padi", "panen", "nelayan", "ikan", "sawah", "pupuk", "tambak"]):
        return "A - Pertanian, Kehutanan, dan Perikanan"
    elif any(w in text_lower for w in ["pabrik", "produksi", "olahan", "industri"]):
        return "C - Industri Pengolahan"
    elif any(w in text_lower for w in ["pasar", "toko", "pedagang", "jual", "umkm", "eceran", "harga"]):
        return "G - Perdagangan Besar dan Eceran; Reparasi Mobil dan Sepeda Motor"
    elif any(w in text_lower for w in ["jalan", "jembatan", "pembangunan", "konstruksi"]):
        return "F - Konstruksi"
    elif any(w in text_lower for w in ["bank", "kredit", "keuangan"]):
        return "K - Jasa Keuangan dan Asuransi"
    elif any(w in text_lower for w in ["wisata", "hotel", "kuliner", "resto"]):
        return "I - Penyediaan Akomodasi dan Makan Minum"
    return "O - Administrasi Pemerintahan, Pertahanan dan Jaminan Sosial Wajib"

# ============================================================
# 🤖 GEMINI AI ANALYZER
# ============================================================

def analyze_with_gemini(article):
    title_text = article.get("title", "")
    content_text = article.get("content", "")
    lower_title = title_text.lower()

    if not client:
        return {
            "ekonomi": True, 
            "sektor": fallback_sector(title_text + " " + content_text), 
            "isu_ekonomi": "Ekonomi Daerah", 
            "ringkasan": f"Laporan berita ini mengulas tentang {title_text.lower()} di Kabupaten Lamongan."
        }

    prompt = f"""
Anda adalah analis berita ekonomi BPS Kabupaten Lamongan.
Tentukan apakah berita ini merupakan berita ekonomi Kabupaten Lamongan atau bukan.

KRITERIA RELEVAN (ekonomi=true):
Membahas pasar, UMKM, pertanian, perikanan, industri, harga, pedagang, ekonomi, pembangunan fisik, investasi.

KRITERIA TOLAK (ekonomi=false):
Kriminal, sepak bola/Persela, politik murni, kecelakaan.

Judul: {title_text}
Isi: {content_text}

Jawab HANYA JSON format berikut:
{{
    "ekonomi": true,
    "sektor_kode": "G",
    "isu_ekonomi": "UMKM",
    "ringkasan": "Ulasan deskriptif ringkas berita (maksimal 25 kata dan jangan mengulang kata-kata di judul)."
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

        res = json.loads(text_resp)
        
        # Jaring pengaman jika AI Gemini menolak berita padahal ada kata ekonomi lokal
        if not res.get("ekonomi", False):
            if any(w in lower_title for w in ["ekonomi", "pasar", "umkm", "tani", "ikan", "harga", "panen", "dagang", "pedagang", "pembangunan", "wisata"]):
                res["ekonomi"] = True
                res["sektor_kode"] = "G"
                res["isu_ekonomi"] = "Ekonomi Daerah"
                res["ringkasan"] = f"Pemberitaan ini mengulas mengenai {title_text.lower()} di Kabupaten Lamongan."
            else:
                return {"ekonomi": False}

        code = str(res.get("sektor_kode", "")).upper()
        sektor_name = SEKTOR_BPS.get(code, fallback_sector(title_text))

        ringkasan = str(res.get("ringkasan", "")).strip()
        norm_title = normalize_text(title_text)
        norm_summary = normalize_text(ringkasan)

        if norm_title in norm_summary or norm_summary in norm_title or len(ringkasan) < 15:
            ringkasan = f"Pemberitaan ini mengulas mengenai {title_text.lower()} yang berdampak pada perekonomian di Kabupaten Lamongan."

        return {
            "ekonomi": True,
            "sektor": sektor_name,
            "isu_ekonomi": str(res.get("isu_ekonomi", "Ekonomi Daerah")).strip(),
            "ringkasan": ringkasan
        }
    except Exception as e:
        logger.error(f"Gemini API Error: {e}")
        if any(w in lower_title for w in ["ekonomi", "pasar", "umkm", "tani", "ikan", "harga", "panen", "dagang"]):
            return {
                "ekonomi": True,
                "sektor": fallback_sector(title_text),
                "isu_ekonomi": "Ekonomi Daerah",
                "ringkasan": f"Laporan berita ini mengulas tentang {title_text.lower()} di Kabupaten Lamongan."
            }
        return {"ekonomi": False}

# ============================================================
# 📥 PENGAMBILAN BERITA VIA GOOGLE NEWS RSS
# ============================================================

def fetch_and_process_news():
    topics = [
        "Lamongan",
        "Kabupaten Lamongan",
        "Pemkab Lamongan",
        "Lamongan ekonomi",
        "Lamongan UMKM pasar",
        "Lamongan tani nelayan"
    ]
    raw_articles = []
    
    progress = st.progress(0)
    status = st.empty()

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    })

    for i, t in enumerate(topics):
        status.info(f"🔎 Mengambil berita topik '{t}' dari internet...")
        try:
            rss_url = f"https://news.google.com/rss/search?q={quote(t)}&hl=id&gl=ID&ceid=ID:id"
            resp = session.get(rss_url, timeout=12)
            feed = feedparser.parse(resp.content)

            for entry in feed.entries:
                title = clean_text(entry.get("title", ""))
                link = normalize_url(entry.get("link", ""))
                content = clean_text(entry.get("summary", ""))

                if not title or not link or len(title) < 10:
                    continue

                source_name = "Berita Online"
                if entry.get("source") and entry.source.get("title"):
                    source_name = entry.source.get("title")
                elif " - " in title:
                    source_name = title.split(" - ")[-1].strip()

                pub_date = datetime.now().strftime("%Y-%m-%d")
                if entry.get("published_parsed"):
                    pub_date = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d")

                raw_articles.append({
                    "title": title,
                    "content": content if len(content) > 10 else title,
                    "source": source_name,
                    "date": pub_date,
                    "url": link
                })
        except Exception as e:
            logger.error(f"Error topic {t}: {e}")
        progress.progress((i + 1) / len(topics))

    status.info("🤖 AI Gemini sedang menyaring & mengelompokkan berita ekonomi...")
    
    unique_articles = {make_id(a["title"], a["url"]): a for a in raw_articles}.values()

    final_records = []
    for art in unique_articles:
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

    status.success(f"✅ Selesai! Berhasil menemukan {len(final_records)} berita ekonomi Lamongan.")
    progress.empty()

    if not final_records:
        return pd.DataFrame()

    df = pd.DataFrame(final_records).drop_duplicates(subset=["ID"]).sort_values("Tanggal Berita", ascending=False)
    return df

def create_sample_data():
    return pd.DataFrame([
        {"ID":"1","Tanggal Berita":"2026-08-17","Media":"ANTARAJATIM","Judul Berita":"Pertumbuhan Ekonomi Pesisir Lamongan Meningkat","Isu Ekonomi":"Perikanan","Sektor":"A - Pertanian, Kehutanan, dan Perikanan","Ringkasan Berita":"Aktivitas perikanan tangkap dan budidaya memberikan kontribusi terhadap pendapatan masyarakat pesisir Lamongan.","Link Berita":"https://jatim.antaranews.com/"},
        {"ID":"2","Tanggal Berita":"2026-08-16","Media":"Radar Lamongan","Judul Berita":"Pasar Tradisional Lamongan Siap Digitalisasi UMKM","Isu Ekonomi":"UMKM dan Perdagangan","Sektor":"G - Perdagangan Besar dan Eceran; Reparasi Mobil dan Sepeda Motor","Ringkasan Berita":"Pedagang UMKM mendapatkan dukungan digitalisasi transaksi dan pemasaran untuk meningkatkan aktivitas perdagangan di pasar daerah.","Link Berita":"https://radarlamongan.jawapos.com/"}
    ])

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

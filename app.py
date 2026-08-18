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
import openpyxl

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
# INISIALISASI GEMINI AI & LOGGING
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
# MASTER SEKTOR BPS & MEDIA SEARCH
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
# PROMPT AI STRICT (LEBIH KETAT MEMILIK BERITA EKONOMI)
# ============================================================

AI_CLASSIFICATION_PROMPT = """
Anda adalah analis berita ekonomi Badan Pusat Statistik (BPS) Kabupaten Lamongan.

TUGAS UTAMA: Tentukan apakah berita ini BENAR-BENAR BERITA EKONOMI KABUPATEN LAMONGAN atau BUKAN.

KRITERIA KETAT (ekonomi = true):
- Membahas aktivitas usaha, UMKM, pasar, perdagangan, pertanian, perikanan, produksi, harga barang, inflasi, industri, investasi, tenaga kerja, infrastruktur ekonomi, atau pendapatan daerah di Kabupaten Lamongan.

KRITERIA TOLAK (ekonomi = false):
- Berita Olahraga / Sepak Bola (Persela, Liga 2, Bursa Transfer, dll) -> WAJIB FALSE.
- Berita Kriminalitas Murni (Pencurian, Kasus Hukum, Korupsi Politik, Pembunuhan) -> WAJIB FALSE.
- Berita Politik / Pilkada / Seremonial tanpa dampak ekonomi -> WAJIB FALSE.
- Berita Hiburan / Karnaval / Wayang / Musik tanpa transaksi ekonomi nyata -> WAJIB FALSE.
- Berita luar daerah yang cuma menyebut nama Lamongan sepintas -> WAJIB FALSE.

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
    "ringkasan": "Ringkasan padat maksimal 2 kalimat dari isi berita."
}}

Jika tidak relevan (ekonomi = false):
{{
    "ekonomi": false,
    "sektor": "Tidak Relevan",
    "isu_ekonomi": "Tidak Relevan",
    "ringkasan": ""
}}

DATA BERITA:
Judul: {title}
Isi Berita: {content}
Media: {source}
Tanggal: {date}
URL: {url}
"""

# ============================================================
# FUNGSI HELPER & DEDUPLIKASI
# ============================================================

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

def title_similarity(title1, title2):
    t1, t2 = normalize_text(title1), normalize_text(title2)
    if not t1 or not t2: return 0
    return SequenceMatcher(None, t1, t2).ratio()

def article_completeness_score(article):
    title = str(article.get("title", "") or "")
    content = str(article.get("content", "") or "")
    score = 0
    content_length = len(content)

    if content_length >= 1500: score += 40
    elif content_length >= 1000: score += 30
    elif content_length >= 700: score += 20
    elif content_length >= 400: score += 10
    else: score += 2

    numbers = re.findall(r"\d+", content)
    if len(numbers) >= 5: score += 15
    elif len(numbers) >= 2: score += 10
    elif len(numbers) >= 1: score += 5

    if '"' in content or "ujar" in content.lower(): score += 10

    for word in ["lamongan", "kecamatan", "desa", "kabupaten"]:
        if word in content.lower(): score += 3

    economic_words = ["umkm", "usaha", "ekonomi", "pertanian", "perikanan", "perdagangan", "pasar", "harga", "inflasi", "investasi", "produksi", "pajak", "pembangunan", "infrastruktur", "omzet", "petani", "nelayan"]
    economic_count = sum(1 for word in economic_words if word in content.lower())
    score += min(economic_count * 2, 20)

    if len(title) >= 40: score += 5
    return score

def is_duplicate_article(article1, article2):
    media1, media2 = normalize_text(article1.get("source", "")), normalize_text(article2.get("source", ""))
    if media1 != media2: return False

    title1, title2 = article1.get("title", ""), article2.get("title", "")
    if title_similarity(title1, title2) >= 0.80: return True

    content1, content2 = normalize_text(article1.get("content", "")), normalize_text(article2.get("content", ""))
    if not content1 or not content2: return False

    if SequenceMatcher(None, content1[:5000], content2[:5000]).ratio() >= 0.75: return True
    return False

def remove_duplicate_articles(articles):
    selected_articles = []
    for article in articles:
        duplicate_index = None
        for i, selected in enumerate(selected_articles):
            if is_duplicate_article(article, selected):
                duplicate_index = i
                break

        if duplicate_index is None:
            selected_articles.append(article)
        else:
            existing_score = article_completeness_score(selected_articles[duplicate_index])
            new_score = article_completeness_score(article)
            if new_score > existing_score:
                selected_articles[duplicate_index] = article
    return selected_articles

def make_id(title, link):
    return hashlib.md5((str(title) + str(link)).encode("utf-8")).hexdigest()

# ============================================================
# PEMPROSESAN AI GEMINI
# ============================================================

def analyze_with_gemini(article):
    if not client:
        return {"ekonomi": True, "sektor": "A - Pertanian, Kehutanan, dan Perikanan", "isu_ekonomi": "Ekonomi Daerah", "ringkasan": article.get("content", "")[:150] + "..."}

    prompt = AI_CLASSIFICATION_PROMPT.format(
        title=article.get("title", ""),
        content=article.get("content", ""),
        source=article.get("source", ""),
        date=article.get("date", ""),
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
            sektor = "R,S,T,U - Jasa Lainnya"

        ringkasan = res.get("ringkasan", "")
        sentences = re.split(r"(?<=[.!?])\s+", ringkasan)
        ringkasan = " ".join(sentences[:2])

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
            resp = requests.get(rss_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            feed = feedparser.parse(resp.content)

            for entry in feed.entries:
                title = clean_text(entry.get("title", ""))
                link = entry.get("link", "")
                content = clean_text(entry.get("summary", ""))

                if not title or not link or len(content) < 80:
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

    status.info("🧹 Menghapus berita duplikat & menganalisis ketat dengan AI...")
    filtered_articles = remove_duplicate_articles(raw_articles)

    final_records = []
    for art in filtered_articles:
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

    status.success("✅ Pengambilan & analisis berita selesai!")
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
# LOAD DATA
# ============================================================

if "data" not in st.session_state:
    if DATA_FILE.exists():
        try:
            st.session_state.data = pd.read_csv(DATA_FILE)
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
        new_data = fetch_and_process_news()
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

# FILTERING
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
# TAMPILAN DASHBOARD
# ============================================================

st.markdown("""
<div class="dashboard-header">
    <div class="dashboard-title">📰 MONITORING BERITA EKONOMI LAMONGAN</div>
    <div class="dashboard-subtitle">Sistem pemantauan media otomatis berbasis AI untuk 17 Sektor Lapangan Usaha BPS Kabupaten Lamongan</div>
</div>
""", unsafe_allow_html=True)

k1, k2, k3, k4 = st.columns(4)
k1.metric("📰 Total Berita", f"{len(filtered):,} artikel")
k2.metric("📅 Berita Hari Ini", f"{len(filtered[filtered['Tanggal Berita'].dt.date == datetime.now().date()]):,} artikel")
k3.metric("🌐 Sumber Media", f"{filtered['Media'].nunique():,} media")
k4.metric("🏭 Sektor Terpantau", f"{filtered['Sektor'].nunique():,} sektor")

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

# ============================================================
# EKSPOR LAPORAN EXCEL RAPI + AUTO-FIT KOLOM (SESUAI REQUEST)
# ============================================================

st.markdown('<div class="section-header">📥 Ekspor Laporan Excel Rapi</div>', unsafe_allow_html=True)

if not filtered.empty:
    exp_df = filtered.copy()
    exp_df["Tanggal Berita"] = exp_df["Tanggal Berita"].dt.strftime("%Y-%m-%d")
    exp_df = exp_df[["Tanggal Berita", "Media", "Judul Berita", "Isu Ekonomi", "Sektor", "Ringkasan Berita", "Link Berita"]]

    # MENGHASILKAN FILE EXCEL SANGAT RAPI WITH AUTO-FIT SPASI
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        exp_df.to_excel(writer, index=False, sheet_name='Monitoring Berita')
        worksheet = writer.sheets['Monitoring Berita']

        # Otomatis melebarkan kolom sesuai panjang teks terbesar
        for col in worksheet.columns:
            max_len = 0
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            for cell in col:
                val_str = str(cell.value or '')
                if len(val_str) > max_len:
                    max_len = len(val_str)
            # Beri ruang spasi ekstra + batasi maks 60 biar tidak terlalu lebar
            worksheet.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 65)

    buffer.seek(0)

    st.download_button(
        label="📊 Download Laporan Format Excel (.xlsx) Rapi & Pas Kolom",
        data=buffer,
        file_name=f"Laporan_Berita_Ekonomi_Lamongan_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

st.divider()
st.caption("Dashboard Monitoring Berita Ekonomi Kabupaten Lamongan | BPS Kabupaten Lamongan")

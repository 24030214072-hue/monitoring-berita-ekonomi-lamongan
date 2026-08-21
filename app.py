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
import sqlite3
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
# KONFIGURASI PENGAMBILAN DATA OTOMATIS
# ============================================================

# Playwright digunakan untuk halaman yang membutuhkan JavaScript.
# Jika Playwright/browser tidak tersedia, sistem otomatis memakai
# fallback requests + BeautifulSoup agar dashboard tetap berjalan.
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False
    sync_playwright = None
    PlaywrightTimeoutError = Exception


# Target website dapat ditambah/dikurangi tanpa mengubah fungsi scraping.
# Google News hanya digunakan untuk menemukan kandidat; media yang
# ditampilkan tetap berasal dari URL/source artikel asli.
TARGET_SOURCES = {
    "ANTARA Jatim": ["jatim.antaranews.com"],
    "ANTARA": ["antaranews.com"],
    "Radar Lamongan": ["radarlamongan.jawapos.com", "radarlamongan.com"],
    "Jawa Pos": ["jawapos.com"],
    "KOMPAS.com": ["kompas.com"],
    "detikJatim": ["detik.com"],
    "KlikJatim": ["klikjatim.com"],
    "BeritaJatim": ["beritajatim.com"],
    "Tribun Jatim": ["surabaya.tribunnews.com", "tribunnews.com"],
    "Jatim Times": ["jatimtimes.com"],
    "Bangsa Online": ["bangsaonline.com"],
    "Suara Surabaya": ["suarasurabaya.net"],
}

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
    "Lamongan nelayan",
    "Lamongan transportasi",
    "Lamongan keuangan",
    "Lamongan konstruksi",
]

MAX_RESULTS_PER_QUERY = 12
MAX_TOTAL_CANDIDATES = 180
SCRAPE_WORKERS = 6
ARTICLE_TIMEOUT_MS = 15000
MAX_CONTENT = 16000
GEMINI_MODEL = st.secrets.get("GEMINI_MODEL", "gemini-2.5-flash")

# ============================================================
# GEMINI CLIENT
# ============================================================

# gemini_client adalah satu-satunya nama client yang digunakan.
# Ini sengaja menghilangkan error lama: NameError: client.
gemini_client = None
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

if GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as exc:
        logger.exception("Gemini client gagal dibuat: %s", exc)
        gemini_client = None


# ============================================================
# DATABASE SQLITE - MIGRASI AMAN
# ============================================================

DB_NAME = str(BASE_DIR / "berita_lamongan.db")


def get_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def create_database():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
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
            sumber_pencarian TEXT,
            domain_media TEXT,
            created_at TEXT
        )
    """)
    existing = {r[1] for r in cur.execute("PRAGMA table_info(berita)").fetchall()}
    migrations = {
        "sumber_pencarian": "TEXT",
        "domain_media": "TEXT",
    }
    for col, typ in migrations.items():
        if col not in existing:
            cur.execute(f"ALTER TABLE berita ADD COLUMN {col} {typ}")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_berita_tanggal ON berita(tanggal)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_berita_media ON berita(media)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_berita_sektor ON berita(sektor)")
    conn.commit()
    conn.close()


create_database()


# ============================================================
# UTILITAS TEKS / TANGGAL
# ============================================================

def clean_text(text):
    if not text:
        return ""
    text = BeautifulSoup(str(text), "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_text(text):
    text = clean_text(text).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def similarity(a, b):
    a, b = normalize_text(a), normalize_text(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def parse_date(value):
    if not value:
        return ""
    dt = pd.to_datetime(clean_text(value), errors="coerce", dayfirst=True)
    if pd.isna(dt):
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# STAGE 1 - TARGET WEBSITE IDENTIFICATION + SEARCH QUERY
# ============================================================

def get_media_from_url(url, source_title=""):
    domain = urlparse(url or "").netloc.lower().replace("www.", "")
    for media, domains in TARGET_SOURCES.items():
        for d in domains:
            if d in domain:
                return media
    s = clean_text(source_title).lower()
    for media in TARGET_SOURCES:
        if media.lower() in s:
            return media
    return domain if domain else "Media tidak diketahui"


def get_google_news_rss(keyword, source_domain=None):
    # Untuk target tertentu, query dibatasi dengan site: sehingga kandidat
    # benar-benar berasal dari media yang diinginkan.
    q = keyword
    if source_domain:
        q = f"{keyword} site:{source_domain}"
    url = (
        "https://news.google.com/rss/search?"
        f"q={quote(q)}&hl=id&gl=ID&ceid=ID:id"
    )
    try:
        response = requests.get(
            url, timeout=12,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36"}
        )
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        results = []
        for item in feed.entries[:MAX_RESULTS_PER_QUERY]:
            source = item.get("source", {})
            source_title = source.get("title", "") if isinstance(source, dict) else getattr(source, "title", "")
            title = clean_text(item.get("title", ""))
            link = item.get("link", "")
            if title and link:
                results.append({
                    "judul_awal": title,
                    "link": link,
                    "tanggal_awal": item.get("published", ""),
                    "deskripsi_awal": clean_text(item.get("summary", "")),
                    "source_title": clean_text(source_title),
                    "query": q,
                    "target_media": get_media_from_url("", source_title),
                })
        return results
    except Exception as exc:
        logger.warning("RSS gagal %s: %s", q, exc)
        return []


def resolve_original_url(url):
    if not url:
        return ""
    domain = urlparse(url).netloc.lower()
    if "news.google.com" not in domain:
        return url
    try:
        r = requests.get(
            url, timeout=12, allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        final_url = r.url
        if final_url and "news.google.com" not in urlparse(final_url).netloc.lower():
            return final_url
    except Exception as exc:
        logger.warning("Resolusi URL gagal: %s", exc)
    return url


def scrape_news():
    """Stage 1 + 3: target source -> query -> kandidat artikel."""
    all_news = []
    jobs = []
    # Semua target source dicari, tetapi jumlah request dibatasi agar tidak lambat.
    for media, domains in TARGET_SOURCES.items():
        for domain in domains[:1]:
            for topic in SEARCH_TOPICS[:10]:
                jobs.append((topic, domain, media))

    progress = st.progress(0)
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(get_google_news_rss, topic, domain): (topic, domain, media)
            for topic, domain, media in jobs
        }
        for i, future in enumerate(as_completed(futures), 1):
            topic, domain, media = futures[future]
            try:
                rows = future.result()
                for row in rows:
                    row["target_media"] = media
                    all_news.append(row)
            except Exception as exc:
                logger.warning("Search job gagal: %s", exc)
            progress.progress(i / len(futures))
    progress.empty()

    # Dedup kandidat berdasarkan URL Google News + judul.
    unique = {}
    for item in all_news:
        key = (normalize_text(item["judul_awal"]), item.get("source_title", ""))
        if key not in unique:
            unique[key] = item
    return list(unique.values())[:MAX_TOTAL_CANDIDATES]


# ============================================================
# STAGE 2 - BROWSER AUTOMATION + FALLBACK
# ============================================================

def _extract_from_soup(soup):
    # JSON-LD sering berisi articleBody yang lebih lengkap.
    jsonld = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        try:
            data = json.loads(raw)
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if not isinstance(obj, dict):
                continue
            graph = obj.get("@graph")
            if isinstance(graph, list):
                objs.extend(x for x in graph if isinstance(x, dict))
            body = obj.get("articleBody", "")
            if body:
                jsonld.append(clean_text(body))

    # Hapus elemen navigasi/script sebelum ekstraksi paragraf.
    for el in soup.find_all(["script", "style", "noscript", "nav", "footer", "header", "aside", "form"]):
        el.decompose()

    title = ""
    og_title = soup.find("meta", property="og:title")
    h1 = soup.find("h1")
    if og_title and og_title.get("content"):
        title = clean_text(og_title["content"])
    elif h1:
        title = clean_text(h1.get_text(" "))
    elif soup.title:
        title = clean_text(soup.title.get_text(" "))

    date = ""
    for tag in [
        soup.find("meta", property="article:published_time"),
        soup.find("meta", attrs={"name": "date"}),
        soup.find("meta", attrs={"name": "pubdate"}),
        soup.find("time"),
    ]:
        if tag:
            value = tag.get("content") or tag.get("datetime") or tag.get_text(" ")
            date = parse_date(value)
            if date:
                break

    candidates = []
    if jsonld:
        candidates.append(" ".join(jsonld))
    article = soup.find("article")
    if article:
        candidates.append(clean_text(article.get_text(" ")))
    main = soup.find("main")
    if main:
        candidates.append(clean_text(main.get_text(" ")))
    paragraphs = []
    seen = set()
    for p in soup.find_all("p"):
        text = clean_text(p.get_text(" "))
        key = normalize_text(text)
        if len(text) >= 35 and key not in seen:
            seen.add(key)
            paragraphs.append(text)
    candidates.append(" ".join(paragraphs))
    content = max((x for x in candidates if len(x) > 100), key=len, default="")
    return title, date, content[:MAX_CONTENT]


def extract_article(url):
    """Stage 2 + 4: render JS dengan Playwright; fallback ke requests."""
    if not url:
        return {"judul": "", "isi_berita": "", "tanggal": "", "url": ""}

    original_url = url
    if "news.google.com" in urlparse(url).netloc.lower():
        url = resolve_original_url(url)

    # Playwright untuk situs JavaScript-heavy.
    if PLAYWRIGHT_AVAILABLE:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(
                    viewport={"width": 1366, "height": 900},
                    user_agent=HEADERS["User-Agent"] if "HEADERS" in globals() else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
                    locale="id-ID",
                )
                page.goto(url, wait_until="domcontentloaded", timeout=ARTICLE_TIMEOUT_MS)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                html = page.content()
                final_url = page.url
                browser.close()
                soup = BeautifulSoup(html, "html.parser")
                title, date, content = _extract_from_soup(soup)
                if len(content) >= 150:
                    return {"judul": title, "isi_berita": content, "tanggal": date, "url": final_url}
        except Exception as exc:
            logger.info("Playwright gagal, fallback requests: %s", exc)

    # Fallback tetap penting untuk deployment yang belum memasang Chromium.
    try:
        response = requests.get(
            url, timeout=15, allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36", "Accept-Language": "id-ID,id;q=0.9"}
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        title, date, content = _extract_from_soup(soup)
        return {"judul": title, "isi_berita": content, "tanggal": date, "url": response.url or url}
    except Exception as exc:
        logger.warning("Requests scraping gagal %s: %s", original_url, exc)
        return {"judul": "", "isi_berita": "", "tanggal": "", "url": url}


# ============================================================
# STAGE 4 - VALIDASI + DEDUPLIKASI + PILIH ARTIKEL TERLENGKAP
# ============================================================

def choose_best_articles(items):
    """Jika berita sama dari beberapa media, pilih artikel dengan isi paling lengkap."""
    selected = []
    for item in sorted(items, key=lambda x: len(x.get("isi_berita", "")), reverse=True):
        duplicate = False
        for old in selected:
            if item.get("link") and old.get("link") == item.get("link"):
                duplicate = True
                break
            if similarity(item.get("judul", ""), old.get("judul", "")) >= 0.92:
                duplicate = True
                break
            a = normalize_text(item.get("isi_berita", "")[:6000])
            b = normalize_text(old.get("isi_berita", "")[:6000])
            if len(a) > 300 and len(b) > 300 and SequenceMatcher(None, a, b).ratio() >= 0.86:
                duplicate = True
                break
        if not duplicate:
            selected.append(item)
    return selected


# ============================================================
# GEMINI AI - KLASIFIKASI BERITA EKONOMI LAMONGAN
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
    "R,S,T,U - Jasa Lainnya",
]


def validate_sector(value):
    value = clean_text(value)
    for sector in SEKTOR_BPS:
        if value.lower() == sector.lower():
            return sector
        code = sector.split(" - ")[0].upper()
        if value.upper().startswith(code + " ") or value.upper() == code:
            return sector
    return "Tidak teridentifikasi"


def analyze_with_gemini(title, media, content):
    """AI membaca isi artikel, bukan judul saja."""
    if len(clean_text(content)) < 120:
        return {
            "relevan": False,
            "isu_ekonomi": "",
            "sektor": "Tidak teridentifikasi",
            "ringkasan": "",
        }

    if gemini_client is None:
        return {
            "relevan": False,
            "isu_ekonomi": "",
            "sektor": "Tidak teridentifikasi",
            "ringkasan": "",
        }

    sector_text = "\n".join(f"- {x}" for x in SEKTOR_BPS)
    prompt = f"""
Kamu adalah analis berita ekonomi BPS Kabupaten Lamongan.

Baca dan pahami ISI ARTIKEL secara menyeluruh. Judul hanya digunakan sebagai konteks.
Tentukan hasil berdasarkan fakta yang terdapat di isi artikel.

MEDIA: {media}
JUDUL: {title}

ISI ARTIKEL:
{content[:10000]}

TUGAS:
1. Tentukan apakah berita ini relevan sebagai BERITA EKONOMI KABUPATEN LAMONGAN.
   Relevan jika membahas kegiatan ekonomi, produksi, perdagangan, usaha, UMKM,
   pertanian, perikanan, industri, investasi, pembangunan ekonomi, pasar, harga,
   keuangan, transportasi, pariwisata, jasa, tenaga kerja, atau aktivitas ekonomi
   lain yang berdampak/terjadi di Kabupaten Lamongan.
2. Jika tidak relevan, relevan=false.
3. Jika relevan, tentukan SATU isu ekonomi yang SPESIFIK sesuai isi artikel.
   DILARANG memakai "Ekonomi Umum" jika isi artikel dapat dijelaskan lebih spesifik.
   Contoh isu: Harga Pangan, Produksi Padi, UMKM, Perdagangan Pasar,
   Investasi Daerah, Perikanan, Industri Pengolahan, Pendapatan Daerah,
   Pariwisata, Transportasi dan Logistik, Koperasi, Konstruksi, dan sebagainya.
4. Tentukan tepat SATU sektor lapangan usaha BPS dari daftar berikut:
{sector_text}
5. Ringkasan 2-3 kalimat, maksimal 80 kata, wajib berdasarkan isi artikel.
   Pertahankan angka, lokasi, pelaku, nilai transaksi, produksi, kebijakan,
   atau dampak ekonomi penting jika memang ada.
6. Jangan mengarang fakta.

KELUARKAN HANYA JSON VALID:
{{
  "relevan": true,
  "isu_ekonomi": "Harga Pangan",
  "sektor": "A - Pertanian, Kehutanan, dan Perikanan",
  "ringkasan": "..."
}}
"""

    try:
        from google.genai import types
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                top_k=20,
                max_output_tokens=900,
                response_mime_type="application/json",
            ),
        )
        text = (response.text or "").strip()
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ValueError("Respons Gemini bukan JSON")
        result = json.loads(match.group(0))
        relevant = bool(result.get("relevan", False))
        issue = clean_text(result.get("isu_ekonomi", ""))
        sector = validate_sector(result.get("sektor", ""))
        summary = clean_text(result.get("ringkasan", ""))

        if relevant and (not issue or issue.lower() in {"ekonomi umum", "ekonomi"}):
            issue = "Isu ekonomi belum teridentifikasi secara spesifik"
        if relevant and sector == "Tidak teridentifikasi":
            # Berita ekonomi tidak dibuang hanya karena output nama sektor sedikit berbeda.
            return {"relevan": True, "isu_ekonomi": issue, "sektor": sector, "ringkasan": summary or content[:500]}
        return {
            "relevan": relevant,
            "isu_ekonomi": issue,
            "sektor": sector,
            "ringkasan": summary or content[:500],
        }
    except Exception as exc:
        logger.exception("Gemini analysis error: %s", exc)
        return {
            "relevan": False,
            "isu_ekonomi": "",
            "sektor": "Tidak teridentifikasi",
            "ringkasan": "",
        }


# ============================================================
# SIMPAN DATABASE
# ============================================================

def save_news(news):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO berita
            (tanggal, media, judul, isu_ekonomi, sektor, ringkasan,
             isi_berita, link, relevan, sumber_pencarian, domain_media, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            news.get("tanggal", ""), news.get("media", ""), news.get("judul", ""),
            news.get("isu_ekonomi", ""), news.get("sektor", ""), news.get("ringkasan", ""),
            news.get("isi_berita", ""), news.get("link", ""),
            1 if news.get("relevan") else 0, news.get("sumber_pencarian", ""),
            urlparse(news.get("link", "")).netloc.lower(), datetime.now().isoformat()
        ))
        conn.commit()
    except Exception as exc:
        logger.exception("Save database error: %s", exc)
    finally:
        conn.close()


def load_database():
    conn = get_connection()
    df = pd.read_sql_query("""
        SELECT id, tanggal, media, judul, isu_ekonomi, sektor, ringkasan, link
        FROM berita WHERE relevan=1 ORDER BY id DESC
    """, conn)
    conn.close()
    df = df.rename(columns={
        "tanggal": "Tanggal Berita", "media": "Media", "judul": "Judul Berita",
        "isu_ekonomi": "Isu Ekonomi", "sektor": "Sektor",
        "ringkasan": "Ringkasan Berita", "link": "Link Berita"
    })
    if "Tanggal Berita" in df.columns:
        df["Tanggal Berita"] = pd.to_datetime(df["Tanggal Berita"], errors="coerce")
    return df


# ============================================================
# PIPELINE UTAMA
# ============================================================

def process_news():
    if gemini_client is None:
        st.error("🔴 Gemini AI belum aktif. Tambahkan GEMINI_API_KEY pada Streamlit Secrets.")
        return

    st.info("🔎 Stage 1/4 — mengidentifikasi sumber dan mencari kandidat berita...")
    candidates = scrape_news()
    if not candidates:
        st.warning("Tidak ditemukan kandidat berita.")
        return
    st.success(f"Ditemukan {len(candidates)} kandidat berita dari sumber target.")

    st.info("🌐 Stage 2/4 — membuka halaman artikel dengan Playwright/fallback...")
    scraped = []
    progress = st.progress(0)
    with ThreadPoolExecutor(max_workers=SCRAPE_WORKERS) as executor:
        futures = {executor.submit(extract_article, resolve_original_url(x["link"])): x for x in candidates}
        for i, future in enumerate(as_completed(futures), 1):
            item = futures[future]
            try:
                article = future.result()
                url = article.get("url") or resolve_original_url(item["link"])
                media = get_media_from_url(url, item.get("source_title", ""))
                title = article.get("judul") or item["judul_awal"]
                content = article.get("isi_berita", "") or item.get("deskripsi_awal", "")
                if len(content) >= 120 and "news.google.com" not in urlparse(url).netloc.lower():
                    scraped.append({
                        "tanggal": article.get("tanggal") or parse_date(item.get("tanggal_awal", "")),
                        "media": media,
                        "judul": title,
                        "isi_berita": content,
                        "link": url,
                        "sumber_pencarian": item.get("query", ""),
                    })
            except Exception as exc:
                logger.exception("Scrape candidate error: %s", exc)
            progress.progress(i / len(futures))
    progress.empty()

    if not scraped:
        st.warning("Kandidat ditemukan, tetapi isi artikel tidak berhasil diekstrak.")
        return

    st.info("🧹 Stage 3/4 — validasi dan memilih artikel paling lengkap jika duplikat...")
    scraped = choose_best_articles(scraped)
    st.success(f"{len(scraped)} artikel unik siap dianalisis Gemini.")

    st.info("🤖 Stage 4/4 — Gemini membaca isi artikel dan menentukan isu + sektor BPS...")
    progress = st.progress(0)
    saved = 0
    relevant_count = 0
    # Gemini API dipanggil secara berurutan agar lebih aman terhadap rate limit.
    for i, item in enumerate(scraped, 1):
        try:
            analysis = analyze_with_gemini(item["judul"], item["media"], item["isi_berita"])
            if analysis["relevan"]:
                relevant_count += 1
                item.update(analysis)
                save_news(item)
                saved += 1
        except Exception as exc:
            logger.exception("AI pipeline error: %s", exc)
        progress.progress(i / len(scraped))
    progress.empty()

    st.success(f"✅ Selesai: {saved} berita ekonomi disimpan ke SQLite.")
    st.caption(f"Artikel unik: {len(scraped)} | Lolos klasifikasi ekonomi: {relevant_count} | Playwright: {'aktif' if PLAYWRIGHT_AVAILABLE else 'fallback requests'}")


# ============================================================
# LOAD DATA + SIDEBAR CONTROL
# ============================================================

# Tidak lagi memakai create_sample_data() atau variabel 'client' yang sebelumnya
# menyebabkan NameError. Sumber data dashboard langsung dari SQLite.
if "data" not in st.session_state:
    st.session_state.data = load_database()

with st.sidebar:
    if BPS_LOGO.exists():
        st.image(BPS_LOGO_URL, width=120)

    st.title("Dashboard Control")

    if gemini_client is not None:
        st.success("🟢 Gemini AI: Active")
    else:
        st.error("🔴 Gemini AI: Offline (Cek Secrets)")

    st.divider()
    st.subheader("⚙️ Aksi")

    if st.button("🔄 Ambil Berita Terbaru", use_container_width=True):
        process_news()
        st.session_state.data = load_database()
        st.rerun()

    if st.button("🗑️ Reset & Bersihkan Data", use_container_width=True):
        conn = get_connection()
        conn.execute("DELETE FROM berita")
        conn.commit()
        conn.close()
        st.session_state.data = load_database()
        st.rerun()

    st.divider()
    st.subheader("🔎 Filter Data")

df = load_database()
st.session_state.data = df.copy()
df["Tanggal Berita"] = pd.to_datetime(df["Tanggal Berita"], errors="coerce")

with st.sidebar:
    valid_dates = df["Tanggal Berita"].dropna() if not df.empty else pd.Series(dtype="datetime64[ns]")
    min_date = valid_dates.min().date() if not valid_dates.empty else datetime.now().date()
    max_date = valid_dates.max().date() if not valid_dates.empty else datetime.now().date()
    date_range = st.date_input("📅 Periode Berita", value=(min_date, max_date))
    selected_media = st.multiselect("🌐 Media", sorted(df["Media"].dropna().unique()))
    selected_sector = st.multiselect("🏭 Sektor Lapangan Usaha", sorted(df["Sektor"].dropna().unique()))
    selected_issue = st.multiselect("📊 Isu Ekonomi", sorted(df["Isu Ekonomi"].dropna().unique()))
    keyword = st.text_input("🔎 Cari kata kunci", placeholder="Ketik kata kunci...")

filtered = df.copy()
if len(date_range) == 2 and not filtered.empty:
    filtered = filtered[(filtered["Tanggal Berita"].dt.date >= date_range[0]) & (filtered["Tanggal Berita"].dt.date <= date_range[1])]
if selected_media:
    filtered = filtered[filtered["Media"].isin(selected_media)]
if selected_sector:
    filtered = filtered[filtered["Sektor"].isin(selected_sector)]
if selected_issue:
    filtered = filtered[filtered["Isu Ekonomi"].isin(selected_issue)]
if keyword and not filtered.empty:
    search_text = keyword.lower()
    cols = ["Judul Berita", "Isu Ekonomi", "Sektor", "Ringkasan Berita", "Media"]
    mask = pd.Series(False, index=filtered.index)
    for col in cols:
        mask |= filtered[col].fillna("").astype(str).str.lower().str.contains(search_text, regex=False)
    filtered = filtered[mask]

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

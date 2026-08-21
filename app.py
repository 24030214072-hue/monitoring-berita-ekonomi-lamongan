import os
import re
import time
import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from urllib.parse import quote, urlparse, urljoin, parse_qs, unquote
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

DB_NAME = str(BASE_DIR / "berita_lamongan.db")


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


def resolve_article_url(url):
    """
    Mengubah link Google News menjadi URL artikel media asli.
    Jika redirect gagal, URL awal tetap digunakan.
    """
    if not url:
        return ""

    try:
        # Google News biasanya akan mengarahkan ke website media asli.
        response = requests.get(
            url,
            timeout=12,
            allow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
                ),
                "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
            },
        )

        final_url = response.url or url

        # Jangan menggunakan URL Google News sebagai URL artikel
        if "news.google.com" not in urlparse(final_url).netloc.lower():
            return final_url

    except Exception as e:
        logger.warning("Gagal resolve URL Google News %s: %s", url, e)

    return url


def get_google_news_rss(keyword):
    """
    Mengambil kandidat berita dari Google News RSS.
    Fungsi ini sengaja hanya mengambil metadata/kandidat.
    Isi artikel diambil oleh extract_article().
    """

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
            timeout=20,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
                ),
                "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
                "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
            },
        )

        response.raise_for_status()

        feed = feedparser.parse(response.content)

        results = []

        for item in feed.entries:
            title = clean_text(item.get("title", ""))
            google_link = item.get("link", "")
            published = item.get("published", "")
            description = clean_text(
                item.get("summary", "") or
                item.get("description", "")
            )

            if not title or not google_link:
                continue

            # Ambil URL media asli.
            article_url = resolve_article_url(google_link)

            # Jika redirect belum berhasil, tetap simpan link Google News
            # karena extract_article akan mencoba URL tersebut.
            if not article_url:
                article_url = google_link

            results.append({
                "judul_awal": title,
                "link": article_url,
                "google_link": google_link,
                "tanggal_awal": published,
                "deskripsi_awal": description,
            })

        logger.info(
            "RSS '%s': HTTP %s, %s entry",
            keyword,
            response.status_code,
            len(results),
        )

        return results

    except Exception as e:
        logger.exception(
            "RSS gagal untuk keyword '%s': %s",
            keyword,
            e,
        )
        return []

# ============================================================
# SCRAPE SEMUA TOPIK
# ============================================================

def scrape_news():
    """
    Mengambil kandidat berita dari seluruh topik secara paralel.
    Sebelumnya proses dilakukan satu per satu sehingga lambat dan
    satu kegagalan request dapat membuat proses terasa seperti 0.
    """

    all_news = []

    progress = st.progress(0)
    status = st.empty()

    total = len(SEARCH_TOPICS)

    def fetch_topic(topic):
        return topic, get_google_news_rss(topic)

    completed = 0

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(fetch_topic, topic)
            for topic in SEARCH_TOPICS
        ]

        for future in as_completed(futures):
            try:
                topic, results = future.result()

                if results:
                    all_news.extend(results)

                completed += 1
                status.write(
                    f"🔎 Mencari berita: {completed}/{total} topik — "
                    f"{len(all_news)} kandidat ditemukan"
                )
                progress.progress(completed / total)

            except Exception as e:
                completed += 1
                logger.exception("Gagal memproses topic: %s", e)
                progress.progress(completed / total)

    progress.empty()
    status.empty()

    # Deduplicate:
    # 1) URL artikel
    # 2) judul yang sangat sama
    unique = {}
    title_keys = set()

    for item in all_news:
        link = (item.get("link") or "").strip()
        title = clean_text(item.get("judul_awal", ""))

        if not link or not title:
            continue

        title_key = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()

        if link in unique:
            continue

        if title_key in title_keys:
            continue

        unique[link] = item
        title_keys.add(title_key)

    results = list(unique.values())

    logger.info(
        "Total kandidat setelah deduplikasi: %s",
        len(results),
    )

    return results

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
    """
    Ekstraksi isi artikel yang lebih tahan terhadap variasi struktur
    website media. Jika <p> tidak berhasil, gunakan meta description,
    JSON-LD articleBody, atau body text sebagai fallback.
    """

    original_url = url or ""
    candidate_urls = [original_url]

    # Kalau URL masih Google News, resolve dulu.
    resolved = resolve_article_url(original_url)
    if resolved and resolved not in candidate_urls:
        candidate_urls.insert(0, resolved)

    last_error = ""

    for target_url in candidate_urls:
        if not target_url:
            continue

        try:
            response = requests.get(
                target_url,
                timeout=15,
                allow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0 Safari/537.36"
                    ),
                    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
                },
            )

            response.raise_for_status()

            final_url = response.url or target_url
            soup = BeautifulSoup(
                response.text,
                "html.parser",
            )

            # Simpan metadata tanggal sebelum elemen dihapus.
            date = ""

            date_meta_selectors = [
                ("meta", {"property": "article:published_time"}),
                ("meta", {"property": "og:published_time"}),
                ("meta", {"name": "date"}),
                ("meta", {"name": "pubdate"}),
                ("meta", {"itemprop": "datePublished"}),
            ]

            for tag_name, attrs in date_meta_selectors:
                meta = soup.find(tag_name, attrs=attrs)
                if meta and meta.get("content"):
                    date = meta.get("content")
                    break

            # JSON-LD dapat berisi articleBody dan datePublished.
            jsonld_bodies = []
            for script in soup.find_all(
                "script",
                attrs={"type": "application/ld+json"},
            ):
                try:
                    raw = script.string or script.get_text()
                    data = json.loads(raw)

                    objects = data if isinstance(data, list) else [data]

                    for obj in objects:
                        if not isinstance(obj, dict):
                            continue

                        # @graph
                        graph = obj.get("@graph")
                        if isinstance(graph, list):
                            objects.extend(
                                x for x in graph
                                if isinstance(x, dict)
                            )

                        body = obj.get("articleBody")
                        if isinstance(body, str) and len(body) > 100:
                            jsonld_bodies.append(clean_text(body))

                        if not date:
                            published = (
                                obj.get("datePublished")
                                or obj.get("dateCreated")
                            )
                            if published:
                                date = str(published)

                except Exception:
                    continue

            # Hapus elemen yang biasanya bukan isi berita.
            for element in soup.find_all(
                [
                    "script",
                    "style",
                    "nav",
                    "footer",
                    "header",
                    "aside",
                    "form",
                    "noscript",
                    "svg",
                ]
            ):
                element.decompose()

            paragraphs = []

            # Prioritaskan selector artikel.
            article_roots = soup.find_all(
                [
                    "article",
                    "main",
                ]
            )

            search_roots = article_roots if article_roots else [soup]

            for root in search_roots:
                for p in root.find_all("p"):
                    value = clean_text(p.get_text(" ", strip=True))

                    # Hindari paragraf menu/promo yang sangat pendek.
                    if len(value) >= 45:
                        paragraphs.append(value)

            # Fallback seluruh halaman.
            if len(paragraphs) < 3:
                for p in soup.find_all("p"):
                    value = clean_text(p.get_text(" ", strip=True))
                    if len(value) >= 45:
                        paragraphs.append(value)

            unique_paragraphs = []
            seen = set()

            for paragraph in paragraphs:
                key = re.sub(
                    r"\s+",
                    " ",
                    paragraph.lower(),
                ).strip()

                if key not in seen:
                    seen.add(key)
                    unique_paragraphs.append(paragraph)

            content = " ".join(unique_paragraphs)

            # Fallback JSON-LD.
            if len(content) < 300 and jsonld_bodies:
                content = max(
                    jsonld_bodies,
                    key=len,
                )

            # Fallback meta description.
            if len(content) < 200:
                description = ""

                for attrs in [
                    {"name": "description"},
                    {"property": "og:description"},
                ]:
                    meta = soup.find(
                        "meta",
                        attrs=attrs,
                    )

                    if meta and meta.get("content"):
                        description = clean_text(
                            meta.get("content")
                        )
                        if len(description) > len(content):
                            content = description

            content = content[:15000]

            if content:
                logger.info(
                    "Artikel berhasil diekstrak: %s | %s karakter | %s",
                    final_url,
                    len(content),
                    date,
                )

                return {
                    "isi_berita": content,
                    "tanggal": date,
                    "url_final": final_url,
                }

            last_error = (
                f"HTTP {response.status_code}, "
                "halaman tidak menghasilkan isi artikel"
            )

        except Exception as e:
            last_error = str(e)
            logger.warning(
                "Gagal ekstrak %s: %s",
                target_url,
                e,
            )

    logger.warning(
        "Semua metode ekstraksi gagal untuk %s: %s",
        original_url,
        last_error,
    )

    return {
        "isi_berita": "",
        "tanggal": "",
        "url_final": original_url,
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

        st.error(
            "❌ Tidak ada kandidat berita yang berhasil diambil."
        )
        st.info(
            "Periksa koneksi Google News RSS dan lihat app.log "
            "untuk mengetahui keyword mana yang gagal."
        )
        return

    st.success(
        f"Berhasil menemukan "
        f"{len(candidates)} kandidat berita."
    )

    # Tampilkan beberapa kandidat untuk memastikan scraping berjalan.
    with st.expander("🔎 Detail proses scraping", expanded=False):
        preview = pd.DataFrame([
            {
                "Judul": x.get("judul_awal", ""),
                "URL": x.get("link", ""),
                "Tanggal RSS": x.get("tanggal_awal", ""),
            }
            for x in candidates[:10]
        ])
        st.dataframe(
            preview,
            use_container_width=True,
            hide_index=True,
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

        content = article.get(
            "isi_berita",
            ""
        )

        # Jika halaman media memblokir scraping,
        # gunakan deskripsi dari RSS sebagai fallback.
        # Ini mencegah seluruh hasil menjadi 0.
        if len(content.strip()) < 200:
            rss_description = clean_text(
                item.get("deskripsi_awal", "")
            )

            if len(rss_description) > len(content):
                content = rss_description

        media = get_media_from_url(
            article.get(
                "url_final",
                item["link"]
            )
        )

        analysis = analyze_with_gemini(
            title,
            content
        )

        tanggal = (
            article.get("tanggal", "")
            or item.get("tanggal_awal", "")
        )

        final_link = article.get(
            "url_final",
            item["link"]
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
                final_link,

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

                # Simpan berita yang dinyatakan relevan oleh AI.
                if result["relevan"]:
                    save_news(result)

            except Exception as e:

                logger.exception(
                    "Gagal memproses artikel: %s",
                    e,
                )

            processed += 1

            progress.progress(
                processed / total
            )

    progress.empty()

    try:
        conn = get_connection()
        total_saved = conn.execute(
            "SELECT COUNT(*) FROM berita WHERE relevan = 1"
        ).fetchone()[0]
        conn.close()
    except Exception:
        total_saved = 0

    if total_saved > 0:
        st.success(
            f"✅ Selesai. Database sekarang memiliki "
            f"{total_saved:,} berita ekonomi."
        )
    else:
        st.warning(
            "⚠️ Kandidat berita ditemukan, tetapi belum ada "
            "berita yang tersimpan. Buka 'Detail proses scraping' "
            "dan periksa app.log."
        )


# ============================================================
# 📌 LOAD DATA & SIDEBAR CONTROL
# ============================================================

# Data utama dashboard sekarang berasal dari SQLite,
# bukan dari CSV/sample data lama.
if "data" not in st.session_state:
    st.session_state.data = load_database()

with st.sidebar:
    if BPS_LOGO.exists():
        st.image(BPS_LOGO_URL, width=120)

    st.title("Dashboard Control")

    if gemini_client is not None:
        st.success("🟢 Gemini AI: Active")
    else:
        st.warning("🟡 Gemini AI: Offline — cek GEMINI_API_KEY di Secrets")

    st.divider()
    st.subheader("⚙️ Aksi")

    if st.button(
        "🔄 Ambil Berita Terbaru",
        use_container_width=True
    ):
        process_news()
        st.session_state.data = load_database()
        st.rerun()

    if st.button(
        "🗑️ Reset Database",
        use_container_width=True
    ):
        conn = get_connection()
        conn.execute("DELETE FROM berita")
        conn.commit()
        conn.close()

        st.session_state.data = load_database()
        st.success("Database berhasil dikosongkan.")
        st.rerun()

    st.divider()
    st.subheader("🔎 Filter Data")

# Ambil data terbaru dari database
df = load_database()

# Samakan nama kolom database dengan nama kolom dashboard
if not df.empty:
    df = df.rename(columns={
        "id": "ID",
        "tanggal": "Tanggal Berita",
        "media": "Media",
        "judul": "Judul Berita",
        "isu_ekonomi": "Isu Ekonomi",
        "sektor": "Sektor",
        "ringkasan": "Ringkasan Berita",
        "link": "Link Berita"
    })

    # Normalisasi tanggal secara aman.
    # utc=True mencegah kolom menjadi object jika sumber berita
    # memiliki format/zona waktu yang berbeda-beda.
    df["Tanggal Berita"] = pd.to_datetime(
        df["Tanggal Berita"],
        errors="coerce",
        utc=True
    )

    # Hilangkan timezone setelah konversi agar aman digunakan
    # dengan .dt.date, .dt.day_name(), resample, dll.
    try:
        df["Tanggal Berita"] = (
            df["Tanggal Berita"]
            .dt.tz_convert(None)
        )
    except Exception:
        pass
else:
    df = pd.DataFrame(columns=[
        "ID",
        "Tanggal Berita",
        "Media",
        "Judul Berita",
        "Isu Ekonomi",
        "Sektor",
        "Ringkasan Berita",
        "Link Berita"
    ])

with st.sidebar:
    if not df.empty:
        valid_dates = df["Tanggal Berita"].dropna()

        if not valid_dates.empty:
            min_date = valid_dates.min().date()
            max_date = valid_dates.max().date()
        else:
            min_date = datetime.now().date()
            max_date = datetime.now().date()
    else:
        min_date = datetime.now().date()
        max_date = datetime.now().date()

    date_range = st.date_input(
        "📅 Periode Berita",
        value=(min_date, max_date)
    )

    media_values = sorted(
        df["Media"].dropna().astype(str).unique().tolist()
    )

    sector_values = sorted(
        df["Sektor"].dropna().astype(str).unique().tolist()
    )

    issue_values = sorted(
        df["Isu Ekonomi"].dropna().astype(str).unique().tolist()
    )

    selected_media = st.multiselect(
        "🌐 Media",
        media_values
    )

    selected_sector = st.multiselect(
        "🏭 Sektor Lapangan Usaha",
        sector_values
    )

    selected_issue = st.multiselect(
        "📊 Isu Ekonomi",
        issue_values
    )

    keyword = st.text_input(
        "🔎 Cari kata kunci",
        placeholder="Ketik kata kunci..."
    )

# ============================================================
# FILTER DATA
# ============================================================

filtered = df.copy()

if len(date_range) == 2 and not filtered.empty:
    # Pastikan tetap datetime setelah proses filter
    filtered["Tanggal Berita"] = pd.to_datetime(
        filtered["Tanggal Berita"],
        errors="coerce",
        utc=True
    ).dt.tz_convert(None)

    start_date = pd.Timestamp(date_range[0])
    end_date = pd.Timestamp(date_range[1]) + pd.Timedelta(days=1)

    filtered = filtered[
        (filtered["Tanggal Berita"] >= start_date)
        &
        (filtered["Tanggal Berita"] < end_date)
    ]

if selected_media:
    filtered = filtered[
        filtered["Media"].isin(selected_media)
    ]

if selected_sector:
    filtered = filtered[
        filtered["Sektor"].isin(selected_sector)
    ]

if selected_issue:
    filtered = filtered[
        filtered["Isu Ekonomi"].isin(selected_issue)
    ]

if keyword:
    search_text = keyword.lower().strip()

    if search_text:
        search_columns = [
            "Judul Berita",
            "Isu Ekonomi",
            "Sektor",
            "Ringkasan Berita"
        ]

        mask = pd.Series(
            False,
            index=filtered.index
        )

        for column in search_columns:
            mask = (
                mask
                |
                filtered[column]
                .fillna("")
                .astype(str)
                .str.lower()
                .str.contains(
                    search_text,
                    regex=False,
                    na=False
                )
            )

        filtered = filtered[mask]

# ============================================================
# 📌 TAMPILAN DASHBOARD UTAMA
# ============================================================
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

# ============================================================
# KPI
# ============================================================

# Pastikan kolom tanggal selalu bertipe datetime sebelum memakai .dt
if not filtered.empty:
    filtered["Tanggal Berita"] = pd.to_datetime(
        filtered["Tanggal Berita"],
        errors="coerce",
        utc=True
    ).dt.tz_convert(None)

    valid_filtered_dates = filtered["Tanggal Berita"].dropna()

    if not valid_filtered_dates.empty:
        today_count = int(
            valid_filtered_dates.dt.normalize()
            .eq(pd.Timestamp(datetime.now().date()))
            .sum()
        )
    else:
        today_count = 0
else:
    today_count = 0

k1, k2, k3, k4 = st.columns(4)

k1.metric(
    "📰 Total Berita",
    f"{len(filtered):,}"
)

k2.metric(
    "📅 Berita Hari Ini",
    f"{today_count:,}"
)

k3.metric(
    "🌐 Sumber Media",
    f"{filtered['Media'].nunique():,}"
)

k4.metric(
    "🏭 Sektor Terpantau",
    f"{filtered['Sektor'].nunique():,}"
)

st.markdown("<br>", unsafe_allow_html=True)


# ============================================================
# DASHBOARD GRAFIK & TREND
# ============================================================

if not filtered.empty:

    st.markdown(
        '<div class="section-header">📊 Ringkasan Visual & Tren Berita</div>',
        unsafe_allow_html=True
    )

    # --------------------------------------------------------
    # SIAPKAN DATA TANGGAL
    # --------------------------------------------------------

    chart_df = filtered.copy()

    chart_df["Tanggal Berita"] = pd.to_datetime(
        chart_df["Tanggal Berita"],
        errors="coerce",
        utc=True
    ).dt.tz_convert(None)

    chart_df = chart_df.dropna(
        subset=["Tanggal Berita"]
    )

    # --------------------------------------------------------
    # BARIS 1: SEKTOR + MEDIA
    # --------------------------------------------------------

    col1, col2 = st.columns(2)

    with col1:

        sector_df = (
            filtered["Sektor"]
            .fillna("Tidak Teridentifikasi")
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
            color="Jumlah",
            color_continuous_scale="Blues",
            title="🏭 Sebaran Berita Berdasarkan 17 Sektor BPS"
        )

        fig_sector.update_layout(
            height=500,
            showlegend=False,
            yaxis={
                "categoryorder":
                "total ascending"
            },
            margin=dict(
                l=10,
                r=10,
                t=60,
                b=10
            )
        )

        st.plotly_chart(
            fig_sector,
            use_container_width=True
        )

    with col2:

        media_df = (
            filtered["Media"]
            .fillna("Media Tidak Diketahui")
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
            title="🌐 Proporsi Berita Berdasarkan Media"
        )

        fig_media.update_layout(
            height=500,
            margin=dict(
                l=10,
                r=10,
                t=60,
                b=10
            )
        )

        st.plotly_chart(
            fig_media,
            use_container_width=True
        )


    # --------------------------------------------------------
    # TREND HARIAN
    # --------------------------------------------------------

    if not chart_df.empty:

        daily_trend = (
            chart_df
            .assign(
                Tanggal=chart_df[
                    "Tanggal Berita"
                ].dt.date
            )
            .groupby("Tanggal")
            .size()
            .reset_index(
                name="Jumlah Berita"
            )
        )

        fig_daily = px.line(
            daily_trend,
            x="Tanggal",
            y="Jumlah Berita",
            markers=True,
            title="📈 Tren Harian Berita Ekonomi Lamongan"
        )

        fig_daily.update_layout(
            height=350,
            hovermode="x unified",
            xaxis_title="Tanggal",
            yaxis_title="Jumlah Berita"
        )

        st.plotly_chart(
            fig_daily,
            use_container_width=True
        )


    # --------------------------------------------------------
    # TREND MINGGUAN
    # --------------------------------------------------------

    if not chart_df.empty:

        weekly_trend = (
            chart_df
            .set_index("Tanggal Berita")
            .resample("W-MON")
            .size()
            .reset_index(
                name="Jumlah Berita"
            )
        )

        weekly_trend["Minggu"] = (
            weekly_trend[
                "Tanggal Berita"
            ].dt.strftime(
                "%d %b %Y"
            )
        )

        fig_weekly = px.bar(
            weekly_trend,
            x="Minggu",
            y="Jumlah Berita",
            text="Jumlah Berita",
            title="📅 Tren Mingguan Volume Berita"
        )

        fig_weekly.update_layout(
            height=350,
            xaxis_title="Minggu",
            yaxis_title="Jumlah Berita"
        )

        st.plotly_chart(
            fig_weekly,
            use_container_width=True
        )


    # --------------------------------------------------------
    # TREND BULANAN
    # --------------------------------------------------------

    if not chart_df.empty:

        monthly_trend = (
            chart_df
            .set_index("Tanggal Berita")
            .resample("MS")
            .size()
            .reset_index(
                name="Jumlah Berita"
            )
        )

        monthly_trend["Bulan"] = (
            monthly_trend[
                "Tanggal Berita"
            ].dt.strftime(
                "%b %Y"
            )
        )

        fig_monthly = px.area(
            monthly_trend,
            x="Bulan",
            y="Jumlah Berita",
            markers=True,
            title="📆 Tren Bulanan Berita Ekonomi"
        )

        fig_monthly.update_layout(
            height=350,
            xaxis_title="Bulan",
            yaxis_title="Jumlah Berita"
        )

        st.plotly_chart(
            fig_monthly,
            use_container_width=True
        )


    # --------------------------------------------------------
    # TREND SEKTOR DARI WAKTU KE WAKTU
    # --------------------------------------------------------

    if not chart_df.empty:

        sector_time = (
            chart_df
            .assign(
                Tanggal=chart_df[
                    "Tanggal Berita"
                ].dt.date
            )
            .groupby(
                ["Tanggal", "Sektor"]
            )
            .size()
            .reset_index(
                name="Jumlah Berita"
            )
        )

        fig_sector_time = px.line(
            sector_time,
            x="Tanggal",
            y="Jumlah Berita",
            color="Sektor",
            markers=True,
            title="🏭 Tren Berita Berdasarkan Sektor BPS"
        )

        fig_sector_time.update_layout(
            height=500,
            hovermode="x unified",
            xaxis_title="Tanggal",
            yaxis_title="Jumlah Berita",
            legend_title="Sektor"
        )

        st.plotly_chart(
            fig_sector_time,
            use_container_width=True
        )


    # --------------------------------------------------------
    # TREND ISU EKONOMI
    # --------------------------------------------------------

    issue_df = (
        filtered["Isu Ekonomi"]
        .fillna("Ekonomi Umum")
        .value_counts()
        .head(15)
        .reset_index()
    )

    issue_df.columns = [
        "Isu Ekonomi",
        "Jumlah"
    ]

    fig_issue = px.bar(
        issue_df,
        x="Jumlah",
        y="Isu Ekonomi",
        orientation="h",
        text="Jumlah",
        color="Jumlah",
        color_continuous_scale="Blues",
        title="💡 15 Isu Ekonomi yang Paling Banyak Diberitakan"
    )

    fig_issue.update_layout(
        height=500,
        yaxis={
            "categoryorder":
            "total ascending"
        },
        showlegend=False
    )

    st.plotly_chart(
        fig_issue,
        use_container_width=True
    )

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
    exp_df["Tanggal Berita"] = pd.to_datetime(
        exp_df["Tanggal Berita"],
        errors="coerce",
        utc=True
    ).dt.tz_convert(None).dt.strftime("%Y-%m-%d")
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

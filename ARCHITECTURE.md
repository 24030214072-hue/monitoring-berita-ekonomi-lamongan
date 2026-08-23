# Arsitektur & Alur Kerja — Monitoring Berita Ekonomi Lamongan

Dokumen ini menjelaskan **bagaimana kode bekerja dari dalam** — untuk developer baru yang ingin memahami, memodifikasi, atau men-debug aplikasi.

---

## Daftar Isi

1. [Gambaran Umum](#1-gambaran-umum)
2. [Struktur Modul](#2-struktur-modul)
3. [Alur Data End-to-End](#3-alur-data-end-to-end)
4. [Penjelasan Tiap Modul](#4-penjelasan-tiap-modul)
5. [Skema Database](#5-skema-database)
6. [Sistem Fingerprint & Deduplikasi](#6-sistem-fingerprint--deduplikasi)
7. [Sistem Multi-Tahun](#7-sistem-multi-tahun)
8. [Klasifikasi: Gemini vs Rules](#8-klasifikasi-gemini-vs-rules)
9. [Antrean Kandidat & Persistensi](#9-antrean-kandidat--persistensi)
10. [Cara Menambah Fitur Baru](#10-cara-menambah-fitur-baru)

---

## 1. Gambaran Umum

Aplikasi ini adalah **dashboard Streamlit** yang secara manual (dipicu oleh tombol) mencari, memproses, dan menyimpan berita ekonomi Kabupaten Lamongan. Data tersimpan di SQLite dan ditampilkan melalui filter, grafik, dan ekspor Excel.

```
Pengguna klik tombol
        │
        ▼
  NewsPipeline.run()
        │
   ┌────┴────┐
   │         │
   ▼         ▼
RSSDiscovery  (ambil antrean lama dari DB)
   │
   ▼
NewsCandidate[] ──► upsert ke news_candidates (SQLite)
                          │
                          ▼
                  ArticleExtractor (ambil HTML)
                          │
                          ▼
                  GoogleNewsResolver (buka redirect)
                          │
                          ▼
                  NewsClassifier (Gemini / rules)
                          │
                          ▼
                  NewsArticle[] ──► upsert ke news_articles (SQLite)
                          │
                          ▼
                  app.py load_data() ──► DataFrame ──► UI
```

---

## 2. Struktur Modul

```
news_monitor/
├── config.py       — semua konstanta dan konfigurasi
├── models.py       — dataclass: NewsCandidate, NewsArticle, dll.
├── text.py         — utilitas teks: fingerprint, normalisasi, ringkasan
├── http.py         — session requests dengan User-Agent
├── discovery.py    — pencarian RSS dari Google News & Bing
├── resolver.py     — konversi URL Google News → URL penerbit asli
├── extractor.py    — pengambilan dan parsing isi artikel HTML
├── classifier.py   — klasifikasi Gemini AI + fallback rules
├── repository.py   — semua akses database SQLite
└── pipeline.py     — orkestrator: gabungkan semua langkah di atas
app.py              — UI Streamlit + pemanggil pipeline
```

---

## 3. Alur Data End-to-End

### Fase 1 — Discovery (Penemuan Kandidat)

```
config.SEARCH_TOPICS (19 topik)
    × 2 provider (Google News RSS, Bing News RSS)
    × 1 bulan dipilih
    = hingga 38 HTTP request paralel (DISCOVERY_WORKERS=6)
         │
         ▼
  RSSDiscovery._fetch_feed()
         │
         ▼
  parse tanggal, judul, URL, sumber media
         │
  filter: published_at.year >= START_YEAR
  filter: tanggal dalam window bulan dipilih
         │
  deduplikasi per URL, lalu per title_fingerprint
         │
         ▼
  list[NewsCandidate]
         │
         ▼
  repository.upsert_candidates()  ──► tabel news_candidates
```

### Fase 2 — Extraction (Pengambilan Isi Artikel)

```
repository.pending_candidates(limit=80, year, month)
         │
         ▼
  ArticleExtractor.extract()  [paralel, EXTRACTION_WORKERS=6]
         │
    GoogleNewsResolver.resolve()
    │   URL bukan Google News? → langsung pakai
    │   URL Google News?
    │     → GET halaman → ambil data-n-a-sg + data-n-a-ts
    │     → POST ke batchexecute → parse garturlres → URL penerbit
         │
         ▼
  HTTP GET ke URL penerbit
         │
  BeautifulSoup: pilih elemen article/main/[itemprop]/dll.
  Fallback: semua <p>, lalu <meta description>
         │
  filter: panjang teks >= 200 karakter
         │
         ▼
  ExtractionResult(resolved_url, content, success=True)
```

### Fase 3 — Classification (Klasifikasi & Ringkasan)

```
list[(title, content)]  ──► NewsClassifier.classify_many()
         │
    Rules check dulu (selalu):
    │  normalize(title + content)
    │  "lamongan" harus ada
    │  setidaknya 1 sektor cocok dengan SECTOR_RULES
    │  setidaknya 2 ECONOMIC_TERMS cocok (atau ada di judul)
    │
    Jika lolos rules DAN Gemini tersedia:
    │  kirim batch ke Gemini (8 artikel/batch)
    │  prompt: JSON array artikel → JSON array hasil
    │  structured output (response_format + schema)
    │  retry 3x jika HTTP 429
    │
    Hasil: AnalysisResult(is_economic, issue, sector, summary, reason, source)
         │
         ▼
  filter: is_economic=True DAN published_at.year == search_year
         │
  _deduplicate_similar(): Jaccard similarity judul >= 0.72 → buang
         │
         ▼
  list[NewsArticle]  ──► repository.upsert()  ──► tabel news_articles
```

### Fase 4 — Display (Tampilan UI)

```
app.py load_data(year)
    → repository.load_dataframe(year)
    → SELECT * WHERE published_at BETWEEN {year}-01-01 AND {year+1}-01-01
    → pd.DataFrame
         │
  filter sidebar: tanggal, media, sektor, isu, keyword
         │
  charts: px.bar (sektor), px.pie (media), px.area (tren waktu)
  table: st.dataframe dengan LinkColumn
  export: openpyxl → BytesIO → st.download_button
```

---

## 4. Penjelasan Tiap Modul

### `config.py`

Satu-satunya tempat konstanta. Ubah di sini, efeknya menyebar ke seluruh sistem.

| Konstanta | Default | Keterangan |
|---|---|---|
| `START_YEAR` | `2026` | Tahun paling awal yang diizinkan masuk DB |
| `MAX_RESULTS_PER_QUERY` | `25` | Batas entry RSS per request |
| `MAX_CANDIDATES` | `1000` | Batas total kandidat per discovery run |
| `MAX_ARTICLES_TO_ANALYZE` | `80` | Batas kandidat yang diproses per klik tombol |
| `DISCOVERY_WORKERS` | `6` | Thread pool untuk RSS fetch paralel |
| `EXTRACTION_WORKERS` | `6` | Thread pool untuk artikel fetch paralel |
| `MAX_CANDIDATE_ATTEMPTS` | `3` | Setelah 3x gagal, kandidat → status `failed` |
| `REQUEST_TIMEOUT` | `15` | Timeout HTTP dalam detik |
| `ARTICLE_MAX_CHARS` | `12000` | Maksimum karakter artikel yang dikirim ke Gemini |
| `GEMINI_MODEL` | `gemini-3.7-flash` | Model yang digunakan |
| `SEARCH_TOPICS` | 19 string | Query OR per sektor BPS untuk RSS |
| `SEKTOR_BPS` | 17 string | Label resmi 17 sektor lapangan usaha |

---

### `models.py`

Empat dataclass ringan (pakai `slots=True` untuk efisiensi memori):

```
NewsCandidate   — hasil discovery, belum diproses
NewsArticle     — artikel yang lolos klasifikasi, siap disimpan
ExtractionResult — hasil download HTML (URL sudah di-resolve)
AnalysisResult  — hasil klasifikasi (rules atau Gemini)
```

Tidak ada business logic di sini.

---

### `text.py`

Utilitas murni tanpa state:

- **`normalize_text()`** — lowercase, hapus karakter non-alphanumeric, collapse whitespace. Dipakai untuk perbandingan teks dan fingerprint.
- **`title_fingerprint()`** — SHA-256 dari `normalize_text(title)`. Dipakai untuk deduplikasi.
- **`news_fingerprint(title, published_at)`** — `"{year}:{title_fingerprint}"`. Ini adalah PRIMARY KEY di database (lihat Sistem Fingerprint).
- **`canonicalize_url()`** — Hapus parameter tracking (UTM, fbclid, dll.), lowercase scheme dan netloc.
- **`parse_feed_date()`** — Parse tanggal dari entry RSS (mendukung `published_parsed`, `updated_parsed`, atau string RFC 2822).
- **`extractive_summary()`** — Pilih 3 kalimat dari artikel yang paling relevan dengan judul (fallback jika Gemini tidak tersedia).

---

### `http.py`

Satu fungsi `build_session()` yang mengembalikan `requests.Session` dengan User-Agent sudah diset. Seluruh HTTP request di aplikasi ini melewati sini agar konsisten.

---

### `discovery.py` — `RSSDiscovery`

**Cara kerja:**

1. Untuk setiap topik di `SEARCH_TOPICS`, buat query: `Lamongan ({topik}) after:{start} before:{end}`
2. Kirim query itu ke **dua provider** sekaligus: Google News RSS dan Bing News RSS
3. Semua request dijalankan **paralel** (ThreadPoolExecutor, 6 worker)
4. Setiap batch hasil langsung di-callback ke `repository.upsert_candidates()` — jadi kalau proses dihentikan, kandidat yang sudah ditemukan tidak hilang
5. Deduplikasi dua lapis: pertama per URL, lalu per `title_fingerprint`

**Google News khusus:**
- Judul format `"Headline - Nama Media"` dipisah menjadi `title` dan `source`
- URL dari RSS bisa masih berupa wrapper `news.google.com/...` → diserahkan ke `resolver.py`

---

### `resolver.py` — `GoogleNewsResolver`

Google News RSS kadang memberikan URL wrapper seperti `https://news.google.com/rss/articles/CBMi...` yang harus di-decode ke URL penerbit asli.

**Cara kerja:**
1. GET halaman Google News → ambil `data-n-a-sg` (signature) dan `data-n-a-ts` (timestamp) dari HTML
2. POST ke endpoint internal Google (`batchexecute`) dengan payload khusus format `garturlreq`
3. Parse respons JSON berlapis → ekstrak URL di field `garturlres`

Jika URL sudah bukan domain Google News, fungsi ini langsung mengembalikan URL tersebut setelah di-canonicalize.

---

### `extractor.py` — `ArticleExtractor`

**Cara kerja:**
1. Panggil `resolver.resolve(url)` untuk dapat URL penerbit asli
2. GET halaman HTML penerbit
3. BeautifulSoup: hapus `<script>`, `<style>`, `<nav>`, `<footer>`, dll.
4. Coba selector prioritas tinggi satu per satu (`article`, `[itemprop='articleBody']`, class-class umum)
5. Jika tidak ada yang cocok: ambil semua `<p>` dari seluruh halaman
6. Fallback terakhir: `<meta name="description">`
7. Tolak jika teks < 200 karakter

Hasilnya dipotong di `ARTICLE_MAX_CHARS` (12.000 karakter) sebelum dikirim ke Gemini.

---

### `classifier.py` — `NewsClassifier`

Dua jalur klasifikasi, dijalankan secara hirarki:

**Jalur 1 — Rules (selalu jalan):**
```
normalize(title + content)
  → cek "lamongan" ada?
  → hitung skor tiap sektor dari SECTOR_RULES (keyword matching)
  → hitung hits dari ECONOMIC_TERMS (26 term gabungan semua sektor)
  → lolos jika: skor_sektor > 0 DAN (hits >= 2 ATAU ada term di judul)
  → pilih isu dari ISSUE_RULES
  → buat ringkasan extractive
```

**Jalur 2 — Gemini (jika tersedia dan artikel lolos rules):**
```
classify_many(articles, batch_size=8):
  → group 8 artikel per batch
  → kirim prompt JSON ke Gemini dengan response_format structured
  → retry 3x jika HTTP 429, delay sesuai header
  → jika error auth/quota: set _ai_disabled=True, lanjut dengan rules
  → hasil Gemini menimpa hasil rules untuk artikel yang eligible
```

Prompt Gemini meminta JSON array dengan field: `id`, `ekonomi`, `isu_ekonomi`, `sektor` (harus dari enum `SEKTOR_BPS`), `ringkasan`, `alasan`.

**Fallback otomatis:** Jika `_ai_disabled=True` (setelah error), semua artikel sisa diproses dengan rules. Tidak ada exception yang crash ke user.

---

### `repository.py` — `NewsRepository`

Satu-satunya lapisan yang boleh menyentuh SQLite. Semua operasi berjalan lewat context manager `_connect()` yang otomatis commit/rollback.

**Method penting:**

| Method | Keterangan |
|---|---|
| `upsert(articles)` | Simpan/update artikel lolos. PRIMARY KEY = fingerprint. |
| `upsert_candidates(candidates)` | Simpan kandidat ke antrean. Jika sudah ada, update `last_seen_at`. |
| `pending_candidates(limit, year, month)` | Ambil kandidat `status='pending'` untuk diproses. |
| `mark_candidates(states)` | Update status kandidat: `accepted`, `rejected`, `duplicate`, `retry`, `failed`. |
| `candidate_status_counts(year, month)` | Hitung kandidat per status (untuk metrik di UI). |
| `load_dataframe(year)` | SELECT artikel untuk tahun tertentu → pd.DataFrame. |
| `clear(year)` | Hapus artikel dan kandidat untuk tahun tertentu. |

**Migrasi otomatis di `_initialize()`:**
Saat pertama kali dijalankan (atau setelah update), dua UPDATE dijalankan untuk memastikan semua fingerprint lama (tanpa prefix tahun) diupgrade ke format `{year}:{hash}`.

---

### `pipeline.py` — `NewsPipeline`

Orkestrator yang menggabungkan semua modul. Satu-satunya titik masuk dari `app.py`:

```python
pipeline.run(progress_callback, search_year, search_month)
```

**Urutan eksekusi:**
1. Cek antrean sudah penuh (`>= MAX_ARTICLES_TO_ANALYZE`) → skip discovery, langsung proses
2. Kalau antrean belum penuh → jalankan `RSSDiscovery.discover()`
3. Ambil `pending_candidates(80, year, month)` dari DB
4. Ekstraksi paralel (`_extract_parallel`)
5. Klasifikasi batch (`classifier.classify_many`)
6. Filter: `is_economic=True` DAN `published_at.year == search_year`
7. Deduplikasi kemiripan judul (Jaccard >= 0.72)
8. Simpan ke DB, update status kandidat
9. Kembalikan `PipelineReport` (statistik lengkap)

---

### `app.py`

Streamlit app. Kode berjalan **dari atas ke bawah** setiap kali ada interaksi user.

**Urutan rendering:**
```
1.  CSS global + konfigurasi halaman
2.  Inisialisasi session_state (active_year, data, gemini_error)
3.  Status Gemini (hijau/kuning/merah)
4.  Selectbox tahun + bulan
5.  Metrik 4 kolom (berita, antrean, ditolak, bulan)
6.  Pesan info antrean
7.  Tombol "Cari & Proses Berita" → panggil pipeline.run()
8.  Expander "Pemeliharaan Data" (reset per tahun)
9.  Sidebar filter (tanggal, media, sektor, isu, keyword)
10. Header dashboard (logo + banner gradien)
11. KPI card 4 kolom
12. Grafik (bar sektor, pie media, area tren)
13. Tabel berita terfilter
14. Tombol ekspor Excel
15. Expander "Test Gemini AI" (alat debug)
16. Footer
```

**State penting di `st.session_state`:**

| Key | Tipe | Keterangan |
|---|---|---|
| `monitor_year` | `int` | Tahun yang sedang dipilih di selectbox |
| `data` | `pd.DataFrame` | Data artikel tahun aktif (cache UI) |
| `data_year` | `int` | Tahun dari `data` (untuk invalidasi cache) |
| `gemini_error` | `str` | Error terakhir dari Gemini (untuk indikator status) |

---

## 5. Skema Database

File: `berita_lamongan.db` (SQLite, mode WAL)

### Tabel `news_articles`

```sql
CREATE TABLE news_articles (
    fingerprint   TEXT PRIMARY KEY,   -- "{year}:{sha256(normalize(title))}"
    published_at  TEXT NOT NULL,       -- ISO 8601, e.g. "2026-08-01T10:00:00"
    media         TEXT NOT NULL,       -- nama sumber media
    title         TEXT NOT NULL,       -- judul artikel
    issue         TEXT NOT NULL,       -- isu ekonomi (dari classifier)
    sector        TEXT NOT NULL,       -- sektor BPS (dari classifier)
    summary       TEXT NOT NULL,       -- ringkasan 2-3 kalimat
    url           TEXT NOT NULL,       -- URL penerbit (sudah di-resolve)
    content       TEXT NOT NULL,       -- isi artikel (maks 12.000 karakter)
    reason        TEXT NOT NULL,       -- alasan klasifikasi dari AI
    updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
```

Index: `idx_news_articles_date` pada `published_at`.

### Tabel `news_candidates`

```sql
CREATE TABLE news_candidates (
    fingerprint       TEXT PRIMARY KEY,
    published_at      TEXT NOT NULL,
    media             TEXT NOT NULL,
    title             TEXT NOT NULL,
    url               TEXT NOT NULL,
    summary           TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',
    -- nilai: 'pending' | 'accepted' | 'rejected' | 'duplicate' | 'failed' | 'retry'
    attempts          INTEGER NOT NULL DEFAULT 0,
    last_error        TEXT NOT NULL DEFAULT '',
    first_seen_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_attempted_at TEXT
)
```

Index: `idx_news_candidates_queue` pada `(status, attempts, published_at)`.

### Tabel `crawl_state`

```sql
CREATE TABLE crawl_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
```

Saat ini menyimpan satu row: `key='backfill_month'` untuk melacak posisi bulan backfill.

---

## 6. Sistem Fingerprint & Deduplikasi

### Fingerprint

```
news_fingerprint(title, published_at)
  = f"{published_at.year}:{sha256(normalize_text(title))}"
```

Contoh hasil: `"2026:a3f8c2d1e9b4..."`

- **Mengapa menyertakan tahun?** Agar artikel dengan judul yang sama di tahun berbeda tidak saling menimpa di database.
- **Mengapa berdasarkan judul bukan URL?** URL bisa berubah (redirect, CDN, parameter), tapi judul artikel lebih stabil.

### Deduplikasi Berlapis

| Lapisan | Tempat | Metode |
|---|---|---|
| Per URL | `RSSDiscovery._deduplicate()` | Exact match URL canonical |
| Per judul | `RSSDiscovery._deduplicate()` | `title_fingerprint` hash |
| Per kemiripan judul | `NewsPipeline._deduplicate_similar()` | Jaccard similarity token >= 0.72 |
| Primary key DB | SQLite | `ON CONFLICT(fingerprint) DO UPDATE` |

---

## 7. Sistem Multi-Tahun

Aplikasi dirancang agar berfungsi untuk tahun **2026 dan seterusnya** tanpa perubahan kode:

- `START_YEAR = 2026` di `config.py` → semua validasi mengacu ke sini
- UI otomatis menampilkan `range(START_YEAR, datetime.now().year + 1)` → tahun baru muncul sendiri saat Januari tiba
- Semua query DB memakai `WHERE published_at >= '{year}-01-01' AND published_at < '{year+1}-01-01'`
- Fingerprint menyertakan tahun → tidak ada tabrakan lintas tahun
- Reset, ekspor, filter, grafik, dan antrean semuanya di-scope per tahun

**Untuk menambah data tahun baru:** Cukup pilih tahun baru di selectbox → klik tombol scan. Tidak perlu migrasi atau perubahan kode apapun.

---

## 8. Klasifikasi: Gemini vs Rules

```
Setiap artikel masuk:

  Rules filter (gate)
       │
       ├── Tidak lolos → status 'rejected', tidak masuk DB artikel
       │
       └── Lolos
               │
               ├── Gemini tidak tersedia → gunakan ringkasan extractive (rules)
               │
               └── Gemini tersedia → kirim ke API
                           │
                           ├── Gemini menolak → status 'rejected'
                           │
                           └── Gemini lolos → simpan dengan source="gemini"
```

**Kenapa rules dulu, bukan Gemini dulu?**
- Hemat kuota API — hanya artikel yang sudah pasti relevan yang dikirim ke Gemini
- Gemini tidak bisa menjadi single point of failure; rules menjamin aplikasi selalu bisa berjalan

---

## 9. Antrean Kandidat & Persistensi

```
Klik pertama (bulan kosong):
  Discovery → temukan 300 kandidat → simpan ke DB sebagai 'pending'
  Ambil 80 pertama → proses → simpan hasil
  Sisa 220 tetap 'pending' di DB

Klik kedua (bulan sama):
  Antrean 220 masih ada → skip discovery → langsung proses 80 berikutnya

Klik ketiga, keempat, ... sampai antrean habis

Gagal ekstraksi (jaringan, paywall, dll.):
  status = 'retry', attempts += 1
  Jika attempts >= MAX_CANDIDATE_ATTEMPTS (3) → status = 'failed'
  Failed tidak diproses ulang (kecuali di-reset manual)
```

**Restart Streamlit tidak menghilangkan progres** — kandidat tetap tersimpan di SQLite.

---

## 10. Cara Menambah Fitur Baru

### Menambah sumber RSS baru

Edit [`discovery.py`](news_monitor/discovery.py) → tambah method `_new_provider()` → panggil dari `_search()`.

### Menambah sektor atau isu baru

Edit [`config.py`](news_monitor/config.py) → tambah ke `SEKTOR_BPS` dan/atau `SEARCH_TOPICS`.
Edit [`classifier.py`](news_monitor/classifier.py) → tambah ke `SECTOR_RULES` dan/atau `ISSUE_RULES`.

### Mengubah model Gemini

Edit `GEMINI_MODEL` di [`config.py`](news_monitor/config.py). Tidak ada perubahan lain yang diperlukan.

### Menambah kolom ke tabel berita

1. Tambah field di dataclass `NewsArticle` ([`models.py`](news_monitor/models.py))
2. Tambah kolom di `CREATE TABLE` ([`repository.py`](news_monitor/repository.py)) — tambahkan `ALTER TABLE` jika DB sudah ada
3. Tambah ke `ALL_COLUMNS` dan/atau `UI_COLUMNS` ([`config.py`](news_monitor/config.py))
4. Isi dari classifier atau extractor sesuai kebutuhan

### Menambah grafik baru di UI

Edit [`app.py`](app.py) di bagian setelah `if not filtered.empty:` — DataFrame `filtered` sudah siap dipakai, semua kolom `UI_COLUMNS` tersedia.

### Mengubah batas per-run

Ubah `MAX_ARTICLES_TO_ANALYZE` di [`config.py`](news_monitor/config.py). Nilai lebih tinggi = lebih banyak artikel per klik tapi lebih lama dan lebih boros kuota Gemini.

---

*Dokumen ini mencerminkan kondisi kode per Agustus 2026. Update dokumen ini jika ada perubahan arsitektur yang signifikan.*

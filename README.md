# Monitoring Berita Ekonomi Lamongan

Dashboard Streamlit untuk menemukan, membaca, mengklasifikasikan, dan merangkum berita ekonomi Kabupaten Lamongan yang terbit pada tahun 2026. Artikel dikelompokkan ke dalam 17 sektor lapangan usaha BPS dan dapat diekspor ke Excel.

## Fitur

- Pencarian berita Lamongan melalui RSS Google News dan Bing News.
- Filter ketat berdasarkan tahun publikasi 2026.
- Resolusi tautan Google News ke halaman media asli.
- Ekstraksi isi artikel dari halaman penerbit.
- Klasifikasi isu ekonomi dan 17 sektor lapangan usaha BPS.
- Ringkasan 2–3 kalimat menggunakan Gemini AI.
- Ringkasan extractive fallback jika Gemini tidak tersedia atau mencapai kuota.
- Deteksi status Gemini: aktif, kredensial salah, atau rate limit tercapai.
- Deduplikasi berdasarkan judul dan kemiripan berita.
- Penyimpanan transaksi menggunakan SQLite.
- Filter tanggal, media, sektor, isu, dan kata kunci.
- Grafik sektor, media, dan tren berita.
- Ekspor laporan terfilter ke Excel.

## Persyaratan

- Python 3.11 atau lebih baru.
- Koneksi internet untuk pencarian berita, pengambilan artikel, dan Gemini.
- Gemini API key dari [Google AI Studio](https://aistudio.google.com/apikey) untuk ringkasan AI.

Aplikasi tetap dapat berjalan tanpa Gemini, tetapi akan menggunakan klasifikasi dan ringkasan fallback.

## Struktur Proyek

```text
monitoring-ekonomi-lamongan/
├── app.py
├── requirements.txt
├── logo_bps.png
├── news_monitor/
│   ├── classifier.py
│   ├── config.py
│   ├── discovery.py
│   ├── extractor.py
│   ├── pipeline.py
│   ├── repository.py
│   ├── resolver.py
│   └── text.py
├── tests/
└── .streamlit/
    └── secrets.toml.example
```

## Instalasi di Windows

### 1. Buka folder proyek

PowerShell:

```powershell
cd C:\path\ke\monitoring-ekonomi-lamongan
```

### 2. Buat virtual environment

```powershell
py -m venv .venv
```

### 3. Instal dependensi

Aktivasi virtual environment bersifat opsional. Cara berikut tidak membutuhkan aktivasi:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 4. Atur Gemini API key

Salin template:

```powershell
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
```

Edit `.streamlit/secrets.toml`:

```toml
GEMINI_API_KEY = "AQ.ganti-dengan-key-anda"
```

Key authorization baru dapat diawali `AQ.`. Standard key lama dapat diawali `AIza`.

### 5. Jalankan aplikasi

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Buka `http://localhost:8501` jika browser tidak terbuka otomatis.

## Instalasi di macOS atau Linux

```bash
cd /path/ke/monitoring-ekonomi-lamongan
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Edit `.streamlit/secrets.toml`, lalu jalankan:

```bash
python -m streamlit run app.py
```

## Cara Mendapatkan Gemini API Key

1. Buka [Google AI Studio API Keys](https://aistudio.google.com/apikey).
2. Masuk dengan akun Google.
3. Buat atau pilih project.
4. Klik **Create API key**.
5. Salin key ke `.streamlit/secrets.toml`.
6. Jangan membagikan atau memasukkan key ke Git.
7. Restart Streamlit setelah mengganti key.

Aplikasi juga menerima nama secret `GOOGLE_API_KEY`:

```toml
GOOGLE_API_KEY = "AQ.ganti-dengan-key-anda"
```

## Cara Menggunakan Dashboard

### Test Analisis Gemini

Gunakan bagian **Test Gemini AI** untuk memastikan autentikasi dan model bekerja. Hasil yang menggunakan AI akan berisi:

```json
{
  "sumber_klasifikasi": "gemini"
}
```

Jika nilainya `rules`, aplikasi menggunakan fallback.

### Ambil Berita Terbaru

Tombol **Ambil Berita Terbaru** menjalankan proses berikut:

1. Mencari berita Lamongan tahun 2026.
2. Menghapus kandidat duplikat.
3. Mengubah tautan Google News menjadi tautan media asli.
4. Mengambil isi artikel dari halaman penerbit.
5. Menolak artikel yang tidak memiliki isi memadai.
6. Memeriksa relevansi ekonomi Lamongan.
7. Menganalisis artikel dengan Gemini dalam batch.
8. Membuat isu, sektor BPS, dan ringkasan.
9. Menggunakan fallback jika Gemini tidak tersedia.
10. Menyimpan atau memperbarui hasil di SQLite.
11. Memuat ulang data tabel, grafik, dan ekspor Excel.

Setelah selesai, UI menampilkan jumlah berita yang dianalisis Gemini dan jumlah yang menggunakan fallback.

### Status Gemini

- **Hijau — Active:** key terdeteksi dan tidak ada error terakhir.
- **Kuning — Rate limit:** kuota sementara tercapai. Aplikasi tetap berjalan dengan fallback dan menampilkan estimasi waktu tunggu jika tersedia.
- **Merah — Offline:** key hilang, format tidak dikenali, atau terjadi error autentikasi/API.

Pantau kuota di [Gemini API Rate Limits](https://ai.dev/rate-limit).

### Reset Data

Tombol **Reset & Bersihkan Data** menghapus semua berita dari database lokal. Tindakan ini tidak dapat dibatalkan.

### Ekspor Excel

Excel dibuat langsung dari data yang sedang tampil setelah filter diterapkan. Karena tabel dan Excel menggunakan DataFrame yang sama, nilai `Ringkasan Berita` pada keduanya akan sama.

## Penyimpanan Data

Data aplikasi disimpan di:

```text
berita_lamongan.db
```

Database menggunakan SQLite dan dibuat otomatis ketika aplikasi pertama kali berjalan. Jangan membagikan database jika berisi data yang tidak boleh dipublikasikan.

## Menjalankan Test

Windows:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

macOS/Linux:

```bash
python -m unittest discover -s tests -v
```

## Troubleshooting

### `ModuleNotFoundError`

Pastikan dependensi dipasang menggunakan interpreter virtual environment yang sama dengan perintah Streamlit:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Gemini menampilkan `rules`

Periksa:

- API key sudah berada di `.streamlit/secrets.toml`.
- Streamlit sudah direstart setelah key diganti.
- Status Gemini di UI.
- Kuota di `https://ai.dev/rate-limit`.

### Gemini menampilkan rate limit atau HTTP 429

Aplikasi akan menunggu dan mencoba ulang. Jika tetap gagal, artikel diproses menggunakan fallback. Tunggu sesuai pesan UI atau gunakan project dengan kuota/billing yang lebih tinggi.

### Berita tidak muncul

- Pastikan koneksi internet tersedia.
- Pastikan sumber RSS dapat diakses dari jaringan.
- Berita harus terbit pada tahun 2026.
- Artikel harus berkaitan dengan ekonomi Lamongan.
- Isi artikel harus dapat diambil dan memiliki panjang yang memadai.

### Ringkasan terlihat seperti judul

Restart aplikasi dan klik **Ambil Berita Terbaru**. Pipeline terbaru hanya menerima artikel dengan isi memadai dan menyimpan URL penerbit asli.

### Port 8501 sudah digunakan

Gunakan port lain:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8502
```

## Keamanan

- Jangan commit `.streamlit/secrets.toml`.
- Jangan mengirim API key melalui chat atau email.
- Rotasi key jika pernah terekspos.
- Gunakan billing alert jika project Gemini menggunakan paket berbayar.
- Untuk deployment, gunakan secret manager milik platform hosting.

Jika `secrets.toml` pernah masuk Git, hapus dari tracking sebelum commit berikutnya:

```bash
git rm --cached .streamlit/secrets.toml
```

Kemudian pastikan `.gitignore` sudah aktif.

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = BASE_DIR / "berita_lamongan.db"
LEGACY_CSV_PATH = BASE_DIR / "berita_lamongan.csv"
LOG_PATH = BASE_DIR / "app.log"
LOGO_PATH = BASE_DIR / "logo_bps.png"

TARGET_YEAR = 2026
MAX_RESULTS_PER_QUERY = 10
MAX_CANDIDATES = 80
MAX_ARTICLES_TO_ANALYZE = 80
REQUEST_TIMEOUT = 15
ARTICLE_MAX_CHARS = 12_000
GEMINI_MODEL = "gemini-3.7-flash"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36"
)

SEARCH_TOPICS = [
    "ekonomi",
    "pertanian perikanan peternakan",
    "industri UMKM koperasi",
    "perdagangan harga pasar inflasi",
    "investasi pembangunan konstruksi",
    "pariwisata hotel kuliner",
    "transportasi logistik energi",
    "tenaga kerja upah",
]

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

UI_COLUMNS = [
    "Tanggal Berita",
    "Media",
    "Judul Berita",
    "Isu Ekonomi",
    "Sektor",
    "Ringkasan Berita",
    "Link Berita",
]

ALL_COLUMNS = UI_COLUMNS + ["Isi Berita", "Alasan AI"]

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = BASE_DIR / "berita_lamongan.db"
LEGACY_CSV_PATH = BASE_DIR / "berita_lamongan.csv"
LOG_PATH = BASE_DIR / "app.log"
LOGO_PATH = BASE_DIR / "logo_bps.png"

START_YEAR = 2026
MAX_RESULTS_PER_QUERY = 25
MAX_CANDIDATES = 1_000
MAX_ARTICLES_TO_ANALYZE = 80
DISCOVERY_WORKERS = 6
EXTRACTION_WORKERS = 6
MAX_CANDIDATE_ATTEMPTS = 3
REQUEST_TIMEOUT = 15
ARTICLE_MAX_CHARS = 12_000
GEMINI_MODEL = "gemini-3.7-flash"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36"
)

# Focused query groups cover all 17 BPS business sectors. OR terms improve
# recall while the strict body extraction and classifier remain the quality gate.
SEARCH_TOPICS = [
    "ekonomi OR bisnis OR pendapatan",
    "pertanian OR petani OR panen OR pupuk",
    "perikanan OR nelayan OR tambak OR peternakan OR ternak",
    "tambang OR galian OR mineral",
    "industri OR pabrik OR manufaktur OR UMKM OR koperasi",
    "listrik OR PLN OR gas OR energi",
    "air bersih OR sampah OR limbah OR daur ulang",
    "konstruksi OR proyek OR infrastruktur OR jalan OR jembatan",
    "perdagangan OR pedagang OR pasar OR harga OR inflasi",
    "transportasi OR angkutan OR logistik OR pelabuhan OR kereta",
    "hotel OR penginapan OR restoran OR kuliner OR pariwisata",
    "internet OR digital OR telekomunikasi OR komunikasi",
    "bank OR kredit OR pembiayaan OR asuransi OR investasi",
    "properti OR perumahan OR real estat",
    "jasa perusahaan OR konsultan OR persewaan",
    "APBD OR pajak OR anggaran OR pendapatan daerah OR pengadaan",
    "pendidikan OR sekolah OR kampus OR kesehatan OR rumah sakit",
    "tenaga kerja OR pekerja OR upah OR pengangguran OR lowongan",
    "ekonomi kreatif OR seni OR hiburan OR jasa lainnya",
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

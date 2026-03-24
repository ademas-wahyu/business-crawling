# Menjalankan Project di Google Colab

Dokumen ini menjelaskan cara menjalankan project `business-crawling` sepenuhnya dalam mode **headless / CLI** di **Google Colab**.

## Ringkasan

Project ini sekarang ditujukan untuk dijalankan tanpa GUI. Alur eksekusi yang dipakai adalah:

- input lokasi dari `lokasi.txt`
- input keyword dari `kata-kunci.csv`
- crawler dijalankan lewat `maps-crawling.py`
- hasil disimpan ke folder `data/`
- state sementara disimpan ke folder `.state/`

## Catatan Penting

Menjalankan Selenium + Google Maps di Google Colab memiliki beberapa keterbatasan:

1. Session Colab bersifat sementara.
2. Google Maps bisa memunculkan CAPTCHA / blokir.
3. Browser harus berjalan dalam mode headless.
4. Chrome dan ChromeDriver harus disiapkan di environment Colab.
5. Jika runtime Colab restart, file lokal akan hilang kecuali disimpan ke Google Drive.

Karena itu, sangat disarankan untuk menyimpan project atau output ke Google Drive.

---

## Opsi 1 — Jalankan dari GitHub

Jika project ini ada di GitHub, cara paling mudah adalah clone langsung di Colab.

### 1. Buka Google Colab

Buat notebook baru.

### 2. Install dependency sistem dan Python

Jalankan cell berikut:

```bash
!apt-get update -y
!apt-get install -y wget unzip curl gnupg2
!apt-get install -y chromium-chromedriver
!pip install -r /content/business-crawling/requirements.txt
```

### 3. Clone repository

Ganti URL berikut dengan repository Anda:

```bash
!git clone https://github.com/USERNAME/REPO.git /content/business-crawling
```

Jika urutan install ingin aman, Anda juga bisa clone dulu lalu install:

```bash
!git clone https://github.com/USERNAME/REPO.git /content/business-crawling
!apt-get update -y
!apt-get install -y wget unzip curl gnupg2 chromium-chromedriver
!pip install -r /content/business-crawling/requirements.txt
```

### 4. Pastikan file input tersedia

Pastikan file berikut ada:

- `/content/business-crawling/lokasi.txt`
- `/content/business-crawling/kata-kunci.csv`
- `/content/business-crawling/niche_packs.json`

Jika ingin mengunggah file manual:

```python
from google.colab import files
uploaded = files.upload()
```

Setelah upload, pindahkan file ke folder project bila perlu.

Contoh:

```bash
!mv lokasi.txt /content/business-crawling/lokasi.txt
!mv kata-kunci.csv /content/business-crawling/kata-kunci.csv
```

### 5. Jalankan crawler

Masuk ke folder project lalu jalankan:

```bash
%cd /content/business-crawling
!python maps-crawling.py --hot-only
```

Atau contoh dengan parameter lengkap:

```bash
%cd /content/business-crawling
!python maps-crawling.py \
  --locations-file lokasi.txt \
  --keywords-csv kata-kunci.csv \
  --niche-path niche_packs.json \
  --data-dir data \
  --db-path data/lead_finder.db \
  --max-results 50 \
  --max-scrolls 30 \
  --stagnation-limit 5 \
  --scroll-pause 1.5 \
  --detail-pause 2.0 \
  --audit-timeout 8 \
  --audit-workers 5 \
  --audit-stale-days 14 \
  --max-retries 2 \
  --captcha-wait-seconds 120 \
  --error-wait-seconds 300 \
  --hot-only
```

---

## Opsi 2 — Jalankan dari Google Drive

Opsi ini lebih cocok kalau Anda ingin file input/output tidak hilang saat runtime Colab selesai.

### 1. Mount Google Drive

```python
from google.colab import drive
drive.mount('/content/drive')
```

### 2. Pindahkan atau clone project ke Drive

Contoh lokasi project:

```text
/content/drive/MyDrive/business-crawling
```

Jika belum ada, Anda bisa clone langsung ke sana:

```bash
!git clone https://github.com/USERNAME/REPO.git /content/drive/MyDrive/business-crawling
```

### 3. Install dependency

```bash
!apt-get update -y
!apt-get install -y wget unzip curl gnupg2 chromium-chromedriver
!pip install -r /content/drive/MyDrive/business-crawling/requirements.txt
```

### 4. Jalankan project

```bash
%cd /content/drive/MyDrive/business-crawling
!python maps-crawling.py --hot-only
```

Jika ingin output langsung masuk ke folder tertentu di Drive:

```bash
%cd /content/drive/MyDrive/business-crawling
!python maps-crawling.py \
  --data-dir /content/drive/MyDrive/business-crawling/data \
  --db-path /content/drive/MyDrive/business-crawling/data/lead_finder.db \
  --hot-only
```

---

## Struktur File Input

### `lokasi.txt`

Satu baris satu lokasi.

Contoh:

```text
Bandung
Cimahi
Kabupaten Bandung
```

### `kata-kunci.csv`

CSV dengan kolom pertama berisi keyword.

Contoh:

```csv
Kata_Kunci
klinik
salon
barbershop
cafe
```

### `niche_packs.json`

Dipakai untuk exclusion keyword scoring.

Contoh struktur:

```json
{
  "packs": {
    "Kesehatan": ["klinik", "dokter gigi"],
    "Kuliner": ["cafe", "restoran"]
  },
  "excluded_keywords": [
    "indomaret",
    "alfamart",
    "starbucks"
  ]
}
```

---

## Output yang Dihasilkan

Setelah crawler berjalan, file yang biasanya muncul:

- `data/*.csv` → hasil export lead
- `data/lead_finder.db` → database SQLite
- `.state/*.working.csv` → raw scrape sementara
- `.state/*.checkpoint.json` → checkpoint resume

Kalau menjalankan per job kota x keyword, nama file biasanya akan mengikuti slug session.

---

## Mengunduh Hasil dari Colab

Kalau Anda tidak memakai Google Drive, hasil bisa di-download manual.

### Download satu file

```python
from google.colab import files
files.download('/content/business-crawling/data/lead_finder.db')
```

Atau file CSV tertentu:

```python
from google.colab import files
files.download('/content/business-crawling/data/nama-file.csv')
```

### Zip seluruh hasil lalu download

```bash
!cd /content/business-crawling && zip -r hasil-crawling.zip data .state
```

Lalu download:

```python
from google.colab import files
files.download('/content/business-crawling/hasil-crawling.zip')
```

---

## Menjalankan Tanpa Audit Website

Kalau Anda ingin proses lebih ringan di Colab, nonaktifkan audit website:

```bash
%cd /content/business-crawling
!python maps-crawling.py --no-audit
```

Atau gabungkan dengan `--hot-only`:

```bash
%cd /content/business-crawling
!python maps-crawling.py --no-audit --hot-only
```

---

## Menonaktifkan Ekspansi Lokasi

Secara default project bisa membuat variasi lokasi seperti utara/selatan/timur/barat. Jika ingin hasil lebih hemat dan lebih cepat:

```bash
%cd /content/business-crawling
!python maps-crawling.py --no-expand-locations
```

---

## Saran Konfigurasi untuk Colab

Untuk mengurangi risiko runtime terlalu berat:

```bash
%cd /content/business-crawling
!python maps-crawling.py \
  --max-results 30 \
  --max-scrolls 20 \
  --stagnation-limit 4 \
  --no-audit \
  --hot-only
```

Rekomendasi awal:

- `--max-results 20` sampai `50`
- `--max-scrolls 15` sampai `30`
- `--no-audit` untuk run awal
- gunakan jumlah lokasi dan keyword sedikit dulu untuk uji coba

---

## Troubleshooting

### 1. Error `selenium` belum terpasang

Jalankan ulang:

```bash
!pip install -r /content/business-crawling/requirements.txt
```

Atau jika project ada di Drive:

```bash
!pip install -r /content/drive/MyDrive/business-crawling/requirements.txt
```

### 2. Error Chrome / Chromedriver tidak siap

Pastikan package sistem terinstall:

```bash
!apt-get update -y
!apt-get install -y chromium-chromedriver
```

### 3. File input tidak ditemukan

Cek apakah file ada di lokasi yang benar:

```bash
!ls -lah /content/business-crawling
```

Atau di Drive:

```bash
!ls -lah /content/drive/MyDrive/business-crawling
```

### 4. Kena CAPTCHA / blocked

Ini umum saat scraping Google Maps. Beberapa langkah yang bisa dicoba:

- kurangi jumlah job
- kurangi `max-scrolls`
- jalankan bertahap
- tunggu beberapa menit lalu lanjutkan lagi
- manfaatkan checkpoint yang sudah tersimpan

### 5. Runtime Colab restart / timeout

Gunakan Google Drive agar file hasil dan checkpoint tidak hilang.

---

## Contoh Alur Paling Praktis

Urutan yang paling direkomendasikan di Colab:

### Cell 1 — Mount Drive

```python
from google.colab import drive
drive.mount('/content/drive')
```

### Cell 2 — Clone project

```bash
!git clone https://github.com/USERNAME/REPO.git /content/drive/MyDrive/business-crawling
```

### Cell 3 — Install dependency

```bash
!apt-get update -y
!apt-get install -y wget unzip curl gnupg2 chromium-chromedriver
!pip install -r /content/drive/MyDrive/business-crawling/requirements.txt
```

### Cell 4 — Masuk folder project

```bash
%cd /content/drive/MyDrive/business-crawling
!ls -lah
```

### Cell 5 — Jalankan crawler

```bash
!python maps-crawling.py --no-audit --hot-only
```

---

## Rekomendasi

Jika target Anda adalah menjalankan project ini **otomatis di Google Colab saja**, maka pola terbaik adalah:

1. simpan project di Google Drive,
2. simpan input (`lokasi.txt`, `kata-kunci.csv`, `niche_packs.json`) di folder project,
3. jalankan lewat `maps-crawling.py`,
4. simpan output ke Drive juga,
5. gunakan checkpoint `.state/` untuk resume bila session terputus.

---

## Contoh Perintah Final

Versi sederhana:

```bash
%cd /content/drive/MyDrive/business-crawling
!python maps-crawling.py --no-audit --hot-only
```

Versi lebih lengkap:

```bash
%cd /content/drive/MyDrive/business-crawling
!python maps-crawling.py \
  --locations-file lokasi.txt \
  --keywords-csv kata-kunci.csv \
  --niche-path niche_packs.json \
  --data-dir /content/drive/MyDrive/business-crawling/data \
  --db-path /content/drive/MyDrive/business-crawling/data/lead_finder.db \
  --max-results 30 \
  --max-scrolls 20 \
  --stagnation-limit 4 \
  --captcha-wait-seconds 120 \
  --error-wait-seconds 180 \
  --no-audit \
  --hot-only
```

## Penutup

Project ini sekarang cocok untuk workflow **CLI/headless**, dan Google Colab bisa dipakai sebagai environment eksekusi selama:

- dependency browser disiapkan,
- file input tersedia,
- output disimpan ke Drive,
- dan Anda siap menghadapi kemungkinan CAPTCHA dari Google Maps.
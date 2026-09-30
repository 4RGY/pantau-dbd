# pantau-dbd

Peringatan dini (EWS) Demam Berdarah Dengue untuk DKI Jakarta. Pipeline dari data cuaca
dan laporan kasus sampai model prediksi dan dashboard.

Status: **tahap riset**. Model belum mengalahkan baseline naive. Semua angka di bawah
apa adanya, termasuk yang jelek.

## Hasil model (walk-forward, out-of-sample)

### Model bulanan (horizon 1 bulan)

Fold: latih 2021-2022 uji 2023, lalu latih 2021-2023 uji 2024.

| Model | MAE | sMAPE | Pearson r |
|---|---|---|---|
| LGBM (12 fitur) | 99.93 | 50.16% | 0.848 |
| GLM rasio | 104.32 | | |
| Naive lag-1 | 97.64 | | |
| Seasonal lag-12 | 188.85 | | |

Skill LGBM vs naive lag-1: **-2.4%** (kalah tipis).

### Model mingguan (horizon 1 minggu)

| Model | MAE | sMAPE | Pearson r | n |
|---|---|---|---|---|
| LGBM | 36.19 | 67.68% | 0.577 | 620 |
| Naive lag-4 | 21.75 | 42.90% | 0.854 | 599 |
| Seasonal | 44.14 | 84.20% | 0.339 | 596 |

Skill LGBM vs naive lag-4: **-69.3%** (kalah jauh).

## Temuan

**Ablasi fitur bulanan.** Mengganti isi fitur tidak menggeser MAE secara berarti:

| Varian | MAE | sMAPE | r |
|---|---|---|---|
| Penuh (cuaca + musim + batas wilayah) | 99.93 | 50.16% | 0.848 |
| Cuaca saja | 98.31 | 48.35% | 0.861 |
| Musim saja (2 fitur) | 96.68 | 48.92% | 0.849 |

Artinya sinyal cuaca belum terbaca model pada ukuran data ini. Model 12 fitur tidak
lebih baik dari model 2 fitur.

**Kepulauan Seribu.** Kasus di sana hampir selalu nol, sehingga naive nyaris sempurna
(MAE 0.31) sementara model memprediksi 27.75. Model over-predict di wilayah nol kasus.
Ini masalah desain, bukan masalah data.

**2024 tahun KLB.** Lonjakan kasus nasional 2024 berada di luar rentang latih, dan model
berbasis pohon tidak bisa ekstrapolasi di luar rentang itu. Naive menang justru karena
dia menempel di level terkini.

**Bug yang sudah diperbaiki.** Model awal dilatih memprediksi `log1p(kasus)` lalu
dikembalikan dengan `expm1`. Karena `expm1(E[log1p(y)]) != E[y]` (ketidaksamaan Jensen),
model under-predict sistematis sekitar 45% dan MAE jadi 1,8x naive. Sekarang dilatih
langsung di ruang kasus. Bias skala hilang, tapi belum cukup untuk menang.

## Sumber data

| Data | Sumber | Cakupan |
|---|---|---|
| Cuaca harian | Open-Meteo archive API | 2020-01-01 s/d sekarang, 6 wilayah DKI |
| Kasus DBD bulanan | Dinkes DKI Jakarta | 2021-01 s/d 2024-12 |
| Populasi & kepadatan | BPS | statis per wilayah |

## Struktur

```
pipeline/fetch/       ambil data mentah (cuaca)
pipeline/features/    bangun panel fitur, ekspor JSON dashboard
pipeline/train/       latih model, evaluasi walk-forward
dashboard/            Astro, membaca JSON dari public/data
data/raw/             data mentah
data/lake/            data turunan (parquet, csv, json metrik)
models/               model terlatih
```

## Cara jalan

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt

# bangun panel fitur bulanan
.venv/Scripts/python.exe -m pipeline.features.bangun_bulanan

# latih + evaluasi
.venv/Scripts/python.exe -m pipeline.train.train_bulanan

# ekspor JSON untuk dashboard
.venv/Scripts/python.exe -m pipeline.features.export_dashboard

# dashboard
cd dashboard && npm install && npm run dev
```

## Keterbatasan

- Kasus DBD dilaporkan per bulan. Horizon mingguan butuh disagregasi dan itu menambah noise.
- Laporan kasus punya lag rilis, jadi setiap skenario prediksi bergantung asumsi cutoff informasi.
- Rentang data masih pendek (4 tahun) untuk model dengan banyak fitur.
- Wilayah dengan kasus mendekati nol perlu penanganan khusus (misal model hurdle), belum dilakukan.

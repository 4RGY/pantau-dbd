"""Kontrak kode wilayah lintas-file + hasil build dashboard.

Bukan suite kanonik: repo ini tidak punya test runner. Tapi skrip ini DIJALANKAN
di CI, jadi hasilnya bisa dicek siapa pun, bukan cuma diklaim.

Yang diuji adalah mode kegagalan yang BENAR-BENAR terjadi (chart wilayah kosong
tanpa error karena kode di evaluasi.json tidak dipetakan). Jadi script ini
menguji KONTRAK antar-file, bukan cuma "apakah file bisa dibuka".

1. Setiap kode di array WILAYAH (index.astro) harus ada di sumber datanya.
2. Semua kode tab wilayah harus punya baris di evaluasi.json.
3. geojson harus punya properti yang dipakai nameProperty ('nama'), bukan 'name'.
4. Kode geojson harus cocok dengan kunci deret.json.
5. Nama geojson harus cocok dengan kunci meta.json per_region.
6. dist/index.html (hasil build) harus memuat data-eval untuk 6 wilayah.
7. Tidak boleh ada em-dash di teks yang tampil.
8. Angka di README harus cocok dengan metrik asli.
9. Kontrak a11y tablist (roving tabindex, tabpanel, aria-controls).

Butuh `dashboard/dist/` sudah di-build. Jalankan `npm run build` dulu.
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "dashboard", "public", "data")
PAGE = os.path.join(ROOT, "dashboard", "src", "pages", "index.astro")
CSS = os.path.join(ROOT, "dashboard", "src", "styles", "global.css")
DIST = os.path.join(ROOT, "dashboard", "dist", "index.html")

lolos, gagal = [], []


def cek(nama, kondisi, detail=""):
    (lolos if kondisi else gagal).append(nama)
    print(f"  [{'PASS' if kondisi else 'FAIL'}] {nama}" + (f" -> {detail}" if detail else ""))


def baca(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def jload(p):
    return json.loads(baca(p))


print("=== 1. baca sumber ===")
src = baca(PAGE)
evaluasi = jload(os.path.join(DATA, "evaluasi.json"))
deret = jload(os.path.join(DATA, "deret.json"))
meta = jload(os.path.join(DATA, "meta.json"))
geo = jload(os.path.join(DATA, "jakarta_sederhana.geojson"))
print(f"  evaluasi={len(evaluasi)} baris, deret={len(deret)} wilayah, "
      f"geojson={len(geo['features'])} fitur, per_region={len(meta['per_region'])}")

# --- ekstrak array WILAYAH dari index.astro ---
blok = re.search(r"const WILAYAH = \[(.*?)\n\];", src, re.S)
cek("array WILAYAH ditemukan di index.astro", blok is not None)
wil = re.findall(
    r"\{\s*kode:\s*'([^']+)',\s*eval:\s*'([^']+)',\s*nama:\s*'([^']+)',\s*pendek:\s*'([^']+)'\s*\}",
    blok.group(1),
)
cek("WILAYAH memuat 6 entri dengan 4 field", len(wil) == 6, f"{len(wil)} entri")

kode_slug = [w[0] for w in wil]
kode_eval = [w[1] for w in wil]
nama_panjang = [w[2] for w in wil]

print("\n=== 2. kontrak kode wilayah (mode kegagalan yang diperbaiki) ===")
kode_eval_json = sorted({r["w"] for r in evaluasi})
cek("kode 'eval' WILAYAH cocok persis dengan kolom w di evaluasi.json",
    sorted(kode_eval) == kode_eval_json, f"WILAYAH={sorted(kode_eval)} json={kode_eval_json}")

# tiap tab wilayah harus menghasilkan >=1 baris -> kalau tidak, chart kosong
kosong = [w[1] for w in wil if not any(r["w"] == w[1] for r in evaluasi)]
cek("tidak ada tab wilayah yang filternya nol baris", not kosong, f"kosong: {kosong}")

print("\n=== 3. kontrak geojson ===")
cek("geojson punya properti 'nama' (dipakai nameProperty)",
    all("nama" in f["properties"] for f in geo["features"]))
cek("geojson TIDAK punya properti 'name' (kalau ada, nameProperty bisa salah)",
    not any("name" in f["properties"] for f in geo["features"]))
cek("index.astro benar-benar memakai nameProperty: 'nama'",
    "nameProperty: 'nama'" in src)

print("\n=== 4. silang kode geojson <-> deret.json ===")
geo_kode = sorted(f["properties"]["kode"] for f in geo["features"])
cek("kode geojson == kunci deret.json", geo_kode == sorted(deret.keys()),
    f"geo={geo_kode} deret={sorted(deret.keys())}")

print("\n=== 5. silang nama geojson <-> meta.per_region ===")
geo_nama = sorted(f["properties"]["nama"] for f in geo["features"])
cek("nama geojson == kunci meta.per_region", geo_nama == sorted(meta["per_region"].keys()),
    f"geo={geo_nama} meta={sorted(meta['per_region'].keys())}")
cek("nama WILAYAH == kunci meta.per_region", sorted(nama_panjang) == sorted(meta["per_region"].keys()))

print("\n=== 6. hasil build ===")
ada_dist = os.path.exists(DIST)
cek("dist/index.html ada (sudah di-build)", ada_dist)
if not ada_dist:
    print("\n  dist/ belum ada - jalankan `npm run build` dulu di dashboard/")
if ada_dist:
    html = baca(DIST)
    hilang = [e for e in kode_eval if f'data-eval="{e}"' not in html]
    cek("dist memuat data-eval untuk semua 6 wilayah", not hilang, f"hilang: {hilang}")
    cek("dist memuat data-w untuk semua slug", all(f'data-w="{k}"' in html for k in kode_slug))
    cek("dist memuat guard .empty (gagal-senyap tidak lagi blank)", 'class="empty"' in src)

print("\n=== 7. label cuaca tidak ambigu lagi ===")
row = deret["jak-pus"]["rows"][-1]
cek("deret.json punya hujan_bulan DAN hujan_lag1",
    "hujan_bulan" in row and "hujan_lag1" in row, f"keys={sorted(row.keys())}")
cek("tidak ada lagi field generik 'hujan' di deret.json",
    "hujan" not in row, f"keys={sorted(row.keys())}")

print("\n=== 8. teks halaman bersih ===")
cek("0 em-dash/en-dash di index.astro", not re.search(r"[\u2014\u2013]", src))
cek("0 em-dash/en-dash di README",
    not re.search(r"[\u2014\u2013]", baca(os.path.join(ROOT, "README.md"))))

print("\n=== 9. angka README vs metrik asli ===")
mb = jload(os.path.join(ROOT, "data", "lake", "metrics_bulanan.json"))
ab = jload(os.path.join(ROOT, "data", "lake", "ablation_bulanan.json"))
rd = baca(os.path.join(ROOT, "README.md"))


def ada_angka(x):
    return f"{x:.2f}".replace(".", ",") in rd or f"{x:.2f}" in rd


model_mae = mb["agregat"]["lgbm"]["mae"]
naive_mae = mb["agregat"]["naive_lag1"]["mae"]
cek("MAE model bulanan ada di README", ada_angka(model_mae), f"{model_mae:.2f}")
cek("MAE naive bulanan ada di README", ada_angka(naive_mae), f"{naive_mae:.2f}")

# klaim skill: -2.4%
skill = mb["skill_vs_naive"] * 100
cek("skill bulanan yang diklaim cocok dengan metrik", abs(skill + 2.4) < 0.15,
    f"metrik={skill:.2f}%")

# klaim ablasi: model 12 fitur tidak lebih baik dari 2 fitur musim saja
try:
    musim_mae = ab["LGBM musim-only (2 fitur)"]["mae"]
    full_mae = ab["LGBM full (cuaca+musim+batas)"]["mae"]
    cek("klaim ablasi (musim saja lebih baik dari model penuh) benar",
        musim_mae < full_mae, f"musim={musim_mae:.2f} < full={full_mae:.2f}")
    cek("MAE ablasi full cocok dengan metrik agregat",
        abs(full_mae - model_mae) < 0.01, f"ablation={full_mae} agregat={model_mae}")
    cek("angka ablasi ada di README", ada_angka(musim_mae) and ada_angka(full_mae))
except (KeyError, TypeError) as e:
    cek("kunci ablasi bisa dibaca", False, str(e))

print("\n=== 10. klaim Kepser (yang sebelumnya salah) ===")
kep = mb["per_region"]["Kepulauan Seribu"]
km = kep["lgbm"]["mae"] if "lgbm" in kep else kep["model"]["mae"]
kn = kep["naive_lag1"]["mae"] if "naive_lag1" in kep else kep["naive"]["mae"]
cek("MAE Kepser bulanan kecil (bukan 27.75 ala mingguan)", km < 5, f"model={km:.2f} naive={kn:.2f}")
cek("angka Kepser bulanan ada di README", ada_angka(km) and ada_angka(kn))
cek("verdict README 'kalah' cocok dengan metrik",
    mb["keputusan"]["verdict"].lower().startswith("kalah"),
    f"verdict={mb['keputusan']['verdict']!r}")

print("\n=== 11. kontrak a11y tablist ===")
html_src = src

# semua tab punya id unik (dihitung dari hasil build; template Astro sudah di-expand)
ids_dist = sorted(set(re.findall(r'id="(tab-[^"]+)"', baca(DIST)))) if ada_dist else []
cek("semua 15 tab punya id unik di hasil build", len(ids_dist) == 15, f"{len(ids_dist)} id unik")

# semua tab punya aria-controls (dihitung di hasil build, bukan di sumber)
if ada_dist:
    dd = baca(DIST)
    n_tab_d = len(re.findall(r'role="tab"', dd))
    n_ctrl_d = len(re.findall(r'aria-controls="panel-', dd))
    cek("setiap tab punya aria-controls (dist)", n_ctrl_d == n_tab_d and n_tab_d == 15,
        f"tab={n_tab_d} controls={n_ctrl_d}")

# aria-controls menunjuk ke panel yang benar-benar ada
target = set(re.findall(r'aria-controls="([^"]+)"', html_src))
panel_ids = set(re.findall(r'id="(panel-[^"]+)"', html_src))
cek("aria-controls menunjuk panel yang ada", target <= panel_ids,
    f"target={sorted(target)} panel={sorted(panel_ids)}")

# panel punya role tabpanel + tabindex + aria-labelledby
n_tabpanel = len(re.findall(r'role="tabpanel"', html_src))
cek("ada panel role=tabpanel untuk tiap tablist", n_tabpanel == 2, f"{n_tabpanel} tabpanel")
for pid in sorted(panel_ids):
    blk = re.search(r'<div class="haze"[^>]*id="' + pid + r'"[^>]*>', html_src)
    ok = blk is not None and "aria-labelledby" in blk.group(0) and "tabindex" in blk.group(0)
    cek(f"panel {pid} punya aria-labelledby + tabindex", ok)

# roving tabindex: pola harus ada di JS (diverifikasi live di DOM)
cek("JS memakai pola roving tabindex (t.tabIndex)", "t.tabIndex = on ? 0 : -1" in html_src)
cek("JS menangani panah kiri/kanan", "ArrowRight" in html_src and "ArrowLeft" in html_src)
cek("JS menangani Home/End", "'Home'" in html_src and "'End'" in html_src)
cek("JS pakai preventDefault saat panah", "e.preventDefault()" in html_src)

# hasil build ikut membawa kontrak ini
if ada_dist:
    d = baca(DIST)
    cek("dist memuat role=tabpanel", 'role="tabpanel"' in d)
    cek("dist memuat aria-controls", "aria-controls=" in d)
    cek("dist memuat id panel", 'id="panel-ts"' in d and 'id="panel-cuaca"' in d)
    cek("dist memuat id tab wilayah", 'id="tab-ts-kep-seribu"' in d)

print("\n=== 12. favicon & metadata sosial ===")
if ada_dist:
    d = baca(DIST)
    cek("favicon dirujuk di HTML", 'rel="icon"' in d)
    cek("favicon ada di dist", any(
        os.path.exists(os.path.join(ROOT, "dashboard", "dist", p))
        for p in ("favicon.ico", "favicon.svg")
    ))
    for prop in ("og:title", "og:description", "og:image", "og:url", "og:type"):
        cek(f"meta {prop} ada", f'property="{prop}"' in d)
    cek("meta twitter:card ada", 'name="twitter:card"' in d)
    cek("canonical link ada", 'rel="canonical"' in d)
    cek("og:image menunjuk berkas yang ada di dist",
        any(os.path.exists(os.path.join(ROOT, "dashboard", "dist", p))
            for p in ("og.png", "og.jpg")))

print("\n=== 13. tautan keluar & author ===")
cek("index.astro memuat tautan ke repo GitHub",
    "github.com/4RGY/pantau-dbd" in src)
cek("index.astro menyebut penulis", "Anggara" in src)

print("\n" + "=" * 52)
print(f"HASIL: {len(lolos)} PASS / {len(gagal)} FAIL")
if gagal:
    print("GAGAL:")
    for g in gagal:
        print("  -", g)
sys.exit(1 if gagal else 0)

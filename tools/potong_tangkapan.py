"""Potong tangkapan layar dashboard jadi per-seksi untuk README.

Offset diambil dari pengukuran DOM langsung (getBoundingClientRect), bukan tebakan.
Viewport 1440, dpr 1.0, jadi koordinat CSS == piksel gambar.

Skrip ini hanya mengurus 01 sampai 05. Dua tangkapan lain datang dari sumber lain,
dan dulu skrip ini ikut menulisnya sehingga menimpa hasil yang benar:
  06-arsitektur.png  -> render tools/diagram_arsitektur.html, bukan potongan browser
  07-mobile.png      -> komposit tiga panel dari tools/susun_mobile.py

Sumber mentah (shot-desktop.png, shot-mobile.png) sengaja tidak ikut repo, jadi
skrip ini jalan di mesin yang menyimpannya, bukan di runner CI.

Jalankan dari home: .venv/Scripts/python.exe <skrip>
"""
from pathlib import Path
from PIL import Image

HOME = Path.home()
OUT = HOME / "pantau-dbd" / "docs"
OUT.mkdir(parents=True, exist_ok=True)

desktop = Image.open(HOME / "shot-desktop.png")
DW, DH = desktop.size

# (nama, atas, bawah): batas dari pengukuran DOM, dilebihkan sedikit biar tidak terpotong
POTONGAN = [
    ("01-hero", 0, 1225),
    ("02-deret", 1215, 2210),
    ("03-cuaca", 2200, 3165),
    ("04-shap", 3155, 4010),
    ("05-wilayah", 4000, 5305),
]

hasil = []
for nama, atas, bawah in POTONGAN:
    atas = max(0, min(atas, DH))
    bawah = max(atas, min(bawah, DH))
    im = desktop.crop((0, atas, DW, bawah))
    p = OUT / f"{nama}.png"
    im.save(p, optimize=True)
    hasil.append((p.name, im.size, p.stat().st_size))

print(f"desktop sumber: {DW}x{DH}")
print(f"keluaran di: {OUT}")
print()
tot = 0
for nama, ukuran, byte in hasil:
    tot += byte
    print(f"  {nama:16s} {ukuran[0]:5d}x{ukuran[1]:<6d} {byte/1024:8.1f} KB")
print(f"\ntotal {len(hasil)} berkas, {tot/1024/1024:.2f} MB")
print("catatan: 06-arsitektur.png dari tools/diagram_arsitektur.html, "
      "07-mobile.png dari tools/susun_mobile.py (bukan dari sini)")

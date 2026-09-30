"""Potong screenshot dashboard jadi per-seksi untuk README.

Offset diambil dari pengukuran DOM langsung (getBoundingClientRect), bukan tebakan.
Viewport 1440, dpr 1.0, jadi koordinat CSS == piksel gambar.

Jalankan dari home: .venv/Scripts/python.exe <skrip>
"""
from pathlib import Path
from PIL import Image

HOME = Path.home()
OUT = HOME / "pantau-dbd" / "docs"
OUT.mkdir(parents=True, exist_ok=True)

desktop = Image.open(HOME / "shot-desktop.png")
mobile = Image.open(HOME / "shot-mobile.png")
DW, DH = desktop.size

# (nama, atas, bawah) — batas dari pengukuran DOM, dilebihkan sedikit biar tidak terpotong
POTONGAN = [
    ("01-hero", 0, 1225),
    ("02-deret", 1215, 2210),
    ("03-cuaca", 2200, 3165),
    ("04-shap", 3155, 4010),
    ("05-wilayah", 4000, 5305),
    ("06-penutup", 5295, DH),
]

hasil = []
for nama, atas, bawah in POTONGAN:
    atas = max(0, min(atas, DH))
    bawah = max(atas, min(bawah, DH))
    im = desktop.crop((0, atas, DW, bawah))
    # sisi kanan kadang ada sisa scrollbar: potong 1px terakhir kalau warnanya seragam gelap
    p = OUT / f"{nama}.png"
    im.save(p, optimize=True)
    hasil.append((p.name, im.size, p.stat().st_size))

m = OUT / "07-mobile.png"
mobile.save(m, optimize=True)
hasil.append((m.name, mobile.size, m.stat().st_size))

print(f"desktop sumber: {DW}x{DH}   mobile sumber: {mobile.size[0]}x{mobile.size[1]}")
print(f"keluaran di: {OUT}")
print()
tot = 0
for nama, ukuran, byte in hasil:
    tot += byte
    print(f"  {nama:16s} {ukuran[0]:5d}x{ukuran[1]:<6d} {byte/1024:8.1f} KB")
print(f"\ntotal {len(hasil)} berkas, {tot/1024/1024:.2f} MB")

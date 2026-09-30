"""Susun tangkapan layar mobile jadi satu gambar 3 panel.

Tangkapan full-page mobile tingginya 6902 px. Kalau ditempel apa adanya di README,
hasilnya jadi strip tipis panjang yang susah dibaca. Jadi dipotong tiga jendela
setinggi viewport (844 px) lalu ditempel berdampingan.
"""

import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")

SUMBER = os.path.join(os.path.expanduser("~"), "shot-mobile.png")
KELUAR = os.path.join(DOCS, "07-mobile.png")

BG = (8, 9, 11)
GARIS = (32, 34, 38)
INK_DIM = (156, 154, 149)

TINGGI_JENDELA = 844
LABEL = ["atas", "tengah", "bawah"]

im = Image.open(SUMBER).convert("RGB")
lebar = im.size[0]

# ambil tiga jendela: paling atas, tengah, dan paling bawah
atas = 0
tengah = max(0, (im.size[1] - TINGGI_JENDELA) // 2)
bawah = max(0, im.size[1] - TINGGI_JENDELA)
potongan = [im.crop((0, y, lebar, y + TINGGI_JENDELA)) for y in (atas, tengah, bawah)]

GAP = 30
PAD = 44
PAD_ATAS = 54

kanvas_w = PAD * 2 + lebar * 3 + GAP * 2
kanvas_h = PAD_ATAS + TINGGI_JENDELA + PAD
kanvas = Image.new("RGB", (kanvas_w, kanvas_h), BG)
gambar = ImageDraw.Draw(kanvas)

try:
    font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 17)
except OSError:
    font = ImageFont.load_default()

for i, (bagian, teks) in enumerate(zip(potongan, LABEL)):
    x = PAD + i * (lebar + GAP)
    kanvas.paste(bagian, (x, PAD_ATAS))
    gambar.rectangle([x, PAD_ATAS, x + lebar - 1, PAD_ATAS + TINGGI_JENDELA - 1], outline=GARIS)
    # Lebar ditulis dari gambar, bukan angka yang diketik manual: label yang
    # diketik manual pernah tertulis 390px padahal panelnya 375px.
    gambar.text((x + 2, PAD_ATAS - 30), f"mobile {lebar}px / {teks}", font=font, fill=INK_DIM)

kanvas.save(KELUAR, optimize=True)
print("ditulis:", KELUAR, kanvas.size, os.path.getsize(KELUAR), "B")

"""Bikin aset sosial dari angka NYATA di data/lake/metrics_bulanan.json.

Kenapa skrip, bukan file gambar tempelan: kartu og:image memuat angka. Kalau model
di-retrain dan angkanya berubah, kartu yang ditempel tangan akan berbohong tanpa
ada yang sadar. Skrip ini membaca metrics_bulanan.json, jadi kartunya selalu ikut
angka terbaru. Jalankan ulang tiap kali metrik berubah.

Menghasilkan (di dashboard/public/, ikut tersalin ke dist/ saat build):
    og.png                1200x630, kartu share WhatsApp/LinkedIn/Discord
    apple-touch-icon.png  180x180
    favicon.ico           16/32/48

favicon.svg ditulis tangan (sumbernya di dashboard/public/favicon.svg).

Pakai:
    .venv/Scripts/python.exe tools/make_assets.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
METRIK = ROOT / "data" / "lake" / "metrics_bulanan.json"
PUB = ROOT / "dashboard" / "public"

# Palet disalin dari dashboard/src/styles/global.css supaya kartu share sewarna
# dengan halaman yang dibagikan.
BG = (13, 13, 14)
INK = (236, 234, 230)
DIM = (156, 154, 149)
FAINT = (107, 105, 101)
AMBER = (217, 155, 63)
HAIR = (40, 40, 43)

W, H = 1200, 630
PAD = 78

FONTS = Path("C:/Windows/Fonts")
GEORGIA, GEORGIA_IT = "georgia.ttf", "georgiai.ttf"
CONSOLA, SEGUI_SB = "consola.ttf", "seguisb.ttf"

# Motif sama dengan favicon.svg (viewBox 32), dipakai sebagai lambang.
SPIKE = [(5.5, 23.6), (12.4, 15.6), (17.6, 19.6), (26.5, 8.4)]


def font(nama: str, size: int) -> ImageFont.FreeTypeFont:
    p = FONTS / nama
    if not p.exists():
        print(f"FATAL: font tidak ada: {p}", file=sys.stderr)
        raise SystemExit(2)
    return ImageFont.truetype(str(p), size)


def tracked(d: ImageDraw.ImageDraw, xy, teks: str, f, fill, tracking: float = 0.0) -> float:
    """Gambar teks dengan jarak antar huruf. Pillow tidak punya letter-spacing."""
    x, y = xy
    for ch in teks:
        d.text((x, y), ch, font=f, fill=fill)
        x += d.textlength(ch, font=f) + tracking
    return x - tracking


def tracked_w(d: ImageDraw.ImageDraw, teks: str, f, tracking: float = 0.0) -> float:
    return sum(d.textlength(c, font=f) + tracking for c in teks) - tracking


def bungkus(d: ImageDraw.ImageDraw, teks: str, f, maxw: float) -> list[str]:
    """Bungkus teks jadi beberapa baris agar tidak melewati maxw."""
    baris: list[str] = []
    cur = ""
    for kata in teks.split():
        coba = f"{cur} {kata}".strip()
        if d.textlength(coba, font=f) <= maxw or not cur:
            cur = coba
        else:
            baris.append(cur)
            cur = kata
    if cur:
        baris.append(cur)
    return baris


def num(x: float, dec: int = 2) -> str:
    """Angka gaya Indonesia: 1.234,56 (bukan 1,234.56)."""
    s = f"{x:,.{dec}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def lambang(size: int, full_bleed: bool = False) -> Image.Image:
    """Lambang Pantau DBD: kotak gelap + garis naik amber."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if full_bleed:
        d.rectangle([0, 0, size - 1, size - 1], fill=BG)
    else:
        d.rounded_rectangle([0, 0, size - 1, size - 1], radius=round(size * 0.235), fill=BG)
    sc = size / 32.0
    lebar = max(1, round(size * 0.084))
    d.line([(x * sc, y * sc) for x, y in SPIKE], fill=AMBER, width=lebar, joint="curve")
    cx, cy, r = SPIKE[-1][0] * sc, SPIKE[-1][1] * sc, size * 0.084
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=AMBER)
    return img


def kartu(m: dict) -> Image.Image:
    mae_model = m["agregat"]["lgbm"]["mae"]
    mae_naive = m["agregat"]["naive_lag1"]["mae"]
    skill = m["skill_vs_naive"] * 100
    n_bulan = m["agregat"]["lgbm"]["n"]
    verdict = m["keputusan"]["verdict"].upper()

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    kanan = W - PAD
    maxw = kanan - PAD

    # 1. eyebrow
    f_eyebrow = font(CONSOLA, 19)
    tracked(d, (PAD, 70), "PROYEK RISET / DKI JAKARTA", f_eyebrow, DIM, 2.6)

    # 2. lambang di kanan atas
    img.paste(lambang(46), (kanan - 46, 62), lambang(46))

    # 3. judul: "dini" miring + amber, seperti <em>dini</em> di halaman
    bagian = [("Peringatan ", False), ("dini", True), (" DBD Jakarta", False)]
    size = 74
    while size > 46:
        f_judul = [font(GEORGIA_IT if it else GEORGIA, size) for _, it in bagian]
        if sum(d.textlength(t, font=f) for (t, _), f in zip(bagian, f_judul)) <= maxw:
            break
        size -= 2
    x, y = PAD, 112
    for (teks, miring), f in zip(bagian, f_judul):
        warna = AMBER if miring else INK
        d.text((x, y), teks, font=f, fill=warna)
        x += d.textlength(teks, font=f)

    # 4. subjudul
    f_sub = font(SEGUI_SB, 25)
    sub = ("LightGBM, GLM rasio, dan baseline naive. Evaluasi walk-forward "
           "out-of-sample, 6 kotamadya DKI Jakarta.")
    y = 224
    for baris in bungkus(d, sub, f_sub, 940)[:2]:
        d.text((PAD, y), baris, font=f_sub, fill=DIM)
        y += 36

    # 5. garis pemisah
    d.line([(PAD, 318), (kanan, 318)], fill=HAIR, width=1)

    # 6. tiga statistik
    kolom = [
        (num(mae_model), "MAE MODEL BULANAN", INK),
        (num(mae_naive), "MAE BASELINE NAIVE", INK),
        (f"{skill:.1f}".replace(".", ",") + "%", "SKILL VS NAIVE", AMBER),
    ]
    f_besar = font(CONSOLA, 58)
    f_label = font(CONSOLA, 17)
    lebar_kolom = 352
    for i, (angka, label, warna) in enumerate(kolom):
        xk = PAD + i * lebar_kolom
        d.text((xk, 352), angka, font=f_besar, fill=warna)
        tracked(d, (xk, 430), label, f_label, FAINT, 2.2)

    # 7. badge verdict (hook jujurnya: hasilnya negatif)
    f_badge = font(CONSOLA, 18)
    teks_badge = f"VERDICT: {verdict}"
    w_badge = tracked_w(d, teks_badge, f_badge, 1.8) + 40
    d.rounded_rectangle([PAD, 494, PAD + w_badge, 536], radius=4, outline=AMBER, width=1)
    tracked(d, (PAD + 20, 504), teks_badge, f_badge, AMBER, 1.8)

    # 8. baris kaki
    f_kaki = font(CONSOLA, 17)
    teks_kaki = "github.com/4RGY/pantau-dbd"
    d.text((kanan - d.textlength(teks_kaki, font=f_kaki), 508), teks_kaki, font=f_kaki, fill=FAINT)
    d.text((kanan - d.textlength(f"{n_bulan} bulan uji", font=f_kaki), 566),
           f"{n_bulan} bulan uji", font=f_kaki, fill=FAINT)

    return img


def main() -> int:
    if not METRIK.exists():
        print(f"FATAL: metrik tidak ada: {METRIK}", file=sys.stderr)
        return 2
    m = json.loads(METRIK.read_text(encoding="utf-8"))

    PUB.mkdir(parents=True, exist_ok=True)

    og = kartu(m)
    assert og.size == (1200, 630), og.size
    og.save(PUB / "og.png", optimize=True)

    lambang(180, full_bleed=True).convert("RGB").save(PUB / "apple-touch-icon.png", optimize=True)

    ico = lambang(48)
    ico.save(PUB / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])

    for nama in ("og.png", "apple-touch-icon.png", "favicon.ico"):
        p = PUB / nama
        print(f"  {nama:24s} {p.stat().st_size:>8,} byte")

    print("\nangka yang dipakai di kartu (dari metrics_bulanan.json):")
    print(f"  MAE model  : {num(m['agregat']['lgbm']['mae'])}")
    print(f"  MAE naive  : {num(m['agregat']['naive_lag1']['mae'])}")
    print(f"  skill      : {m['skill_vs_naive'] * 100:.2f}%")
    print(f"  verdict    : {m['keputusan']['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

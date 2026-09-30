"""Kontrak aset publik: tangkapan layar README dan kartu share.

Yang dijaga di sini adalah aset yang DILIHAT orang di GitHub dan di kartu share:
tangkapan layar di README, diagram arsitektur, og.png, favicon. Cek kontrak lain
(angka pipeline, kode wilayah, gaya) ada di berkas tetangga.

Kenapa diperiksa dari PIKsel, bukan dari skrip pembuatnya:
`tools/potong_tangkapan.py` dan `tools/susun_mobile.py` memotong dari
`~/shot-desktop.png` dan `~/shot-mobile.png`, dua berkas tangkapan mentah yang
sengaja TIDAK ikut repo (400 KB lebih, dan cuma bisa dibuat ulang dengan
menjalankan browser lagi). Jadi skripnya tidak bisa dijalankan di runner bersih.
Yang bisa diperiksa siapa pun, di mana pun, adalah hasil akhirnya: berkas di
docs/ dan dashboard/public/. Itu yang dilakukan harness ini.

Pillow dipakai dan itu memang satu-satunya cara membaca piksel. Pillow terdaftar
di requirements-dev.txt, jadi runner CI menjalankan cek yang sama persis.

Jalankan: python tests/test_assets_contract.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(ROOT, "README.md")
DOCS = os.path.join(ROOT, "docs")
PUB = os.path.join(ROOT, "dashboard", "public")
DIST = os.path.join(ROOT, "dashboard", "dist")

lolos, gagal = [], []


def cek(nama, syarat, info=""):
    (lolos if syarat else gagal).append(nama)
    print(f"  [{'PASS' if syarat else 'FAIL'}] {nama}" + (f" -> {info}" if info else ""))


def baca(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def png_dim(p):
    """Lebar dan tinggi dari chunk IHDR. Tanpa dependensi, untuk berkas besar."""
    with open(p, "rb") as f:
        kp = f.read(24)
    if kp[:8] != b"\x89PNG\r\n\x1a\n" or kp[12:16] != b"IHDR":
        raise ValueError(f"bukan PNG: {p}")
    return int.from_bytes(kp[16:20], "big"), int.from_bytes(kp[20:24], "big")


def warna_unik(p):
    """Jumlah warna unik. Ini pengukur 'ada isinya', bukan entropi byte."""
    from PIL import Image
    im = Image.open(p)
    im.load()
    # getcolors menghitung di sisi C dan tidak deprecated seperti getdata().
    # Batas 2**20 jauh di atas aset terbesar di repo (19.365 warna), jadi None
    # praktis tidak terjadi; kalau terjadi, dilaporkan sebagai nilai batas.
    cols = im.convert("RGBA").getcolors(maxcolors=1 << 20)
    return 1 << 20 if cols is None else len(cols)


# Ambang "gambar ada isinya". Diukur dari aset yang ada: tangkapan layar paling
# polos di docs/ (04-shap.png) punya 2.229 warna unik, jadi 500 menyisakan
# margin lebih dari 4x. Kontrol negatifnya kuat: PNG satu warna = 1 warna unik,
# dan PNG yang IDAT-nya rusak gagal saat didekompresi, bukan lolos diam-diam.
AMBANG_UNIK = 500

# Geometri yang disengaja, dan angkanya bukan pilihan sendiri:
#   1425 = viewport 1440 dikurangi scrollbar Chrome
#   1273 = kanvas tiga panel mobile (44 + 3x375 + 2x30 + 44)
#   1901 = diagram arsitektur, hasil render HTML jadi memang lebih lebar
# Menyimpang dari himpunan ini berarti ada yang di-crop atau di-render ulang
# dengan ukuran tak terduga, dan itu yang mau ditangkap.
LEBAR_SAH = {1425, 1273, 1901}

teks = baca(README)
print("=== 1. README merujuk aset yang ada, dan tidak ada aset menganggur ===")
semua_ref = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", teks)
lokal = [r for r in semua_ref if not r.startswith(("http://", "https://"))]
remote = [r for r in semua_ref if r.startswith(("http://", "https://"))]
for r in remote:
    print(f"  [SKIP] gambar remote (badge): {r[:70]}")
hilang = [r for r in lokal if not os.path.exists(os.path.join(ROOT, r))]
cek("setiap gambar lokal yang dirujuk README benar-benar ada", not hilang,
    f"{len(lokal)} rujukan lokal, hilang={hilang or 'tidak ada'}")
cek("jumlah rujukan gambar sesuai isi README", len(lokal) >= 7,
    f"{len(lokal)} rujukan lokal (harapannya >= 7)")

ada = sorted(f"docs/{f}" for f in os.listdir(DOCS) if f.endswith(".png"))
menganggur = [f for f in ada if f not in lokal]
cek("tidak ada berkas docs/ yang tidak dipakai README", not menganggur,
    f"dipakai {len(ada) - len(menganggur)} dari {len(ada)}; menganggur={menganggur or 'tidak ada'}")


print("\n=== 2. jalur gambar relatif (bukan absolut, bukan keluar repo) ===")
def bentuk_aneh(r):
    return (r.startswith("/") or "\\" in r or ".." in r.split("/")
            or re.match(r"^[A-Za-z]:", r) or " " in r)


buruk = [r for r in lokal if bentuk_aneh(r)]
cek("semua rujukan gambar relatif, tanpa spasi, tanpa keluar repo", not buruk,
    f"bermasalah={buruk or 'tidak ada'}")


print("\n=== 3. tangkapan layar di docs/ benar-benar ada isinya ===")
# Kalau crop meleset ke area kosong, berkasnya tetap PNG yang sah dan tetap
# tampil di README, tapi cuma kotak gelap. Jadi yang diperiksa bukan sekadar
# 'berkasnya ada', melainkan 'pikselnya beragam'.
if not os.path.isdir(DOCS):
    cek("direktori docs/ ada", False, DOCS)
else:
    ringkas = []
    for nama in sorted(os.listdir(DOCS)):
        if not nama.endswith(".png"):
            continue
        p = os.path.join(DOCS, nama)
        try:
            w, h = png_dim(p)
        except ValueError as e:
            cek(f"{nama}: PNG sah", False, str(e))
            continue
        try:
            n = warna_unik(p)
        except Exception as e:  # berkas rusak harus GAGAL, bukan lolos
            cek(f"{nama}: bisa dibaca", False, f"{type(e).__name__}: {e}")
            continue
        ringkas.append((nama, w, h, n))
        cek(f"{nama}: ada isinya", n >= AMBANG_UNIK,
            f"{w}x{h}, {n} warna unik (ambang {AMBANG_UNIK})")

    if ringkas:
        terendah = min(ringkas, key=lambda r: r[3])
        cek("semua tangkapan layar lebih tinggi dari 800 px",
            all(h >= 800 for _, _, h, _ in ringkas),
            f"terendah={min(h for _, _, h, _ in ringkas)}px")
        cek("tidak ada tangkapan layar dengan lebar tak terduga",
            all(w in LEBAR_SAH for _, w, _, _ in ringkas),
            f"lebar terlihat: {sorted({w for _, w, _, _ in ringkas})}, sah={sorted(LEBAR_SAH)}")
        print(f"  catatan: paling polos = {terendah[0]} dengan {terendah[3]} warna unik")


print("\n=== 4. aset sosial (kartu share, ikon) ===")
def ico_ukuran(p):
    """Ukuran gambar di dalam .ico, dibaca dari header. Stdlib saja."""
    b = open(p, "rb").read()
    if len(b) < 6 or b[0:4] != b"\x00\x00\x01\x00":
        raise ValueError("header ICO tidak sah")
    n = int.from_bytes(b[4:6], "little")
    if n == 0:
        raise ValueError("ICO tanpa gambar")
    out = []
    for i in range(n):
        off = 6 + i * 16
        if off + 16 > len(b):
            raise ValueError("direktori ICO terpotong")
        w, h = b[off], b[off + 1]
        out.append((w or 256, h or 256))
    return sorted(out)


OG = os.path.join(PUB, "og.png")
APPLE = os.path.join(PUB, "apple-touch-icon.png")
ICO = os.path.join(PUB, "favicon.ico")

if not os.path.exists(OG):
    cek("dashboard/public/og.png ada", False, OG)
else:
    w, h = png_dim(OG)
    cek("kartu share berukuran 1200x630", (w, h) == (1200, 630), f"{w}x{h}")
    n = warna_unik(OG)
    cek("kartu share tidak kosong", n >= AMBANG_UNIK,
        f"{n} warna unik (ambang {AMBANG_UNIK})")

if not os.path.exists(APPLE):
    cek("dashboard/public/apple-touch-icon.png ada", False, APPLE)
else:
    w, h = png_dim(APPLE)
    cek("ikon sentuh berukuran 180x180", (w, h) == (180, 180), f"{w}x{h}")

if not os.path.exists(ICO):
    cek("dashboard/public/favicon.ico ada", False, ICO)
else:
    try:
        uk = ico_ukuran(ICO)
        cek("favicon.ico memuat 16, 32, dan 48", uk == [(16, 16), (32, 32), (48, 48)],
            f"terbaca: {uk}")
    except ValueError as e:
        cek("favicon.ico berformat sah", False, str(e))

cek("favicon.svg (sumber ikon) ikut repo",
    os.path.exists(os.path.join(PUB, "favicon.svg")), "dashboard/public/favicon.svg")


print("\n=== 5. aset terbawa ke hasil build dan tertaut di HTML ===")
HTML = os.path.join(DIST, "index.html")
if not os.path.exists(HTML):
    cek("dashboard/dist/index.html ada (jalankan npm run build dulu)", False, HTML)
else:
    for nama in ("og.png", "apple-touch-icon.png", "favicon.ico", "favicon.svg"):
        a = os.path.join(PUB, nama)
        b = os.path.join(DIST, nama)
        if not os.path.exists(a):
            cek(f"{nama} tersalin ke dist/", False, "tidak ada di dashboard/public/")
            continue
        if not os.path.exists(b):
            cek(f"{nama} tersalin ke dist/", False, "tidak ada di dashboard/dist/")
            continue
        cek(f"{nama} tersalin ke dist/ tanpa berubah",
            open(a, "rb").read() == open(b, "rb").read(),
            f"{os.path.getsize(a):,} byte")

    # Aset yang dibuat tapi tidak pernah ditautkan sama saja tidak ada: kartu
    # share akan tetap kosong dan tidak ada yang gagal.
    html = baca(HTML)
    for nama, pola in (("og.png", r'property="og:image"'), ("apple-touch-icon.png", r"apple-touch-icon"),
                       ("favicon.svg", r"favicon\.svg"), ("favicon.ico", r"favicon\.ico")):
        m = re.search(pola, html)
        cek(f"dist/index.html menautkan {nama}", bool(m),
            f"pola {pola!r} {'ditemukan' if m else 'TIDAK ditemukan'}")


print("\n=== 6. gerbang README benar-benar bisa merah ===")
PERIKSA = os.path.join(ROOT, "tools", "periksa_readme.py")
if not os.path.exists(PERIKSA):
    cek("tools/periksa_readme.py ada", False, PERIKSA)
else:
    def periksa(berkas):
        return subprocess.run([sys.executable, PERIKSA, berkas], cwd=ROOT,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    cek("periksa_readme.py hijau pada README repo", periksa(README).returncode == 0,
        "exit=0 diharapkan")

    # Uji merah. Tanpa ini, skrip yang selalu keluar 0 akan terlihat sehat, dan
    # itu memang keadaan skrip ini sebelumnya. Yang dirusak adalah salinan di
    # direktori sementara, jadi README repo tidak pernah tersentuh.
    fd, rusak = tempfile.mkstemp(suffix=".md")
    os.close(fd)
    try:
        with open(rusak, "w", encoding="utf-8") as f:
            f.write(baca(README).replace("proyek", "proyek \u2014", 1))
        r = periksa(rusak)
        cek("periksa_readme.py merah pada README yang dirusak", r.returncode == 1,
            f"exit={r.returncode} (harus 1)")
    finally:
        os.unlink(rusak)


print(f"\n{'=' * 46}")
print(f"HASIL: {len(lolos)} PASS / {len(gagal)} FAIL")
sys.exit(1 if gagal else 0)





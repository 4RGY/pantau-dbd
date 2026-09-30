"""Kontrak sistem visual: lantai ukuran font, reduced-motion, aset build.

Bukan suite kanonik: repo ini tidak punya test runner. Tapi skrip ini DIJALANKAN
di CI, jadi hasilnya bisa dicek siapa pun, bukan cuma diklaim.

Kenapa "lantai font" dan bukan "diff lawan commit X": cek diff sekali-pakai
(`git show d091589~1:...`) membuktikan satu perubahan historis tidak menyentuh
properti lain, tapi mati begitu commit itu tidak ada di riwayat (clone dangkal di
CI). Yang bertahan adalah kontraknya: tidak ada teks di bawah 11px, dan
prefers-reduced-motion dihormati.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS_SRC = os.path.join(ROOT, "dashboard", "src", "styles", "global.css")
DIST = os.path.join(ROOT, "dashboard", "dist")
DIST_HTML = os.path.join(DIST, "index.html")

FLOOR = 11.0

lolos, gagal = [], []


def cek(nama, syarat, info=""):
    (lolos if syarat else gagal).append(nama)
    print(f"  [{'PASS' if syarat else 'FAIL'}] {nama}" + (f" -> {info}" if info else ""))


def baca(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


css = baca(CSS_SRC)


def blok(sel):
    m = re.search(re.escape(sel) + r"\s*\{([^}]*)\}", css)
    return m.group(1) if m else ""


def fs(sel):
    m = re.search(r"font-size:\s*([\d.]+)px", blok(sel))
    return float(m.group(1)) if m else None


print("=== 1. lantai ukuran font (kontrak, bukan diff historis) ===")
# semua deklarasi font-size dalam px di stylesheet harus >= FLOOR
semua_px = [float(x) for x in re.findall(r"font-size:\s*([\d.]+)px", css)]
terlalu_kecil = sorted({v for v in semua_px if v < FLOOR})
cek(f"tidak ada font-size < {FLOOR}px di stylesheet", not terlalu_kecil,
    f"terkecil={min(semua_px)}px, langgar={terlalu_kecil}" if semua_px else "tidak ada font-size px")

# varian rem juga diperiksa: 1rem = 16px asumsi browser default
semua_rem = [float(x) for x in re.findall(r"font-size:\s*([\d.]+)rem", css)]
cek(f"tidak ada font-size rem < {FLOOR / 16:.4f}rem",
    all(v * 16 >= FLOOR for v in semua_rem),
    f"{[v for v in semua_rem if v * 16 < FLOOR]}")

cek("th = 11.5px", fs("th") == 11.5, f"{fs('th')}px")
cek(".cell-label = 11.5px", fs(".cell-label") == 11.5, f"{fs('.cell-label')}px")
cek("tidak ada 10.5px tersisa", "font-size: 10.5px" not in css)

print("\n=== 2. tabel: kolom angka tidak boleh membungkus ===")
cek("td pakai white-space: nowrap (kolom angka)", "nowrap" in blok("td"))
cek("tabel pakai border-collapse", "border-collapse" in css)
cek("tabel dibungkus .tbl-wrap dengan overflow-x",
    ".tbl-wrap" in css and "overflow-x" in blok(".tbl-wrap"))
cek("ada caption tabel atau aria-label pengganti", "<caption" in baca(
    os.path.join(ROOT, "dashboard", "src", "pages", "index.astro")))

print("\n=== 3. prefers-reduced-motion dihormati ===")
cek("ada media query prefers-reduced-motion", "prefers-reduced-motion" in css)
blk_rm = re.search(r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(.*?)\n\}", css, re.S)
cek("blok reduced-motion mengatur animation/transition",
    blk_rm is not None and ("animation" in blk_rm.group(1) or "transition" in blk_rm.group(1)),
    (blk_rm.group(1).strip().replace("\n", " ")[:80] if blk_rm else "blok tidak ditemukan"))

print("\n=== 4. focus ring untuk panel tablist ===")
cek("focus-visible untuk panel tablist ada", "tabpanel']:focus-visible" in css)

print("\n=== 5. hasil build membawa kontrak ini ===")
if os.path.exists(DIST_HTML):
    d = baca(DIST_HTML)
    cek("dist/index.html ada", True)
    hrefs = re.findall(r'<link[^>]+href="([^"]+\.css)"', d)
    isi = "".join(
        baca(os.path.join(DIST, h.lstrip("/")))
        for h in hrefs
        if os.path.exists(os.path.join(DIST, h.lstrip("/")))
    )
    cek("aset CSS build terbaca", bool(isi), f"{len(hrefs)} stylesheet, {len(isi)} char")
    if isi:
        px_build = [float(x) for x in re.findall(r"font-size:\s*([\d.]+)px", isi)]
        kecil_build = sorted({v for v in px_build if v < FLOOR})
        cek(f"build: tidak ada font-size < {FLOOR}px", not kecil_build, f"langgar={kecil_build}")
        cek("build: tidak ada 10.5px", "10.5px" not in isi)
        cek("build: cell-label 11.5px", "11.5px" in isi)
else:
    cek("dist/index.html ada", False, "belum di-build - jalankan `npm run build`")

print("\n=== 6. skrip halaman benar-benar dimuat (jebakan Astro 5.18.2) ===")
# Astro 5.18.2 membuang tag <script> dari HTML hasil build kalau blok script diawali
# komentar: chunk JS tetap ditulis ke dist/_astro/, tapi tidak pernah direferensikan.
# Akibatnya semua chart kosong sementara konsol tetap bersih tanpa error, sehingga
# tidak ada gate lain yang menangkapnya. Diukur: 3/3 build gagal dengan komentar di
# baris pertama, 3/3 benar tanpa komentar, 3/3 benar dengan komentar setelah import.
if os.path.exists(DIST_HTML):
    d = baca(DIST_HTML)
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', d)
    cek("dist/index.html mereferensikan berkas JS", bool(srcs), f"{len(srcs)} tag script")

    total = 0
    ditemukan = []
    for s in srcs:
        p = os.path.join(DIST, s.lstrip("/"))
        if os.path.exists(p):
            n = os.path.getsize(p)
            total += n
            ditemukan.append(f"{os.path.basename(p)} {n}B")
    cek("semua berkas JS yang direferensikan ada di disk", len(ditemukan) == len(srcs),
        "; ".join(ditemukan))

    # Gerbang ukuran: ECharts sudah diimpor per-modul. Kalau angka ini naik jauh,
    # hampir pasti ada yang kembali mengimpor paket penuh.
    BATAS_JS = 700_000
    cek(f"bundel JS <= {BATAS_JS} B", 0 < total <= BATAS_JS, f"{total} B")

    idx = baca(os.path.join(ROOT, "dashboard", "src", "pages", "index.astro"))
    penuh = re.search(r"""import\s+\*\s+as\s+echarts\s+from\s+['"]echarts['"]""", idx)
    cek("index.astro tidak mengimpor paket penuh ECharts", penuh is None)

    m = re.search(r"<script>\r?\n(\s*)([^\r\n]*)", idx)
    awal = m.group(2).strip() if m else ""
    cek("blok script tidak diawali komentar (jebakan Astro)", not awal.startswith("//"),
        f"baris pertama: {awal[:50]!r}")

print("\n=== 7. kartu share menunjuk domain yang benar ===")
# Bug nyata yang pernah terjadi di repo ini: `site` diisi pantau-dbd.vercel.app padahal
# alias project Vercel-nya pantau-dbd-seven.vercel.app (yang polos sudah dipakai orang
# lain). Halaman tetap HTTP 200 dan konsol tetap bersih, tapi og:image menunjuk berkas
# yang tidak ada, jadi kartu share-nya kosong. Tidak ada gate lain yang menangkapnya.
CFG = os.path.join(ROOT, "dashboard", "astro.config.mjs")
if os.path.exists(DIST_HTML) and os.path.exists(CFG):
    ms = re.search(r"site:\s*['\"]([^'\"]+)['\"]", baca(CFG))
    site = ms.group(1).rstrip("/") if ms else ""
    cek("astro.config.mjs punya site absolut", site.startswith("http"), site or "tidak ada")

    d = baca(DIST_HTML)
    tag = {
        "og:url": re.search(r'og:url"\s+content="([^"]+)"', d),
        "og:image": re.search(r'og:image"\s+content="([^"]+)"', d),
        "canonical": re.search(r'rel="canonical"\s+href="([^"]+)"', d),
    }
    for nama, m in tag.items():
        val = m.group(1) if m else ""
        cek(f"{nama} memakai domain site", val == site or val.startswith(site + "/"),
            val or "tidak ada")

    # og:image dan ikon harus benar-benar ada sebagai berkas di hasil build
    if tag["og:image"] and site:
        rel = tag["og:image"].group(1)[len(site):].lstrip("/")
        cek(f"berkas og:image ada di build ({rel})",
            os.path.exists(os.path.join(DIST, rel)))

    for m in re.finditer(r'<link[^>]+rel="(?:icon|apple-touch-icon)"[^>]+href="([^"]+)"', d):
        rel = m.group(1).lstrip("/")
        cek(f"berkas ikon ada di build ({rel})", os.path.exists(os.path.join(DIST, rel)))

print("\n" + "=" * 52)
print(f"HASIL: {len(lolos)} PASS / {len(gagal)} FAIL")
if gagal:
    print("GAGAL:")
    for g in gagal:
        print(f"  - {g}")
sys.exit(1 if gagal else 0)

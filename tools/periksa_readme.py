"""Periksa README: tanda hubung terlarang, berkas gambar, dan frasa bau AI.

Ini gerbang, bukan laporan. Sebelumnya skrip ini mencetak FAIL tapi selalu keluar
dengan kode 0, jadi tidak ada yang bisa dibuat merah olehnya. Sekarang temuan
apa pun membuat exit code 1.

Berkas yang diperiksa bisa ditunjuk lewat argumen, supaya harness bisa menguji
skrip ini pada README yang sengaja dirusak tanpa menyentuh README repo.

Pakai:
    python tools/periksa_readme.py              # README repo ini
    python tools/periksa_readme.py <berkas.md>  # berkas lain
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "README.md")
teks = open(README, encoding="utf-8").read()

gagal = []


def cek(judul, syarat, info=""):
    print(f"  [{'PASS' if syarat else 'FAIL'}] {judul}" + (f": {info}" if info else ""))
    if not syarat:
        gagal.append(judul)


print(f"=== 1. tanda hubung terlarang ({os.path.basename(README)}) ===")
terlarang = {"em-dash U+2014": "\u2014", "en-dash U+2013": "\u2013",
             "minus U+2212": "\u2212", "ellipsis U+2026": "\u2026"}
for nama, ch in terlarang.items():
    cek(nama, teks.count(ch) == 0, f"{teks.count(ch)} buah")

print("\n=== 2. gambar ===")
semua = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", teks)
ref = [r for r in semua if not r.startswith(("http://", "https://"))]
for r in [r for r in semua if r.startswith(("http://", "https://"))]:
    print(f"  [SKIP] gambar remote (badge): {r[:70]}")
for r in ref:
    cek(f"dirujuk: {r}", os.path.exists(os.path.join(ROOT, r)))
dir_docs = os.path.join(ROOT, "docs")
ada_di_disk = sorted(f"docs/{f}" for f in os.listdir(dir_docs)) if os.path.isdir(dir_docs) else []
menganggur = [f for f in ada_di_disk if f not in ref]
cek(f"dipakai {len(ref)} dari {len(ada_di_disk)} berkas docs/", not menganggur,
    f"tidak dirujuk: {menganggur}" if menganggur else "")

print("\n=== 3. frasa bau AI ===")
bau = ["Dalam era", "Di era", "Selain itu", "Namun demikian", "Sebagai kesimpulan",
       "Poin penting", "Perlu dicatat bahwa", "sangat penting untuk", "tidak hanya",
       "membuka wawasan", "solusi menyeluruh", "mari kita", "bayangkan", "tak terbantahkan",
       "komprehensif", "robust dan", "seamless", "leverage", "game-changer"]
temuan = [b for b in bau if b.lower() in teks.lower()]
cek("frasa bau AI", not temuan, str(temuan or "tidak ada"))

print("\n=== 4. emoji ===")
emo = re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", teks)
cek("emoji", not emo, str(emo or "tidak ada"))

print("\n=== 5. bentuk ===")
print(f"  {len(teks)} char, {teks.count(chr(10)) + 1} baris")
judul = re.findall(r"^## (.+)$", teks, re.M)
print(f"  {len(judul)} seksi: {', '.join(judul)}")

print(f"\nHASIL: {len(gagal)} temuan")
sys.exit(1 if gagal else 0)

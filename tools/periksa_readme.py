"""Periksa README: tanda hubung terlarang, berkas gambar, dan frasa bau AI."""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(ROOT, "README.md")
teks = open(README, encoding="utf-8").read()

print("=== 1. tanda hubung terlarang ===")
terlarang = {"em-dash U+2014": "\u2014", "en-dash U+2013": "\u2013",
             "minus U+2212": "\u2212", "ellipsis U+2026": "\u2026"}
for nama, ch in terlarang.items():
    n = teks.count(ch)
    print(f"  [{'PASS' if n == 0 else 'FAIL'}] {nama}: {n}")

print("\n=== 2. gambar ===")
ref = [r for r in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", teks) if not r.startswith(("http://", "https://"))]
luar = [r for r in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", teks) if r.startswith(("http://", "https://"))]
for r in luar:
    print(f"  [SKIP] gambar remote (badge): {r[:70]}")
ada_di_disk = sorted(f"docs/{f}" for f in os.listdir(os.path.join(ROOT, "docs")))
for r in ref:
    ok = os.path.exists(os.path.join(ROOT, r))
    print(f"  [{'PASS' if ok else 'FAIL'}] dirujuk: {r}")
tidak_dirujuk = [f for f in ada_di_disk if f not in ref]
print(f"  [{'PASS' if not tidak_dirujuk else 'FAIL'}] dipakai {len(ref)} dari {len(ada_di_disk)} berkas docs/")
if tidak_dirujuk:
    print("    tidak dirujuk:", tidak_dirujuk)

print("\n=== 3. frasa bau AI ===")
bau = ["Dalam era", "Di era", "Selain itu", "Namun demikian", "Sebagai kesimpulan",
       "Poin penting", "Perlu dicatat bahwa", "sangat penting untuk", "tidak hanya",
       "membuka wawasan", "solusi menyeluruh", "mari kita", "bayangkan", "tak terbantahkan",
       "komprehensif", "robust dan", "seamless", "leverage", "game-changer"]
temuan = [b for b in bau if b.lower() in teks.lower()]
print(f"  [{'PASS' if not temuan else 'FAIL'}] frasa bau AI: {temuan or 'tidak ada'}")

print("\n=== 4. emoji ===")
emo = re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", teks)
print(f"  [{'PASS' if not emo else 'FAIL'}] emoji: {emo or 'tidak ada'}")

print("\n=== 5. bentuk ===")
print(f"  {len(teks)} char, {teks.count(chr(10)) + 1} baris")
judul = re.findall(r"^## (.+)$", teks, re.M)
print(f"  {len(judul)} seksi: {', '.join(judul)}")

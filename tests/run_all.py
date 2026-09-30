"""Jalankan semua harness kontrak dan agregasi hasilnya.

Repo ini tidak punya test runner, dan sengaja tidak menambah pytest: semua cek
adalah stdlib + polars + Pillow, dijalankan sebagai subprocess supaya satu skrip yang
mati tidak menjatuhkan yang lain, dan exit code-nya tetap benar untuk CI.

Pakai:
    python tests/run_all.py

Prasyarat: `npm run build` sudah dijalankan di dashboard/ (tiga skrip membaca dist/).
"""

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKRIP = [
    "test_export_contract.py",
    "test_dashboard_contract.py",
    "test_style_contract.py",
    "test_assets_contract.py",
]

total_pass = 0
total_fail = 0
skrip_gagal: list[str] = []
skrip_tanpa_hasil: list[str] = []

for nama in SKRIP:
    print(f"\n{'#' * 62}\n# {nama}\n{'#' * 62}")
    r = subprocess.run(
        [sys.executable, str(HERE / nama)],
        text=True, capture_output=True, encoding="utf-8", errors="replace",
    )
    print(r.stdout, end="")
    if r.stderr.strip():
        print("--- stderr ---")
        print(r.stderr[-3000:], end="")

    m = re.search(r"HASIL: (\d+) PASS / (\d+) FAIL", r.stdout)
    if m:
        total_pass += int(m.group(1))
        total_fail += int(m.group(2))
    else:
        skrip_tanpa_hasil.append(nama)
    if r.returncode != 0 and nama not in skrip_gagal:
        skrip_gagal.append(nama)

print(f"\n{'=' * 62}")
print(f"TOTAL: {total_pass} PASS / {total_fail} FAIL")
if skrip_tanpa_hasil:
    print(f"SKRIP TANPA BARIS HASIL (crash sebelum selesai): {', '.join(skrip_tanpa_hasil)}")
if skrip_gagal:
    print(f"SKRIP EXIT != 0: {', '.join(skrip_gagal)}")

# Angka di README adalah klaim yang bisa diperiksa orang lain. Kalau harness
# ditambah atau dikurangi tapi angkanya tidak ikut diperbarui, dokumentasinya
# berbohong, dan itu kegagalan yang tidak kelihatan dari mana pun. Jadi dicocokkan
# di sini, bukan diandalkan ingatan orang yang terakhir menyunting.
readme = (HERE.parent / "README.md").read_text(encoding="utf-8")
masalah: list[str] = []

m1 = re.search(r"(\d+) cek, semuanya lulus", readme)
if not m1:
    masalah.append("README tidak memuat kalimat '<N> cek, semuanya lulus'")
elif int(m1.group(1)) != total_pass:
    masalah.append(f"README bilang {m1.group(1)} cek, hasil nyata {total_pass}")

m2 = re.search(r"Hasilnya sama: (\d+) PASS / (\d+) FAIL", readme)
if not m2:
    masalah.append("README tidak memuat 'Hasilnya sama: <N> PASS / <M> FAIL'")
elif (int(m2.group(1)), int(m2.group(2))) != (total_pass, total_fail):
    masalah.append(f"README bilang {m2.group(1)} PASS / {m2.group(2)} FAIL, "
                   f"hasil nyata {total_pass} PASS / {total_fail} FAIL")

if masalah:
    print("\nANGKA DI README TIDAK COCOK DENGAN HASIL NYATA:")
    for x in masalah:
        print(f"  - {x}")
else:
    print(f"\nREADME cocok dengan hasil nyata: {total_pass} PASS / {total_fail} FAIL")

sys.exit(1 if (total_fail or skrip_gagal or skrip_tanpa_hasil or masalah) else 0)

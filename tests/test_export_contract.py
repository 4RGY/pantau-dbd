"""Kontrak pipeline -> dashboard JSON (export_dashboard.py).

Bukan suite kanonik: repo ini tidak punya test runner. Tapi skrip ini DIJALANKAN
di CI, jadi hasilnya bisa dicek siapa pun yang membuka repo, bukan cuma diklaim.

Yang diuji:
1. Modul bisa di-import, semua fungsi publik ada.
2. Jalankan export 2x -> output deterministik.
3. Skema tiap JSON sesuai kontrak yang dipakai dashboard.
4. Nilai metrik cocok dengan metrics_bulanan.json di lake (bukan disalin tangan).
5. Cross-check deret.json <-> panel_bulanan.parquet.
6. Label cuaca: hujan_bulan = bulan sama, hujan_lag1 = bulan sebelumnya.
   (regresi untuk bug "cuaca geser 1 bulan tanpa penanda")
7. Kontrol negatif: cek #6 harus diskriminatif, kalau tidak berarti tidak berguna.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
OUT = ROOT / "dashboard" / "public" / "data"
PY = sys.executable
TOL = 0.02

FILES = ["meta.json", "evaluasi.json", "deret.json", "profil.json"]

# Harness ini menjalankan export_dashboard.py, yang menulis ulang berkas di
# dashboard/public/data/. Berkas itu di-track git, jadi tanpa pemulihan ini setiap
# kali tes dijalankan working tree jadi kotor (timestamp `dibuat` berubah). Snapshot
# diambil sekarang dan dipulihkan di akhir, apa pun hasil tesnya. Di CI tidak
# berpengaruh, tapi lokal ini yang membedakan "tes aman dijalankan kapan saja" dari
# "tes meninggalkan jejak".
ASLI = {f: (OUT / f).read_bytes() for f in FILES if (OUT / f).exists()}
gagal: list[str] = []
lolos: list[str] = []


def cek(nama: str, kondisi: bool, detail: str = "") -> None:
    (lolos if kondisi else gagal).append(f"{nama}{' - ' + detail if detail else ''}")
    print(f"  [{'PASS' if kondisi else 'FAIL'}] {nama}{'  ' + detail if detail else ''}")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_export() -> int:
    r = subprocess.run(
        [PY, "-m", "pipeline.features.export_dashboard"],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
    )
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:])
    return r.returncode


print("=== 1. import & API ===")
sys.path.insert(0, str(ROOT))
from pipeline.features import export_dashboard as ed  # noqa: E402

for fn in ("meta", "evaluasi", "deret", "profil", "cuaca_bulanan", "main"):
    cek(f"fungsi {fn}() ada", callable(getattr(ed, fn, None)))

print("\n=== 2. determinisme (export 2x) ===")
with tempfile.TemporaryDirectory(prefix="pantau-dbd-verify-") as td:
    snap = Path(td) / "a"
    snap.mkdir()
    cek("run pertama exit 0", run_export() == 0)
    for f in FILES:
        shutil.copy2(OUT / f, snap / f)

    def norm(p: Path) -> dict:
        d = json.loads(p.read_text(encoding="utf-8"))
        d.pop("dibuat", None)
        return d

    cek("run kedua exit 0", run_export() == 0)
    for f in FILES:
        a, b = snap / f, OUT / f
        if f == "meta.json":
            cek(f"{f} identik (tanpa timestamp)", norm(a) == norm(b))
        else:
            cek(f"{f} byte-identical", sha(a) == sha(b), sha(b)[:12])

print("\n=== 3. skema JSON ===")
m = json.loads((OUT / "meta.json").read_text(encoding="utf-8"))
cek("meta: 12 key", len(m) == 12, str(len(m)))
for k in ("dibuat", "cakupan_kasus", "cakupan_cuaca", "metrik", "skill_vs_naive",
          "keputusan", "catatan_cuaca", "shap", "desain", "per_region",
          "jumlah_fitur", "jumlah_fitur_glm"):
    cek(f"meta.{k}", k in m)
cek("meta.dibuat ISO", isinstance(m["dibuat"], str) and "T" in m["dibuat"], m["dibuat"])
cek("meta.shap non-kosong", len(m["shap"]) > 0, f"{len(m['shap'])} fitur")
cek("meta.keputusan punya verdict", "verdict" in m["keputusan"])
cek("meta.catatan_cuaca menyebut lag", "lag" in m["catatan_cuaca"].lower())

ev = json.loads((OUT / "evaluasi.json").read_text(encoding="utf-8"))
cek("evaluasi: list", isinstance(ev, list), f"{len(ev)} baris")
keys_ev = {"w", "wilayah", "tahun", "bulan", "kasus", "pred_glm", "pred_lgbm", "naive", "fold"}
cek("evaluasi: skema baris", all(keys_ev <= set(r) for r in ev))
cek("evaluasi: 2 fold", {r["fold"] for r in ev} == {2023, 2024})

dr = json.loads((OUT / "deret.json").read_text(encoding="utf-8"))
cek("deret: 6 wilayah", len(dr) == 6, ",".join(dr))
keys_dr = {"tahun", "bulan", "kasus",
           "hujan_bulan", "suhu_bulan", "rh_bulan", "hari_hujan_bulan",
           "hujan_lag1", "suhu_lag1", "rh_lag1", "hari_hujan_lag1"}
cek("deret: skema rows (11 field)", all(keys_dr <= set(r) for v in dr.values() for r in v["rows"]))
cek("deret: tiap wilayah punya nama+pendek",
    all("nama" in v and "pendek" in v for v in dr.values()))
cek("deret: tidak ada field 'hujan' ambigu",
    not any("hujan" in r for v in dr.values() for r in v["rows"]))

pr = json.loads((OUT / "profil.json").read_text(encoding="utf-8"))
cek("profil: 3 key (catatan/satuan/bulan)", set(pr) == {"catatan", "satuan", "bulan"}, ",".join(pr))
cek("profil: 12 bulan", len(pr["bulan"]) == 12, ",".join(sorted(pr["bulan"], key=int)))
cek("profil: skema bulan",
    all({"hujan", "suhu", "rh", "hari_hujan"} <= set(v) for v in pr["bulan"].values()))
cek("profil.catatan menyebut lag-1", "lag-1" in pr["catatan"])

print("\n=== 4. metrik cocok dengan lake ===")
lake_m = json.loads((LAKE / "metrics_bulanan.json").read_text(encoding="utf-8"))
cek("metrik == lake.agregat", m["metrik"] == lake_m["agregat"])
cek("skill == lake.skill_vs_naive", m["skill_vs_naive"] == lake_m["skill_vs_naive"])
cek("keputusan == lake.keputusan", m["keputusan"] == lake_m["keputusan"])
cek("jumlah_fitur == len(lake.fitur_lgbm)", m["jumlah_fitur"] == len(lake_m["fitur_lgbm"]))

print("\n=== 5. cross-check deret <-> panel ===")
import polars as pl  # noqa: E402

panel = pl.read_parquet(LAKE / "panel_bulanan.parquet")
tot_json = sum(len(v["rows"]) for v in dr.values())
cek("total baris deret == panel", tot_json == panel.height, f"{tot_json} vs {panel.height}")
row = panel.filter(
    (pl.col("wilayah") == "jak-pus") & (pl.col("tahun") == 2024) & (pl.col("bulan") == 6)
)
jr = next(r for r in dr["jak-pus"]["rows"] if r["tahun"] == 2024 and r["bulan"] == 6)
cek("spot-check jak-pus 2024-06 kasus",
    float(row["kasus"][0]) == jr["kasus"], f"parquet={row['kasus'][0]} json={jr['kasus']}")
cek("tiap wilayah punya kasus non-null",
    all(any(r["kasus"] is not None for r in v["rows"]) for v in dr.values()))

print("\n=== 6. REGRESI: label cuaca tidak ambigu lagi ===")
cuaca = pl.read_parquet(LAKE / "cuaca_harian.parquet")
raw = (
    cuaca.with_columns([
        pl.col("tanggal").dt.year().alias("tahun"),
        pl.col("tanggal").dt.month().alias("bulan"),
    ])
    .group_by(["wilayah", "tahun", "bulan"])
    .agg(pl.col("precipitation_sum").sum().round(2).alias("hujan_mentah"))
    .with_columns((pl.col("tahun") * 12 + pl.col("bulan")).alias("periode"))
)

# hujan_bulan harus == hujan bulan yang SAMA
beda_sama = diperiksa = 0
for w, blok in dr.items():
    idx = {(r["tahun"], r["bulan"]): r["hujan_bulan"] for r in blok["rows"]}
    p = raw.filter(pl.col("wilayah") == w)
    for r in p.iter_rows(named=True):
        j = idx.get((r["tahun"], r["bulan"]))
        if j is None:
            continue
        diperiksa += 1
        if abs(j - r["hujan_mentah"]) > TOL:
            beda_sama += 1
cek("hujan_bulan == cuaca bulan SAMA", beda_sama == 0, f"{diperiksa} dicek, {beda_sama} beda")

# hujan_lag1 harus == hujan bulan SEBELUMNYA
beda_lag = diperiksa_lag = 0
for w, blok in dr.items():
    idx = {(r["tahun"], r["bulan"]): r["hujan_lag1"] for r in blok["rows"]}
    # geser periode raw +1, lalu turunkan ulang tahun/bulan DARI periode baru.
    # (kalau tahun/bulan tidak dihitung ulang, lookup-nya salah arah -> false FAIL)
    p = (
        raw.with_columns((pl.col("periode") + 1).alias("periode"))
        .with_columns([
            ((pl.col("periode") - 1) // 12).alias("tahun"),
            ((pl.col("periode") - 1) % 12 + 1).alias("bulan"),
        ])
        .filter(pl.col("wilayah") == w)
    )
    for r in p.iter_rows(named=True):
        j = idx.get((r["tahun"], r["bulan"]))
        if j is None:
            continue
        diperiksa_lag += 1
        if abs(j - r["hujan_mentah"]) > TOL:
            beda_lag += 1
cek("hujan_lag1 == cuaca bulan SEBELUMNYA", beda_lag == 0, f"{diperiksa_lag} dicek, {beda_lag} beda")

# kedua field harus benar-benar beda (bukan copy)
contoh = next(r for r in dr["jak-pus"]["rows"] if r["tahun"] == 2024 and r["bulan"] == 6)
cek("hujan_bulan != hujan_lag1 (bukan duplikat)",
    contoh["hujan_bulan"] != contoh["hujan_lag1"],
    f"bulan={contoh['hujan_bulan']} lag1={contoh['hujan_lag1']}")

print("\n=== 7. KONTROL NEGATIF (bukti cek #6 punya gigi) ===")
# Kalau hujan_lag1 dibandingkan dengan cuaca bulan SAMA, harus BANYAK yang beda.
# Kalau hasilnya 0 beda, berarti cek #6 tidak diskriminatif alias tidak berguna.
neg_beda = 0
for w, blok in dr.items():
    idx = {(r["tahun"], r["bulan"]): r["hujan_lag1"] for r in blok["rows"]}
    p = raw.filter(pl.col("wilayah") == w)
    for r in p.iter_rows(named=True):
        j = idx.get((r["tahun"], r["bulan"]))
        if j is None:
            continue
        if abs(j - r["hujan_mentah"]) > TOL:
            neg_beda += 1
cek("kontrol negatif: lag1 vs bulan-sama HARUS beda", neg_beda > 0, f"{neg_beda} beda (harus > 0)")

# pulihkan berkas yang ditulis ulang oleh export, supaya working tree tetap bersih
dipulihkan = []
for f, isi in ASLI.items():
    if (OUT / f).read_bytes() != isi:
        (OUT / f).write_bytes(isi)
        dipulihkan.append(f)
if dipulihkan:
    print(f"\n  [INFO] dipulihkan ke isi sebelum tes: {', '.join(dipulihkan)}")

print(f"\n{'=' * 46}\nHASIL: {len(lolos)} PASS / {len(gagal)} FAIL")
if gagal:
    print("\nGAGAL:")
    for g in gagal:
        print("  -", g)
    sys.exit(1)
print("SEMUA VERIFIKASI LULUS")

"""
Export data lake -> JSON ringkas untuk dashboard Astro.

Yang diekspor:
- data/meta.json         metadata run, cakupan, metrik agregat, SHAP
- data/evaluasi.json     prediksi vs aktual walk-forward (2023+2024)
- data/deret.json        deret waktu bulanan per wilayah: kasus + cuaca
- data/profil.json       profil cuaca bulanan (median historis) untuk What-If

CATATAN PENTING soal cuaca (perbaikan 2026-09-30)
--------------------------------------------------
Fitur model memakai cuaca LAG: ch_lag1 = curah hujan bulan t-1, karena forecast
dibuat saat data bulan t-1 sudah rilis (lihat pipeline/features/bangun_bulanan.py).
Itu benar untuk model.

Tapi kalau nilai lag-1 diekspor begitu saja dengan nama "hujan" lalu diplot
sejajar kasus bulan t, pembaca akan mengira itu cuaca bulan yang sama. Itu cacat
label, bukan cacat data. Sekarang kedua versi diekspor terpisah dan dinamai jelas:

  hujan_bulan / suhu_bulan / ...      = cuaca aktual bulan yang sama (untuk plot)
  hujan_lag1  / suhu_lag1  / ...      = cuaca bulan t-1, yang dipakai model
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
LAKE = ROOT / "data" / "lake"
OUT = ROOT / "dashboard" / "public" / "data"
OUT.mkdir(parents=True, exist_ok=True)

WILAYAH_ORDER = ["jak-pus", "jak-ut", "jak-bar", "jak-sel", "jak-tim", "kep-seribu"]
NAMA_WILAYAH = {
    "jak-pus": "Jakarta Pusat",
    "jak-ut": "Jakarta Utara",
    "jak-bar": "Jakarta Barat",
    "jak-sel": "Jakarta Selatan",
    "jak-tim": "Jakarta Timur",
    "kep-seribu": "Kepulauan Seribu",
}
NAMA_PENDEK = {
    "jak-pus": "Jakpus",
    "jak-ut": "Jakut",
    "jak-bar": "Jakbar",
    "jak-sel": "Jaksel",
    "jak-tim": "Jaktim",
    "kep-seribu": "Kepser",
}

CATATAN_CUACA = (
    "Fitur model memakai cuaca lag (bulan t-1 sampai t-4) karena forecast dibuat "
    "saat data bulan t-1 sudah rilis. Di dashboard, field *_bulan adalah cuaca "
    "aktual bulan yang sama dengan kasus, sedangkan *_lag1 adalah cuaca bulan "
    "sebelumnya yang benar-benar dipakai model."
)


def _f(x):
    """float atau None, tanpa mengarang nilai."""
    return None if x is None else float(x)


def _i(x):
    """int atau None."""
    return None if x is None else int(x)


def cuaca_bulanan() -> pl.DataFrame:
    """Agregat cuaca per wilayah-bulan, same-month, dihitung dari data harian.

    Dipakai untuk plot yang jujur: nilai cuaca pada bulan yang SAMA dengan kasus.
    """
    cuaca = pl.read_parquet(LAKE / "cuaca_harian.parquet")
    return (
        cuaca.with_columns(
            [
                pl.col("tanggal").dt.year().alias("tahun"),
                pl.col("tanggal").dt.month().alias("bulan"),
            ]
        )
        .group_by(["wilayah", "tahun", "bulan"])
        .agg(
            [
                pl.col("precipitation_sum").sum().round(2).alias("hujan_bulan"),
                (pl.col("precipitation_sum") >= 1.0).sum().alias("hari_hujan_bulan"),
                pl.col("temperature_2m_mean").mean().round(2).alias("suhu_bulan"),
                pl.col("relative_humidity_2m_mean").mean().round(2).alias("rh_bulan"),
            ]
        )
    )


def meta() -> dict:
    m = json.loads((LAKE / "metrics_bulanan.json").read_text())
    shap = json.loads((LAKE / "shap_bulanan.json").read_text())
    panel = pl.read_parquet(LAKE / "panel_bulanan.parquet")
    valid = panel.filter(pl.col("kasus").is_not_null())
    cuaca = pl.read_parquet(LAKE / "cuaca_harian.parquet")

    # SHAP dipetakan ke label Indonesia
    label = {
        "mo_sin": "Musim (sin)",
        "mo_cos": "Musim (cos)",
        "ch_lag1": "Curah hujan t-1",
        "ch_lag2": "Curah hujan t-2",
        "ch_lag3": "Curah hujan t-3",
        "ch_lag4": "Curah hujan t-4",
        "ch_rol3": "Rata-rata hujan 3 bln",
        "ch_rol6": "Rata-rata hujan 6 bln",
        "rh_lag1": "Kelembapan t-1",
        "tavg_lag1": "Suhu rata-rata t-1",
        "hhuj_lag1": "Hari hujan t-1",
        "kepadatan_km2": "Kepadatan penduduk",
        "wilayah_kode": "Wilayah",
    }
    shap_feats = [
        {
            "kode": f["nama"],
            "label": label.get(f["nama"], f["nama"]),
            "mean_abs": f["mean_abs"],
        }
        for f in shap["features"]
    ]

    return {
        "dibuat": None,  # diisi di main()
        "cakupan_kasus": {
            "mulai": f"{valid['tahun'].min()}-{valid['bulan'].min():02d}",
            "akhir": f"{valid['tahun'].max()}-{valid['bulan'].max():02d}",
            "n_baris": valid.height,
        },
        "cakupan_cuaca": {
            "mulai": str(cuaca["tanggal"].min()),
            "akhir": str(cuaca["tanggal"].max()),
            "n_hari": cuaca.height,
        },
        "metrik": m["agregat"],
        "skill_vs_naive": m["skill_vs_naive"],
        "keputusan": m["keputusan"],
        "catatan_cuaca": CATATAN_CUACA,
        "shap": shap_feats,
        "desain": m["desain"],
        "per_region": m["per_region"],
        "jumlah_fitur": len(m["fitur_lgbm"]),
        "jumlah_fitur_glm": len(m["fitur_glm"]),
    }


def evaluasi() -> list[dict]:
    df = pl.read_csv(LAKE / "eval_bulanan.csv")
    df = df.sort(["wilayah", "tahun", "bulan"])
    return [
        {
            "w": NAMA_PENDEK[r["wilayah"]],
            "wilayah": NAMA_WILAYAH[r["wilayah"]],
            "tahun": r["tahun"],
            "bulan": r["bulan"],
            "kasus": r["kasus"],
            "pred_glm": r["pred_glm"],
            "pred_lgbm": r["pred_lgbm"],
            "naive": r["kasus_lag1"],
            "fold": r["fold"],
        }
        for r in df.iter_rows(named=True)
    ]


def deret() -> dict:
    panel = pl.read_parquet(LAKE / "panel_bulanan.parquet")
    same = cuaca_bulanan()
    panel = panel.join(same, on=["wilayah", "tahun", "bulan"], how="left")
    panel = panel.sort(["wilayah", "periode"])
    out = {}
    for w in WILAYAH_ORDER:
        sub = panel.filter(pl.col("wilayah") == w)
        out[w] = {
            "nama": NAMA_WILAYAH[w],
            "pendek": NAMA_PENDEK[w],
            "rows": [
                {
                    "tahun": r["tahun"],
                    "bulan": r["bulan"],
                    "kasus": _f(r["kasus"]),
                    # cuaca aktual bulan yang sama (untuk plot)
                    "hujan_bulan": _f(r["hujan_bulan"]),
                    "suhu_bulan": _f(r["suhu_bulan"]),
                    "rh_bulan": _f(r["rh_bulan"]),
                    "hari_hujan_bulan": _i(r["hari_hujan_bulan"]),
                    # cuaca bulan t-1, yang dipakai model
                    "hujan_lag1": _f(r["ch_lag1"]),
                    "suhu_lag1": _f(r["tavg_lag1"]),
                    "rh_lag1": _f(r["rh_lag1"]),
                    "hari_hujan_lag1": _i(r["hhuj_lag1"]),
                }
                for r in sub.iter_rows(named=True)
            ],
        }
    return out


def profil() -> dict:
    """Profil cuaca bulanan historis (median 2021-2025) untuk simulasi What-If.

    Nilainya adalah cuaca bulan t-1 (lag-1), persis seperti input yang dipakai
    model saat memprediksi bulan t. Karena itu ada catatan eksplisit di output.
    """
    panel = pl.read_parquet(LAKE / "panel_bulanan.parquet")
    with_ch = panel.filter(
        pl.col("ch_lag1").is_not_null() & (pl.col("tahun").is_between(2021, 2025))
    )
    aggs = (
        with_ch.group_by("bulan")
        .agg(
            [
                pl.col("ch_lag1").median().round(1).alias("hujan_median"),
                pl.col("tavg_lag1").median().round(2).alias("suhu_median"),
                pl.col("rh_lag1").median().round(1).alias("rh_median"),
                pl.col("hhuj_lag1").median().alias("hari_hujan_median"),
            ]
        )
        .sort("bulan")
    )
    return {
        "catatan": (
            "Median historis 2021-2025 per bulan kalender. Nilainya cuaca bulan t-1 "
            "(lag-1), sama seperti input yang dipakai model untuk memprediksi bulan t."
        ),
        "satuan": {
            "hujan": "mm per bulan",
            "suhu": "derajat Celsius",
            "rh": "persen",
            "hari_hujan": "hari",
        },
        "bulan": {
            str(r["bulan"]): {
                "hujan": r["hujan_median"],
                "suhu": r["suhu_median"],
                "rh": r["rh_median"],
                "hari_hujan": r["hari_hujan_median"],
            }
            for r in aggs.iter_rows(named=True)
        },
    }


def main():
    from datetime import datetime, timezone

    meta_json = meta()
    meta_json["dibuat"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    (OUT / "meta.json").write_text(json.dumps(meta_json, indent=2, ensure_ascii=False))
    (OUT / "evaluasi.json").write_text(json.dumps(evaluasi(), indent=1, ensure_ascii=False))
    (OUT / "deret.json").write_text(json.dumps(deret(), indent=1, ensure_ascii=False))
    (OUT / "profil.json").write_text(json.dumps(profil(), indent=1, ensure_ascii=False))

    for f in sorted(OUT.glob("*.json")):
        print(f"  {f.name:20s} {f.stat().st_size/1024:7.1f} KB")
    print(f"\nekspor ke {OUT}")


if __name__ == "__main__":
    main()

"""
Export data lake -> JSON ringkas untuk dashboard Astro.

Yang diekspor:
- data/meta.json         metadata run, cakupan, metrik agregat, SHAP
- data/evaluasi.json     prediksi vs aktual walk-forward (2023+2024)
- data/deret.json        deret waktu bulanan per wilayah: kasus + cuaca
- data/profil.json       profil cuaca bulanan (rata-rata historis) untuk What-If
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
        "dibuat": None,  # diisi di bawah
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
                    "kasus": None if r["kasus"] is None else float(r["kasus"]),
                    "hujan": None if r["ch_lag1"] is None else float(r["ch_lag1"]),
                    "suhu": None if r["tavg_lag1"] is None else float(r["tavg_lag1"]),
                    "rh": None if r["rh_lag1"] is None else float(r["rh_lag1"]),
                    "hari_hujan": None if r["hhuj_lag1"] is None else int(r["hhuj_lag1"]),
                }
                for r in sub.iter_rows(named=True)
            ],
        }
    return out


def profil() -> dict:
    """Profil cuaca bulanan historis (median 2021-2025) untuk simulasi What-If."""
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
        str(r["bulan"]): {
            "hujan": r["hujan_median"],
            "suhu": r["suhu_median"],
            "rh": r["rh_median"],
            "hari_hujan": r["hari_hujan_median"],
        }
        for r in aggs.iter_rows(named=True)
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

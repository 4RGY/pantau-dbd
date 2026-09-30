"""
Export koefisien GLM final + contoh prediksi 1 langkah (Jan 2025).

- koefisien.json : intercept + koefisien fitur GLM rasio (untuk simulasi
  What-If di dashboard; simulasi jalan di client pakai koefisien asli model)
- contoh_prediksi.json : prediksi Jan 2025 per wilayah, dihitung model final
  dengan jangkar kasus Des 2024 (aktual) + cuaca real
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import polars as pl
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parents[2]
LAKE = ROOT / "data" / "lake"
MODEL_DIR = ROOT / "models"
OUT = ROOT / "dashboard" / "public" / "data"

FITUR = [
    "ch_lag1", "ch_lag2", "ch_lag3", "ch_lag4",
    "ch_rol3", "ch_rol6",
    "rh_lag1", "tavg_lag1", "hhuj_lag1",
    "mo_sin", "mo_cos",
]
WILAYAH_CODE = {w: i for i, w in enumerate(["jak-pus", "jak-ut", "jak-bar", "jak-sel", "jak-tim", "kep-seribu"])}
NAMA_WILAYAH = {
    "jak-pus": "Jakarta Pusat", "jak-ut": "Jakarta Utara", "jak-bar": "Jakarta Barat",
    "jak-sel": "Jakarta Selatan", "jak-tim": "Jakarta Timur", "kep-seribu": "Kepulauan Seribu",
}


def main():
    with open(MODEL_DIR / "dbd_glm_ratio.pkl", "rb") as f:
        obj = pickle.load(f)
    glm = obj["model"]
    cols = obj["fitur"]

    koef = {"const": float(glm.params[0])}
    for i, c in enumerate(cols):
        koef[c] = float(glm.params[i + 1])
    (OUT / "koefisien.json").write_text(json.dumps(koef, indent=2))
    print("koefisien.json ditulis:", {k: round(v, 4) for k, v in list(koef.items())[:6]})

    # ---- contoh prediksi Jan 2025 (periode 2025*12+1 = 24301)
    panel = pl.read_parquet(LAKE / "panel_bulanan.parquet")
    baris = panel.filter(pl.col("periode") == 2025 * 12 + 1)
    print(f"baris Jan 2025: {baris.height}")

    rows_out = []
    if baris.height == 6:
        # jangkar kasus_lag1 = kasus Des 2024
        anchors = {}
        for r in baris.iter_rows(named=True):
            anchors[r["wilayah"]] = r["kasus_lag1"]
            x = [koef["const"]]
            for c in FITUR:
                v = r.get(c)
                if v is None:
                    x = None
                    break
                x.append(float(v))
            if x is None:
                print(f"  fitur kurang utk {r['wilayah']}, skip")
                continue
            x.append(float(WILAYAH_CODE[r["wilayah"]]))
            ratio = float(glm.predict(np.array([x]))[0])
            pred = (float(r["kasus_lag1"]) + 1.0) * np.exp(ratio) - 1.0
            rows_out.append(
                {
                    "wilayah": r["wilayah"],
                    "nama": NAMA_WILAYAH[r["wilayah"]],
                    "jangkar_kasus": float(r["kasus_lag1"]),
                    "hujan_bulan_lalu": float(r["ch_lag1"]),
                    "ratio_pred": round(ratio, 4),
                    "pred_kasus": round(float(pred), 1),
                    "naive": float(r["kasus_lag1"]),
                }
            )
            print(
                f"  {NAMA_WILAYAH[r['wilayah']]:20s} jangkar={float(r['kasus_lag1']):7.1f} "
                f"ratio={ratio:+.3f} pred={pred:8.1f}"
            )
    (OUT / "contoh_prediksi.json").write_text(json.dumps(rows_out, indent=2, ensure_ascii=False))
    print(f"contoh_prediksi.json: {len(rows_out)} wilayah")


if __name__ == "__main__":
    main()

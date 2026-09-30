"""Training LightGBM + walk-forward validation + SHAP + export prediksi.

Desain evaluasi (jujur, tanpa leakage):
- target: log1p(kasus mingguan) -> prediksi dikembalikan ke skala kasus
- fitur: hanya cuaca minggu <= t-4 + kalender + demografi statis
- walk-forward: train 2021-2022 -> test 2023; train 2021-2023 -> test 2024
- baseline pembanding: naive lag-4 dan seasonal (minggu sama tahun lalu)
- final model dilatih di seluruh data valid, dipakai untuk forecast live
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
LAKE = ROOT / "data" / "lake"
MODEL_DIR = ROOT / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

import lightgbm as lgb

WILAYAH_ORDER = ["jak-pus", "jak-ut", "jak-bar", "jak-sel", "jak-tim", "kep-seribu"]
WILAYAH_CODE = {w: i for i, w in enumerate(WILAYAH_ORDER)}

FEATURE_PREFIXES = (
    "ch_", 
    "rh_", 
    "tavg_", 
    "tmin_", 
    "tmax_", 
    "hhuj_", 
    "woy_"
)

def daftar_fitur(panel: pl.DataFrame) -> list[str]:
    cols = [c for c in panel.columns if c.startswith(FEATURE_PREFIXES)]
    cols += ["pop_ribu", "kepadatan_km2"]
    return sorted(cols)

def siapkan_matrix(panel: pl.DataFrame, fitur: list[str]):
    X = panel.select(fitur).to_pandas().copy()
    X["wilayah_kode"] = panel["wilayah"].replace(WILAYAH_CODE).cast(pl.Int8).to_list()
    cols = fitur + ["wilayah_kode"]
    X = X[cols]
    return X, cols

def smape(y, p):
    y = np.asarray(y, dtype=float)
    p = np.clip(np.asarray(p, dtype=float), 0, None)
    denom = (np.abs(y) + np.abs(p)) / 2
    mask = denom > 1e-9
    return float(np.mean(np.abs(y[mask] - p[mask]) / denom[mask]) * 100)

def metrik(y, p):
    y = np.asarray(y, dtype=float)
    p = np.clip(np.asarray(p, dtype=float), 0, None)
    return {
        "mae": float(np.mean(np.abs(y - p))),
        "rmse": float(np.sqrt(np.mean((y - p) ** 2))),
        "smape": smape(y, p),
        "pearson_r": float(np.corrcoef(y, p)[0, 1]) if np.std(y) > 0 else None,
        "n": int(len(y)),
    }

def latih_fold(X_tr, y_tr):
    """Latih di RUANG KASUS langsung.

    Sebelumnya target = log1p(kasus) lalu prediksi di-expm1(). Itu bias:
    expm1(E[log1p(y)]) != E[y] (Jensen), dan early-stopping di ruang log
    berhenti sebelum mean tercapai -> under-prediksi sistematis ~45%.
    Objektif huber tahan terhadap lonjakan outbreak mingguan.
    """
    params = dict(
        objective="huber",
        alpha=5.0,
        metric="l1",
        learning_rate=0.03,
        num_leaves=15,
        min_data_in_leaf=25,
        feature_fraction=0.8,
        bagging_fraction=0.8,
        bagging_freq=1,
        lambda_l2=1.0,
        verbosity=-1,
        seed=42,
    )
    # validasi internal: 20% terakhir (time-ordered) dari train
    n_va = max(int(len(y_tr) * 0.2), 40)
    tr_i = list(range(len(y_tr) - n_va))
    va_i = list(range(len(y_tr) - n_va, len(y_tr)))
    dtr = lgb.Dataset(X_tr.iloc[tr_i], label=y_tr[tr_i])
    dva = lgb.Dataset(X_tr.iloc[va_i], label=y_tr[va_i])
    return lgb.train(
        params, dtr, num_boost_round=2000, valid_sets=[dva],
        callbacks=[lgb.early_stopping(80, verbose=False), lgb.log_evaluation(0)],
    )

def main() -> None:
    panel = pl.read_parquet(LAKE / "panel_mingguan.parquet")
    fitur = daftar_fitur(panel)
    print(f"fitur: {len(fitur)} kolom")

    panel = panel.with_columns(
        [
            pl.col("tanggal_mulai").dt.year().alias("thn"),
            pl.col("wilayah").replace_strict(WILAYAH_CODE).cast(pl.Int8).alias("wilayah_kode"),
        ]
    )
    valid = panel.filter(pl.col("kasus").is_not_null())
    print(f"baris valid (dgn kasus): {valid.height}")

    X, cols = siapkan_matrix(valid, fitur)
    y = valid["kasus"].to_numpy().astype(float)

    hasil_rows = []
    folds = [(2023, [2021, 2022]), (2024, [2021, 2022, 2023])]
    model_fold = None
    for tahun_test, tahun_train in folds:
        mask_tr = valid["thn"].to_numpy() <= max(tahun_train)
        mask_te = valid["thn"].to_numpy() == tahun_test
        booster = latih_fold(X[mask_tr], y[mask_tr])
        pred = booster.predict(X[mask_te])
        sub = (
            valid.filter(pl.col("thn") == tahun_test)
            .with_row_index("row")
            .with_columns(pl.Series("pred", np.round(pred, 2)))
        )
        hasil_rows.append(
            sub.select(
                [
                    pl.lit(tahun_test).alias("fold"),
                    "wilayah",
                    "tanggal_mulai",
                    "kasus",
                    "pred",
                    "baseline_lag4",
                    "baseline_seasonal",
                ]
            )
        )
        m = metrik(sub["kasus"].to_numpy(), pred)
        # bandingkan baseline di baris yang baseline-nya ada
        cmp = sub.filter(pl.col("baseline_lag4").is_not_null())
        mb = metrik(cmp["kasus"].to_numpy(), cmp["baseline_lag4"].to_numpy())
        mp = metrik(cmp["kasus"].to_numpy(), cmp["pred"].to_numpy())
        skill = 1 - mp["mae"] / mb["mae"] if mb["mae"] > 0 else None
        print(
            f"fold test {tahun_test}: MAE={m['mae']:.2f}  "
            f"vs naive-lag4 MAE={mb['mae']:.2f} (skill {skill:+.1%}, n={cmp.height})"
        )
        model_fold = booster

    hasil = pl.concat(hasil_rows)
    hasil.write_csv(LAKE / "eval_predictions.csv")

    # agregat
    agg = {
        "lgbm": metrik(hasil["kasus"].to_numpy(), hasil["pred"].to_numpy()),
        "naive_lag4": metrik(hasil["kasus"].to_numpy(), hasil["baseline_lag4"].to_numpy()),
    }
    # seasonal baseline if present
    if "baseline_seasonal" in hasil.columns:
        agg["seasonal"] = metrik(hasil["kasus"].to_numpy(), hasil["baseline_seasonal"].to_numpy())

    print("\n=== agregat (walk-forward 2023 + 2024) ===")
    for k, v in agg.items():
        print(f"  {k:15s}: MAE={v['mae']:8.2f}  RMSE={v['rmse']:8.2f}  r={v['pearson_r']}  sMAPE={v['smape']}%")
    # overall skill vs naive-lag4
    if "naive_lag4" in agg:
        sk = 1 - agg["lgbm"]["mae"] / agg["naive_lag4"]["mae"]
        print(f"  skill lgbm vs naive-lag4: {sk:+.1%}")

    # ---------------- final model di seluruh data valid
    booster_final = latih_fold(X, y)
    booster_final.save_model(str(MODEL_DIR / "dbd_lgbm.txt"))

    # metrik agregat
    y_all = hasil["kasus"].to_numpy()
    p_all = hasil["pred"].to_numpy()
    agg_model = metrik(y_all, p_all)
    cmp_all = hasil.filter(pl.col("baseline_lag4").is_not_null())
    agg_naive = metrik(cmp_all["kasus"].to_numpy(), cmp_all["baseline_lag4"].to_numpy())
    agg_model_cmp = metrik(cmp_all["kasus"].to_numpy(), cmp_all["pred"].to_numpy())
    agg_season = (
        metrik(
            cmp_all.filter(pl.col("baseline_seasonal").is_not_null())["kasus"].to_numpy(),
            cmp_all.filter(pl.col("baseline_seasonal").is_not_null())["baseline_seasonal"].to_numpy(),
        )
        if cmp_all.filter(pl.col("baseline_seasonal").is_not_null()).height > 0
        else None
    )
    per_region = {}
    for w in WILAYAH_ORDER:
        reg = hasil.filter((pl.col("wilayah") == w) & pl.col("baseline_lag4").is_not_null())
        if reg.height > 0:
            per_region[w] = {
                "model": metrik(reg["kasus"].to_numpy(), reg["pred"].to_numpy()),
                "naive": metrik(reg["kasus"].to_numpy(), reg["baseline_lag4"].to_numpy()),
            }
    metrics = {
        "model": agg_model,
        "model_pada_subset_baseline": agg_model_cmp,
        "naive_lag4": agg_naive,
        "seasonal": agg_season,
        "skill_vs_naive": 1 - agg_model_cmp["mae"] / agg_naive["mae"],
        "per_region": per_region,
    }
    (LAKE / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in metrics.items() if k != "per_region"}, indent=2))

    # ---------------- SHAP pada model final
    import shap

    explainer = shap.TreeExplainer(booster_final)
    sv = explainer.shap_values(X)
    imp = np.abs(sv).mean(axis=0)
    pairs = sorted(zip(cols, imp), key=lambda t: -t[1])[:26]
    shap_out = {"features": [{"nama": n, "mean_abs": round(float(v), 4)} for n, v in pairs]}
    (LAKE / "shap_importance.json").write_text(json.dumps(shap_out, indent=2))
    print("top-5 SHAP:", [n for n, _ in pairs[:5]])

    print("selesai: eval_predictions.csv, metrics.json, shap_importance.json, models/")

if __name__ == "__main__":
    main()
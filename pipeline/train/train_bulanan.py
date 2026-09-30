"""
Training final: prediksi RASIO PERTUMBUHAN kasus DBD.

Target: y = log((kasus_t + 1) / (kasus_lag1 + 1))
Prediksi kasus: (kasus_lag1 + 1) * exp(pred) - 1

Kenapa bukan prediksi level langsung:
- 2024 tahun epidemi (KLB nasional); tree gak bisa ekstrapolasi level di luar
  range training. Rasio menghilangkan masalah itu: prediksi selalu jangkar
  di kasus bulan lalu, model hanya belajar arah + magnitude relatif dari
  cuaca + musim.
- Ini juga desain yang dipakai literatur EWS dengue (growth-rate forecasting).

Pembanding: naive-1, seasonal-12, NB-GLM dengan log(lag1) sebagai regressor.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
LAKE = ROOT / "data" / "lake"
MODEL_DIR = ROOT / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

import lightgbm as lgb
import statsmodels.api as sm

WILAYAH_ORDER = ["jak-pus", "jak-ut", "jak-bar", "jak-sel", "jak-tim", "kep-seribu"]
WILAYAH_CODE = {w: i for i, w in enumerate(WILAYAH_ORDER)}
NAMA_WILAYAH = {
    "jak-pus": "Jakarta Pusat",
    "jak-ut": "Jakarta Utara",
    "jak-bar": "Jakarta Barat",
    "jak-sel": "Jakarta Selatan",
    "jak-tim": "Jakarta Timur",
    "kep-seribu": "Kepulauan Seribu",
}

# fitur cuaca: lag 1-4 bulan (semua diketahui saat forecast bulan t dibuat)
# GLM memakai subset PARSIMONI (non-collinear) -> koefisien interpretable
# LGBM tetap pakai semua untuk comparison
FITUR_LGBM = [
    "ch_lag1", "ch_lag2", "ch_lag3", "ch_lag4",
    "ch_rol3", "ch_rol6",
    "rh_lag1", "tavg_lag1", "hhuj_lag1",
    "mo_sin", "mo_cos",
]
FITUR_GLM = [
    "ch_lag1",        # curah hujan bulan lalu (efek langsung)
    "ch_rol3",        # rata-rata 3 bulan (akumulasi)
    "rh_lag1",        # kelembapan
    "tavg_lag1",      # suhu
    "mo_sin", "mo_cos",  # musim
]


def metrik(y, p):
    y = np.asarray(y, dtype=float)
    p = np.clip(np.asarray(p, dtype=float), 0, None)
    denom = (np.abs(y) + np.abs(p)) / 2
    mask = denom > 1e-9
    out = {
        "mae": round(float(np.mean(np.abs(y - p))), 2),
        "rmse": round(float(np.sqrt(np.mean((y - p) ** 2))), 2),
        "n": int(len(y)),
    }
    out["smape_pct"] = (
        round(float(np.mean(np.abs(y[mask] - p[mask]) / denom[mask]) * 100), 2)
        if int(np.sum(mask)) > 0
        else None
    )
    out["pearson_r"] = (
        round(float(np.corrcoef(y, p)[0, 1]), 4)
        if np.std(y) > 0 and np.std(p) > 0
        else None
    )
    return out


def latih_lgbm(X_tr, y_tr):
    params = dict(
        objective="regression",
        metric="l1",
        learning_rate=0.04,
        num_leaves=7,
        min_data_in_leaf=25,
        feature_fraction=0.75,
        bagging_fraction=0.75,
        bagging_freq=1,
        lambda_l2=3.0,
        verbosity=-1,
        seed=42,
    )
    n_va = max(int(len(y_tr) * 0.25), 24)
    dtr = lgb.Dataset(X_tr.iloc[: -n_va], label=y_tr[:-n_va])
    dva = lgb.Dataset(X_tr.iloc[-n_va:], label=y_tr[-n_va:])
    return lgb.train(
        params, dtr, num_boost_round=1200, valid_sets=[dva],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(0)],
    )


def prediksi_dari_ratio(ratio_pred, kasus_lag1):
    return np.clip((np.asarray(kasus_lag1, float) + 1.0) * np.exp(ratio_pred) - 1.0, 0, None)


def main():
    panel = pl.read_parquet(LAKE / "panel_bulanan.parquet")

    # baris valid: punya kasus t dan kasus_lag1 (anchor AR)
    valid = panel.filter(
        pl.col("kasus").is_not_null() & pl.col("kasus_lag1").is_not_null()
    ).drop_nulls(FITUR_LGBM)
    print(f"baris modeling: {valid.height} (dari {panel.filter(pl.col('kasus').is_not_null()).height} baris berkasus)")

    X_pd = valid.select(FITUR_LGBM).to_pandas().copy()
    X_pd["wilayah_kode"] = valid["wilayah"].replace(WILAYAH_CODE).to_numpy().astype(np.int8)
    cols_lgbm = FITUR_LGBM + ["wilayah_kode"]
    X_pd = X_pd[cols_lgbm]

    X_glm = valid.select(FITUR_GLM).to_pandas().copy()
    X_glm["log_anchor"] = np.log(valid["kasus_lag1"].to_numpy().astype(float) + 1.0)
    cols_glm = FITUR_GLM + ["log_anchor"]
    X_glm = X_glm[cols_glm]

    kasus = valid["kasus"].to_numpy().astype(float)
    kasus_lag1 = valid["kasus_lag1"].to_numpy().astype(float)
    y_ratio = np.log((kasus + 1.0) / (kasus_lag1 + 1.0))
    tahun = valid["tahun"].to_numpy()

    folds = [(2023, [2021, 2022]), (2024, [2021, 2022, 2023])]

    all_rows = []
    for tahun_test, tahun_train in folds:
        mask_tr = np.isin(tahun, tahun_train)
        mask_te = tahun == tahun_test

        # --- LGBM pada target rasio
        booster = latih_lgbm(X_pd[mask_tr], y_ratio[mask_tr])
        ratio_pred = booster.predict(X_pd[mask_te])
        pred_lgbm = prediksi_dari_ratio(ratio_pred, kasus_lag1[mask_te])

        # --- GLM pada target rasio (fitur PARSIMONI + log anchor)
        glm = None
        try:
            Xc = sm.add_constant(X_glm[mask_tr].to_numpy(dtype=float))
            glm = sm.GLM(y_ratio[mask_tr], Xc, family=sm.families.Gaussian()).fit(maxiter=200, disp=0)
        except Exception as exc:  # noqa: BLE001
            print(f"  [GLM] gagal: {exc}")
        if glm is not None:
            ratio_glm = glm.predict(sm.add_constant(X_glm[mask_te].to_numpy(dtype=float)))
            pred_glm = prediksi_dari_ratio(ratio_glm, kasus_lag1[mask_te])
        else:
            pred_glm = np.full(mask_te.sum(), np.nan)

        sub = valid.filter(pl.col("tahun") == tahun_test).with_columns(
            [
                pl.lit(tahun_test).alias("fold"),
                pl.Series("pred_lgbm", np.round(pred_lgbm, 1)),
                pl.Series("pred_glm", np.round(pred_glm, 1)),
            ]
        )
        all_rows.append(
            sub.select(
                ["fold", "wilayah", "tahun", "bulan", "kasus", "kasus_lag1", "kasus_lag12", "pred_lgbm", "pred_glm"]
            )
        )

        m_lgbm = metrik(kasus[mask_te], pred_lgbm)
        m_naive = metrik(kasus[mask_te], kasus_lag1[mask_te])
        cmp12 = ~np.isnan(valid.filter(pl.col("tahun") == tahun_test)["kasus_lag12"].to_numpy())
        m_seas = metrik(kasus[mask_te][cmp12], valid.filter(pl.col("tahun") == tahun_test)["kasus_lag12"].to_numpy()[cmp12]) if cmp12.sum() > 0 else None
        line = f"fold {tahun_test}: LGBM MAE={m_lgbm['mae']} | naive1 MAE={m_naive['mae']}"
        if m_seas:
            line += f" | seas12 MAE={m_seas['mae']}"
        if glm is not None:
            m_glm = metrik(kasus[mask_te], pred_glm)
            line += f" | GLM MAE={m_glm['mae']}"
        print(line)

    hasil = pl.concat(all_rows, how="vertical_relaxed")
    hasil.write_csv(LAKE / "eval_bulanan.csv")

    # agregat
    agg = {
        "lgbm": metrik(hasil["kasus"].to_numpy(), hasil["pred_lgbm"].to_numpy()),
        "naive_lag1": metrik(hasil["kasus"].to_numpy(), hasil["kasus_lag1"].to_numpy()),
    }
    if not np.any(np.isnan(hasil["pred_glm"].to_numpy())):
        agg["glm_ratio"] = metrik(hasil["kasus"].to_numpy(), hasil["pred_glm"].to_numpy())
    seas = hasil.filter(pl.col("kasus_lag12").is_not_null())
    if seas.height > 0:
        agg["seasonal_lag12"] = metrik(seas["kasus"].to_numpy(), seas["kasus_lag12"].to_numpy())

    # ---- honest skill check: apakah model benar-benar mengalahkan naive?
    # Ablation (data/lake/ablation_bulanan.json) menunjukkan ablasi fitur
    # menggeser MAE hanya dalam rentang noise, jadi gate ini memakai
    # signifikansi relatif sederhana thd baseline terkuat.
    base_mae = min(agg[k]["mae"] for k in ("naive_lag1", "seasonal_lag12") if k in agg)
    best_model = min(("lgbm", "glm_ratio"), key=lambda k: agg[k]["mae"] if k in agg else np.inf)
    skill = 1 - agg[best_model]["mae"] / base_mae
    keputusan = {
        "baseline_terkuat_mae": base_mae,
        "model_terbaik": best_model,
        "skill_vs_baseline": round(float(skill), 4),
        "verdict": "mengalahkan baseline" if skill > 0.02 else (
            "setara baseline (dalam noise)" if skill > -0.02 else "KALAH dari baseline"
        ),
        "catatan": (
            "Ablasi fitur (cuaca-only / musim-only / penuh) menggeser MAE hanya "
            "dalam rentang noise; lonjakan DBD Maret & Juni tidak terbaca dari "
            "cuaca t-4. Jangan klaim early warning sampai skill > 2%."
        ),
    }

    print("\n=== agregat (walk-forward 2023 + 2024) ===")
    for k, v in agg.items():
        print(f"  {k:15s}: MAE={v['mae']:8.2f}  RMSE={v['rmse']:8.2f}  r={v['pearson_r']}  sMAPE={v['smape_pct']}%")
    for k in ("lgbm", "glm_ratio"):
        if k in agg:
            sk = 1 - agg[k]["mae"] / agg["naive_lag1"]["mae"]
            print(f"  skill {k} vs naive-1: {sk:+.1%}")

    # ---- model final di seluruh data valid
    booster_final = latih_lgbm(X_pd, y_ratio)
    booster_final.save_model(str(MODEL_DIR / "dbd_lgbm_ratio.txt"))

    # GLM final (fitur parsimoni + log anchor, seluruh data valid)
    glm_final = sm.GLM(
        y_ratio, sm.add_constant(X_glm.to_numpy(dtype=float)), family=sm.families.Gaussian()
    ).fit(maxiter=200, disp=0)
    with open(MODEL_DIR / "dbd_glm_ratio.pkl", "wb") as f:
        pickle.dump({"model": glm_final, "fitur": cols_glm}, f)

    # SHAP pada model final
    import shap

    sv = shap.TreeExplainer(booster_final).shap_values(X_pd)
    imp = np.abs(sv).mean(axis=0)
    pairs = sorted(zip(cols_lgbm, imp), key=lambda t: -t[1])[:20]
    shap_out = {"features": [{"nama": n, "mean_abs": round(float(v), 5)} for n, v in pairs]}
    (LAKE / "shap_bulanan.json").write_text(json.dumps(shap_out, indent=2))
    print("\ntop-5 SHAP:", [n for n, _ in pairs[:5]])

    # per-region metrik (buat transparansi)
    per_region = {}
    for w in WILAYAH_ORDER:
        reg = hasil.filter(pl.col("wilayah") == w)
        if reg.height > 0:
            per_region[NAMA_WILAYAH[w]] = {
                "model": metrik(reg["kasus"].to_numpy(), reg["pred_lgbm"].to_numpy()),
                "naive": metrik(reg["kasus"].to_numpy(), reg["kasus_lag1"].to_numpy()),
            }

    metrics = {
        "agregat": agg,
        "skill_vs_naive": round(1 - agg["lgbm"]["mae"] / agg["naive_lag1"]["mae"], 4),
        "keputusan": keputusan,
        "fitur_lgbm": cols_lgbm,
        "fitur_glm": cols_glm,
        "per_region": per_region,
        "desain": {
            "target": "log((kasus_t+1)/(kasus_lag1+1))",
            "basis": "growth-rate forecasting, anchored AR",
            "fold": "train 2021-2022 test 2023; train 2021-2023 test 2024",
        },
    }
    (LAKE / "metrics_bulanan.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    print("\nselesai: eval_bulanan.csv, metrics_bulanan.json, shap_bulanan.json, models/")


if __name__ == "__main__":
    main()
"""
Panel bulanan: level asli data kasus Dinkes DKI (tanpa disagregasi artifisial).

Desain information cutoff:
- forecast dibuat saat data bulan t-1 sudah dirilis (akhir bulan t-1)
- fitur: cuaca bulan t-1..t-4, kasus bulan t-1 (AR), kasus bulan t-12
  (seasonal), kalender bulan, demografi statis
- target: kasus bulan t  -> horizon efektif ~4 minggu
"""

from __future__ import annotations

import polars as pl

from pipeline.features.bangun_dataset import (
    LAKE,
    muat_cuaca_harian,
    muat_kasus_bulanan,
    muat_populasi,
)


def bulanan_cuaca() -> pl.DataFrame:
    cuaca = muat_cuaca_harian()
    df = cuaca.with_columns(
        [
            pl.col("tanggal").dt.year().alias("y"),
            pl.col("tanggal").dt.month().alias("m"),
        ]
    )
    aggs = [
        pl.col("precipitation_sum").sum().round(2).alias("curah_hujan_mm"),
        pl.col("precipitation_sum").mean().round(2).alias("ch_harian_mean"),
        (pl.col("precipitation_sum") >= 1.0).sum().alias("hari_hujan"),
        pl.col("temperature_2m_max").mean().round(2).alias("suhu_max_c"),
        pl.col("temperature_2m_min").mean().round(2).alias("suhu_min_c"),
        pl.col("temperature_2m_mean").mean().round(2).alias("suhu_mean_c"),
        pl.col("relative_humidity_2m_mean").mean().round(2).alias("kelembapan_pct"),
    ]
    out = df.group_by(["wilayah", "y", "m"]).agg(aggs)
    out = out.rename({"y": "tahun", "m": "bulan"})
    # periode = tahun*12+bulan supaya lag bulanan gampang
    out = out.with_columns((pl.col("tahun") * 12 + pl.col("bulan")).alias("periode"))
    return out.sort(["wilayah", "periode"])


def buat_fitur_lag(cuaca_bl: pl.DataFrame) -> pl.DataFrame:
    """Fitur cuaca bulan t-1..t-4 (self-join via periode shift)."""
    base = cuaca_bl.select(
        ["wilayah", "periode", "curah_hujan_mm", "kelembapan_pct", "suhu_mean_c", "hari_hujan"]
    )
    out = cuaca_bl.select(["wilayah", "periode"])
    cols_map = {
        "curah_hujan_mm": "ch",
        "kelembapan_pct": "rh",
        "suhu_mean_c": "tavg",
        "hari_hujan": "hhuj",
    }
    for lag in range(1, 5):
        shifted = base.with_columns(
            (pl.col("periode") + lag).alias("periode")
        ).rename({k: f"{v}_lag{lag}" for k, v in cols_map.items()})
        out = out.join(shifted, on=["wilayah", "periode"], how="left")

    # rolling yang berakhir t-1: mean curah hujan 3 & 6 bulan terakhir
    rolled = (
        base.with_columns((pl.col("periode") + 1).alias("periode"))
        .sort(["wilayah", "periode"])
        .with_columns(
            [
                pl.col("curah_hujan_mm").rolling_mean(3, min_samples=3).over("wilayah").round(2).alias("ch_rol3"),
                pl.col("curah_hujan_mm").rolling_mean(6, min_samples=6).over("wilayah").round(2).alias("ch_rol6"),
                pl.col("kelembapan_pct").rolling_mean(3, min_samples=3).over("wilayah").round(2).alias("rh_rol3"),
                pl.col("suhu_mean_c").rolling_mean(3, min_samples=3).over("wilayah").round(2).alias("tavg_rol3"),
            ]
        )
        .select(["wilayah", "periode", "ch_rol3", "ch_rol6", "rh_rol3", "tavg_rol3"])
    )
    out = out.join(rolled, on=["wilayah", "periode"], how="left")
    return out.sort(["wilayah", "periode"])


def bangun_bulanan() -> pl.DataFrame:
    cuaca_bl = bulanan_cuaca()
    fitur = buat_fitur_lag(cuaca_bl)
    kasus = muat_kasus_bulanan()  # wilayah, tahun, bulan, kasus
    pop = muat_populasi()

    kasus = kasus.with_columns((pl.col("tahun") * 12 + pl.col("bulan")).alias("periode"))

    panel = fitur.join(kasus.select(["wilayah", "periode", "kasus"]), on=["wilayah", "periode"], how="left")

    # AR lag-1 (kasus bulan t-1) dan seasonal lag-12
    ar = kasus.select(["wilayah", "periode", "kasus"]).rename({"kasus": "kasus_lag1"})
    ar = ar.with_columns((pl.col("periode") + 1).alias("periode"))
    panel = panel.join(ar, on=["wilayah", "periode"], how="left")

    seas = kasus.select(["wilayah", "periode", "kasus"]).rename({"kasus": "kasus_lag12"})
    seas = seas.with_columns((pl.col("periode") + 12).alias("periode"))
    panel = panel.join(seas, on=["wilayah", "periode"], how="left")

    # demografi statis
    pop_last = pop.group_by("wilayah").agg(
        [pl.col("pop_ribu").last(), pl.col("kepadatan_km2").last()]
    )
    panel = panel.join(pop_last, on="wilayah", how="left")

    # fitur kalender (turunkan dari periode dulu, lalu pakai)
    panel = panel.with_columns(
        [
            ((pl.col("periode") - 1) % 12 + 1).alias("bulan"),
            ((pl.col("periode") - 1) // 12).alias("tahun"),
        ]
    )
    panel = panel.with_columns(
        [
            (pl.col("bulan").cast(pl.Float64) / 12 * 2 * 3.14159).sin().round(4).alias("mo_sin"),
            (pl.col("bulan").cast(pl.Float64) / 12 * 2 * 3.14159).cos().round(4).alias("mo_cos"),
        ]
    )
    panel = panel.with_columns(
        (pl.col("kasus") / (pl.col("pop_ribu") / 1000.0) * 100_000).round(3).alias("insidensi_per100k")
    )
    panel = panel.sort(["wilayah", "periode"])
    out = LAKE / "panel_bulanan.parquet"
    panel.write_parquet(out)
    n_valid = panel.filter(pl.col("kasus").is_not_null()).height
    print(f"[panel bulanan] {panel.height} baris x {panel.width} kolom ({n_valid} dgn kasus) -> {out}")
    return panel


if __name__ == "__main__":
    bangun_bulanan()

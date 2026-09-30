"""
Pipeline utama: cuaca harian -> fitur mingguan/epi-week -> gabung kasus DBD.

Alur:
1. muat cuaca harian (Parquet kalau sudah ada, jika belum fetch ke Open-Meteo)
2. agregasi ke epi-week per wilayah
3. bangun fitur dengan DISIPLIN INFORMATION CUTOFF:
   semua fitur cuaca hanya boleh berisi info minggu <= t-4, sehingga model
   valid dipakai sebagai early warning 4 minggu ke depan tanpa leakage.
4. muat kasus DBD per kota (Dinkes DKI via dataset terbuka)
5. gabung jadi panel wilayah x epi-week + baseline (naive lag-4, seasonal)
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
LAKE = ROOT / "data" / "lake"
LAKE.mkdir(parents=True, exist_ok=True)

LEAD_MINGGU = 4  # horizon early warning; fitur hanya info <= t-4

# pemetaan nama kotamadya di sumber data -> kode wilayah standar
MAP_KOTA = {
    "Jakarta Pusat": "jak-pus",
    "Jakarta Utara": "jak-ut",
    "Jakarta Barat": "jak-bar",
    "Jakarta Selatan": "jak-sel",
    "Jakarta Timur": "jak-tim",
    "Kab. Kep. Seribu": "kep-seribu",
    "Kepulauan Seribu": "kep-seribu",
}

# Kepadatan penduduk per km2 (BPS DKI, angka sensus/estimasi terbaru)
KEPADATAN_KM2 = {
    "jak-pus": 20360,
    "jak-ut": 12042,
    "jak-bar": 18800,
    "jak-sel": 14475,
    "jak-tim": 16729,
    "kep-seribu": 2774,
}


# ---------------------------------------------------------------- cuaca harian
def muat_cuaca_harian() -> pl.DataFrame:
    """Parquet cache dipakai kalau ada; kalau belum, fetch Open-Meteo."""
    cache = LAKE / "cuaca_harian.parquet"
    if cache.exists():
        df = pl.read_parquet(cache)
        print(f"[cache] cuaca harian: {df.height} baris")
        return df

    from pipeline.fetch.cuaca import fetch_all_regions

    print("[fetch] tarik Open-Meteo 2020 -> hari ini ...")
    rows_by_region = fetch_all_regions("2020-01-01")
    frames = [pl.DataFrame(rows) for rows in rows_by_region.values()]
    df = pl.concat(frames, how="diagonal_relaxed")
    df = df.with_columns(pl.col("tanggal").str.to_date("%Y-%m-%d"))
    df.write_parquet(cache)
    print(f"[tulis] {cache} ({df.height} baris)")
    return df


# ---------------------------------------------------------- agregasi mingguan
def ke_mingguan(cuaca: pl.DataFrame) -> pl.DataFrame:
    """Harian -> epi-week (ISO, mulai Senin)."""
    df = cuaca.with_columns(
        [
            pl.col("tanggal").dt.week().alias("minggu"),
            pl.col("tanggal").dt.year().alias("tahun_iso"),
        ]
    )
    aggs = [
        pl.col("precipitation_sum").sum().alias("curah_hujan_mm"),
        pl.col("temperature_2m_max").mean().round(2).alias("suhu_max_c"),
        pl.col("temperature_2m_min").mean().round(2).alias("suhu_min_c"),
        pl.col("temperature_2m_mean").mean().round(2).alias("suhu_mean_c"),
        pl.col("relative_humidity_2m_mean").mean().round(2).alias("kelembapan_pct"),
        pl.col("wind_speed_10m_max").mean().round(2).alias("angin_max_ms"),
        pl.len().alias("_n_hari"),
    ]
    mingguan = df.group_by(["wilayah", "tahun_iso", "minggu"]).agg(aggs)
    extra = (
        df.with_columns(
            [
                (pl.col("precipitation_sum") >= 1.0).cast(pl.Int8).alias("_hujan"),
                (pl.col("temperature_2m_max") >= 34.0).cast(pl.Int8).alias("_panas"),
            ]
        )
        .group_by(["wilayah", "tahun_iso", "minggu"])
        .agg(
            [
                pl.col("_hujan").sum().alias("hari_hujan"),
                pl.col("_panas").sum().alias("hari_panas_ekstrem"),
            ]
        )
    )
    mingguan = mingguan.join(extra, on=["wilayah", "tahun_iso", "minggu"], how="left")
    senin = df.group_by(["wilayah", "tahun_iso", "minggu"]).agg(
        pl.col("tanggal").min().alias("tanggal_mulai")
    )
    mingguan = mingguan.join(senin, on=["wilayah", "tahun_iso", "minggu"], how="left")
    return mingguan.sort(["wilayah", "tanggal_mulai"])


# ------------------------------------------------- fitur dengan cutoff t-4
def tambah_fitur_cutoff(mingguan: pl.DataFrame) -> pl.DataFrame:
    """
    Semua fitur = fungsi cuaca minggu <= t-LEAD_MINGGU. Mekanisme biologis
    (telur -> larva -> dewasa) memang bekerja pada lag 4-12 minggu, jadi
    cutoff t-4 selalu jujur sekaligus cukup informatif.
    """
    w = mingguan.select(
        [
            "wilayah",
            "tanggal_mulai",
            "curah_hujan_mm",
            "suhu_min_c",
            "suhu_mean_c",
            "suhu_max_c",
            "kelembapan_pct",
            "hari_hujan",
        ]
    )

    out = mingguan.select(["wilayah", "tanggal_mulai", "tahun_iso", "minggu"])

    # --- lag tunggal: cuaca minggu t-(4+k) untuk k = 0..8  =>  lag 4..12
    for lag in range(LEAD_MINGGU, LEAD_MINGGU + 9):
        wk = w.with_columns(
            (pl.col("tanggal_mulai") + pl.duration(weeks=lag)).alias("tanggal_mulai")
        ).rename(
            {
                "curah_hujan_mm": f"ch_lag{lag}",
                "kelembapan_pct": f"rh_lag{lag}",
                "suhu_mean_c": f"tavg_lag{lag}",
                "suhu_min_c": f"tmin_lag{lag}",
                "suhu_max_c": f"tmax_lag{lag}",
                "hari_hujan": f"hhuj_lag{lag}",
            }
        )
        out = out.join(wk, on=["wilayah", "tanggal_mulai"], how="left")

    # --- rolling window yang BERAKHIR di minggu t-4
    s = (
        w.with_columns(
            (pl.col("tanggal_mulai") + pl.duration(weeks=LEAD_MINGGU)).alias("tanggal_mulai")
        )
        .sort(["wilayah", "tanggal_mulai"])
        .with_columns(
            [
                pl.col("curah_hujan_mm").rolling_mean(4, min_samples=4).over("wilayah").round(2).alias("ch_rol4"),
                pl.col("curah_hujan_mm").rolling_sum(8, min_samples=8).over("wilayah").round(2).alias("ch_sum8"),
                pl.col("curah_hujan_mm").rolling_mean(12, min_samples=12).over("wilayah").round(2).alias("ch_rol12"),
                pl.col("kelembapan_pct").rolling_mean(4, min_samples=4).over("wilayah").round(2).alias("rh_rol4"),
                pl.col("kelembapan_pct").rolling_mean(12, min_samples=12).over("wilayah").round(2).alias("rh_rol12"),
                pl.col("suhu_mean_c").rolling_mean(4, min_samples=4).over("wilayah").round(2).alias("tavg_rol4"),
                pl.col("hari_hujan").rolling_sum(8, min_samples=8).over("wilayah").alias("hhuj_sum8"),
            ]
        )
        .select(["wilayah", "tanggal_mulai", "ch_rol4", "ch_sum8", "ch_rol12", "rh_rol4", "rh_rol12", "tavg_rol4", "hhuj_sum8"])
    )
    out = out.join(s, on=["wilayah", "tanggal_mulai"], how="left")

    # --- fitur kalender (known by construction)
    out = out.with_columns(
        [
            (pl.col("minggu").cast(pl.Float64) / 52.18 * 2 * 3.14159).sin().round(4).alias("woy_sin"),
            (pl.col("minggu").cast(pl.Float64) / 52.18 * 2 * 3.14159).cos().round(4).alias("woy_cos"),
        ]
    )
    return out.sort(["wilayah", "tanggal_mulai"])


# ------------------------------------------------------------------- kasus DBD
def muat_kasus() -> pl.DataFrame:
    """
    Kasus DBD bulanan per kotamadya -> didistribusi ke epi-week proporsional
    jumlah hari. Asumsi didokumentasikan di model card (bukan interpolasi
    rahasia). Kasus tetap agregat bulanan di kolom asal.
    """
    p = RAW / "Kasus_dbd_raw.csv"
    df = pl.read_csv(p).rename(
        {
            "kabupaten_kota": "kota_raw",
            "kasus_dbd": "kasus",
        }
    )
    df = df.with_columns(
        pl.col("kota_raw").replace_strict(MAP_KOTA, default=None).alias("wilayah")
    ).drop_nulls(["wilayah"])

    rows: list[dict] = []
    for r in df.iter_rows(named=True):
        y, m, kota, kasus = r["tahun"], r["bulan"], r["wilayah"], int(r["kasus"])
        awal_bulan_lanjut = dt.date(y + (m == 12), (m % 12) + 1, 1)
        n_hari = (awal_bulan_lanjut - dt.timedelta(days=1)).day
        per_minggu: dict[tuple[int, int], int] = {}
        for d in range(1, n_hari + 1):
            iso = dt.date(y, m, d).isocalendar()
            per_minggu[(iso[0], iso[1])] = per_minggu.get((iso[0], iso[1]), 0) + 1
        for (thn, mgg), n in per_minggu.items():
            rows.append(
                {
                    "wilayah": kota,
                    "tahun_iso": thn,
                    "minggu": mgg,
                    "kasus": kasus * n / n_hari,
                }
            )
    weekly = (
        pl.DataFrame(rows)
        .group_by(["wilayah", "tahun_iso", "minggu"])
        .agg(pl.col("kasus").sum().round(3).alias("kasus"))
    )
    return weekly.sort(["wilayah", "tahun_iso", "minggu"])


def muat_kasus_bulanan() -> pl.DataFrame:
    """Kasus DBD bulanan per kotamadya DKI, level ASLI tanpa disagregasi.

    Sumber: dataset terbuka rekap Dinkes DKI Jakarta.
    Output kolom: tahun, bulan, kabupaten_kota->wilayah, kasus_dbd->kasus
    """
    p = RAW / "Kasus_dbd_raw.csv"
    df = pl.read_csv(p)
    df = df.rename({"kabupaten_kota": "kota_raw", "kasus_dbd": "kasus"})
    df = df.with_columns(
        pl.col("kota_raw").replace_strict(MAP_KOTA, default=None).alias("wilayah")
    ).drop_nulls(["wilayah"])
    return df.select(["wilayah", "tahun", "bulan", "kasus"]).sort(["wilayah", "tahun", "bulan"])


def muat_populasi() -> pl.DataFrame:
    """Penduduk + kepadatan per kotamadya (BPS DKI).

    Kolom beraksen Indonesia non-ASCII dihindari; kepadatan diambil dari
    nilai BPS yang sudah diverifikasi di lampiran model card.
    """
    p = RAW / "kepadatan_penduduk_raw.csv"
    df = pl.read_csv(p).select(["Kabupaten/Kota", "tahun", "Jumlah Penduduk (Ribu)"])
    df = df.rename({"Jumlah Penduduk (Ribu)": "pop_ribu"})
    df = df.with_columns(
        pl.col("Kabupaten/Kota").replace_strict(MAP_KOTA, default=None).alias("wilayah")
    ).drop_nulls(["wilayah"])
    # Kepadatan penduduk per km2 (BPS DKI 2021), nilai statis per wilayah
    df = df.with_columns(
        pl.col("wilayah")
        .replace_strict(
            {k: float(v) for k, v in KEPADATAN_KM2.items()},
            default=None,
            return_dtype=pl.Float64,
        )
        .alias("kepadatan_km2")
    )
    df = df.select(
        [
            "wilayah",
            pl.col("tahun").cast(pl.Int32),
            pl.col("pop_ribu").cast(pl.Float64),
            "kepadatan_km2",
        ]
    )
    return df.sort(["wilayah", "tahun"])


def bangun_panel() -> pl.DataFrame:
    cuaca = muat_cuaca_harian()
    mingguan = ke_mingguan(cuaca)
    fitur = tambah_fitur_cutoff(mingguan)
    kasus = muat_kasus()
    pop = muat_populasi()

    panel = fitur.join(kasus, on=["wilayah", "tahun_iso", "minggu"], how="left")

    # baseline: naive lag-4 (kasus minggu t-4, diketahui saat cutoff)
    kasus_lag = kasus.with_columns(
        (pl.col("tahun_iso") * 100 + pl.col("minggu")).alias("_k")
    )
    kunci = panel.select(["wilayah", "tahun_iso", "minggu"]).with_columns(
        (pl.col("tahun_iso") * 100 + pl.col("minggu")).alias("_k")
    )
    # minggu t-4 per wilayah via tanggal
    tanggal_ref = fitur.select(["wilayah", "tanggal_mulai", "tahun_iso", "minggu"])
    lag4 = (
        tanggal_ref.with_columns(
            (pl.col("tanggal_mulai") + pl.duration(weeks=LEAD_MINGGU)).alias("tanggal_mulai")
        )
        .join(kasus, on=["wilayah", "tahun_iso", "minggu"], how="inner")
        .select(["wilayah", "tanggal_mulai", pl.col("kasus").alias("baseline_lag4")])
    )
    panel = panel.join(lag4, on=["wilayah", "tanggal_mulai"], how="left")

    # baseline seasonal: kasus minggu ISO sama tahun lalu
    seasonal = kasus.with_columns(
        [
            (pl.col("tahun_iso") + 1).alias("tahun_iso"),
            pl.col("kasus").alias("baseline_seasonal"),
        ]
    ).select(["wilayah", "tahun_iso", "minggu", "baseline_seasonal"])
    panel = panel.join(seasonal, on=["wilayah", "tahun_iso", "minggu"], how="left")

    # populasi & kepadatan (statis per wilayah, pakai nilai terakhir)
    pop_last = pop.group_by("wilayah").agg(
        [pl.col("pop_ribu").last(), pl.col("kepadatan_km2").last()]
    )
    panel = panel.join(pop_last, on="wilayah", how="left")
    panel = panel.with_columns(
        [
            (pl.col("kasus") / (pl.col("pop_ribu") / 1000.0) * 100_000)
            .round(3)
            .alias("insidensi_per100k")
        ]
    )
    panel = panel.sort(["wilayah", "tanggal_mulai"])
    out = LAKE / "panel_mingguan.parquet"
    panel.write_parquet(out)
    n_valid = panel.filter(pl.col("kasus").is_not_null()).height
    print(f"[panel] {panel.height} baris x {panel.width} kolom ({n_valid} dgn kasus) -> {out}")
    return panel


if __name__ == "__main__":
    bangun_panel()

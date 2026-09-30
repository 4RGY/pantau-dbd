"""
Bungkus Open-Meteo Archive API.

Dipakai dua arah:
- historis  -> archive-api.open-meteo.com (dari 2020-01-01)
- near-real -> archive-api juga, karena ERA5 cutoff ~5 hari

Tiap kotamadya Jakarta diwakili satu koordinat centroid supaya representatif
daripada cuma pakai satu titikpusat kota.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

import httpx

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "precipitation_sum",
    "rain_sum",
    "relative_humidity_2m_mean",
    "wind_speed_10m_max",
    "shortwave_radiation_sum",
    "et0_fao_evapotranspiration",
]

HOURLY_AGG = "relative_humidity_2m"

# Centroid per kotamadya DKI Jakarta (perkiraan titik tengah administratif).
JAKARTA_REGIONS: dict[str, dict[str, Any]] = {
    "jak-pus": {
        "nama": "Jakarta Pusat",
        "nama_pendek": "Jakpus",
        "lat": -6.1764,
        "lon": 106.8396,
        "pop": 1_066_500,
        "luas_km2": 48.13,
    },
    "jak-ut": {
        "nama": "Jakarta Utara",
        "nama_pendek": "Jakut",
        "lat": -6.1382,
        "lon": 106.8636,
        "pop": 1_801_900,
        "luas_km2": 146.66,
    },
    "jak-bar": {
        "nama": "Jakarta Barat",
        "nama_pendek": "Jakbar",
        "lat": -6.1568,
        "lon": 106.7922,
        "pop": 2_437_100,
        "luas_km2": 129.54,
    },
    "jak-sel": {
        "nama": "Jakarta Selatan",
        "nama_pendek": "Jaksel",
        "lat": -6.2615,
        "lon": 106.8436,
        "pop": 2_233_800,
        "luas_km2": 141.27,
    },
    "jak-tim": {
        "nama": "Jakarta Timur",
        "nama_pendek": "Jaktim",
        "lat": -6.2251,
        "lon": 106.9004,
        "pop": 3_056_300,
        "luas_km2": 188.03,
    },
    "kep-seribu": {
        "nama": "Kepulauan Seribu",
        "nama_pendek": "Kepser",
        "lat": -5.6068,
        "lon": 106.5418,
        "pop": 28_200,
        "luas_km2": 8.70,
    },
}


def fetch_daily(
    lat: float,
    lon: float,
    start: str,
    end: str,
    retries: int = 3,
) -> list[dict[str, Any]]:
    """Tarik cuaca harian untuk satu titik. Balik list of dict per hari."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "daily": ",".join(DAILY_VARS),
        "timezone": "Asia/Jakarta",
    }
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            r = httpx.get(ARCHIVE_URL, params=params, timeout=60.0)
            if r.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"    429 rate-limited, tunggu {wait}s ...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            payload = r.json()
            break
        except Exception as exc:  # noqa: BLE001 - retry transien
            last_err = exc
            time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError(f"Gagal fetch Open-Meteo: {last_err}")

    daily = payload.get("daily", {})
    times = daily.get("time", [])
    cols = {k: daily.get(k, []) for k in DAILY_VARS}
    rows: list[dict[str, Any]] = []
    for i, t in enumerate(times):
        row: dict[str, Any] = {"tanggal": t}
        for var in DAILY_VARS:
            seq = cols[var]
            row[var] = seq[i] if i < len(seq) else None
        rows.append(row)
    return rows


def fetch_all_regions(
    start: str = "2020-01-01",
    end: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    end = end or date.today().isoformat()
    out: dict[str, list[dict[str, Any]]] = {}
    for kode, meta in JAKARTA_REGIONS.items():
        rows = fetch_daily(meta["lat"], meta["lon"], start, end)
        for r in rows:
            r["wilayah"] = kode
        out[kode] = rows
        print(f"  {meta['nama']:20s} {len(rows):5d} hari  {rows[0]['tanggal']} -> {rows[-1]['tanggal']}")
        time.sleep(6)  # Open-Meteo 429 agresif; 6s/wilayah aman
    return out


if __name__ == "__main__":
    res = fetch_all_regions("2020-01-01")
    total = sum(len(v) for v in res.values())
    print(f"total baris: {total}")

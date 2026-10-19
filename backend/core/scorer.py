"""Scorer kandidat (murni) - 6 sinyal berbobot §4.2 + zona keputusan §4.3 PROMPT.

Input: observasi ternormalisasi + umur menit. Output: SkorResult(score, zone).
Deterministik - sinyal yang sama selalu skor sama (testable).
"""
from __future__ import annotations

from dataclasses import dataclass

WEIGHTS = {
    "momentum": 20,        # naik sehat, tidak vertikal
    "volume_sustain": 20,  # h1 vs h24: keberlanjutan, bukan sekali ledak
    "buy_sell_ratio": 15,  # 1.1-3.0 sehat; >5 = pump bot
    "liq_vs_fdv": 15,      # >=2% aman
    "age_sweetspot": 15,   # 30 mnt - 6 jam
    "supply_known": 15,    # data onchain tersedia (placeholder AI fase 5)
}

# Kalibrasi live 19 Okt 2026: syarat momentum realistis utk scalp pump.fun
MIN_CHG_PER_MIN_PCT = 0.1   # naik >=0.1% per menit = tren hidup
MIN_VOL_M5 = 300.0          # ada aksi minimal $300 dalam 5 menit
M5_MINUTES = 5.0            # durasi window chg_m5

MIN_BUY_SELL = 1.1
MAX_BUY_SELL_HEALTHY = 3.0
MAX_BUY_SELL_BOT = 5.0
MAX_VERTICAL_PCT_H1 = 200.0
SWEETSPOT_MIN = 30.0
SWEETSPOT_MAX = 360.0  # 6 jam
MIN_LIQ_FDV_PCT = 2.0


@dataclass
class SkorResult:
    score: float
    zone: str  # "BUY" | "WATCH" | "PASSIVE"
    parts: dict  # transparansi: kontribusi tiap sinyal


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def score(row: dict, age_min: float | None, supply: float | None) -> SkorResult:
    parts: dict[str, float] = {}

    # 1. Momentum: naik = baik, tapi >200%/jam = vertikal (pump) -> dicoret
    chg_h1 = row.get("chg_h1") or 0.0
    chg_pm = row.get("chg_m5", 0.0) or 0.0
    chg_pm = chg_pm / M5_MINUTES  # normalisasi ke per-menit
    if chg_pm <= 0:
        parts["momentum"] = 0.0
    elif chg_pm > MAX_VERTICAL_PCT_H1 / 60.0:
        parts["momentum"] = 0.0  # vertikal = bahkan berbahaya
    else:
        parts["momentum"] = WEIGHTS["momentum"] * _clamp01(chg_pm / (100.0 / 60.0))

    # 2. Keberlanjutan volume: h1/h24 tinggi = masih ramah sekarang
    vol_h1, vol_h24 = row.get("vol_h1") or 0.0, row.get("vol_h24") or 0.0
    ratio_h1 = vol_h1 / vol_h24 if vol_h24 > 0 else 0.0
    parts["volume_sustain"] = WEIGHTS["volume_sustain"] * _clamp01(ratio_h1 / 0.5)  # 50% volume 24j terjadi di 1 jam terakhir = sangat aktif

    # 3. Buy/sell ratio m5: 1.1-3.0 sehat
    buys, sells = row.get("buys_m5") or 0, row.get("sells_m5") or 0
    if buys + sells < 10:
        parts["buy_sell_ratio"] = 0.0  # terlalu sepi untuk dinilai
    else:
        r = buys / max(sells, 1)
        if r < MIN_BUY_SELL:
            parts["buy_sell_ratio"] = 0.0
        elif r <= MAX_BUY_SELL_HEALTHY:
            parts["buy_sell_ratio"] = WEIGHTS["buy_sell_ratio"]
        elif r <= MAX_BUY_SELL_BOT:
            parts["buy_sell_ratio"] = WEIGHTS["buy_sell_ratio"] * 0.4
        else:
            parts["buy_sell_ratio"] = 0.0  # pump bot

    # 4. Likuiditas relatif FDV
    liq, fdv = row.get("liquidity_usd") or 0.0, row.get("fdv") or 0.0
    pct = (liq / fdv * 100.0) if fdv > 0 else 0.0
    parts["liq_vs_fdv"] = WEIGHTS["liq_vs_fdv"] * _clamp01(pct / MIN_LIQ_FDV_PCT)

    # 5. Umur sweet spot
    if age_min is None:
        parts["age_sweetspot"] = 0.0
    elif SWEETSPOT_MIN <= age_min <= SWEETSPOT_MAX:
        parts["age_sweetspot"] = WEIGHTS["age_sweetspot"]
    else:
        # luar sweet spot tapi lolos filter keras: sebagian
        parts["age_sweetspot"] = WEIGHTS["age_sweetspot"] * 0.3

    # 6. Data supply onchain tersedia (transparansi; AI berita mengambil slot ini di fase 5)
    parts["supply_known"] = WEIGHTS["supply_known"] if supply else 0.0

    total = round(sum(parts.values()), 1)
    # scalp: momentum WAJIB hidup - ukur per MENIT (tahan thd jeda observasi apa pun)
    chg_m5 = row.get("chg_m5") or 0.0
    vol_m5 = row.get("vol_m5") or 0.0
    chg_per_min = chg_m5 / M5_MINUTES
    has_momentum = chg_per_min >= MIN_CHG_PER_MIN_PCT and vol_m5 >= MIN_VOL_M5
    if total >= 65 and has_momentum:
        zone = "BUY"
    elif total >= 65:
        zone = "WATCH"  # skor cukup tapi pasar diam -> tunggu momentum
    elif total >= 40:
        zone = "WATCH"
    else:
        zone = "PASSIVE"
    return SkorResult(score=total, zone=zone, parts={k: round(v, 1) for k, v in parts.items()})

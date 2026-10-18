"""Bot A - Sentiment (murni): hitung hype score per kandidat dari data sumber.

Hype score 0-100 = seberapa ramai pembicaraan/uang promosi di sekitar coin:
- CoinGecko trending (organik): symbol muncul di trending global -> +55
- DexScreener boost (berbayar): dev bayar promosi -> +35, TAPI boost besar
  (>= 200 total) sambil momentum lemah = red flag manipulasi (dipakai AI/journal)

PENTING: hype bukan sinyal beli - ia PENGALI kepercayaan. Hype tinggi + skor teknikal
baik = konfirmasi. Hype tinggi + metrik buruk = justru waspada. Bobot maksimal kecil
(dipakai scorer sebagai bonus/pinalti poin, bukan penentu).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HypeScore:
    score: int          # 0..100
    sources: list[str]  # sumber yang mendeteksi
    paid_boost: bool    # promosi berbayar terdeteksi (ditandai eksplisit)
    note: str


def hype_for(symbol: str, mint: str, trending: list[str], boosts: dict[str, dict]) -> HypeScore:
    """Deterministik: data sama -> skor sama."""
    score = 0
    sources: list[str] = []
    paid = False

    if symbol and symbol.upper() in trending:
        score += 55
        sources.append("coingecko_trending")

    b = boosts.get(mint)
    if b:
        paid = True
        score += 35
        sources.append("dexscreener_boost")
        # boost raksasa tanpa bukti organik lain = waspada (tidak menaikkan skor lagi)
        if b.get("total_boosts", 0) >= 200 and not sources[:-1]:
            score = min(score, 40)
            sources.append("boost_waspada")

    return HypeScore(score=min(score, 100), sources=sources, paid_boost=paid,
                     note=", ".join(sources) if sources else "tidak ada sinyal sosial")


def adjust_technical_score(tech_score: float, hype: HypeScore) -> float:
    """Sentiment hanya menggeser +/- maksimal 10 poin dari skor teknikal.

    Hype organik tinggi + skor oke  -> bonus hingga +10
    Paid boost tanpa organik        -> pinalti -5 (waspadai manipulasi)
    Tidak ada sinyal                -> netral
    """
    adj = 0.0
    if hype.score >= 55 and hype.paid_boost:
        adj = 10.0        # organik + berbayar sekaligus = hype kuat
    elif hype.score >= 55:
        adj = 6.0         # organik saja
    elif hype.score > 0 and hype.paid_boost:
        adj = -5.0        # hanya berbayar = curiga
    return round(max(0.0, min(100.0, tech_score + adj)), 1)

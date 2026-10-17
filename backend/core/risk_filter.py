"""Mesin anti-scam (murni) - 5 filter keras §4.1 PROMPT.

Semua fungsi menerima baris observasi ternormalisasi (dari adapter) + umur menit.
Output: daftar alasan reject (kosong = lolos semua). Setiap penolakan PUNYA alasan -
itu kontrak jurnal (tidak ada penolakan siluman).
"""
from __future__ import annotations

MIN_LIQUIDITY_USD = 5_000.0
MIN_AGE_MINUTES = 30.0
MAX_FDV = 5_000_000.0
MAX_VOL_TO_LIQ_24H = 15.0
MAX_DROP_FROM_5M_HIGH = -60.0  # persen; di bawah ini dianggap sudah rug


def reject_reasons(
    row: dict,
    age_min: float | None,
    chg_m5_low: float | None = None,
) -> list[str]:
    """Evaluasi semua filter keras. Kembalikan daftar alasan REJECT (kosong = lolos).

    row: observasi ternormalisasi (price_usd, liquidity_usd, fdv, vol_h24, ...)
    age_min: umur pair dalam menit (None = API tidak memberi data -> tidak bisa dinilai umur)
    chg_m5_low: perubahan harga 5 menit paling dalam yang terlihat (persen) - pakai chg_m5.
    """
    reasons: list[str] = []

    liq = row.get("liquidity_usd") or 0.0
    if liq < MIN_LIQUIDITY_USD:
        reasons.append(f"likuiditas ${liq:,.0f} < ${MIN_LIQUIDITY_USD:,.0f}")

    if age_min is None:
        reasons.append("umur pair tidak diketahui (API tidak memberi pairCreatedAt)")
    elif age_min < MIN_AGE_MINUTES:
        reasons.append(f"umur {age_min:.0f} menit < {MIN_AGE_MINUTES:.0f} menit minimum")

    fdv = row.get("fdv") or 0.0
    if fdv > MAX_FDV:
        reasons.append(f"FDV ${fdv:,.0f} > ${MAX_FDV:,.0f}")

    vol24 = row.get("vol_h24") or 0.0
    if liq > 0 and vol24 / liq > MAX_VOL_TO_LIQ_24H:
        reasons.append(
            f"volume/likuiditas 24 jam {vol24 / liq:.1f}x > {MAX_VOL_TO_LIQ_24H:.0f}x (indikasi wash trading)"
        )

    drop = chg_m5_low if chg_m5_low is not None else row.get("chg_m5")
    if drop is not None and drop <= MAX_DROP_FROM_5M_HIGH:
        reasons.append(f"harga turun {drop:.0f}% dalam 5 menit (sudah rug saat kita lihat)")

    return reasons

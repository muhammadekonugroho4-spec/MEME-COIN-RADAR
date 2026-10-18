"""Aturan exit (murni) - mode SCALP (pilihan user 18 Okt 2026).

Filosofi scalp: masuk saat momentum jalan, ambil profit kecil cepat, potong rugi
secepatnya, dan KELUAR karena waktu bila pasar diam. Tidak ada "menunggu berharap".

Prioritas exit (pertama yang kena):
1. Stop loss harga: -5% dari entry
2. Likuiditas ditarik dev: <60% dari saat beli
3. Take profit: +8% dari entry (langsung exit penuh - scalp)
4. Trailing stop: -3% dari harga puncak sejak entry
5. Max hold: 15 menit -> exit apapun hasilnya
"""
from __future__ import annotations

from dataclasses import dataclass

STOP_LOSS_PCT = -5.0
LIQ_DROP_EXIT_PCT = 0.60       # likuiditas sekarang < 60% dari saat beli -> exit
TP_TRIGGER_PCT = 8.0           # scalp: profit kecil cepat, exit penuh
TRAILING_PCT = 3.0             # kunci profit: 3% dari puncak
MAX_HOLD_MINUTES = 15.0


@dataclass
class ExitSignal:
    action: str      # "exit" | "hold"
    reason: str
    fraction: float  # 1.0 = semua


def evaluate_position(
    pos: dict,
    price: float,
    liquidity_usd: float,
    now_ts: float,
) -> ExitSignal:
    """pos: {'qty','entry_price','entry_ts','peak_price','entry_liquidity'}"""
    qty = pos.get("qty") or 0.0
    entry = pos.get("entry_price") or 0.0
    if qty <= 0 or entry <= 0:
        return ExitSignal("hold", "posisi tidak valid", 0.0)

    pnl_pct = (price - entry) / entry * 100.0
    entry_liq = pos.get("entry_liquidity") or 0.0
    peak = max(pos.get("peak_price") or entry, price)

    # 1. stop loss
    if pnl_pct <= STOP_LOSS_PCT:
        return ExitSignal("exit", f"stop-loss {pnl_pct:.1f}% dari entry", 1.0)

    # 2. likuiditas ditarik
    if entry_liq > 0 and liquidity_usd < entry_liq * (1 - LIQ_DROP_EXIT_PCT):
        return ExitSignal(
            "exit",
            f"likuiditas pair drop ke ${liquidity_usd:,.0f} (<60% dari ${entry_liq:,.0f} saat beli)",
            1.0,
        )

    # 5. max hold
    minutes = (now_ts - pos.get("entry_ts", now_ts)) / 60.0
    if minutes >= MAX_HOLD_MINUTES:
        return ExitSignal("exit", f"scalp timeout: {minutes:.0f} menit >= {MAX_HOLD_MINUTES:.0f} menit", 1.0)

    # 3. take profit
    if pnl_pct >= TP_TRIGGER_PCT:
        return ExitSignal("exit", f"take-profit scalp +{pnl_pct:.1f}%", 1.0)

    # 4. trailing stop
    drop_from_peak = (price - peak) / peak * 100.0
    if drop_from_peak <= -TRAILING_PCT:
        return ExitSignal("exit", f"trailing stop: {drop_from_peak:.1f}% dari puncak", 1.0)

    return ExitSignal("hold", f"hold, PnL {pnl_pct:+.1f}%", 0.0)


def update_peak(pos: dict, price: float) -> dict:
    """Peak price diupdate tiap observasi (untuk trailing)."""
    pos = dict(pos)
    pos["peak_price"] = max(pos.get("peak_price") or pos.get("entry_price") or 0.0, price)
    return pos

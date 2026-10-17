"""Aturan exit (murni) - §4.4.4-6 PROMPT. Evaluasi 1 posisi terhadap observasi terbaru.

Prioritas exit (pertama yang kena):
1. Stop-exit: harga -35% dari entry ATAU likuiditas pair drop >50% dari saat beli (dev menarik LP)
2. Take-profit bertahap: +100% dari entry -> jual 50%
3. Trailing stop: turun 25% dari harga tertinggi sejak entry (hanya aktif setelah TP pertama)
4. Hold maksimum 48 jam -> jual sisa
"""
from __future__ import annotations

from dataclasses import dataclass

STOP_LOSS_PCT = -35.0
LIQ_DROP_EXIT_PCT = 0.50   # likuiditas sekarang < 50% dari saat beli -> exit
TP_TRIGGER_PCT = 100.0
TP_SELL_FRACTION = 0.5
TRAILING_PCT = 25.0
MAX_HOLD_HOURS = 48.0


@dataclass
class ExitSignal:
    action: str      # "exit" | "partial_exit" | "hold"
    reason: str
    fraction: float  # 1.0 = semua, 0.5 = setengah


def evaluate_position(
    pos: dict,
    price: float,
    liquidity_usd: float,
    now_ts: float,
) -> ExitSignal:
    """pos: {'qty','entry_price','entry_ts','peak_price','tp_done','entry_liquidity'}"""
    qty = pos.get("qty") or 0.0
    entry = pos.get("entry_price") or 0.0
    if qty <= 0 or entry <= 0:
        return ExitSignal("hold", "posisi tidak valid", 0.0)

    pnl_pct = (price - entry) / entry * 100.0
    entry_liq = pos.get("entry_liquidity") or 0.0
    peak = max(pos.get("peak_price") or entry, price)

    # 1a. stop loss harga
    if pnl_pct <= STOP_LOSS_PCT:
        return ExitSignal("exit", f"stop-loss {pnl_pct:.0f}% dari entry", 1.0)

    # 1b. likuiditas ditarik dev
    if entry_liq > 0 and liquidity_usd < entry_liq * (1 - LIQ_DROP_EXIT_PCT):
        return ExitSignal(
            "exit",
            f"likuiditas pair drop ke ${liquidity_usd:,.0f} (<50% dari ${entry_liq:,.0f} saat beli)",
            1.0,
        )

    # 4. hold maksimum
    hours = (now_ts - pos.get("entry_ts", now_ts)) / 3600.0
    if hours >= MAX_HOLD_HOURS:
        return ExitSignal("exit", f"hold {hours:.0f} jam >= 48 jam maksimum", 1.0)

    # 2. TP pertama: +100% -> jual 50%
    if not pos.get("tp_done") and pnl_pct >= TP_TRIGGER_PCT:
        return ExitSignal("partial_exit", f"take-profit pertama +{pnl_pct:.0f}%, jual 50%", TP_SELL_FRACTION)

    # 3. trailing stop: hanya setelah TP pertama
    if pos.get("tp_done"):
        drop_from_peak = (price - peak) / peak * 100.0
        if drop_from_peak <= -TRAILING_PCT:
            return ExitSignal("exit", f"trailing stop: {drop_from_peak:.0f}% dari puncak {peak:.8f}", 1.0)

    return ExitSignal("hold", f"hold, PnL {pnl_pct:+.0f}%", 0.0)


def update_peak(pos: dict, price: float) -> dict:
    """Peak price diupdate tiap observasi (untuk trailing)."""
    pos = dict(pos)
    pos["peak_price"] = max(pos.get("peak_price") or pos.get("entry_price") or 0.0, price)
    return pos

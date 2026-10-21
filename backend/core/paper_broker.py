"""Paper broker (murni) - aturan realistis §4.4 PROMPT.

Kunci anti-self-deception:
1. Order sinyal TIDAK langsung fill - fill di harga observasi BERIKUTNYA (§4.4.1).
2. Slippage model: 0.5% + (ukuran_order_usd / likuiditas_usd) x 100% (§4.4.2).
3. Max 5 posisi bersamaan, 1 posisi per mint, ukuran 10% equity (§4.4.3).
Semua fungsi murni: state masuk keluar, tidak ada I/O. Persistence di portfolio.py.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

BASE_SLIPPAGE_PCT = 0.5
MAX_POSITIONS = 20         # MODE UJI: longgar agar semua scan bisa di-buy (dulu 3)
POSITION_PCT_EQUITY = 0.05 # 5% per posisi (dulu 15%) - muat banyak posisi uji
MIN_ORDER_USD = 5.0


@dataclass
class PendingOrder:
    mint: str
    symbol: str
    side: str  # "buy" | "sell"
    signal_ts: float
    signal_price: float | None
    signal_score: float
    qty: float | None = None       # utk sell (partial exit)
    reason: str = ""
    usd_size: float | None = None  # utk buy


@dataclass
class Fill:
    mint: str
    symbol: str
    side: str
    qty: float
    price: float
    slippage_pct: float
    usd: float
    signal_ts: float
    signal_price: float | None
    reason: str


def slippage_pct(order_usd: float, liquidity_usd: float) -> float:
    """0.5% dasar + impact; likuiditas 0 -> tak terhingga (ditolak)."""
    if liquidity_usd <= 0:
        return float("inf")
    return BASE_SLIPPAGE_PCT + (order_usd / liquidity_usd) * 100.0


def position_size(equity: float, open_count: int) -> float | None:
    """USD untuk posisi baru. None bila slot penuh / terlalu kecil."""
    if open_count >= MAX_POSITIONS:
        return None
    usd = equity * POSITION_PCT_EQUITY
    return usd if usd >= MIN_ORDER_USD else None


def queue_buy(mint: str, symbol: str, now: float, price: float | None, score: float, equity: float, open_count: int) -> PendingOrder | None:
    usd = position_size(equity, open_count)
    if usd is None:
        return None
    return PendingOrder(
        mint=mint, symbol=symbol, side="buy", signal_ts=now,
        signal_price=price, signal_score=score, usd_size=usd,
        reason=f"zona BUY skor {score}",
    )


def fill_buy(order: PendingOrder, next_price: float, liquidity_usd: float, now: float) -> Fill | None:
    """Fill buy di harga NEXT scan dengan slippage model."""
    slip = slippage_pct(order.usd_size or 0.0, liquidity_usd)
    if slip == float("inf") or next_price <= 0:
        return None
    fill_price = next_price * (1 + slip / 100.0)
    qty = (order.usd_size or 0.0) / fill_price
    return Fill(
        mint=order.mint, symbol=order.symbol, side="buy", qty=qty, price=fill_price,
        slippage_pct=round(slip, 3), usd=order.usd_size or 0.0,
        signal_ts=order.signal_ts, signal_price=order.signal_price,
        reason=order.reason,
    )


def fill_sell(order: PendingOrder, next_price: float, liquidity_usd: float, now: float) -> Fill | None:
    slip = slippage_pct(1.0, liquidity_usd)  # sell ukuran kecil relatif liq; pakai dasar
    if slip == float("inf") or next_price <= 0 or (order.qty or 0) <= 0:
        return None
    fill_price = next_price * (1 - slip / 100.0)
    return Fill(
        mint=order.mint, symbol=order.symbol, side="sell", qty=order.qty or 0.0,
        price=fill_price, slippage_pct=round(slip, 3),
        usd=(order.qty or 0.0) * fill_price,
        signal_ts=order.signal_ts, signal_price=order.signal_price,
        reason=order.reason,
    )

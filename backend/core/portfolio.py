"""Portfolio paper (murni logic + I/O JSON/CSV sederhana). State idempotent.

State: data/portfolio/state.json  (equity, positions, pending orders)
Trade log: data/portfolio/trades.csv
Equity curve: data/portfolio/equity.csv
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from backend.core.paper_broker import Fill

STATE_FILE = "state.json"
TRADES_FILE = "trades.csv"
EQUITY_FILE = "equity.csv"


def load_state(portfolio_dir: Path, start_equity: float = 1000.0) -> dict:
    p = portfolio_dir / STATE_FILE
    if p.exists():
        return json.loads(p.read_text())
    return {"equity": start_equity, "start_equity": start_equity, "positions": {}, "pending": []}


def save_state(portfolio_dir: Path, state: dict) -> None:
    portfolio_dir.mkdir(parents=True, exist_ok=True)
    (portfolio_dir / STATE_FILE).write_text(json.dumps(state, indent=2))


def open_positions(state: dict) -> int:
    return len(state.get("positions", {}))


def unrealized_pnl(state: dict, prices: dict[str, float]) -> float:
    total = 0.0
    for mint, pos in state.get("positions", {}).items():
        px = prices.get(mint)
        if px is not None:
            total += (px - pos["entry_price"]) * pos["qty"]
    return total


def total_equity(state: dict, prices: dict[str, float]) -> float:
    return state["equity"] + unrealized_pnl(state, prices)


def apply_buy_fill(state: dict, fill: Fill) -> dict:
    """Kurangi equity cash, tambah posisi. Idempotent per fill (key unik)."""
    key = f"{fill.mint}:{fill.signal_ts}"
    done = state.setdefault("_applied", [])
    if key in done:
        return state
    state["equity"] = round(state["equity"] - fill.usd, 6)
    pos = state["positions"].setdefault(
        fill.mint,
        {
            "symbol": fill.symbol, "qty": 0.0, "entry_price": fill.price,
            "entry_ts": fill.signal_ts, "peak_price": fill.price,
            "tp_done": False, "entry_liquidity": 0.0,
        },
    )
    # rata-rata harga bila posisi sama ditambah (tidak seharusnya, tapi aman)
    total_qty = pos["qty"] + fill.qty
    pos["entry_price"] = (pos["entry_price"] * pos["qty"] + fill.price * fill.qty) / total_qty
    pos["qty"] = total_qty
    pos["entry_liquidity"] = fill.usd / max(fill.price, 1e-18)  # aproksimasi; di-update trader dgn liq nyata
    done.append(key)
    return state


def apply_sell_fill(state: dict, fill: Fill, fraction: float = 1.0) -> dict:
    key = f"sell:{fill.mint}:{fill.signal_ts}"
    done = state.setdefault("_applied", [])
    if key in done:
        return state
    pos = state.get("positions", {}).get(fill.mint)
    if not pos or pos["qty"] <= 0:
        return state
    sell_qty = min(pos["qty"], pos["qty"] * fraction if fraction < 1 else pos["qty"])
    proceeds = sell_qty * fill.price
    state["equity"] = round(state["equity"] + proceeds, 6)
    pos["qty"] = round(pos["qty"] - sell_qty, 12)
    if fill.reason and "take-profit" in fill.reason:
        pos["tp_done"] = True
    if pos["qty"] <= 1e-12 or fraction >= 1.0:
        state["positions"].pop(fill.mint, None)
    done.append(key)
    return state


def log_trade(portfolio_dir: Path, fill: Fill) -> None:
    portfolio_dir.mkdir(parents=True, exist_ok=True)
    row = pd.DataFrame([{
        "ts": pd.Timestamp.utcnow().isoformat(),
        "mint": fill.mint, "symbol": fill.symbol, "side": fill.side,
        "qty": fill.qty, "price": fill.price, "usd": fill.usd,
        "slippage_pct": fill.slippage_pct,
        "signal_price": fill.signal_price, "reason": fill.reason,
    }])
    p = portfolio_dir / TRADES_FILE
    df = pd.concat([pd.read_csv(p), row], ignore_index=True) if p.exists() else row
    df.to_csv(p, index=False)


def log_equity(portfolio_dir: Path, equity_cash: float, unrealized: float) -> None:
    portfolio_dir.mkdir(parents=True, exist_ok=True)
    row = pd.DataFrame([{
        "ts": pd.Timestamp.utcnow().isoformat(),
        "equity_cash": round(equity_cash, 4),
        "unrealized": round(unrealized, 4),
        "total": round(equity_cash + unrealized, 4),
    }])
    p = portfolio_dir / EQUITY_FILE
    df = pd.concat([pd.read_csv(p), row], ignore_index=True) if p.exists() else row
    df.to_csv(p, index=False)

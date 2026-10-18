"""Agregat PnL harian untuk kalender web (murni baca file).

Output: {'YYYY-MM-DD': {'pnl': float, 'trades': int}} berdasarkan equity curve:
PnL hari-D = equity total TERAKHIR hari-D - equity total TERAKHIR hari-(D-1).
Hari tanpa observasi = tidak ada entri (kalender menandai netral/abu).
"""
from __future__ import annotations

import pandas as pd

from backend import config
from backend.core import portfolio as pf


def daily_pnl() -> dict[str, dict]:
    eq_path = config.PORTFOLIO_DIR / pf.EQUITY_FILE
    if not eq_path.exists():
        return {}
    df = pd.read_csv(eq_path)
    if df.empty or "total" not in df.columns:
        return {}
    df["date"] = pd.to_datetime(df["ts"], utc=True, errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["date"])
    if df.empty:
        return {}

    # equity penutup tiap hari = baris terakhir hari itu
    close = df.groupby("date")["total"].last()

    # jumlah trade per hari
    trades_per_day: dict[str, int] = {}
    tr_path = config.PORTFOLIO_DIR / pf.TRADES_FILE
    if tr_path.exists():
        tr = pd.read_csv(tr_path)
        if not tr.empty and "ts" in tr.columns:
            tr["date"] = pd.to_datetime(tr["ts"], utc=True, errors="coerce").dt.strftime("%Y-%m-%d")
            trades_per_day = tr.groupby("date").size().to_dict()

    out: dict[str, dict] = {}
    dates = list(close.index)
    for i, d in enumerate(dates):
        prev = close.iloc[i - 1] if i > 0 else (df["total"].iloc[0])  # hari pertama dibanding start
        pnl = float(close.loc[d]) - float(prev)
        out[d] = {"pnl": round(pnl, 4), "trades": int(trades_per_day.get(d, 0))}
    return out

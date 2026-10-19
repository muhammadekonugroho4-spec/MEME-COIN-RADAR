"""Job trader MCR: sinyal BUY -> pending order -> fill harga next scan -> monitor exit.

    .venv/bin/python -m jobs.job_trader

Alur per run:
1. Muat state paper (equity, posisi, pending orders).
2. Ambil harga terkini semua mint yang relevan (posisi + pending) dari data/coins parquet.
3. Fill pending orders di harga scan TERBARU (karena sinyal dibuat run sebelumnya).
4. Evaluasi exit tiap posisi (strategy) -> queue sell.
5. Sinyal BUY baru dari hasil scan terakhir (zona BUY) -> queue buy (fill run berikutnya).
6. Simpan state + jurnal + equity curve.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

from backend import config
from backend.core import paper_broker, portfolio, strategy
from backend.core.paper_broker import PendingOrder

PRICE_STALE_SECONDS = 360   # scalp: observasi >6 menit = basi (SL/TP harus reaksi cepat)


def latest_prices(coins_dir: Path, mints: list[str]) -> dict[str, dict]:
    """{'mint': {'price':..., 'liquidity':..., 'ts':...}} dari baris terakhir parquet."""
    out: dict[str, dict] = {}
    for mint in mints:
        df = portfolio_load(coins_dir, mint)
        if df is None or df.empty:
            continue
        last = df.iloc[-1].to_dict()
        if last.get("price_usd") and last.get("ts"):
            out[mint] = {
                "price": float(last["price_usd"]),
                "liquidity": float(last.get("liquidity_usd") or 0.0),
                "ts": float(last["ts"]),
            }
    return out


def portfolio_load(coins_dir: Path, mint: str):
    return pd.read_parquet(coins_dir / f"{_safe(mint)}.parquet") if (coins_dir / f"{_safe(mint)}.parquet").exists() else None


def _safe(mint: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in mint)[:60]


def _latest_scan_buys() -> list[dict]:
    """Kandidat zona BUY dari scan terakhir (data/daily terbaru)."""
    dirs = sorted((d for d in config.DAILY_DIR.iterdir() if d.is_dir() and d.name[:2] == "20"), reverse=True)
    for d in dirs:
        p = d / "scan_results.csv"
        if p.exists():
            df = pd.read_csv(p)
            if "zone" in df.columns:
                buys = df[df["zone"] == "BUY"].to_dict(orient="records")
                return buys
            return []
    return []


def run(dry_run: bool = False) -> dict:
    state = portfolio.load_state(config.PORTFOLIO_DIR, config.PAPER_START_EQUITY)
    now = time.time()

    # kumpulkan semua mint yang relevan
    pos_mints = list(state.get("positions", {}).keys())
    pend_mints = [o["mint"] for o in state.get("pending", [])]
    buys = _latest_scan_buys()
    buy_mints = [b["mint"] for b in buys if b["mint"] not in pos_mints]
    all_mints = list(dict.fromkeys(pos_mints + pend_mints + buy_mints))
    prices = latest_prices(config.COINS_DIR, all_mints)

    journal: list[dict] = []

    # --- 1. fill pending orders (harga scan terbaru = "next scan" dari sinyal) ---
    remaining: list[dict] = []
    for o in state.get("pending", []):
        pinfo = prices.get(o["mint"])
        if not pinfo or now - pinfo["ts"] > PRICE_STALE_SECONDS:
            # belum ada harga baru -> tetap pending (max 6 run, lalu batal)
            o["tries"] = o.get("tries", 0) + 1
            if o["tries"] <= 3:
                remaining.append(o)
            else:
                journal.append({"mint": o["mint"], "action": "cancel", "reason": "tidak ada fill 6 run"})
            continue
        order = PendingOrder(**{k: o[k] for k in
                                ("mint", "symbol", "side", "signal_ts", "signal_price", "signal_score") if k in o},
                             qty=o.get("qty"), reason=o.get("reason", ""), usd_size=o.get("usd_size"))
        if o["side"] == "buy":
            fill = paper_broker.fill_buy(order, pinfo["price"], pinfo["liquidity"], now)
            if fill:
                fill.usd = order.usd_size or fill.usd
                state = portfolio.apply_buy_fill(state, fill)
                pos = state["positions"].get(fill.mint)
                if pos:
                    pos["entry_liquidity"] = pinfo["liquidity"]  # liq nyata saat fill
                portfolio.log_trade(config.PORTFOLIO_DIR, fill)
                journal.append({"mint": fill.mint, "action": "buy_fill", "price": fill.price,
                                "slippage_pct": fill.slippage_pct, "reason": fill.reason})
        else:  # sell
            fill = paper_broker.fill_sell(order, pinfo["price"], pinfo["liquidity"], now)
            if fill:
                frac = o.get("fraction", 1.0)
                state = portfolio.apply_sell_fill(state, fill, fraction=frac)
                portfolio.log_trade(config.PORTFOLIO_DIR, fill)
                journal.append({"mint": fill.mint, "action": "sell_fill", "fraction": frac,
                                "price": fill.price, "reason": fill.reason})
    state["pending"] = remaining

    # --- 2. evaluasi exit posisi terbuka ---
    for mint, pos in list(state.get("positions", {}).items()):
        pinfo = prices.get(mint)
        if not pinfo or now - pinfo["ts"] > PRICE_STALE_SECONDS:
            continue  # tanpa harga segar, tunggu
        pos.update({k: v for k, v in pos.items()})
        pos = strategy.update_peak(pos, pinfo["price"])
        sig = strategy.evaluate_position(pos, pinfo["price"], pinfo["liquidity"], now)
        if sig.action in ("exit", "partial_exit"):
            already = any(o["mint"] == mint and o["side"] == "sell" for o in state["pending"])
            if not already:  # idempotent: jangan dobel order sell
                state["pending"].append({
                    "mint": mint, "symbol": pos.get("symbol", mint[:8]), "side": "sell",
                    "signal_ts": now, "signal_price": pinfo["price"], "signal_score": 0.0,
                    "qty": pos["qty"], "fraction": sig.fraction, "reason": sig.reason,
                    "tries": 0,
                })
            journal.append({"mint": mint, "action": f"queue_{sig.action}", "reason": sig.reason})
        state["positions"][mint] = pos

    # --- 3. sinyal BUY baru (zona BUY dari scan terakhir) ---
    open_count = portfolio.open_positions(state)
    pending_buy_mints = {o["mint"] for o in state["pending"] if o["side"] == "buy"}
    for b in buys:
        mint = b["mint"]
        if mint in state["positions"] or mint in pending_buy_mints:
            continue  # sudah punya posisi/order (idempotent)
        pinfo = prices.get(mint)
        order = paper_broker.queue_buy(
            mint, str(b.get("symbol", mint[:8])), now,
            float(b["price_usd"]) if b.get("price_usd") else None,
            float(b.get("score") or 0.0),
            portfolio.total_equity(state, {m: pi["price"] for m, pi in prices.items()}),
            open_count,
        )
        if order is None:
            journal.append({"mint": mint, "action": "skip_buy", "reason": "slot penuh / equity kecil"})
            continue
        state["pending"].append({
            "mint": mint, "symbol": order.symbol, "side": "buy",
            "signal_ts": now, "signal_price": order.signal_price, "signal_score": order.signal_score,
            "usd_size": order.usd_size, "reason": order.reason, "tries": 0,
        })
        open_count += 1
        journal.append({"mint": mint, "action": "queue_buy", "reason": order.reason})

    # --- 4. simpan + equity curve ---
    prices_for_pnl = {m: pi["price"] for m, pi in prices.items() if now - pi["ts"] <= PRICE_STALE_SECONDS}
    unreal = portfolio.unrealized_pnl(state, prices_for_pnl)
    if not dry_run:
        portfolio.save_state(config.PORTFOLIO_DIR, state)
        portfolio.log_equity(config.PORTFOLIO_DIR, state["equity"], unreal)

    manifest = {
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "equity_cash": round(state["equity"], 4),
        "unrealized": round(unreal, 4),
        "total": round(state["equity"] + unreal, 4),
        "open_positions": len(state.get("positions", {})),  # faktual dari state, bukan counter
        "pending": len(state["pending"]),
        "actions": journal,
    }
    day_dir = config.DAILY_DIR / time.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "trader_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest


def main() -> int:
    import argparse
    from backend.core.cycle_runner import run_cycles

    ap = argparse.ArgumentParser(description="MCR paper trader (multi-siklus)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cycles", type=int, default=10, help="jumlah siklus dalam 1 run (Solusi A)")
    ap.add_argument("--interval", type=int, default=60, help="jeda antar siklus (detik)")
    args = ap.parse_args()

    results = run_cycles(lambda: run(dry_run=args.dry_run),
                         cycles=args.cycles, interval_seconds=args.interval, deadline_min=14.0)
    last = results[-1] if results else {}
    print(json.dumps({k: v for k, v in last.items() if k != "actions"}, indent=2))
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())

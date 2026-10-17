"""Job scan MCR: deteksi coin baru -> parquet + manifest + jurnal keputusan.

    .venv/bin/python -m jobs.job_scan

Tiap run: scan pasangan baru -> untuk mint baru ambil detail + supply -> catat observasi.
Filter/scorer menyusul di Fase 2; di sini pipeline data mentah + jurnal "seen".
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

from backend import config
from backend.adapters.base import DataSourceError
from backend.adapters.coingecko import CoinGeckoAdapter
from backend.adapters.dexscreener import DexScreenerAdapter
from backend.adapters.solana_rpc import SolanaRpcAdapter
from backend.core import coin_store


def run(queries: tuple[str, ...] = ("pump", "sol"), max_new: int = 15) -> dict:
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    dx = DexScreenerAdapter()
    sol = SolanaRpcAdapter()
    cg = CoinGeckoAdapter()

    pairs = dx.scan_new_pairs(queries=queries)
    seen = coin_store.known_mints(config.COINS_DIR)

    # dedup antar mint, ambil yang benar-benar baru
    by_mint: dict[str, dict] = {}
    for p in pairs:
        by_mint.setdefault(p["mint"], p)
    fresh = [p for m, p in by_mint.items() if m not in seen][:max_new]

    sol_ok = sol.health()
    sol_price = cg.price_sol()

    results: list[dict] = []
    for p in fresh:
        mint = p["mint"]
        detail = None
        try:
            detail = dx.token_detail(mint)
        except DataSourceError:
            detail = None
        best = detail or p  # detail lebih likuid; fallback hasil search
        supply_info = sol.token_supply(mint) if sol_ok else None
        row = {
            "ts": time.time(),
            "mint": mint,
            "price_usd": best["price_usd"],
            "liquidity_usd": best["liquidity_usd"],
            "fdv": best["fdv"],
            "market_cap": best["market_cap"],
            "vol_m5": best["vol_m5"],
            "vol_h1": best["vol_h1"],
            "vol_h24": best["vol_h24"],
            "buys_m5": best["buys_m5"],
            "sells_m5": best["sells_m5"],
            "buys_h1": best["buys_h1"],
            "sells_h1": best["sells_h1"],
            "chg_m5": best["chg_m5"],
            "chg_h1": best["chg_h1"],
            "chg_h24": best["chg_h24"],
            "supply": supply_info["supply"] if supply_info else None,
        }
        if row["price_usd"] is None:
            results.append({"mint": mint, "symbol": best["symbol"], "action": "skip:no_price"})
            continue
        rows_total = coin_store.append_observation(config.COINS_DIR, row)
        results.append(
            {
                "mint": mint,
                "symbol": best["symbol"],
                "action": "recorded",
                "price_usd": row["price_usd"],
                "liquidity_usd": row["liquidity_usd"],
                "age_min": coin_store.age_minutes(best["pair_created_at"]),
                "supply": row["supply"],
                "rows": rows_total,
            }
        )

    manifest = {
        "run_at": started,
        "pairs_scanned": len(pairs),
        "known_before": len(seen),
        "fresh_candidates": len(fresh),
        "recorded": sum(1 for r in results if r["action"] == "recorded"),
        "skipped": sum(1 for r in results if r["action"] != "recorded"),
        "solana_rpc_ok": sol_ok,
        "sol_price_usd": sol_price,
        "results": results,
    }
    day_dir = config.DAILY_DIR / time.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "scan_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    pd.DataFrame(results).to_csv(day_dir / "scan_results.csv", index=False)
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description="MCR scan pipeline")
    ap.add_argument("--max-new", type=int, default=15)
    args = ap.parse_args()
    m = run(max_new=args.max_new)
    print(json.dumps({k: v for k, v in m.items() if k != "results"}, indent=2))
    return 0 if m["pairs_scanned"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())

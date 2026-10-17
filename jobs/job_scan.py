"""Job scan MCR: deteksi coin baru -> filter keras -> skor -> parquet + manifest + jurnal.

    .venv/bin/python -m jobs.job_scan

Tiap mint baru dinilai: PASS (BUY zone) / WATCH / REJECT (dengan alasan).
Semua keputusan tercatat di data/daily/YYYY-MM-DD/.
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
from backend.core import coin_store, risk_filter, scorer


def _evaluate(row: dict, age_min: float | None, supply: float | None) -> dict:
    """Filter keras dulu (REJECT), lalu skor untuk yang lolos."""
    reasons = risk_filter.reject_reasons(row, age_min, chg_m5_low=row.get("chg_m5"))
    if reasons:
        return {"zone": "REJECT", "score": 0.0, "reasons": reasons, "parts": {}}
    s = scorer.score(row, age_min, supply)
    return {"zone": s.zone, "score": s.score, "reasons": [], "parts": s.parts}


def run(queries: tuple[str, ...] = ("pump", "sol"), max_new: int = 15) -> dict:
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    dx = DexScreenerAdapter()
    sol = SolanaRpcAdapter()
    cg = CoinGeckoAdapter()

    pairs = dx.scan_new_pairs(queries=queries)
    seen = coin_store.known_mints(config.COINS_DIR)

    by_mint: dict[str, dict] = {}
    for p in pairs:
        by_mint.setdefault(p["mint"], p)
    fresh = [p for m, p in by_mint.items() if m not in seen][:max_new]

    sol_ok = sol.health()
    sol_price = cg.price_sol()

    results: list[dict] = []
    zone_counts = {"BUY": 0, "WATCH": 0, "PASSIVE": 0, "REJECT": 0}
    for p in fresh:
        mint = p["mint"]
        try:
            detail = dx.token_detail(mint)
        except DataSourceError:
            detail = None
        best = detail or p
        supply_info = sol.token_supply(mint) if sol_ok else None
        age_min = coin_store.age_minutes(best["pair_created_at"])
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
            results.append({"mint": mint, "symbol": best["symbol"], "zone": "SKIP", "score": 0.0,
                            "reasons": "harga tidak tersedia", "parts": json.dumps({})})
            zone_counts["SKIP"] = zone_counts.get("SKIP", 0) + 1
            continue

        verdict = _evaluate(row, age_min, row["supply"])

        # simpan observasi hanya untuk yang layak dipantau (hemat ruang git);
        # REJECT diarsipkan cukup di jurnal harian.
        if verdict["zone"] in ("BUY", "WATCH"):
            coin_store.append_observation(config.COINS_DIR, row)

        results.append({
            "mint": mint,
            "symbol": best["symbol"],
            "zone": verdict["zone"],
            "score": verdict["score"],
            "reasons": " | ".join(verdict["reasons"]),
            "parts": json.dumps(verdict["parts"]),
            "price_usd": row["price_usd"],
            "liquidity_usd": row["liquidity_usd"],
            "fdv": row["fdv"],
            "age_min": round(age_min, 1) if age_min is not None else None,
            "chg_h1": row["chg_h1"],
        })
        zone_counts[verdict["zone"]] = zone_counts.get(verdict["zone"], 0) + 1

    manifest = {
        "run_at": started,
        "pairs_scanned": len(pairs),
        "known_before": len(seen),
        "fresh_candidates": len(fresh),
        "zones": zone_counts,
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
    ap = argparse.ArgumentParser(description="MCR scan + filter + skor")
    ap.add_argument("--max-new", type=int, default=15)
    args = ap.parse_args()
    m = run(max_new=args.max_new)
    print(json.dumps({k: v for k, v in m.items() if k != "results"}, indent=2, ensure_ascii=False))
    return 0 if m["pairs_scanned"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())

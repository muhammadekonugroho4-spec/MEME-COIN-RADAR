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
from backend.adapters.pumpfun import PumpFunAdapter
from backend.adapters.solana_rpc import SolanaRpcAdapter
from backend.core import coin_store, risk_filter, scorer
from backend.adapters.sentiment import SentimentAdapter
from backend.core.ai_service import analyze_risk
from backend.core.sentiment import adjust_technical_score, hype_for
from backend.core.onchain_filter import onchain_reasons, top10_pct_from_accounts


def _evaluate(row: dict, age_min: float | None, supply: float | None, min_age_minutes: float = 30.0) -> dict:
    """Filter keras dulu (REJECT), lalu skor untuk yang lolos."""
    reasons = risk_filter.reject_reasons(row, age_min, chg_m5_low=row.get("chg_m5"), min_age_minutes=min_age_minutes)
    if reasons:
        return {"zone": "REJECT", "score": 0.0, "reasons": reasons, "parts": {}}
    s = scorer.score(row, age_min, supply)
    return {"zone": s.zone, "score": s.score, "reasons": [], "parts": s.parts}


def _evaluate_onchain(mint_authority, freeze_authority, top10_pct) -> list[str]:
    return onchain_reasons(mint_authority, freeze_authority, top10_pct)


def run(queries: tuple[str, ...] = ("pump", "sol"), max_new: int = 15, min_age: float = 5.0) -> dict:
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    dx = DexScreenerAdapter()
    pf_adapter = PumpFunAdapter()
    sol = SolanaRpcAdapter()
    cg = CoinGeckoAdapter()

    sol_ok = sol.health()
    sol_price = cg.price_sol()

    pairs = dx.scan_new_pairs(queries=queries)
    seen = coin_store.known_mints(config.COINS_DIR)

    by_mint: dict[str, dict] = {}
    for p in pairs:
        by_mint.setdefault(p["mint"], p)

    # Sumber UTAMA coin baru: pump.fun newest (search DexScreener tidak menampilkan
    # coin umur menit karena sort likuiditas). Untuk mint baru pump.fun yang belum
    # ada detail pair, tetap masuk kandidat (harga bisa None -> SKIP dgn jurnal).
    for nc in pf_adapter.newest_coins(limit=20):
        if nc["mint"] in seen:
            continue
        # Harga real-time dari bonding curve: usd_mcap / 1e9 (supply pump.fun konstan)
        # Likuiditas efektif = real SOL di curve x harga SOL (untuk scalp, pool belum terbentuk)
        mcap = nc.get("usd_market_cap") or 0.0
        sol_in_curve = nc.get("real_sol_reserves") or 0.0
        liq_eff = sol_in_curve * (sol_price or 100.0)
        existing = by_mint.get(nc["mint"])
        if existing is not None:
            # search sudah punya pair-nya; tapi curve lebih segar utk likuiditas kecil:
            # ambil likuiditas terbesar, harga curve tetap dipakai bila search tidak punya harga
            if liq_eff > (existing.get("liquidity_usd") or 0):
                existing["liquidity_usd"] = liq_eff
            if existing.get("price_usd") is None and mcap > 0:
                existing["price_usd"] = mcap / 1e9
                existing["fdv"] = mcap
                existing["market_cap"] = mcap
            if not existing.get("pair_created_at") and nc.get("created_ms"):
                existing["pair_created_at"] = nc["created_ms"]
            continue
        by_mint[nc["mint"]] = {
                "mint": nc["mint"], "pair_address": "", "symbol": nc["symbol"],
                "name": nc["name"], "dex": "pumpfun",
                "price_usd": mcap / 1e9 if mcap > 0 else None,
                "liquidity_usd": liq_eff, "fdv": mcap, "market_cap": mcap,
                "vol_m5": 0.0, "vol_h1": 0.0, "vol_h24": 0.0,
                "buys_m5": 0, "sells_m5": 0, "buys_h1": 0, "sells_h1": 0,
                "buys_h24": 0, "sells_h24": 0,
                "chg_m5": 0.0, "chg_h1": 0.0, "chg_h24": 0.0,
                "pair_created_at": nc.get("created_ms"),
            }
    fresh = [p for m, p in by_mint.items() if m not in seen][:max_new]

    # Bot A - sentiment: SEKALI per run (hemat quota), dipakai semua kandidat
    sent = SentimentAdapter()
    trending = sent.coingecko_trending_symbols()
    boosts_list = sent.dexscreener_boosts_solana()
    boosts = {b["mint"]: b for b in boosts_list}

    results: list[dict] = []
    zone_counts = {"BUY": 0, "WATCH": 0, "PASSIVE": 0, "REJECT": 0}
    for p in fresh:
        mint = p["mint"]
        try:
            detail = dx.token_detail(mint)
        except DataSourceError:
            detail = None
        # Prioritas: kalau kandidat datang dari pump.fun (curve aktif), harga/likuiditas
        # curve lebih segar; DexScreener detail dipakai bila likuiditasnya lebih besar.
        p_row = by_mint[mint]
        d_row = detail or {}
        if d_row and (d_row.get("liquidity_usd") or 0) > (p_row.get("liquidity_usd") or 0):
            best = d_row
        else:
            best = p_row
        supply_info = sol.token_supply(mint) if sol_ok else None
        age_min = coin_store.age_minutes(best["pair_created_at"])
        row = {
            "ts": time.time(),
            "dex": best.get("dex", ""),
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

        verdict = _evaluate(row, age_min, row["supply"], min_age_minutes=min_age)

        # Lapisan on-chain (Fase 4): authority + konsentrasi holder, hanya untuk yang lolos filter API
        if verdict["zone"] != "REJECT":
            top10 = sol.top10_holders_pct(mint, row["supply"]) if row["supply"] else None
            oc_reasons = _evaluate_onchain(
                supply_info.get("mint_authority") if supply_info else None,
                supply_info.get("freeze_authority") if supply_info else None,
                top10,
            )
            if oc_reasons:
                verdict = {"zone": "REJECT", "score": 0.0,
                           "reasons": verdict["reasons"] + oc_reasons, "parts": verdict["parts"]}

        # Bot A: hype score dari sentiment, geser skor teknikal maks ±10
        hype = hype_for(best["symbol"], mint, trending, boosts)
        if verdict["zone"] != "REJECT":
            verdict["score"] = adjust_technical_score(verdict["score"], hype)
            # zona bisa berubah setelah adjust (65 ambang BUY)
            if verdict["score"] < 65 and verdict["zone"] == "BUY":
                verdict["zone"] = "WATCH"

        # Narasi AI (Fase 5): 1-2 kalimat risiko; mock bila key kosong
        top10_for_ai = sol.top10_holders_pct(mint, row["supply"]) if row["supply"] else None
        ai = analyze_risk(
            row, verdict["score"], verdict["zone"], verdict["reasons"], top10_for_ai, age_min
        )

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
            "ai_flag": ai.flag,
            "hype_score": hype.score,
            "hype_note": hype.note,
            "hype_paid": hype.paid_boost,
            "ai_note": ai.note,
            "ai_engine": ai.engine,
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
        "sentiment": {"trending_symbols": trending[:10], "boosts_tracked": len(boosts)},
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

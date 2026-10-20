"""API MCR - baca hasil scan terbaru dari data/daily/ (murni baca file)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
from fastapi import APIRouter

from backend import config
from backend.core.links import all_links

router = APIRouter(prefix="/api")


def _latest_day() -> Path | None:
    dirs = sorted((d for d in config.DAILY_DIR.iterdir() if d.is_dir() and d.name[:2] == "20"), reverse=True)
    return dirs[0] if dirs else None


@router.get("/scan")
def api_scan(day: str | None = None):
    d = Path(day) if day else _latest_day()
    if d is None or not (d / "scan_results.csv").exists():
        return {"day": None, "manifest": {}, "results": []}
    mf = d / "scan_manifest.json"
    manifest = json.loads(mf.read_text()) if mf.exists() else {}
    df = pd.read_csv(d / "scan_results.csv").astype(object)
    df = df.where(pd.notna(df), None)
    rows = [{k: (None if isinstance(v, float) and v != v else v) for k, v in r.items()} for r in df.to_dict(orient="records")]
    # deep link terminal trading (GMGN/Photon/Jupiter/...) per kandidat
    for r in rows:
        r["links"] = all_links(str(r.get("mint") or ""))
    return {"day": d.name, "manifest": manifest, "results": rows}


@router.get("/stats")
def api_stats():
    """Statistik filter kumulatif: berapa % reject per kelompok alasan."""
    buckets = {"likuiditas": 0, "umur": 0, "FDV": 0, "wash": 0, "rug": 0, "umur tidak diketahui": 0, "lain": 0}
    total = 0
    for d in sorted(config.DAILY_DIR.glob("20*")):
        p = d / "scan_results.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p)
        for reasons in df.get("reasons", pd.Series(dtype=str)).fillna(""):
            if not reasons:
                continue
            total += 1
            rl = reasons.lower()
            if "likuiditas" in rl:
                buckets["likuiditas"] += 1
            elif "tidak diketahui" in rl:
                buckets["umur tidak diketahui"] += 1
            elif "umur" in rl:
                buckets["umur"] += 1
            elif "FDV" in reasons:
                buckets["FDV"] += 1
            elif "wash" in rl:
                buckets["wash"] += 1
            elif "rug" in rl:
                buckets["rug"] += 1
            else:
                buckets["lain"] += 1
    return {"total_rejected": total, "by_reason": buckets}


@router.get("/positions")
def api_positions():
    """State paper: KPI + posisi terbuka (dgn harga kini) + pending + equity curve."""
    from backend.core import portfolio as pf

    state = pf.load_state(config.PORTFOLIO_DIR, config.PAPER_START_EQUITY)

    def _latest(mint: str):
        p = config.COINS_DIR / f"{mint}.parquet"
        if not p.exists():
            return None
        df = pd.read_parquet(p)
        if df.empty:
            return None
        last = df.iloc[-1].to_dict()
        return {"price": last.get("price_usd"), "ts": last.get("ts")}

    positions = []
    for mint, pos in state.get("positions", {}).items():
        info = _latest(mint)
        positions.append({
            "mint": mint, "symbol": pos.get("symbol", mint[:8]),
            "qty": pos.get("qty"), "entry_price": pos.get("entry_price"),
            "price_now": info["price"] if info else None,
            "tp_done": pos.get("tp_done", False),
            "links": all_links(mint),
        })
    pending = state.get("pending", [])
    for o in pending:
        o["links"] = all_links(str(o.get("mint") or ""))
    equity_df = pd.read_csv(config.PORTFOLIO_DIR / pf.EQUITY_FILE).tail(50).to_dict(orient="records") \
        if (config.PORTFOLIO_DIR / pf.EQUITY_FILE).exists() else []

    prices_now = {p["mint"]: p["price_now"] for p in positions if p["price_now"] is not None}
    unreal = pf.unrealized_pnl(state, prices_now)
    return {
        "start_equity": state.get("start_equity", config.PAPER_START_EQUITY),
        "equity_cash": state["equity"],
        "unrealized": round(unreal, 4),
        "total": round(state["equity"] + unreal, 4),
        "open_positions": len(positions),
        "positions": positions,
        "pending": pending,
        "equity": equity_df,
    }


@router.get("/calendar")
def api_calendar():
    dpnl = config.PORTFOLIO_DIR / "daily_pnl.json"
    return {"days": json.loads(dpnl.read_text()) if dpnl.exists() else {}}


@router.get("/radar")
def api_radar():
    """Ringkasan untuk halaman utama: temuan terbaru + kalender PnL.

    Temuan = semua kandidat non-REJECT hari terakhir, terurut skor.
    """
    d = _latest_day()
    findings: list[dict] = []
    if d is not None and (d / "scan_results.csv").exists():
        df = pd.read_csv(d / "scan_results.csv").astype(object)
        df = df.where(pd.notna(df), None)
        for r in df.to_dict(orient="records"):
            if str(r.get("zone") or "").upper() == "REJECT":
                continue
            findings.append({
                "signal": r.get("zone"),
                "symbol": r.get("symbol"),
                "mint": r.get("mint"),
                "score": r.get("score"),
                "price_usd": r.get("price_usd"),
                "liquidity_usd": r.get("liquidity_usd"),
                "fdv": r.get("fdv"),
                "age_min": r.get("age_min"),
                "chg_h1": r.get("chg_h1"),
                "hype_score": r.get("hype_score"),
                "hype_paid": r.get("hype_paid"),
                "ai_flag": r.get("ai_flag"),
                "ai_note": r.get("ai_note"),
                "links": all_links(str(r.get("mint") or "")),
            })
        findings.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    cal = api_calendar()
    return {"day": d.name if d else None, "findings": findings, **cal}


@router.get("/journal")
def api_journal(day: str | None = None):
    d = Path(day) if day else _latest_day()
    if d is None:
        return {"day": None, "trades": []}
    p = config.PORTFOLIO_DIR / "trades.csv"
    trades = pd.read_csv(p).tail(100).to_dict(orient="records") if p.exists() else []
    return {"day": d.name, "trades": trades}

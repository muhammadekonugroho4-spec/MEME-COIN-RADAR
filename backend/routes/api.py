"""API MCR - baca hasil scan terbaru dari data/daily/ (murni baca file)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
from fastapi import APIRouter

from backend import config

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
    rows = pd.read_csv(d / "scan_results.csv").where(pd.notna(pd.read_csv(d / "scan_results.csv")), None).to_dict(orient="records")
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

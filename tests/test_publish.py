"""Test job publish: render statis dari data palsu - offline penuh."""
import json
from pathlib import Path

import pandas as pd

from jobs import job_publish


def _seed(tmp_path: Path):
    coins, daily, port = tmp_path / "coins", tmp_path / "daily", tmp_path / "portfolio"
    day = daily / "2026-10-17"
    day.mkdir(parents=True)
    coins.mkdir()

    pd.DataFrame([{"mint": "M" * 44, "symbol": "TST", "zone": "REJECT", "score": 0.0,
                   "reasons": "likuiditas $900 < $5,000", "parts": "{}", "ai_flag": "danger",
                   "ai_note": "gagal filter.", "price_usd": 0.001, "liquidity_usd": 900.0,
                   "fdv": 1000.0, "age_min": 5.0, "chg_h1": 0.0}]).to_csv(day / "scan_results.csv", index=False)
    (day / "scan_manifest.json").write_text(json.dumps({"zones": {"REJECT": 1}, "pairs_scanned": 5}))
    (day / "report.md").write_text("# Laporan\n\n- Win rate: 50%")

    port.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"ts": "2026-10-17T10:00:00", "mint": "M" * 44, "symbol": "TST", "side": "buy",
                   "qty": 100.0, "price": 1.0, "usd": 100.0, "slippage_pct": 0.5,
                   "signal_price": 0.99, "reason": "zona BUY skor 75"}]).to_csv(port / "trades.csv", index=False)
    (port / "equity.csv").write_text("ts,equity_cash,unrealized,total\n2026-10-17T10:00:00,900.0,0.0,900.0\n")
    (port / "state.json").write_text(json.dumps({
        "equity": 900.0, "start_equity": 1000.0, "positions": {}, "pending": [], "_applied": []}))
    return coins, daily, port


def test_build_offline(tmp_path, monkeypatch):
    from backend.core import portfolio as pf  # noqa: F401
    coins, daily, port = _seed(tmp_path)
    monkeypatch.setattr(job_publish.config, "COINS_DIR", coins)
    monkeypatch.setattr(job_publish.config, "DAILY_DIR", daily)
    monkeypatch.setattr(job_publish.config, "PORTFOLIO_DIR", port)

    out = job_publish.build(tmp_path / "publish")
    assert (out / "index.html").exists() and (out / "data.json").exists()

    data = json.loads((out / "data.json").read_text())
    assert data["day"] == "2026-10-17"
    assert data["scan"]["results"][0]["zone"] == "REJECT"
    assert data["portfolio"]["equity_cash"] == 900.0
    assert data["stats"]["total_rejected"] == 1
    assert "Win rate" in data["report_md"]

    html_text = (out / "index.html").read_text()
    assert "MEME-COIN-RADAR" in html_text
    assert "data.json" in html_text  # dashboard memuat data.json


def test_build_empty_data_ok(tmp_path, monkeypatch):
    coins, daily, port = tmp_path / "coins", tmp_path / "daily", tmp_path / "portfolio"
    coins.mkdir(); daily.mkdir(); port.mkdir()
    monkeypatch.setattr(job_publish.config, "COINS_DIR", coins)
    monkeypatch.setattr(job_publish.config, "DAILY_DIR", daily)
    monkeypatch.setattr(job_publish.config, "PORTFOLIO_DIR", port)

    out = job_publish.build(tmp_path / "publish")
    data = json.loads((out / "data.json").read_text())
    assert data["day"] is None and data["scan"]["results"] == []

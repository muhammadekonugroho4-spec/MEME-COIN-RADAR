"""Test job report (Fase 7): win rate, rug stats, baseline acak, laporan MD."""
from pathlib import Path
import pytest
import pandas as pd

from backend.core import portfolio as pf
from jobs import job_report


def _seed_trades(port: Path):
    rows = [
        # 1 menang (+100%), 1 rug (-35%), hold wajar
        {"ts": "2026-10-17T10:00:00", "mint": "AAA", "symbol": "WIN", "side": "buy", "qty": 100.0,
         "price": 1.0, "usd": 100.0, "slippage_pct": 0.5, "signal_price": 0.99, "reason": "zona BUY"},
        {"ts": "2026-10-17T12:00:00", "mint": "AAA", "symbol": "WIN", "side": "sell", "qty": 50.0,
         "price": 2.0, "usd": 100.0, "slippage_pct": 0.5, "signal_price": 2.05, "reason": "take-profit pertama +100%, jual 50%"},
        {"ts": "2026-10-17T12:30:00", "mint": "AAA", "symbol": "WIN", "side": "sell", "qty": 50.0,
         "price": 2.4, "usd": 120.0, "slippage_pct": 0.5, "signal_price": 2.5, "reason": "trailing stop"},
        {"ts": "2026-10-17T10:10:00", "mint": "BBB", "symbol": "RUG", "side": "buy", "qty": 100.0,
         "price": 1.0, "usd": 100.0, "slippage_pct": 0.5, "signal_price": 0.99, "reason": "zona BUY"},
        {"ts": "2026-10-17T11:00:00", "mint": "BBB", "symbol": "RUG", "side": "sell", "qty": 100.0,
         "price": 0.65, "usd": 65.0, "slippage_pct": 0.5, "signal_price": 0.65, "reason": "stop-loss -35% dari entry"},
    ]
    pd.DataFrame(rows).to_csv(port / pf.TRADES_FILE, index=False)


def test_match_trades_fifo(tmp_path):
    _seed_trades(tmp_path)
    df = pd.read_csv(tmp_path / pf.TRADES_FILE)
    rt = job_report._match_trades(df)
    assert len(rt) == 2
    aaa = rt[rt["mint"] == "AAA"].iloc[0]
    # TP jual 50 @2.0 (pnl +50) + trailing jual 50 @2.4 (pnl +70) = +120
    assert aaa["pnl"] == pytest.approx(120.0, abs=0.01)
    bbb = rt[rt["mint"] == "BBB"].iloc[0]
    assert bbb["pnl"] == pytest.approx(-35.0, abs=0.01)
    assert "stop-loss" in bbb["reason"]


def test_report_full(tmp_path, monkeypatch):
    coins, daily, port = tmp_path / "coins", tmp_path / "daily", tmp_path / "portfolio"
    coins.mkdir(); daily.mkdir(); port.mkdir()
    _seed_trades(port)
    pd.DataFrame([{"zone": ["REJECT"] * 8 + ["BUY"]}], )  # placeholder shape
    scan = pd.DataFrame({"zone": ["REJECT"] * 8 + ["BUY"]})
    d = daily / "2026-10-17"
    d.mkdir(parents=True)
    scan.to_csv(d / "scan_results.csv", index=False)

    monkeypatch.setattr(job_report.config, "PORTFOLIO_DIR", port)
    monkeypatch.setattr(job_report.config, "DAILY_DIR", daily)

    r = job_report.run()
    st = r["stats"]
    assert st["round_trips"] == 2
    assert st["wins"] == 1 and st["win_rate_pct"] == 50.0
    assert st["total_pnl"] == pytest.approx(85.0, abs=0.01)
    assert st["rug_exits"] == 1

    text = Path(r["report_path"]).read_text()
    assert "Win rate" in text
    assert "strategi" in text.lower()
    assert "Simulasi virtual" in text


def test_report_empty_portfolio(tmp_path, monkeypatch):
    daily = tmp_path / "daily"
    daily.mkdir()
    monkeypatch.setattr(job_report.config, "PORTFOLIO_DIR", tmp_path / "portfolio")
    monkeypatch.setattr(job_report.config, "DAILY_DIR", daily)

    r = job_report.run()
    # laporan ditulis di folder hari ini (job_report memakai tanggal run)
    text = Path(r["report_path"]).read_text()
    assert "Belum ada trade" in text


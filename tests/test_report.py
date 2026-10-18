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



def test_daily_pnl_aggregation(tmp_path, monkeypatch):
    from backend.core import daily_stats

    port = tmp_path / "portfolio"
    port.mkdir(parents=True)
    pd.DataFrame([
        {"ts": "2026-10-17T10:00:00+00:00", "equity_cash": 1000.0, "unrealized": 0.0, "total": 1000.0},
        {"ts": "2026-10-17T18:00:00+00:00", "equity_cash": 1050.0, "unrealized": 0.0, "total": 1050.0},
        {"ts": "2026-10-18T10:00:00+00:00", "equity_cash": 1020.0, "unrealized": 0.0, "total": 1020.0},
    ]).to_csv(port / pf.EQUITY_FILE, index=False)
    pd.DataFrame([
        {"ts": "2026-10-17T10:00:00+00:00", "mint": "A", "symbol": "A", "side": "buy", "qty": 1, "price": 1, "usd": 1, "slippage_pct": 0, "signal_price": 1, "reason": ""},
        {"ts": "2026-10-17T11:00:00+00:00", "mint": "A", "symbol": "A", "side": "sell", "qty": 1, "price": 2, "usd": 2, "slippage_pct": 0, "signal_price": 2, "reason": ""},
        {"ts": "2026-10-18T10:00:00+00:00", "mint": "B", "symbol": "B", "side": "buy", "qty": 1, "price": 1, "usd": 1, "slippage_pct": 0, "signal_price": 1, "reason": ""},
    ]).to_csv(port / pf.TRADES_FILE, index=False)

    monkeypatch.setattr(daily_stats.config, "PORTFOLIO_DIR", port)
    d = daily_stats.daily_pnl()
    assert d["2026-10-17"]["pnl"] == pytest.approx(50.0)  # 1050 - 1000 (vs start)
    assert d["2026-10-17"]["trades"] == 2
    assert d["2026-10-18"]["pnl"] == pytest.approx(-30.0)  # 1020 - 1050 (vs kemarin)
    assert d["2026-10-18"]["trades"] == 1


def test_calendar_api_and_render(tmp_path, monkeypatch):
    import json as _json
    from fastapi.testclient import TestClient
    from backend import config as cfg
    from backend.main import app

    monkeypatch.setattr(cfg, "PORTFOLIO_DIR", tmp_path)
    (tmp_path / "daily_pnl.json").write_text(_json.dumps({"2026-10-18": {"pnl": 12.5, "trades": 2}}))

    c = TestClient(app)
    body = c.get("/api/calendar").json()
    assert body["days"]["2026-10-18"]["pnl"] == 12.5
    assert c.get("/").status_code == 200

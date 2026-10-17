import pandas as pd
"""Test mesin anti-scam & scorer - offline, deterministik (§4.1-4.3 PROMPT)."""
import pytest

from backend.core import risk_filter, scorer


def row(**over):
    base = {
        "mint": "M", "price_usd": 0.001, "liquidity_usd": 20_000.0, "fdv": 100_000.0,
        "vol_m5": 1_000.0, "vol_h1": 8_000.0, "vol_h24": 30_000.0,
        "buys_m5": 40, "sells_m5": 25, "buys_h1": 300, "sells_h1": 200,
        "chg_m5": 0.5, "chg_h1": 25.0, "chg_h24": 40.0,
    }
    base.update(over)
    return base


# ---------- filter keras §4.1 ----------

def test_healthy_coin_passes_all_filters():
    assert risk_filter.reject_reasons(row(), age_min=90.0) == []


def test_low_liquidity_rejected():
    r = risk_filter.reject_reasons(row(liquidity_usd=900.0), age_min=90.0)
    assert any("likuiditas" in x for x in r)


def test_too_young_rejected():
    r = risk_filter.reject_reasons(row(), age_min=5.0)
    assert any("umur" in x for x in r)


def test_unknown_age_rejected():
    r = risk_filter.reject_reasons(row(), age_min=None)
    assert any("umur pair tidak diketahui" in x for x in r)


def test_high_fdv_rejected():
    r = risk_filter.reject_reasons(row(fdv=50_000_000.0), age_min=90.0)
    assert any("FDV" in x for x in r)


def test_wash_trading_rejected():
    r = risk_filter.reject_reasons(row(vol_h24=900_000.0), age_min=90.0)  # 45x likuiditas
    assert any("wash" in x for x in r)


def test_rugged_rejected():
    r = risk_filter.reject_reasons(row(chg_m5=-75.0), age_min=90.0, chg_m5_low=-75.0)
    assert any("sudah rug" in x for x in r)


def test_multiple_reasons_accumulate():
    r = risk_filter.reject_reasons(row(liquidity_usd=100.0), age_min=1.0)
    assert len(r) >= 2  # likuiditas + umur, keduanya tercatat


# ---------- scorer §4.2-4.3 ----------

def test_scorer_deterministic():
    s1 = scorer.score(row(), 90.0, 1e9)
    s2 = scorer.score(row(), 90.0, 1e9)
    assert s1.score == s2.score and s1.parts == s2.parts


def test_scorer_healthy_coin_high_score():
    s = scorer.score(row(), 90.0, 1e9)  # umur 1.5 jam = sweet spot
    assert s.zone in ("BUY", "WATCH")
    assert s.parts["age_sweetspot"] == 15.0
    assert s.parts["supply_known"] == 15.0


def test_scorer_vertical_pump_gets_zero_momentum():
    s = scorer.score(row(chg_h1=350.0), 90.0, 1e9)  # vertikal
    assert s.parts["momentum"] == 0.0


def test_scorer_pump_bot_ratio_zero():
    s = scorer.score(row(buys_m5=200, sells_m5=10), 90.0, 1e9)  # rasio 20x
    assert s.parts["buy_sell_ratio"] == 0.0


def test_scorer_quiet_book_zero_ratio():
    s = scorer.score(row(buys_m5=2, sells_m5=1), 90.0, 1e9)  # <10 tx = sepi
    assert s.parts["buy_sell_ratio"] == 0.0


def test_scorer_no_supply_no_points():
    s = scorer.score(row(), 90.0, None)
    assert s.parts["supply_known"] == 0.0
    assert s.score < 100.0


def test_zones_boundaries():
    assert scorer.SkorResult(75.0, "BUY", {}).zone == "BUY"
    assert scorer.SkorResult(50.0, "WATCH", {}).zone == "WATCH"
    assert scorer.SkorResult(10.0, "PASSIVE", {}).zone == "PASSIVE"


# ---------- API fase 2 ----------

def test_api_scan_endpoint(tmp_path, monkeypatch):
    import json as _json
    from fastapi.testclient import TestClient
    from backend import config as cfg
    from backend.main import app

    d = tmp_path / "daily" / "2026-10-17"
    d.mkdir(parents=True)
    pd.DataFrame([{"mint": "M", "symbol": "TST", "zone": "REJECT", "score": 0.0,
                   "reasons": "likuiditas $900 < $5,000", "parts": "{}"}]).to_csv(d / "scan_results.csv", index=False)
    (d / "scan_manifest.json").write_text(_json.dumps({"zones": {"REJECT": 1}}))
    monkeypatch.setattr(cfg, "DAILY_DIR", tmp_path / "daily")

    c = TestClient(app)
    r = c.get("/api/scan")
    assert r.status_code == 200
    body = r.json()
    assert body["results"][0]["zone"] == "REJECT"


def test_api_stats_buckets(tmp_path, monkeypatch):
    import pandas as _pd
    from fastapi.testclient import TestClient
    from backend import config as cfg
    from backend.main import app

    d = tmp_path / "daily" / "2026-10-17"
    d.mkdir(parents=True)
    _pd.DataFrame({"reasons": ["likuiditas $900 < $5,000", "umur 5 menit < 30 menit minimum", ""]}).to_csv(d / "scan_results.csv", index=False)
    monkeypatch.setattr(cfg, "DAILY_DIR", tmp_path / "daily")

    c = TestClient(app)
    body = c.get("/api/stats").json()
    assert body["total_rejected"] == 2
    assert body["by_reason"]["likuiditas"] == 1
    assert body["by_reason"]["umur"] == 1


def test_ui_radar_page():
    from fastapi.testclient import TestClient
    from backend.main import app

    r = TestClient(app).get("/")
    assert r.status_code == 200
    assert "RADAR" in r.text


def test_ui_all_pages():
    from fastapi.testclient import TestClient
    from backend.main import app

    c = TestClient(app)
    for path, needle in [("/", "RADAR"), ("/positions", "Posisi"), ("/journal", "Jurnal"), ("/stats", "Statistik")]:
        r = c.get(path)
        assert r.status_code == 200, path
        assert needle in r.text, path

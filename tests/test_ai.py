"""Test AI service MCR (mock deterministik + fallback + parser) - offline."""
from unittest.mock import patch

from backend.core import ai_service

ROW = {"mint": "M", "symbol": "TST", "price_usd": 0.001, "liquidity_usd": 20_000.0,
       "fdv": 100_000.0, "chg_h1": 25.0, "buys_m5": 40, "sells_m5": 25}


def test_mock_ok_when_metrics_normal():
    a = ai_service.analyze_risk(ROW, 75.0, "BUY", [], top10_pct=10.0, age_min=90.0)
    assert a.engine == "mock" and a.flag == "ok"


def test_mock_danger_on_filter_fail():
    a = ai_service.analyze_risk(ROW, 0.0, "REJECT", ["likuiditas $900 < $5,000"], None, 90.0)
    assert a.flag == "danger" and "filter" in a.note


def test_mock_caution_on_whales():
    a = ai_service.analyze_risk(ROW, 60.0, "WATCH", [], top10_pct=38.0, age_min=90.0)
    assert a.flag == "caution" and "top-10" in a.note


def test_mock_caution_on_vertical_pump():
    a = ai_service.analyze_risk(dict(ROW, chg_h1=250.0), 60.0, "WATCH", [], None, 90.0)
    assert a.flag in ("caution", "danger")


def test_deterministic():
    a1 = ai_service.analyze_risk(ROW, 75.0, "BUY", [], 10.0, 90.0)
    a2 = ai_service.analyze_risk(ROW, 75.0, "BUY", [], 10.0, 90.0)
    assert a1.note == a2.note


def test_gemini_path(monkeypatch):
    monkeypatch.setattr(ai_service.config, "GEMINI_API_KEY", "FAKE")
    payload = {"candidates": [{"content": {"parts": [{"text": '{"risk_note":"x","flag":"ok"}'}]}}]}

    class R:
        status_code = 200
        def json(self):
            return payload

    with patch.object(ai_service.requests, "post", return_value=R()):
        a = ai_service.analyze_risk(ROW)
    assert a.engine == "gemini" and a.flag == "ok"


def test_fallback_to_mock_on_llm_fail(monkeypatch):
    monkeypatch.setattr(ai_service.config, "GEMINI_API_KEY", "FAKE")
    monkeypatch.setattr(ai_service.config, "GROQ_API_KEY", "")

    class R:
        status_code = 500
        def json(self):
            return {}

    with patch.object(ai_service.requests, "post", return_value=R()):
        a = ai_service.analyze_risk(ROW)
    assert a.engine == "mock"


def test_json_parser_tolerant():
    assert ai_service._parse_json('```json\n{"a":1}\n```') == {"a": 1}
    assert ai_service._parse_json("bukan json") is None

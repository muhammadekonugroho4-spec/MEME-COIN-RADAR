"""Test Bot A sentiment: hype score deterministik, adjust batas ±10, adapter offline."""
from unittest.mock import patch

from backend.adapters.sentiment import SentimentAdapter
from backend.core.sentiment import adjust_technical_score, hype_for


# ---------- hype_for ----------

def test_no_signal_neutral():
    h = hype_for("TST", "M", trending=[], boosts={})
    assert h.score == 0 and not h.paid_boost and h.note == "tidak ada sinyal sosial"


def test_coingecko_trending_organic():
    h = hype_for("TST", "M", trending=["TST", "BTC"], boosts={})
    assert h.score == 55 and "coingecko_trending" in h.sources and not h.paid_boost


def test_paid_boost_alone():
    h = hype_for("TST", "M", trending=[], boosts={"M": {"mint": "M", "total_boosts": 50, "max_single": 50}})
    assert h.paid_boost and h.score == 35


def test_organic_plus_paid_is_strong():
    h = hype_for("TST", "M", trending=["TST"], boosts={"M": {"mint": "M", "total_boosts": 80, "max_single": 50}})
    assert h.score == 90 and h.paid_boost  # 55+35


def test_huge_paid_boost_without_organic_is_capped():
    # boost 500 sambil nol sinyal organik = red flag, skor dipatok rendah
    h = hype_for("TST", "M", trending=[], boosts={"M": {"mint": "M", "total_boosts": 500, "max_single": 200}})
    assert h.score <= 40 and "boost_waspada" in h.sources


def test_deterministic():
    a = hype_for("TST", "M", trending=["TST"], boosts={"M": {"mint": "M", "total_boosts": 50, "max_single": 10}})
    b = hype_for("TST", "M", trending=["TST"], boosts={"M": {"mint": "M", "total_boosts": 50, "max_single": 10}})
    assert a == b


# ---------- adjust_technical_score ----------

def test_adjust_bounds():
    # bonus maksimal +10
    h = hype_for("TST", "M", trending=["TST"], boosts={"M": {"mint": "M", "total_boosts": 80, "max_single": 50}})
    assert adjust_technical_score(60.0, h) == 70.0
    assert adjust_technical_score(95.0, h) == 100.0  # tidak melewati 100
    # paid saja -> pinalti -5, tidak di bawah 0
    h2 = hype_for("TST", "M", trending=[], boosts={"M": {"mint": "M", "total_boosts": 30, "max_single": 30}})
    assert adjust_technical_score(20.0, h2) == 15.0
    assert adjust_technical_score(2.0, h2) == 0.0
    # tanpa sinyal -> netral
    h3 = hype_for("TST", "M", [], {})
    assert adjust_technical_score(60.0, h3) == 60.0


# ---------- adapter (HTTP mock, offline) ----------

def test_trending_symbols_parse():
    class R:
        status_code = 200
        def json(self):
            return {"coins": [{"item": {"symbol": "dog"}}, {"item": {"symbol": "pepe"}}]}

    with patch.object(SentimentAdapter, "_get", lambda self, url, timeout=12: R().json() if "trending" in url else None):
        s = SentimentAdapter()
        assert s.coingecko_trending_symbols() == ["DOG", "PEPE"]


def test_boosts_merge_dedup():
    class R:
        status_code = 200
        def __init__(self, data):
            self._d = data
        def json(self):
            return self._d

    latest = [{"chainId": "solana", "tokenAddress": "A" * 44, "amount": 50, "totalAmount": 150}]
    top = [{"chainId": "solana", "tokenAddress": "A" * 44, "amount": None, "totalAmount": 300}]
    with patch.object(SentimentAdapter, "_get", lambda self, url, timeout=12: latest if "latest" in url else top):
        s = SentimentAdapter()
        out = s.dexscreener_boosts_solana()
    assert len(out) == 1  # dedup per mint
    assert out[0]["total_boosts"] == 300  # ambil max

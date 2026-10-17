"""Test offline fase 1: normalisasi pair, coin store, job scan dengan adapter palsu."""
from unittest.mock import patch

import pandas as pd
import pytest

from backend.adapters.dexscreener import _norm_pair
from backend.core import coin_store


def make_pair(mint="HKdmDxcaRtxLNu7msz1h5f8NUZQqLNDiN3FLUDu1pump", chain="solana", **over):
    base = {
        "chainId": chain,
        "dexId": "pumpfun",
        "pairAddress": "PAIR1111",
        "baseToken": {"address": mint, "name": "Test Coin", "symbol": "TST"},
        "quoteToken": {"address": "So11111111111111111111111111111111111111112", "symbol": "SOL"},
        "priceUsd": "0.000004353",
        "fdv": 4353.94,
        "marketCap": 4353.94,
        "liquidity": {"usd": 8200.5, "base": 1, "quote": 2},
        "volume": {"m5": 100.0, "h1": 5000.0, "h24": 40000.0},
        "txns": {
            "m5": {"buys": 10, "sells": 4},
            "h1": {"buys": 100, "sells": 60},
            "h24": {"buys": 900, "sells": 700},
        },
        "priceChange": {"m5": -0.3, "h1": 22.0, "h24": 40.0},
        "pairCreatedAt": 1760000000000,
    }
    base.update(over)
    return base


# ---------- normalisasi ----------

def test_norm_pair_full():
    n = _norm_pair(make_pair())
    assert n["mint"] == "HKdmDxcaRtxLNu7msz1h5f8NUZQqLNDiN3FLUDu1pump"
    assert n["price_usd"] == pytest.approx(0.000004353)
    assert n["liquidity_usd"] == pytest.approx(8200.5)
    assert n["buys_h1"] == 100 and n["sells_m5"] == 4
    assert n["chg_h1"] == 22.0
    assert n["pair_created_at"] == 1760000000000


def test_norm_pair_rejects_non_solana():
    assert _norm_pair(make_pair(chain="ethereum")) is None


def test_norm_pair_rejects_bad_mint():
    assert _norm_pair(make_pair(mint="SHORT")) is None
    assert _norm_pair(make_pair(mint="")) is None


def test_norm_pair_rejects_self_pair():
    same = "AA" * 24
    p = make_pair(mint=same)
    p["quoteToken"] = {"address": same, "symbol": "X"}
    assert _norm_pair(p) is None


def test_norm_pair_truncates_spam_symbol():
    spam = make_pair()
    spam["baseToken"]["symbol"] = "X" * 5000  # seperti token spam nyata yang kita lihat
    n = _norm_pair(spam)
    assert len(n["symbol"]) == 60


def test_norm_pair_handles_missing_fields():
    bare = {"chainId": "solana", "baseToken": {"address": "BB" * 24}}
    n = _norm_pair(bare)
    assert n is not None
    assert n["price_usd"] is None and n["liquidity_usd"] == 0.0 and n["dex"] == ""


# ---------- coin store ----------

def _obs(mint="MINT_A", ts=1000.0, price=0.001):
    return {"ts": ts, "mint": mint, "price_usd": price, "liquidity_usd": 9000.0,
            "fdv": 10000.0, "market_cap": 10000.0, "vol_m5": 1, "vol_h1": 2, "vol_h24": 3,
            "buys_m5": 1, "sells_m5": 1, "buys_h1": 2, "sells_h1": 1,
            "chg_m5": 0.1, "chg_h1": 1.0, "chg_h24": 2.0, "supply": 1e9}


def test_append_dedup_and_known(tmp_path):
    coin_store.append_observation(tmp_path, _obs(ts=1000.0))
    coin_store.append_observation(tmp_path, _obs(ts=1000.0))  # duplikat persis
    coin_store.append_observation(tmp_path, _obs(ts=1001.0))  # observasi baru
    df = coin_store.load_history(tmp_path, "MINT_A")
    assert len(df) == 2  # dedup ts+mint bekerja
    assert "MINT_A" in coin_store.known_mints(tmp_path)
    assert "MINT_B" not in coin_store.known_mints(tmp_path)


def test_age_minutes():
    now = 1760001000000  # +1000 detik dari pair_created_at=1760000000000
    assert coin_store.age_minutes(1760000000000, now_ms=now) == pytest.approx(1000 / 60)
    assert coin_store.age_minutes(None) is None


# ---------- job dengan adapter palsu ----------

class FakeDx:
    def scan_new_pairs(self, queries=("pump",), per_query=30):
        return [_norm_pair(make_pair(mint="NEWCOIN1" + "X" * 30))]

    def token_detail(self, mint):
        return _norm_pair(make_pair(mint=mint, liquidity={"usd": 12000.0, "base": 1, "quote": 2}))


class FakeSol:
    def health(self):
        return True

    def token_supply(self, mint):
        return {"supply": 1_000_000_000.0, "decimals": 6}


class FakeCg:
    def price_sol(self):
        return 210.5


def test_job_scan_offline(tmp_path, monkeypatch):
    import jobs.job_scan as job

    monkeypatch.setattr(job.config, "COINS_DIR", tmp_path / "coins")
    monkeypatch.setattr(job.config, "DAILY_DIR", tmp_path / "daily")
    monkeypatch.setattr(job, "DexScreenerAdapter", lambda: FakeDx())
    monkeypatch.setattr(job, "SolanaRpcAdapter", lambda: FakeSol())
    monkeypatch.setattr(job, "CoinGeckoAdapter", lambda: FakeCg())

    m = job.run()
    assert m["pairs_scanned"] >= 1
    assert m["fresh_candidates"] == 1
    assert m["zones"]["BUY"] + m["zones"]["WATCH"] + m["zones"]["PASSIVE"] + m["zones"]["REJECT"] == 1
    assert m["solana_rpc_ok"] is True

    # idempotent: run ke-2, mint sudah dikenal -> tidak ada fresh
    m2 = job.run()
    assert m2["fresh_candidates"] == 0

    hist = coin_store.load_history(tmp_path / "coins", "NEWCOIN1" + "X" * 30)
    assert hist is not None and len(hist) == 1

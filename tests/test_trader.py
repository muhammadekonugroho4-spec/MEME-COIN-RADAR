"""Test paper broker, strategy exit, portfolio, dan job trader end-to-end (offline)."""
import json
from pathlib import Path

import pandas as pd
import pytest

from backend.core import paper_broker, portfolio, strategy
from backend.core.paper_broker import PendingOrder


# ---------- slippage & sizing ----------

def test_slippage_model():
    # $100 di likuiditas $20k = 0.5 + 0.5 = 1.0%
    assert paper_broker.slippage_pct(100.0, 20_000.0) == pytest.approx(1.0)
    assert paper_broker.slippage_pct(100.0, 0.0) == float("inf")  # tanpa likuiditas = tolak


def test_position_size_limits():
    assert paper_broker.position_size(1000.0, 0) == pytest.approx(150.0)  # 15% (scalp)
    assert paper_broker.position_size(1000.0, 3) is None                   # slot penuh (3)
    assert paper_broker.position_size(20.0, 0) is None                     # < $5 minimum


# ---------- fill di harga NEXT scan ----------

def test_fill_buy_uses_next_price_with_slippage():
    order = PendingOrder("M", "TST", "buy", 1.0, 1.0, 80.0, usd_size=100.0)
    fill = paper_broker.fill_buy(order, next_price=1.0, liquidity_usd=20_000.0, now=2.0)
    assert fill.price == pytest.approx(1.01)   # 1% slippage dari $100 di $20k liq
    assert fill.qty == pytest.approx(100.0 / 1.01)
    assert fill.signal_price == 1.0            # bukti sinyal≠fill (anti lookahead)


def test_fill_sell_prices_down():
    order = PendingOrder("M", "TST", "sell", 1.0, 1.0, 0.0, qty=50.0)
    fill = paper_broker.fill_sell(order, next_price=2.0, liquidity_usd=20_000.0, now=2.0)
    # fill_sell pakai ukuran dasar $1 -> slippage = 0.5% + (1/20000)*100 = 0.505%
    assert fill.price == pytest.approx(2.0 * (1 - 0.505 / 100))
    assert fill.price < 2.0  # sell selalu kena slippage ke bawah


# ---------- strategy exits §4.4 ----------

def _pos(**over):
    base = {"qty": 100.0, "entry_price": 1.0, "entry_ts": 0.0, "peak_price": 1.0,
            "tp_done": False, "entry_liquidity": 20_000.0}
    base.update(over)
    return base


def test_stop_loss_35pct():
    sig = strategy.evaluate_position(_pos(), price=0.64, liquidity_usd=20_000.0, now_ts=3600)
    assert sig.action == "exit" and "stop-loss" in sig.reason


def test_liquidity_pulled_exit():
    sig = strategy.evaluate_position(_pos(), price=1.2, liquidity_usd=7_000.0, now_ts=600)  # <60% dari 20k
    assert sig.action == "exit" and "likuiditas" in sig.reason


def test_max_hold_15_minutes():
    sig = strategy.evaluate_position(_pos(), price=1.0, liquidity_usd=20_000.0, now_ts=16 * 60)
    assert sig.action == "exit" and "scalp timeout" in sig.reason


def test_scalp_take_profit_8pct():
    sig = strategy.evaluate_position(_pos(), price=1.09, liquidity_usd=20_000.0, now_ts=300)
    assert sig.action == "exit" and "take-profit" in sig.reason and sig.fraction == 1.0


def test_scalp_stop_5pct():
    sig = strategy.evaluate_position(_pos(), price=0.94, liquidity_usd=20_000.0, now_ts=120)
    assert sig.action == "exit" and "stop-loss" in sig.reason


def test_scalp_trailing_3pct():
    pos = _pos(peak_price=1.10)
    sig = strategy.evaluate_position(pos, price=1.06, liquidity_usd=20_000.0, now_ts=240)
    assert sig.action == "exit" and "trailing" in sig.reason


def test_scalp_hold_when_quiet_but_young():
    sig = strategy.evaluate_position(_pos(), price=1.01, liquidity_usd=20_000.0, now_ts=240)
    assert sig.action == "hold"


# (profil scalp: TP exit penuh +8%, trailing aktif sejak awal - test menggantikan versi swing)


def test_update_peak_monotonic():
    assert strategy.update_peak(_pos(peak_price=1.2), 1.5)["peak_price"] == 1.5
    assert strategy.update_peak(_pos(peak_price=1.6), 1.5)["peak_price"] == 1.6


# ---------- portfolio state ----------

def _fill(side="buy", mint="M", price=1.0, qty=100.0, usd=101.0, ts=1.0):
    return paper_broker.Fill(mint=mint, symbol="TST", side=side, qty=qty, price=price,
                             slippage_pct=1.0, usd=usd, signal_ts=ts, signal_price=1.0, reason="test")


def test_buy_then_sell_roundtrip(tmp_path):
    st = portfolio.load_state(tmp_path, start_equity=1000.0)
    st = portfolio.apply_buy_fill(st, _fill())
    assert st["equity"] == pytest.approx(899.0)
    assert st["positions"]["M"]["qty"] == 100.0

    st = portfolio.apply_sell_fill(st, _fill(side="sell", price=2.0, usd=200.0), fraction=1.0)
    assert st["equity"] == pytest.approx(899.0 + 200.0)
    assert "M" not in st["positions"]


def test_idempotent_fills(tmp_path):
    st = portfolio.load_state(tmp_path, start_equity=1000.0)
    st = portfolio.apply_buy_fill(st, _fill())
    st = portfolio.apply_buy_fill(st, _fill())  # fill sama diputar ulang
    assert st["equity"] == pytest.approx(899.0)  # tidak dobel kurang


def test_tp_marked_on_sell_reason(tmp_path):
    st = portfolio.load_state(tmp_path, start_equity=1000.0)
    st = portfolio.apply_buy_fill(st, _fill())
    f = _fill(side="sell", price=2.2, usd=110.0, ts=2.0)
    f = paper_broker.Fill(**{**f.__dict__, "reason": "take-profit pertama +120%, jual 50%"})
    st = portfolio.apply_sell_fill(st, f, fraction=0.5)
    assert st["positions"]["M"]["tp_done"] is True
    assert st["positions"]["M"]["qty"] == pytest.approx(50.0)


def test_equity_and_trade_log(tmp_path):
    st = portfolio.load_state(tmp_path, start_equity=1000.0)
    st = portfolio.apply_buy_fill(st, _fill())
    portfolio.save_state(tmp_path, st)
    portfolio.log_trade(tmp_path, _fill())
    portfolio.log_equity(tmp_path, 899.0, 1.0)
    portfolio.log_equity(tmp_path, 899.0, 2.0)
    assert (tmp_path / "trades.csv").exists()
    eq = pd.read_csv(tmp_path / "equity.csv")
    assert len(eq) == 2
    st2 = portfolio.load_state(tmp_path)
    assert st2["equity"] == pytest.approx(899.0)  # state persist


# ---------- job trader end-to-end (offline, data scan & harga palsu) ----------

def _write_scan(day_dir: Path, mint: str, price: float):
    day_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"mint": mint, "symbol": "TST", "zone": "BUY", "score": 75.0,
                   "price_usd": price, "reasons": "", "parts": "{}"}]).to_csv(day_dir / "scan_results.csv", index=False)


def _write_price(coins_dir: Path, mint: str, price: float, liq: float = 50_000.0, ts: float = 0.0):
    import time as _t

    coins_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"ts": ts or _t.time(), "mint": mint, "price_usd": price, "liquidity_usd": liq,
                   "fdv": 100000.0, "market_cap": 100000.0, "vol_m5": 0, "vol_h1": 0, "vol_h24": 0,
                   "buys_m5": 0, "sells_m5": 0, "buys_h1": 0, "sells_h1": 0,
                   "chg_m5": 0, "chg_h1": 0, "chg_h24": 0, "supply": 1e9}]).to_parquet(
        coins_dir / f"{mint}.parquet", index=False)


def test_trader_full_cycle_buy_watch_exit(tmp_path, monkeypatch):
    import jobs.job_trader as job
    import time as _t

    coins, daily, port = tmp_path / "coins", tmp_path / "daily", tmp_path / "portfolio"
    monkeypatch.setattr(job.config, "COINS_DIR", coins)
    monkeypatch.setattr(job.config, "DAILY_DIR", daily)
    monkeypatch.setattr(job.config, "PORTFOLIO_DIR", port)
    monkeypatch.setattr(job.config, "PAPER_START_EQUITY", 1000.0)

    mint = "COINX" + "0" * 36

    # run 1: sinyal BUY, belum ada harga -> order antri
    _write_scan(daily / "2026-10-17", mint, 1.0)
    m1 = job.run()
    assert m1["pending"] == 1 and m1["open_positions"] == 0

    # run 2: harga muncul (next scan) -> fill buy dgn slippage
    _write_price(coins, mint, 1.0, ts=_t.time())
    m2 = job.run()
    assert any(a["action"] == "buy_fill" for a in m2["actions"])
    assert m2["open_positions"] == 1
    st = portfolio.load_state(port)
    assert st["positions"][mint]["entry_price"] > 1.0  # slippage membuat entry lebih mahal

    # run 3: harga crash -40% -> queue exit
    _write_price(coins, mint, 0.6, ts=_t.time())
    m3 = job.run()
    assert any(a["action"] == "queue_exit" for a in m3["actions"])
    assert m3["pending"] == 1  # order sell menunggu fill

    # run 4: sell ter-fill -> posisi tertutup, equity berkurang (rugi nyata tercatat)
    _write_price(coins, mint, 0.6, ts=_t.time())
    m4 = job.run()
    assert any(a["action"] == "sell_fill" for a in m4["actions"])
    st4 = portfolio.load_state(port)
    assert mint not in st4["positions"]
    assert st4["equity"] < 1000.0  # rugi tercatat jujur di equity curve

    eq = pd.read_csv(port / "equity.csv")
    assert eq["total"].iloc[-1] < 1000.0

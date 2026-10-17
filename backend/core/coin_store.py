"""Penyimpanan coin (murni): parquet per mint + dedup. TANPA network."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

HISTORY_COLUMNS = [
    "ts", "mint", "price_usd", "liquidity_usd", "fdv", "market_cap",
    "vol_m5", "vol_h1", "vol_h24", "buys_m5", "sells_m5", "buys_h1", "sells_h1",
    "chg_m5", "chg_h1", "chg_h24", "supply",
]


def _safe(mint: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in mint)[:60]


def coin_path(coins_dir: Path, mint: str) -> Path:
    return coins_dir / f"{_safe(mint)}.parquet"


def known_mints(coins_dir: Path) -> set[str]:
    """Mint yang sudah pernah dipantau (dedup antar-scan)."""
    return {p.stem for p in coins_dir.glob("*.parquet")}


def load_history(coins_dir: Path, mint: str) -> pd.DataFrame | None:
    p = coin_path(coins_dir, mint)
    if not p.exists():
        return None
    return pd.read_parquet(p)


def append_observation(coins_dir: Path, row: dict) -> int:
    """Tambah 1 observasi harga (idempotent per detik ts+mint). Return jumlah baris total."""
    p = coin_path(coins_dir, row["mint"])
    new = pd.DataFrame([{k: row.get(k) for k in HISTORY_COLUMNS}])
    if p.exists():
        old = pd.read_parquet(p)
        merged = pd.concat([old, new], ignore_index=True)
        merged = merged.drop_duplicates(subset=["ts", "mint"], keep="last")
        merged = merged.tail(2000)  # jaga ukuran: meme coin mati cepat, 2000 titik cukup
    else:
        merged = new
    p.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(p, index=False)
    return len(merged)


def age_minutes(pair_created_at_ms: int | None, now_ms: int | None = None) -> float | None:
    """Umur pair dalam menit; None bila API tidak memberi data."""
    if not pair_created_at_ms:
        return None
    now_ms = now_ms or (pd.Timestamp.utcnow().value // 1_000_000)
    return max(0.0, (now_ms - pair_created_at_ms) / 60_000.0)

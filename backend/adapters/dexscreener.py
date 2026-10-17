"""Adapter DexScreener - deteksi pair baru & detail (verifikasi hidup 17 Okt 2026).

Endpoint publik tanpa key; limit resmi 300 req/menit (kita jauh di bawahnya).
Struktur respons diverifikasi: baseToken/quoteToken/priceUsd/fdv/marketCap/
liquidity.usd/pairCreatedAt(ms epoch)/txns{m5,h1,h6,h24{buys,sells}}/volume.
"""
from __future__ import annotations

from typing import Any

import requests

from backend import config
from backend.adapters.base import DataSourceError, RateLimit, RateLimitManager

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) mcr-scan/0.1"}
SEARCH_URL = f"{config.DEXSCREENER_BASE}/latest/dex/search"
TOKENS_URL = f"{config.DEXSCREENER_BASE}/tokens/v1/solana"  # /{mint}
KNOWN_SOL_QUOTE = "So11111111111111111111111111111111111111112"  # Wrapped SOL


def _get(session: requests.Session, url: str, timeout: int = 15) -> Any:
    r = session.get(url, headers=UA, timeout=timeout)
    if r.status_code == 429:
        raise DataSourceError(f"dexscreener 429 (rate limit): {url}")
    if r.status_code != 200:
        raise DataSourceError(f"dexscreener HTTP {r.status_code}: {url}")
    return r.json()


def _norm_pair(p: dict) -> dict | None:
    """Normalkan 1 pair ke baris scan. None bila tidak relevan (bukan Solana, bukan vs SOL)."""
    if p.get("chainId") != "solana":
        return None
    base, quote = p.get("baseToken") or {}, p.get("quoteToken") or {}
    if not base.get("address") or base["address"] == quote.get("address"):
        return None
    mint = base["address"]
    if not mint or len(mint) < 32:  # mint address Solana ~44 char
        return None
    try:
        price_usd = float(p["priceUsd"]) if p.get("priceUsd") else None
    except (TypeError, ValueError):
        price_usd = None
    liq = (p.get("liquidity") or {}).get("usd")
    created = p.get("pairCreatedAt")
    txns = p.get("txns") or {}
    out = {
        "mint": mint,
        "pair_address": p.get("pairAddress") or "",
        "symbol": (base.get("symbol") or "")[:60],  # symbol spam bisa ribuan char
        "name": (base.get("name") or "")[:100],
        "dex": p.get("dexId") or "",
        "price_usd": price_usd,
        "liquidity_usd": float(liq) if liq else 0.0,
        "fdv": float(p["fdv"]) if p.get("fdv") else 0.0,
        "market_cap": float(p["marketCap"]) if p.get("marketCap") else 0.0,
        "vol_m5": float((p.get("volume") or {}).get("m5") or 0),
        "vol_h1": float((p.get("volume") or {}).get("h1") or 0),
        "vol_h24": float((p.get("volume") or {}).get("h24") or 0),
        "buys_m5": int((txns.get("m5") or {}).get("buys") or 0),
        "sells_m5": int((txns.get("m5") or {}).get("sells") or 0),
        "buys_h1": int((txns.get("h1") or {}).get("buys") or 0),
        "sells_h1": int((txns.get("h1") or {}).get("sells") or 0),
        "buys_h24": int((txns.get("h24") or {}).get("buys") or 0),
        "sells_h24": int((txns.get("h24") or {}).get("sells") or 0),
        "chg_m5": float((p.get("priceChange") or {}).get("m5") or 0),
        "chg_h1": float((p.get("priceChange") or {}).get("h1") or 0),
        "chg_h24": float((p.get("priceChange") or {}).get("h24") or 0),
        "pair_created_at": int(created) if created else None,  # ms epoch
    }
    return out


class DexScreenerAdapter:
    source = "dexscreener"

    def __init__(self, session: requests.Session | None = None, rate: RateLimitManager | None = None):
        self.session = session or requests.Session()
        self.rate = rate or RateLimitManager()
        self.rate.configure(self.source, RateLimit(max_per_minute=120))

    def scan_new_pairs(self, queries: tuple[str, ...] = ("pump", "sol"), per_query: int = 30) -> list[dict]:
        """Gabung hasil beberapa query pencarian; caller yang dedup."""
        rows: list[dict] = []
        for q in queries:
            self.rate.wait_turn(self.source)
            data = _get(self.session, f"{SEARCH_URL}?q={requests.utils.quote(q)}")
            for p in data.get("pairs") or []:
                n = _norm_pair(p)
                if n:
                    rows.append(n)
            if len(rows) >= per_query * len(queries):
                break
        return rows

    def token_detail(self, mint: str) -> dict | None:
        """Detail pair terbaik untuk 1 mint (paling likuid). None bila tidak ada."""
        self.rate.wait_turn(self.source)
        data = _get(self.session, f"{TOKENS_URL}/{mint}")
        pairs = [n for p in (data or []) if (n := _norm_pair(p))]
        if not pairs:
            return None
        return max(pairs, key=lambda x: x["liquidity_usd"])

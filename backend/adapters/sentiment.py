"""Bot A - Sentiment adapter (Fase sentiment): sumber publik gratis, tanpa key.

Sumber terverifikasi hidup (18 Okt 2026):
1. CoinGecko /search/trending  - 15 coin trending global (hype organik)
2. DexScreener /token-boosts   - coin yang DIBAYAR dev-nya untuk dipromosikan
                                 (hype berbayar: bisa positif, sering red flag)

Semua best-effort: gagal satu sumber -> lanjut dengan sumber lain / kosong.
"""
from __future__ import annotations

import requests

from backend import config
from backend.adapters.base import DataSourceError, RateLimit, RateLimitManager

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) mcr-sentiment/0.1"}
CG_TRENDING = f"{config.COINGECKO_BASE}/search/trending"
DX_BOOSTS_LATEST = f"{config.DEXSCREENER_BASE}/token-boosts/latest/v1"
DX_BOOSTS_TOP = f"{config.DEXSCREENER_BASE}/token-boosts/top/v1"


class SentimentAdapter:
    source = "sentiment"

    def __init__(self, session: requests.Session | None = None, rate: RateLimitManager | None = None):
        self.session = session or requests.Session()
        self.rate = rate or RateLimitManager()
        self.rate.configure(self.source, RateLimit(max_per_minute=20))

    def _get(self, url: str, timeout: int = 12) -> list | dict | None:
        try:
            self.rate.wait_turn(self.source, timeout=20.0)
            r = self.session.get(url, headers=UA, timeout=timeout)
            if r.status_code != 200:
                return None
            return r.json()
        except (requests.RequestException, ValueError):
            return None

    def coingecko_trending_symbols(self) -> list[str]:
        """Simbol coin trending CoinGecko (maks 15), uppercase."""
        d = self._get(CG_TRENDING)
        if not d:
            return []
        out = []
        for c in d.get("coins", []):
            sym = (c.get("item") or {}).get("symbol")
            if sym:
                out.append(sym.upper())
        return out[:15]

    def dexscreener_boosts_solana(self) -> list[dict]:
        """{'mint','total_boosts','max_single'} dari gabungan latest+top boosts (solana)."""
        merged: dict[str, dict] = {}
        for url in (DX_BOOSTS_LATEST, DX_BOOSTS_TOP):
            d = self._get(url)
            if not isinstance(d, list):
                continue
            for x in d:
                if x.get("chainId") != "solana" or not x.get("tokenAddress"):
                    continue
                mint = x["tokenAddress"]
                amount = int(x.get("amount") or 0)
                total = int(x.get("totalAmount") or 0)
                cur = merged.setdefault(mint, {"mint": mint, "total_boosts": 0, "max_single": 0})
                cur["total_boosts"] = max(cur["total_boosts"], total)
                cur["max_single"] = max(cur["max_single"], amount)
        return list(merged.values())

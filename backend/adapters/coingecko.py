"""CoinGecko public API - cross-check harga (fallback, verifikasi ping 200 tgl 17 Okt 2026)."""
from __future__ import annotations

import requests

from backend import config
from backend.adapters.base import DataSourceError, RateLimit, RateLimitManager

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) mcr-scan/0.1"}


class CoinGeckoAdapter:
    source = "coingecko"

    def __init__(self, session: requests.Session | None = None, rate: RateLimitManager | None = None):
        self.session = session or requests.Session()
        self.rate = rate or RateLimitManager()
        self.rate.configure(self.source, RateLimit(max_per_minute=25))

    def price_sol(self) -> float | None:
        """Harga SOL/USD untuk konteks (bukan kandidat). None bila gagal."""
        try:
            self.rate.wait_turn(self.source)
            r = self.session.get(
                f"{config.COINGECKO_BASE}/simple/price",
                params={"ids": "solana", "vs_currencies": "usd"},
                headers=UA,
                timeout=12,
            )
            if r.status_code != 200:
                return None
            return float(r.json()["solana"]["usd"])
        except (requests.RequestException, KeyError, ValueError):
            return None

    def ping(self) -> bool:
        try:
            self.rate.wait_turn(self.source)
            r = self.session.get(f"{config.COINGECKO_BASE}/ping", headers=UA, timeout=10)
            return r.status_code == 200
        except requests.RequestException:
            return False

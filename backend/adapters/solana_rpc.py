"""Adapter Solana RPC publik (verifikasi hidup 17 Okt 2026: getHealth, getTokenSupply OK).

Rate limit publik ketat -> cache in-memory + error lembut (caller melanjutkan tanpa supply).
"""
from __future__ import annotations

import time

import requests

from backend import config
from backend.adapters.base import DataSourceError, RateLimit, RateLimitManager

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) mcr-scan/0.1"}


class SolanaRpcAdapter:
    source = "solana_rpc"

    def __init__(self, session: requests.Session | None = None, rate: RateLimitManager | None = None, ttl: int = 3600):
        self.session = session or requests.Session()
        self.rate = rate or RateLimitManager()
        self.rate.configure(self.source, RateLimit(max_per_minute=20))
        self.ttl = ttl
        self._cache: dict[str, tuple[float, dict]] = {}

    def _rpc(self, method: str, params: list) -> dict:
        r = self.session.post(
            config.SOLANA_RPC,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            headers=UA,
            timeout=15,
        )
        if r.status_code == 429:
            raise DataSourceError("solana rpc 429")
        if r.status_code != 200:
            raise DataSourceError(f"solana rpc HTTP {r.status_code}")
        body = r.json()
        if "error" in body:
            raise DataSourceError(f"solana rpc error: {str(body['error'])[:80]}")
        return body["result"]

    def health(self) -> bool:
        try:
            self.rate.wait_turn(self.source)
            return self._rpc("getHealth", []) == "ok"
        except (DataSourceError, requests.RequestException):
            return False

    def token_supply(self, mint: str) -> dict | None:
        """{'supply': float, 'decimals': int} dengan cache TTL. None bila RPC gagal."""
        now = time.monotonic()
        hit = self._cache.get(mint)
        if hit and now - hit[0] < self.ttl:
            return hit[1]
        try:
            self.rate.wait_turn(self.source)
            res = self._rpc("getTokenSupply", [mint])
            value = res.get("value") or {}
            out = {
                "supply": float(value.get("uiAmount") or 0),
                "decimals": int(value.get("decimals") or 0),
            }
        except (DataSourceError, requests.RequestException):
            return None  # lembut: scan lanjut tanpa data supply
        self._cache[mint] = (now, out)
        return out

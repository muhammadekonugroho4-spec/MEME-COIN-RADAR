"""Adapter pump.fun (endpoint publik frontend-api, tanpa key) - sumber coin BARU real-time.

Kenapa perlu: DexScreener /search menyortir berdasar likuiditas -> coin baru pump.fun
(umur menit, likuiditas kecil) TIDAK PERNAH muncul. Itu penyebab scanner lama sepi.

Endpoint diverifikasi hidup 18 Okt 2026: GET /coins?sort=created_timestamp (200).
Hanya baca daftar publik - tanpa login, tanpa transaksi.
"""
from __future__ import annotations

import requests

from backend.adapters.base import DataSourceError, RateLimit, RateLimitManager

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) mcr-scan/0.1"}
NEW_URL = "https://frontend-api-v3.pump.fun/coins"


def parse_coins(items: list[dict]) -> list[dict]:
    """Normalisasi ke {'mint','symbol','name','created_ms'} - hanya field yang dipakai scan."""
    out = []
    for x in items:
        mint = x.get("mint") or ""
        if not mint or len(mint) < 32:
            continue
        out.append({
            "mint": mint,
            "symbol": (x.get("symbol") or "")[:60],
            "name": (x.get("name") or "")[:100],
            "created_ms": x.get("created_timestamp"),
            "usd_market_cap": float(x.get("usd_market_cap") or 0),
            "real_sol_reserves": float(x.get("real_sol_reserves") or 0) / 1e9,  # lamport -> SOL
            "complete": bool(x.get("complete")),
        })
    return out


class PumpFunAdapter:
    source = "pumpfun"

    def __init__(self, session: requests.Session | None = None, rate: RateLimitManager | None = None):
        self.session = session or requests.Session()
        self.rate = rate or RateLimitManager()
        self.rate.configure(self.source, RateLimit(max_per_minute=15))

    def _fetch(self, params: dict) -> list[dict]:
        try:
            self.rate.wait_turn(self.source, timeout=15.0)
            r = self.session.get(NEW_URL, params=params, headers=UA, timeout=15)
            if r.status_code != 200:
                return []
            return parse_coins(r.json())
        except Exception:
            return []  # best-effort mutlak: gagal apa pun = kosong

    def newest_coins(self, limit: int = 20) -> list[dict]:
        """Coin paling baru di-launch pump.fun. Gagal -> [] (lembut)."""
        return self._fetch({"offset": 0, "limit": limit, "sort": "created_timestamp",
                            "order": "DESC", "includeNsfw": "false"})

    def graduating_coins(self, limit: int = 20) -> list[dict]:
        """Coin pump.fun yang sudah 'berdiri' (belum complete, sort market_cap desc).

        Inilah kandidat scalp sehat: sudah punya volume & holder, curve besar,
        dan masih bisa naik sebelum graduate ke Raydium.
        """
        return self._fetch({"offset": 0, "limit": limit, "sort": "market_cap",
                            "order": "DESC", "includeNsfw": "false", "complete": "false"})

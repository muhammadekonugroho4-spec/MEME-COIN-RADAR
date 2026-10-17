"""Dasar adapter: error baku + pembatas laju per sumber (port pola GLOBAL-STOCK-AI)."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


class DataSourceError(RuntimeError):
    """Gagal umum mengambil data dari sumber."""


@dataclass
class RateLimit:
    max_per_minute: int = 0  # 0 = tanpa batas lokal
    max_per_day: int = 0


class RateLimitManager:
    """Penghitung pemakaian per sumber. Thread-safe, in-memory (cukup untuk 1 job)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._minute: dict[str, list[float]] = {}
        self._day: dict[str, int] = {}
        self._limits: dict[str, RateLimit] = {}

    def configure(self, source: str, limit: RateLimit) -> None:
        with self._lock:
            self._limits[source] = limit

    def check(self, source: str) -> bool:
        with self._lock:
            lim = self._limits.get(source, RateLimit())
            now = time.monotonic()
            stamps = [t for t in self._minute.get(source, []) if now - t < 60.0]
            if lim.max_per_minute and len(stamps) >= lim.max_per_minute:
                self._minute[source] = stamps
                return False
            if lim.max_per_day and self._day.get(source, 0) >= lim.max_per_day:
                return False
            stamps.append(now)
            self._minute[source] = stamps
            self._day[source] = self._day.get(source, 0) + 1
            return True

    def used_today(self, source: str) -> int:
        with self._lock:
            return self._day.get(source, 0)

    def wait_turn(self, source: str, timeout: float = 90.0) -> None:
        deadline = time.monotonic() + timeout
        while not self.check(source):
            if time.monotonic() > deadline:
                raise DataSourceError(f"rate-limit timeout untuk '{source}'")
            time.sleep(1.0)

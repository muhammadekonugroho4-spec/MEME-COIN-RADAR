"""Loop internal utk jobs (Solusi A): 1 run Actions = N siklus berjarak T detik.

GitHub Actions meng-throttle cron padat (*/2 aktualnya jadi ±2 jam). Solusinya:
1 cron -> job berjalan N siklus berturut-turut di dalam runner yang sama, jeda T detik
antara siklus. Dengan 10 siklus x 60 detik = konstanta observasi 1 menit tanpa
bergantung pada jadwal platform. Tetap hormati batas waktu runner (timeout workflow).
"""
from __future__ import annotations

import time


def run_cycles(fn, cycles: int = 10, interval_seconds: int = 60, deadline_min: float = 18.0) -> list[dict]:
    """Panggil fn() sebanyak cycles kali, jeda interval detik di antaranya.

    Berhenti lebih awal bila mendekati deadline menit (batas timeout runner).
    Mengembalikan daftar hasil tiap siklus.
    """
    results: list[dict] = []
    started = time.monotonic()
    deadline = started + deadline_min * 60.0
    for i in range(cycles):
        if i > 0:
            sleep_s = interval_seconds - (time.monotonic() - started - i * interval_seconds)
            if sleep_s > 0:
                time.sleep(sleep_s)
        if time.monotonic() > deadline:
            break
        try:
            results.append(fn())
        except Exception as exc:  # satu siklus gagal = lanjut siklus berikut
            results.append({"cycle_error": type(exc).__name__, "detail": str(exc)[:120]})
    return results

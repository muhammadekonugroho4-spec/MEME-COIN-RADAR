"""Filter on-chain (murni) - Fase 4: lapisan kedua setelah filter API (§5 fase 4 PROMPT).

Sinyal:
1. mint_authority masih aktif  -> dev bisa cetak token baru (BAHAYA, reject)
2. freeze_authority masih aktif -> dev bisa beku rekening holder (BAHAYA, reject)
3. top-10 holder > 40% supply   -> konsentrasi ekstrem, mudah di-dump

Semua fungsi menerima data onchain yang SUDAH diambil adapter; di sini murni evaluasi.
"""
from __future__ import annotations

MAX_TOP10_HOLDERS_PCT = 40.0


def onchain_reasons(mint_authority: str | None, freeze_authority: str | None, top10_pct: float | None) -> list[str]:
    """Kembalikan alasan REJECT (kosong = lolos). Data None = tidak bisa dinilai (bukan reject)."""
    reasons: list[str] = []
    if mint_authority is not None:
        reasons.append(f"mint authority masih aktif ({str(mint_authority)[:8]}…), dev bisa cetak token baru")
    if freeze_authority is not None:
        reasons.append("freeze authority masih aktif, dev bisa beku rekening holder")
    if top10_pct is not None and top10_pct > MAX_TOP10_HOLDERS_PCT:
        reasons.append(f"top-10 holder menguasai {top10_pct:.0f}% supply > {MAX_TOP10_HOLDERS_PCT:.0f}%")
    return reasons


def top10_pct_from_accounts(largest: list[dict], total_supply: float | None) -> float | None:
    """Hitung % supply dipegang top-10. Butuh uiAmount tiap akun + total supply.

    largest: [{'uiAmount': float|None}, ...] dari getTokenLargestAccounts (ambil 10 pertama)
    """
    if total_supply is None or total_supply <= 0:
        return None
    held = sum(a.get("uiAmount") or 0.0 for a in largest[:10])
    return held / total_supply * 100.0

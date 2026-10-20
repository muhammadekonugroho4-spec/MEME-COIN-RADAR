"""Deep links ke terminal trading publik (murni, tanpa I/O).

MCR tidak punya API eksekusi real - GMGN/Photon tidak menyediakan API publik resmi.
Jembatan yang didukung: deep link per token. Satu klik dari radar -> review di
terminal -> user yang memutuskan (keputusan akhir tetap manusia).

Semua URL publik, tanpa secret. Params tambahan (referrer dll) tidak dipakai.
"""
from __future__ import annotations


def gmgn(mint: str) -> str:
    return f"https://gmgn.ai/sol/token/{mint}"


def photon(mint: str) -> str:
    return f"https://photon-sol.com/tinyap/{mint}"


def jupiter(mint: str) -> str:
    return f"https://jup.ag/tokens/{mint}"


def pumpfun(mint: str) -> str:
    return f"https://pump.fun/coin/{mint}"


def dexscreener(mint: str) -> str:
    return f"https://dexscreener.com/solana/{mint}"


def rugcheck(mint: str) -> str:
    return f"https://rugcheck.xyz/tokens/{mint}"


def solscan(mint: str) -> str:
    return f"https://solscan.io/token/{mint}"


def all_links(mint: str) -> dict[str, str]:
    """Semua deep link untuk satu mint - dipasang di hasil scan & posisi."""
    return {
        "gmgn": gmgn(mint),
        "photon": photon(mint),
        "jupiter": jupiter(mint),
        "pumpfun": pumpfun(mint),
        "dexscreener": dexscreener(mint),
        "rugcheck": rugcheck(mint),
        "solscan": solscan(mint),
    }

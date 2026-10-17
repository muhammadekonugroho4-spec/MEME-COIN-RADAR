"""MEME-COIN-RADAR - konfigurasi terpusat (baca .env, tanpa hardcoded secret).

Proyek PAPER-ONLY: tidak ada kredensial wallet di sini, selamanya.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


GEMINI_API_KEY = _get("GEMINI_API_KEY")
GROQ_API_KEY = _get("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID")

ENV = _get("MCR_ENV", "dev")
PAPER_START_EQUITY = float(_get("PAPER_START_EQUITY", "1000") or 1000)

DATA_DIR = BASE_DIR / "data"
COINS_DIR = DATA_DIR / "coins"
DAILY_DIR = DATA_DIR / "daily"
PORTFOLIO_DIR = DATA_DIR / "portfolio"

# Sumber data (diverifikasi 17 Okt 2026)
DEXSCREENER_BASE = "https://api.dexscreener.com"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"


def missing_credentials(*names: str) -> list[str]:
    """Nama env yang masih kosong (untuk /health, tanpa nilai)."""
    return [n for n in names if not _get(n)]

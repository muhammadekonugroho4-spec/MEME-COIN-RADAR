"""MEME-COIN-RADAR - FastAPI app (Fase 0: health + skeleton). Paper-only proyek."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from backend import config

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    for sub in ("", "coins", "daily", "portfolio"):
        (config.DATA_DIR / sub).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="MEME-COIN-RADAR", version=VERSION, lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": VERSION,
        "env": config.ENV,
        "mode": "paper-only",
        "missing_credentials": config.missing_credentials(
            "GEMINI_API_KEY",
            "GROQ_API_KEY",
            "TELEGRAM_BOT_TOKEN",
        ),
    }


@app.get("/", response_class=HTMLResponse)
def index():
    return (
        "<html><head><title>MEME-COIN-RADAR</title></head><body>"
        "<h1>MEME-COIN-RADAR</h1>"
        f"<p>v{VERSION} - Fase 0 skeleton. Mode: PAPER-ONLY (simulasi virtual).</p>"
        '<p><a href="/health">/health</a> | <a href="/docs">/docs</a></p>'
        "</body></html>"
    )

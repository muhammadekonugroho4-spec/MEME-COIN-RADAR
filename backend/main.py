"""GLOBAL-STOCK... eh, MEME-COIN-RADAR - FastAPI app (Fase 2: radar UI + API)."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend import config
from backend.routes.api import router as api_router

VERSION = "0.2.0"
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    for sub in ("", "coins", "daily", "portfolio"):
        (config.DATA_DIR / sub).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="MEME-COIN-RADAR", version=VERSION, lifespan=lifespan)
app.include_router(api_router)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


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
def index(request: Request):
    return TEMPLATES.TemplateResponse(request, "radar.html")


@app.get("/positions", response_class=HTMLResponse)
def positions_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "positions.html")

"""Test skeleton fase 0 MCR - offline penuh."""
import asyncio

from fastapi.testclient import TestClient

from backend import config
from backend.main import VERSION, app

client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == VERSION
    assert body["mode"] == "paper-only"  # kontrak proyek terlihat di health
    assert isinstance(body["missing_credentials"], list)


def test_health_does_not_leak_secret_values():
    text = client.get("/health").text.lower()
    assert "gemini_api_key=" not in text
    if config.GEMINI_API_KEY:
        assert config.GEMINI_API_KEY.lower() not in text


def test_index_page():
    r = client.get("/")
    assert r.status_code == 200
    assert "MEME-COIN-RADAR" in r.text


def test_data_dirs_created(tmp_path, monkeypatch):
    d = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", d)

    from backend.main import lifespan

    async def run():
        async with lifespan(None):
            pass

    asyncio.run(run())
    for sub in ("coins", "daily", "portfolio"):
        assert (d / sub).is_dir()

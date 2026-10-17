"""Analisa AI risiko per kandidat meme coin (port pola gsai fase 3).

Auto-fallback: Gemini -> Groq -> MOCK deterministik.
Output: 1-2 kalimat risiko bahasa manusia + verdict singkat. Tidak pernah raise.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import requests

from backend import config

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
TIMEOUT = 40

SYSTEM_PROMPT = (
    "Kamu auditor meme coin Solana. Berdasarkan data berikut, nilai risiko SINGKAT dalam JSON valid "
    "tanpa markdown: {\"risk_note\":\"1-2 kalimat bahasa Indonesia tentang risiko spesifik coin ini\","
    "\"flag\":\"ok|caution|danger\"}. Fokus: konsentrasi holder, umur, momentum tak wajar, likuiditas. "
    "Jangan mengada-ada data yang tidak diberikan."
)


@dataclass
class AIRisk:
    mint: str
    flag: str        # ok | caution | danger
    note: str
    engine: str      # gemini | groq | mock
    generated_at: str


def _facts(row: dict, score, zone, reasons: list[str], top10_pct, age_min) -> str:
    parts = [
        f"symbol {row.get('symbol')}",
        f"harga ${row.get('price_usd')}",
        f"likuiditas ${row.get('liquidity_usd'):,.0f}" if row.get("liquidity_usd") else None,
        f"FDV ${row.get('fdv'):,.0f}" if row.get("fdv") else None,
        f"perubahan 1 jam {row.get('chg_h1')}%",
        f"buy/sell m5 {row.get('buys_m5')}/{row.get('sells_m5')}",
    ]
    if score is not None:
        parts.append(f"skor sistem {score} zona {zone}")
    if reasons:
        parts.append("catatan filter: " + "; ".join(reasons))
    if top10_pct is not None:
        parts.append(f"top-10 holder {top10_pct:.0f}% supply")
    if age_min is not None:
        parts.append(f"umur {age_min:.0f} menit")
    return " | ".join(p for p in parts if p)


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("` \n").removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _mock(row: dict, score, zone, reasons: list[str], top10_pct, age_min) -> AIRisk:
    # deterministik dari data
    flags, notes = [], []
    if reasons:
        flags.append("danger")
        notes.append("gagal filter: " + "; ".join(reasons[:2]))
    if top10_pct is not None and top10_pct > 25:
        flags.append("caution")
        notes.append(f"konsentrasi top-10 holder {top10_pct:.0f}%")
    chg = row.get("chg_h1") or 0
    if chg > 100:
        flags.append("caution")
        notes.append(f"naik {chg:.0f}% dalam 1 jam (pump cepat)")
    elif chg < -30:
        flags.append("danger")
        notes.append(f"turun {chg:.0f}% dalam 1 jam")
    if age_min is not None and age_min < 60:
        notes.append(f"sangat baru ({age_min:.0f} menit)")
    if not notes:
        return AIRisk(row["mint"], "ok", "Metrik pasar dalam batas wajar untuk meme coin.", "mock",
                      time.strftime("%Y-%m-%dT%H:%M:%S"))
    flag = "danger" if "danger" in flags else "caution"
    return AIRisk(row["mint"], flag, "; ".join(notes[:2]) + ".", "mock",
                  time.strftime("%Y-%m-%dT%H:%M:%S"))


def _gemini(facts: str, key: str) -> dict | None:
    try:
        r = requests.post(
            f"{GEMINI_URL}?key={key}",
            json={
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"parts": [{"text": facts}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 200},
            },
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None
        return _parse_json(r.json()["candidates"][0]["content"]["parts"][0]["text"])
    except (requests.RequestException, KeyError, IndexError):
        return None


def _groq(facts: str, key: str) -> dict | None:
    try:
        r = requests.post(
            GROQ_URL,
            json={
                "model": "llama-3.3-70b-versatile",
                "temperature": 0.2,
                "max_tokens": 200,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                             {"role": "user", "content": facts}],
            },
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None
        return _parse_json(r.json()["choices"][0]["message"]["content"])
    except (requests.RequestException, KeyError):
        return None


def analyze_risk(row: dict, score=None, zone=None, reasons: list[str] | None = None,
                 top10_pct=None, age_min=None) -> AIRisk:
    reasons = reasons or []
    facts = _facts(row, score, zone, reasons, top10_pct, age_min)
    if config.GEMINI_API_KEY:
        d = _gemini(facts, config.GEMINI_API_KEY)
        if d:
            return AIRisk(row["mint"], d.get("flag", "caution"), d.get("risk_note", ""), "gemini",
                          time.strftime("%Y-%m-%dT%H:%M:%S"))
    if config.GROQ_API_KEY:
        d = _groq(facts, config.GROQ_API_KEY)
        if d:
            return AIRisk(row["mint"], d.get("flag", "caution"), d.get("risk_note", ""), "groq",
                          time.strftime("%Y-%m-%dT%H:%M:%S"))
    return _mock(row, score, zone, reasons, top10_pct, age_min)

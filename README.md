# MEME-COIN-RADAR

Radar meme coin Solana + simulator paper trading. **PAPER-ONLY** — tanpa wallet, tanpa private key.

## Arsitektur
- Scan */10 mnt: DexScreener → filter keras (5) → skor (6 sinyal) → filter on-chain (authority + holder) → AI note
- Trade */5 mnt: sinyal BUY → fill next-scan (slippage model) → stop -35% / liq-pull / TP +100% / trailing 25% / max 48 jam
- Report harian: win rate, rug stats, strategi vs acak

## Jalankan lokal
```bash
.venv/bin/python -m uvicorn backend.main:app --port 8780
# / radar, /positions, /journal, /stats, /health
```

Laporan terbaru: `data/daily/YYYY-MM-DD/report.md`

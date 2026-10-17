# PROMPT PROYEK: MEME-COIN-RADAR (MCR)
> Radar + simulator paper trading meme coin Solana — deteksi coin baru, filter anti-scam otomatis,
> skor risiko AI, beli/jual **virtual**. Total biaya pembangunan: **$0** (semua API free tier permanen,
> semuanya sudah diverifikasi hidup per 17 Okt 2026).

---

## 0. PRINSIP & BATASAN PROYEK (BACA DULU — TIDAK BISA DITAWAR)

1. **PAPER ONLY.** Tidak ada koneksi wallet asli, tidak ada private key, tidak ada transaksi nyata
   dalam seluruh Fase 0–7. Eksekusi uang asli adalah keputusan terpisah di luar file ini dan WAJIB
   menunggu bukti statistik dari simulator (§7).
2. **Angka realitas:** mayoritas meme coin rug/honeypot dalam hitungan jam. Target utama proyek ini
   BUKAN "profit" tapi **membuktikan dengan data** berapa % coin yang bisa diselamatkan filter,
   dan apakah strategi lolos-filter punya harapan matematis. Kemenangan proyek = data jujur.
3. **Kegagalan bukan error, adalah data.** Coin yang rug setelah dibeli virtual tetap dicatat di
   jurnal — itulah produk paling berharga dari proyek ini.
4. **Modal laptop + $0:** semua data via API publik gratis, semua komputasi lokal, semua hasil
   disimpan via git (pola "git as database" terbukti dari GLOBAL-STOCK-AI).
5. **File ini adalah kontrak prompt.** Setiap sesi kerja baru hanya mengerjakan SATU fase:
   `"Kerjakan Fase <N> dari /home/kaltaraid/Documents/MEME-COIN-RADAR/PROMPT_PROJECT_MEME_COIN_RADAR.md.
   Ikuti kontrak §6 dan definisi selesai §5. Laporkan file berubah + hasil verifikasi."`

---

## 1. SUMBER DATA — SEMUA SUDAH DIVERIFIKASI HIDUP (17 OKT 2026)

| # | Sumber | Status uji | Untuk apa | Limit |
|---|--------|-----------|-----------|-------|
| 1 | **DexScreener API** `api.dexscreener.com` | ✅ 200 (search 30 pairs, token endpoint OK, token-profiles OK) | Deteksi pair/coin baru, harga real-time, likuiditas, FDV, volume m5/h1/h24, priceChange | 300 req/menit (cukup longgar) |
| 2 | **Solana RPC publik** `api.mainnet-beta.solana.com` | ✅ 200 (getHealth ok, getTokenSupply ok) | Token supply, decimais, (fase lanjut) distribusi holder via getProgramAccounts | Rate limit publik ketat → pakai cache + backoff; alternatif gratis: `solana-devnet` TIDAK (harus mainnet), cadangan: Helius free tier kalau perlu |
| 3 | **CoinGecko public API** | ✅ 200 (ping ok) | Cross-check harga + metadata coin besar | 30 req/menit free |
| 4 | **LLM Groq / Gemini free tier** (port dari GLOBAL-STOCK-AI fase 3, sudah jalan) | ✅ sudah teruji di proyek saham | Ringkasan risiko per coin bahasa manusia | cukup untuk top-10/hari |
| 5 | (Fase lanjut) RugCheck API publik | perlu diuji saat fase tsb | Skor risiko pihak ketiga | TBD |

**Tidak dipakai:** semua endpoint butuh key/paid, bot Telegram scraping, endpoint tak resmi.

---

## 2. ARSITEKTUR (MENIRU GLOBAL-STOCK-AI — KONTRAK SAMA)

```
MEME-COIN-RADAR/
├── backend/
│   ├── config.py               # env loader (port dari gsai)
│   ├── main.py                 # FastAPI + /health + UI
│   ├── core/                   # MURNI, tanpa network
│   │   ├── risk_filter.py      # ⭐ inti anti-scam (§4)
│   │   ├── scorer.py           # skor kandidat 0-100
│   │   ├── indicators.py       # EMA/momentum/m5-h1-h24 untuk meme (versi ringan)
│   │   ├── strategy.py         # aturan entry/exit/stop untuk simulator
│   │   ├── paper_broker.py     # broker virtual: fill realistis (§4.4)
│   │   ├── portfolio.py        # posisi, PnL, equity curve
│   │   ├── journal.py          # catatan tiap keputusan + "mengapa" (explainable)
│   │   ├── ai_service.py       # port dari gsai (gemini→groq→mock fallback)
│   │   └── formatter.py
│   ├── adapters/               # SEMUA network di sini
│   │   ├── base.py             # RateLimitManager (port dari gsai)
│   │   ├── dexscreener.py      # search/new pairs/token detail
│   │   ├── solana_rpc.py       # supply, mint authority (JSON-RPC)
│   │   └── coingecko.py        # cross-check
│   ├── routes/api.py           # /api/scan /api/positions /api/journal /api/stats
│   └── templates/              # dashboard dark (pola gsai)
├── jobs/
│   ├── job_scan.py             # cron: deteksi + filter + skor → CSV (jalan tiap 10 mnt)
│   ├── job_trader.py           # cron: hitung strategi → paper order (jalan tiap 5 mnt)
│   └── job_report.py           # harian: rekap PnL + statistik filter + laporan
├── data/
│   ├── coins/                  # parquet per mint address (riwayat harga)
│   ├── daily/                  # YYYY-MM-DD/: scan_manifest, trades, journal
│   └── portfolio/              # equity.csv, positions.json (state paper)
├── tests/                      # pytest offline (mock HTTP, seperti gsai)
├── .github/workflows/
│   ├── scan.yml                # */10 jam 00-23 UTC hari kerja+weekend (crypto 24/7)
│   ├── trade.yml               # */5
│   └── report.yml              # 00:30 UTC
├── PROMPT_PROJECT_MEME_COIN_RADAR.md  (file ini)
└── PROGRESS.md
```

**Kontrak keras (sama seperti gsai):**
- `core/` tidak boleh import requests — semua I/O di `adapters/`, supaya semua logika dites offline.
- Setiap coin diidentifikasi **mint address** (bukan symbol — symbol palsu sangat umum).
- Semua keputusan (beli/tolak/jual) punya alasan tertulis di jurnal. Tidak ada black box.
- `.env` di `.gitignore` sejak commit pertama. Tidak ada private key di proyek ini, titik.

---

## 3. PIPELINE DETEKSI COIN BARU

```
[tiap 10 menit]
1. DexScreener token-profiles/latest + search q=pump  → daftar pair baru chainId=solana
2. Dedup vs data/coins/ (mint address)                → hanya mint baru
3. Untuk tiap mint baru: detail pair (priceUsd, liquidity.usd, fdv, volume, txns)
4. Solana RPC: getTokenSupply (untuk skor distribusi; mint authority cek fase 4)
5. risk_filter evaluasi (§4)                          → PASS / REJECT + alasan
6. scorer (§4.3)                                      → skor 0-100 untuk yang lolos
7. simpan parquet + journal entry                     → hasil scan harian CSV
```

---

## 4. MESIN ANTI-SCAM (risk_filter.py) — JANTUNG PROYEK

### 4.1 Filter keras (REJECT langsung, alasan dicatat)
| Filter | Ambang awal | Kenapa |
|---|---|---|
| Likuiditas USD | < $5.000 | terlalu tipis untuk keluar posisi |
| Umur pair | > 24 jam ATAU < 2 menit (opsi mematikan "baru lahir") | coin <2 menit = arena sniper bot; default kita: minimal 30 menit |
| FDV | > $5.000.000 | pump.fun rata2 rug sebelum cap segini |
| Volume/Liquidity rasio 24h | > 15 | likuiditas kecil tapi volume raksasa = wash trading |
| Harga dari harga tertinggi 5m | drop > 60% | sudah rug saat kita lihat |

### 4.2 Filter skor (menurunkan skor, tidak menolak)
| Sinyal | Bobot |
|---|---|
| Momentum m5/h1 sehat (naik tapi tidak vertikal >200%/jam) | 20 |
| Volume h1 vs h24 (keberlanjutan, bukan sekali ledak) | 20 |
| Txns buy/sell rasio 5m (1.1–3.0 sehat; >5 = pump bot) | 15 |
| Likuiditas relatif FDV (>=2% aman) | 15 |
| Usia: 30 mnt–6 jam sweet spot | 15 |
| Berita/sentimen AI (fase 5) | 15 |

### 4.3 Keputusan
- Skor >= 70 → kandidat BELI VIRTUAL (masuk antrian strategy)
- 40–69 → watchlist (dipantau tiap scan, bisa naik)
- < 40 / REJECT → hanya jurnal + statistik filter

### 4.4 Paper broker — aturan realistis (WAJIB, jangan disederhanakan)
1. **Fill di harga scan BERIKUTNYA** (bukan harga sinyal) — menghilangkan bias lookahead.
2. **Slippage model:** 0.5% + (ukuran order / likuiditas) × 100% — beli coin tipis mahal harganya.
3. **Max position** 10% dari equity virtual; **max 5 posisi bersamaan**.
4. **Stop-exit otomatis:** -35% dari entry (rug cepat) atau likuiditas pair < 50% dari saat beli
   (sinyal dev menarik likuiditas) → jual virtual apa pun hargaannya.
5. **Take-profit bertahap:** +100% jual 50%, sisanya trailing stop 25%.
6. **Hold maksimum 48 jam** — meme coin bukan investasi.
7. Semua fill/exit dicatat: mint, waktu, harga sinyal vs harga fill, slippage, alasan entry/exit.

---

## 5. ROADMAP & DEFINISI SELESAI

| Fase | Hasil | Definisi selesai |
|---|---|---|
| 0 | Kerangka proyek | Folder §2, venv, /health 200, .gitignore(.env), pytest jalan, repo GitHub + push pertama |
| 1 | Adapter + scan pipeline | job_scan via GitHub Actions tiap 10 mnt sukses 1 hari; ≥1 mint baru tercatat; parquet terisi; fallback dexscreener→coingecko teruji |
| 2 | risk_filter + scorer | Semua filter §4.1 dengan unit test per kasus; ≥10 coin ter-reject dengan alasan jelas di jurnal; skor tercetak untuk yang lolos |
| 3 | Paper broker + portfolio | Siklus penuh: sinyal→order virtual→fill next-scan→posisi tampil di UI→stop/TP jalan; equity curve CSV |
| 4 | Deep filter Solana | Cek mint authority/revoked, cek konsentrasi holder (top-10 holder < 40% supply) via RPC; filter menjadi 2 lapis (API+onchain) |
| 5 | AI layer | ai_service memberi 1 kalimat risiko per kandidat (mock bila key kosong); jurnal memuat narasi AI |
| 6 | UI dashboard | Halaman: Radar (kandidat live), Posisi, Jurnal, Statistik filter (berapa % reject per alasan) — dark theme PWA |
| 7 | Analisis 30 hari | job_report menghasilkan: win rate, rata-rata rug dalam X jam, kurva equity, jawaban "apakah strategi lolos-filter unggul dari acak?" — PDF/MD report |

---

## 6. ATURAN KEAMANAN & KEBENARAN

1. Tidak pernah ada private key / seed phrase di kode, config, atau log. Proyek ini TIDAK berhubungan
   dengan wallet asli.
2. Semua klaim performa harus dari data `data/` yang bisa diaudit git. Tidak ada angka karangan di UI.
3. Rate limit dihormati (RateLimitManager per sumber); tidak ada retry agresif.
4. UI memasang disclaimer tetap: "Simulasi virtual — bukan saran finansial. Meme coin berisiko total loss."
5. Laporan Fase 7 WAJIB memuat hasil negatif (kalau strategi kalah dari acak, ditulis begitu).

---

## 7. GERBANG KE KEPUTUSAN UANG ASLI (di luar scope file ini)

Simulator berjalan minimal **30 hari** sebelum ada pembicaraan uang asli. Syarat minimal semua:
- Win rate + rata-rata PnL positif setelah model slippage,
- Max drawdown < 50% equity,
- Statistik filter: >= 90% rug ter-tangkap sebelum entry,
- Pemilik proyek memutuskan sendiri, dengan modal yang siap hilang 100%.

---

## 8. HUBUNGAN DENGAN GLOBAL-STOCK-AI

- Kode diporting (bukan di-share) dari gsai: base.py, ai_service.py, pola jobs/workflows/UI.
- Kedua proyek berjalan sendiri-sendiri; tidak ada dependensi lintas folder.
- GSAI fase 4+ ditunda sampai MCR fase 3 selesai (kesepakatan pivot 17 Okt 2026).

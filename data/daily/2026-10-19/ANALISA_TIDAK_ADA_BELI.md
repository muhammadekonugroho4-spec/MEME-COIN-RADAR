# ANALISA: Kenapa Belum Ada Pembelian (19 Okt 2026, 11:37 UTC)

> Laporan investigasi — tidak ada kode yang diubah. Semua temuan berdasarkan data
> terukur (log Actions, CSV hasil scan, panggilan API live, simulasi scorer).

## Ringkasan 5 penyebab (urut bobot dampak)

### 1. GitHub Actions MENG-THROTTLE cron */2 — bukti keras
Jeda aktual antar run scan (15 run terakhir, dari API):
`310, 254, 178, 134, 124, 123, 122, 115, 52, 30, 25, 25, 24, 3, 3 menit`
→ rata-rata **±2 jam**, bukan 2 menit. GitHub membatasi jadwal padat.
**Dampak berantai:** momentum m5 butuh observasi berjarak ≤5 menit. Dengan jeda 2 jam,
perbandingan harga selalu basi → `vol_m5`/`chg_m5` tetap 0 → syarat momentum WAJIB
untuk zona BUY tidak pernah terpenuhi. **Ini penyebab #1.**

### 2. Syarat momentum = ambang untuk pasar yang sedang tidur
Uji langsung ke 20 coin graduating (mcap terbesar yang belum graduate) via DexScreener:
- **0/20** punya `chg_m5 > 0` DAN `vol_m5 ≥ $2000` saat ini
- Vol m5 teratas cuma **$75**; kebanyakan $0
Jam UTC 07:00 = dini hari pasar AS — likuiditas meme coin menguap. Scalper butuh
koin yang SEDANG meledak; tidak ada satu pun sekarang. **Ini kondisi pasar, bukan bug.**

### 3. Data momentum koin graduating memang tersedia — tapi tidak dipakai penuh
DexScreener token endpoint memberikan vol m5/h1/h24, txns buy/sell, chg lengkap
(terverifikasi: MITCH vol m5 $0.73, chg h24 +3.46%). Kode `best = d_row` sudah benar.
Jadi data ada; masalahnya cuma **tidak pernah fresh** karena penyebab #1.

### 4. Sentiment hype 0 untuk semua kandidat
`hype_score: 0` di semua baris: coin graduating jarang muncul di CoinGecko trending
(yang trending = coin besar) dan tidak di-boost. Bobot sentiment praktis mati untuk
segmen koin ini.

### 5. Run Actions terakhir hanya mendapat 5 kandidat non-REJECT
Kandidat graduating benar (MITCH, GOR, CTO, RHUB, PUMP — likuiditas $8k–$2M, FDV
$360k–$2.2M, lolos semua filter keamanan). Skor mereka 34.5–38: gagal cuma di
momentum/volume/ratio (semua 0 karena penyebab #1–2). **Fundamental koin-koin ini sehat.**

## Kesimpulan
Sistem bekerja sesuai desain; yang salah adalah **ASUMSI**: bahwa cron */2 = jalan tiap
2 menit (salah, jadi ~2 jam) dan bahwa selalu ada koin bergerak kapan pun (salah, pasar
ada jam sibuknya). Akibatnya sinyal BUY butuh momentum yang mustahil terukur.

## Solusi berurutan (proposal — menunggu persetujuan)

### Solusi A — Hilangkan ketergantungan pada jadwal Actions (dampak terbesar)
1. **Momentum dari interval berapa pun**: simpan ts observasi; hitung chg per menit
   (`Δharga/Δmenit`), bukan chg m5 literal. Jeda 2 jam pun bisa dinilai "tren naik/turun".
2. **Run loop berantai dalam 1 run Actions** (job matrix 20 menit × loop internal 1 menit):
   1 run cron = 20 siklus scan. Melewati throttle GitHub sepenuhnya, tetap gratis.
3. Cadangan: trigger berantai (workflow membuat `workflow_dispatch` berikutnya via API)
   untuk jeda stabil ~1 menit antar siklus.

### Solusi B — Sumber koin yang SEDANG meledak
4. **Scanner vol-m5**: pilih kandidat dari koin dengan vol m5 terbesar hari ini
   (bukan top mcap / terbaru). Scalper mengikuti aksi, bukan daftar statis.
5. **Batasi jam aktif**: jalankan hanya saat pasar AS & Eropa ramah (UTC 12:00–22:00) —
   di luar itu pasar tidur, TIDAK ADA yang bisa di-scalp siapa pun.

### Solusi C — Kalibrasi ulang skor (santai, tetap disiplin)
6. Ambang momentum: `chg_m5 > 0 & vol_m5 ≥ $2000` → **`chg_per_menit > 0.1% & vol_m5 ≥ $300`**
   (dikalibrasi dari data live hari ini, bukan tebakan).
7. Koin sehat tanpa momentum → tetap WATCH (bukan dibuang); masuk BUY otomatis begitu
   momentum muncul — ini sudah bekerja, tinggal diberi data segar (Solusi A).
8. Sentiment: bobot tetap kecil; hype CoinGecko memang jarang kena koin micro-cap.

### Yang TIDAK perlu diubah
- Filter keamanan (FDV ≤$5M, curve, holder) — bekerja sempurna, semua REJECT memang sampah.
- Paper broker, SL/TP/timeout — aturan scalp sudah benar.
- Arsitektur adapters/core — solid, teruji 85 test.

## Bukti utama
| Bukti | Sumber |
|---|---|
| Jeda run 3–310 menit | API Actions runs (15 run terakhir) |
| 0/20 koin bergerak, vol m5 maks $75 | DexScreener token endpoint, live |
| Data vol/chg lengkap tersedia utk koin graduating | DexScreener, MITCH live |
| Skor 34.5–38 semua karena momentum=0 | Simulasi komponen scorer |
| 15 kandidat lolos keamanan di run 06:54 | scan_results.csv 2026-10-19 |

---
*Analisa saja — menunggu keputusan sebelum ada perubahan.*

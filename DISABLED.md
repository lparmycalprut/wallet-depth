# Fitur yang sudah dihapus

Wallet Depth kini fokus pada **kedalaman holder** (real > $10 vs dust,
dust % MC). Seluruh sistem sinyal
dan notifikasi sudah dihapus total:

- sinyal SMART SEROK (WASPADA DUMP / SIAP2 PUMP / BATTLE TERJADI);
- sinyal reversal (REVERSAL UP / REVERSAL DOWN) + struktur SBR;
- 3 sinyal bottom harian (SELLER_EXHAUSTION / REVERSAL / AKUMULASI);
- semua alert & transport **Telegram** (`signals.py`, secrets, callback mute);
- backtest/confidence sinyal lama;
- **silent accumulation 12 jam** (net flow 12 jam, `detect_silent`,
  filter SILENT/LP/PUMPDUMP, `enrich_rows`) — dihapus 2026-09-03;
- **Overlay dust % MC semua token LP** (expander di card Chart LP,
  `lp_watchlist.lp_overlay_figure` tidak lagi dirender) — 2026-09-07;
- **kolom tabel `Δ 4 jam` + `Grafik 4 jam`** (sparkline) di semua card
  watchlist — 2026-09-07; grafik hanya tersisa di expander per token;
- **halaman `📊 CVD`, `🔎 Deteksi Akumulasi`, `🚀 Pre-Pump`** beserta section
  Pre-Pump di dashboard — dihapus dari `pages/` 2026-09-07. Modul
  `cvd.py` / `accumulation.py` / `pre_pump_screener.py` masih ada (dipakai
  test + skrip), tapi tidak ada rute UI ke sana dan alias deep-link lama
  (`?page=cvd`, `?page=akumulasi`, `?page=prepump`) berhenti di dashboard.

Modul yang dihapus: `signals.py`, `serok_engine.py`, `reversal_engine.py`,
`reversal_state.py`, `reversal_status.py`, `price_structure.py`,
`effort_detector.py`, `scripts/realtime_reversal.py`,
`scripts/backtest_confidence.py`, `silent_accumulation.py` (→
`holder_analysis.py`), `silent_status.py` (→ `holder_status.py`),
`scripts/scan_silent.py` (→ `scripts/scan_holders.py`).

Yang tetap aktif:

- watchlist add/remove dan sinkronisasi GitHub;
- fetch trade GMGN dengan fallback Helius;
- listing Trending/Degen tanpa ranking dan tanpa analisis holder;
- penyimpanan `daily_effort.json` (agregasi harian saja, tanpa sinyal);
- chart harga/CVD + volume USD;
- cron GitHub Actions: scan holder watchlist target 1× per jam
  (`cron "0 * * * *"`; schedule GitHub best-effort, lihat DEPLOY.md),
  publish `holder_status.json` + backup store ke ref `holder-live`.

Jangan menghidupkan kembali modul atau palang `TELEGRAM_*` lama.

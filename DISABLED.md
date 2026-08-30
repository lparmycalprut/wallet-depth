# Fitur yang sudah dihapus

Wallet Depth kini fokus pada **silent accumulation 12 jam terakhir** dan
**kedalaman holder** (real > $10 vs dust, dust % MC). Seluruh sistem sinyal
dan notifikasi sudah dihapus total:

- sinyal SMART SEROK (WASPADA DUMP / SIAP2 PUMP / BATTLE TERJADI);
- sinyal reversal (REVERSAL UP / REVERSAL DOWN) + struktur SBR;
- 3 sinyal bottom harian (SELLER_EXHAUSTION / REVERSAL / AKUMULASI);
- semua alert & transport **Telegram** (`signals.py`, secrets, callback mute);
- backtest/confidence sinyal lama.

Modul yang dihapus: `signals.py`, `serok_engine.py`, `reversal_engine.py`,
`reversal_state.py`, `reversal_status.py`, `price_structure.py`,
`effort_detector.py`, `scripts/realtime_reversal.py`,
`scripts/backtest_confidence.py`.

Yang tetap aktif:

- watchlist add/remove dan sinkronisasi GitHub;
- fetch trade GMGN dengan fallback Helius;
- listing Trending/Degen tanpa ranking, kini diperkaya analisis holder
  (real vs dust, dust % MC) dan flow 12 jam;
- penyimpanan `daily_effort.json` (agregasi harian saja, tanpa sinyal);
- chart harga/CVD + volume USD;
- cron GitHub Actions: scan silent-accumulation watchlist setiap ~15 menit,
  publish `silent_status.json` ke ref `silent-live`.

Jangan menghidupkan kembali modul atau palang `TELEGRAM_*` lama.

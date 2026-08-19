# Kegiatan — 19 Agustus 2026

Port sinyal ekstensi [SMART_SEROK v9.1.3](https://github.com/lparmycalprut/SMART_SEROK) ke wallet-depth.

## Yang dikerjakan

1. **Watchlist dikosongkan** (`watchlist.json` = `{}`).
2. **Symbol otomatis** saat CA manual: field ticker dihapus di form Streamlit;
   `watchlist.fetch_token_symbol()` memanggil DexScreener.
3. **Sinyal diganti** dari wash-collapse / SBR menjadi:
   - 🔴 WASPADA DUMP
   - 🟢 SIAP2 PUMP
   - ⚔️ BATTLE TERJADI
   Engine: `serok_engine.py` (bar 1 jam, R ≥10× prev + |R|≥10, battle gap ≤2.5% + P65).
4. **Scan tiap 15 menit** (cron Actions `*/15`). Fetch window 48 jam.
5. **Telegram** rapi: judul + `$SYMBOL`, syarat, R/CVD/TX/wallet, range MC (battle),
   jam WIB, tautan GMGN + DexScreener. Satu alert per `event_id`.
6. **Tes** `tests/test_serok_engine.py`; payload Telegram & UI disesuaikan.
   `python -m unittest` untuk modul baru lulus.

Tidak diubah tanpa perlu: halaman CVD, listing Trending/Degen, fetch GMGN,
persist watchlist GitHub.

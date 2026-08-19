# AGENTS.md — Wallet Depth

Dashboard dan scanner token Solana dari GMGN. Sistem notifikasi utama adalah
tiga sinyal **SMART SEROK v9.1.3** pada candle 1 jam.

## Sumber kebenaran

- `serok_engine.py`: port Python `content.js` SMART SEROK — bar 1H, R-spike,
  WASPADA DUMP / SIAP2 PUMP / BATTLE TERJADI.
- `reversal_engine.py`: normalisasi trade GMGN + FIFO wash matcher (dipakai
  aggregator bar).
- `scripts/realtime_reversal.py`: fetch raw GMGN, cache incremental 48 jam,
  klasifikasi SEROK, state event_id, dan Telegram.
- `reversal_state.py`: satu Telegram per `event_id` (bar+sinyal).
- `last_scan_result.json` / `reversal_status.json`: state scanner + snapshot UI.
- `.github/workflows/daily-effort.yml`: scan setiap 15 menit.

Watchlist di `app.py` membaca `load_reversal_status()`. Tambah CA manual
mem-fetch symbol dari DexScreener (`watchlist.fetch_token_symbol`).

## Sinyal (parity ekstensi)

```text
WASPADA DUMP  : harga naik + cumCVD naik + |R| ≥ 10× bar sebelumnya + |R| ≥ 10
SIAP2 PUMP    : harga turun + cumCVD turun + |R| ≥ 10× prev + |R| ≥ 10
BATTLE TERJADI: hanya setelah setup di klaster aktif;
                gap |BUY−SELL|/(BUY+SELL) ≤ 2,5%;
                TX, wallet unik, fresh_wallet ≥ P65;
                bar selesai; tag fresh_wallet wajib ada
```

R = |cvdClean| / |priceChgPct|. Wash ditampilkan, bukan syarat sinyal.

## Alert

Tiga tipe Telegram. Payload: judul + symbol, syarat, metrik bar, range MC
(battle), jam WIB, tautan GMGN + DexScreener.

Jalankan:

```bash
python -m unittest discover tests
python -m py_compile serok_engine.py reversal_state.py scripts/realtime_reversal.py
```

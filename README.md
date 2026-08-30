# Wallet Depth — Silent Accumulation 12H

Wallet Depth memantau token Solana dari GMGN dan berfokus pada
**silent accumulation dalam 12 jam terakhir** serta **kedalaman holder**
(real holder > $10 value vs dust). Semua sinyal lama (reversal, SMART
SEROK, seller exhaustion, battle) dan notifikasi Telegram sudah dihapus.

## Konsep

1. **Silent accumulation 12 jam** — dari trade 12 jam terakhir:
   - `net_usd` positif (beli > jual),
   - minimal 3 wallet net-beli (akumulator),
   - harga hampir tidak bergerak (≤ ±5%),
   - share mev/bot rendah (≤ 35%).
2. **Real holder vs dust** — dari daftar holder GMGN (paginasi penuh):
   - **real holder**: nilai posisi > $10,
   - **dust holder**: 0 < nilai ≤ $10,
   - **dust % dari marketcap** = total nilai dust / marketcap × 100,
   - dust % supply juga dihitung dari `amount_percentage`.
3. **Dust** dihitung hanya dari wallet murni (LP/pool/exchange dikeluarkan).

## Modul

| File | Peran |
|---|---|
| `silent_accumulation.py` | fetch holder (paginasi `next`), klasifikasi real/dust, net flow 12 jam, deteksi silent, `enrich_rows` |
| `silent_status.py` | snapshot status untuk dashboard (GitHub ref `silent-live`) |
| `scripts/scan_silent.py` | cron: scan watchlist 12 jam + holder, publish status |
| `cvd_daily.py` / `daily_store.py` | agregasi harian CVD/volume (tanpa sinyal) + storage idempoten |
| `gmgn_screener.py` | listing Trending/Degen (tanpa skoring) |
| `trending_ui.py` | tabel listing + kolom holder depth & silent 12h |
| `pages/4_📊_CVD.py` | chart flow & CVD harian (tanpa sinyal) |

## Menjalankan

```bash
pip install -r requirements.txt
streamlit run app.py
```

Scan watchlist otomatis tiap ~15 menit via GitHub Actions
(`.github/workflows/daily-effort.yml`). Snapshot dashboard dibaca dari
`silent_status.json` (ref `silent-live`). `GITHUB_TOKEN` streamlit secret /
env hanya untuk publish snapshot dan sinkronisasi watchlist.

## Pengujian

```bash
python -m unittest discover tests
python -m py_compile silent_accumulation.py silent_status.py \
  scripts/scan_silent.py
```

Analisis bersifat heuristik dan bukan saran keuangan.

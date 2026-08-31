# AGENTS.md — Wallet Depth

Dashboard dan scanner token Solana dari GMGN. Fokus: **silent accumulation
12 jam terakhir** + **kedalaman holder** (real > $10 vs dust, dust % MC).
Tidak ada sinyal dan tidak ada notifikasi Telegram.

## Sumber kebenaran

- `silent_accumulation.py`: fetch holder (paginasi `next`), klasifikasi
  real/dust, net flow 12 jam (`cvd.fetch_gmgn_swaps`), deteksi silent,
  `analyze_token`, `enrich_rows`, `resolve_holder_source`.
- `solscan_holders.py`: holder Solscan (Pro API `v2.0/token/holders` →
  Public API `token/holders`) + `wallet_depth` (bucket & tier ala halaman
  analytics Solscan). Watchlist memakai `auto` = Solscan dulu, fallback
  GMGN/Helius; listing Trending/Degen tetap `gmgn`.
- `helius_holders.py`: **Scan Holder Khusus** satu token di halaman utama —
  `scan_token_holders(ca)` memaksa holder dari Helius DAS
  `getTokenAccounts` (paginasi cursor via `fetch_holders_helius`) lalu
  `depth_bar_chart` menampilkan bar chart distribusi holder per range nilai
  (Wallet Depth by Threshold). Butuh Helius API key.
- `silent_status.py`: snapshot `silent_status.json` → GitHub ref
  `silent-live` (pinggir `main`, mencegah redeploy Streamlit).
- `scripts/scan_silent.py`: cron GitHub Actions (~15 menit) untuk watchlist.
- `scripts/realtime_reversal.py`: adapter saja — workflow lama memanggil file
  ini, isinya meneruskan ke `scan_silent.py` (tanpa sinyal/Telegram).
- `gmgn_screener.py`: listing Trending/Degen tanpa skoring.
- `cvd_daily.py` + `daily_store.py`: agregasi harian CVD/volume + storage
  (tanpa klasifikasi sinyal).
- `watchlist.py`: watchlist + sinkronisasi GitHub.

Watchlist di `app.py` membaca `load_silent_status()`. Tambah CA manual
mem-fetch symbol dari DexScreener (`watchlist.fetch_token_symbol`).
Scan Trending/Degen memanggil `enrich_rows` sehingga tiap baris langsung
mendapat `analysis` (holders + flow 12 jam).

## Ambang

```text
dust_limit_usd        : 10.0  (real > $10; dust 0 < value <= $10)
window 12 jam         : 12h (rolling, dari now)
silent net min        : >= $50
silent akumulator     : >= 3 wallet
silent harga          : |change| <= 5%
silent bot share      : <= 35%
max holders/token     : 3000 (cron) / 2000 (scan UI), paginasi 1000/halaman
max trade pages       : 8 (cron) / 6 (scan UI), 100 trade/halaman

Wallet depth Solscan (buckets, semua akun): >$0-$10, $10-$100, $100-$1k,
$1k-$10k, $10k-$100k, $100k-$500k, >$500k
Tier (wallet murni saja): 🦐 Shrimp <=$100, 🦀 Crab $100-$1k,
🐟 Fish $1k-$10k, 🐬 Dolphin $10k-$100k, 🦈 Shark >$100k
LP/pool dikecualikan dari tier via pair_addresses DexScreener + config.

holder_source (config.json / env HOLDER_SOURCE): auto (default, watchlist
pakai Solscan dulu) | solscan | gmgn. `SOLSCAN_API_KEY` (config/env/
secrets) mengaktifkan Pro API; tanpanya Public API + fallback GMGN/Helius.

Filter tabel scan (silent_accumulation.holder_filter_match):
SILENT    : silent accumulation 12 jam terdeteksi
LP        : dust_count > 0.5 * real_count DAN (real_pct_mc + dust_pct_mc) < 0.5
PUMPDUMP  : real_count < 0.2 * dust_count
```

Jalankan:

```bash
python -m unittest discover tests
python -m py_compile silent_accumulation.py silent_status.py \
  scripts/scan_silent.py
```

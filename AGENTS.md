# AGENTS.md — Wallet Depth

Dashboard token Solana. Fokus: **analisa holder dust** (jumlah + % MC,
grafik 4 jam, kohort Crab+Fish) dan **Scan Meteora DLMM**. Tidak ada
sinyal 12 jam dan tidak ada Telegram.

## Sumber kebenaran

- `holder_history.py`: store `holder_history.json`, freeze kohort 4 jam,
  resample grafik 4 jam, ambang dust **≥ 1% MC hati-hati** /
  **> 2% MC limit** (sembunyikan dari Meteora).
- `meteora_screener.py`: pool-discovery Meteora 24h (`fee_ratio≥250`) +
  1h (`fee_ratio≥1`), `active_tvl≥1000`, DLMM. Pool 24h yang masih di 1h
  tetap tampil. Dust > 2% MC dibuang.
- `silent_accumulation.py`: **Helius** sumber holder utama
  (`fetch_holders_helius`). `analyze_token(..., include_flow=False)`
  untuk jalur dust (tanpa swap 12 jam). `extra_pools` + `cohort_addrs`
  untuk Meteora / kohort.
- `solscan_holders.py`: hanya kalkulasi `wallet_depth`.
- `helius_holders.py`: Scan Holder Khusus satu token.
- `silent_status.py`: snapshot `silent_status.json` → ref `silent-live`
  (ikut `history` 4 jam, tanpa flow/silent).
- `scripts/scan_silent.py`: cron watchlist, holder-only + ingest history.
- `scripts/realtime_reversal.py`: adapter workflow lama → `scan_silent`.
- `gmgn_screener.py`: listing Trending/Degen.
- `pages/5_🧮_Holder.py`: Holder Analytic (di bawah CVD).
- `pages/4_📊_CVD.py`: CVD/flow harian saja (tanpa Holder Analytic).

Watchlist di `app.py` membaca `load_silent_status()` + `holder_history`.
Trending/Degen **tidak** menganalisa holder. Scan Meteora menganalisa
holder per mint lalu filter dust > 2% MC.

## Ambang

```text
dust_limit_usd        : 10.0  (real > $10; dust 0 < value <= $10)
dust hati-hati        : >= 1% marketcap
dust limit / hide     : >  2% marketcap
grafik / kohort       : bucket 4 jam
mid-tier (pilar)      : Crab+Fish = $100–$10k, freeze max 200 address
max holders/token     : 3000 (cron) / 2000 (scan UI)

Wallet depth (buckets): >$0-$10 … >$500k — default wallet murni
Tier: 🦐 Shrimp ≤$100, 🦀 Crab $100-$1k, 🐟 Fish $1k-$10k,
      🐬 Dolphin $10k-$100k, 🦈 Shark >$100k.
```

Jalankan:

```bash
python -m unittest discover tests
python -m py_compile holder_history.py meteora_screener.py \
  silent_accumulation.py silent_status.py scripts/scan_silent.py
```

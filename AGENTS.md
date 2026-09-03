# AGENTS.md — Wallet Depth

Dashboard token Solana. Fokus: **analisa holder dust** (jumlah + % MC,
grafik 4 jam, kohort Crab+Fish) dan **Scan Meteora DLMM**. Sinyal trading
lama dan silent accumulation / flow 12 jam sudah tidak dipakai. Telegram
alert dust aktif melalui `telegram_alerts.py` dan secrets workflow.

## Sumber kebenaran

- `holder_history.py`: store `holder_history.json`, freeze kohort 4 jam,
  resample grafik 4 jam, ambang dust **≥ 1% MC = BAHAYA**
  (sembunyikan dari Meteora).
- `meteora_screener.py`: pool-discovery Meteora 24h (`fee_ratio≥250`) +
  1h (`fee_ratio≥1`), `active_tvl≥1000`, DLMM. Pool 24h yang masih di 1h
  tetap tampil. Dust ≥ 1% MC dibuang.
- `holder_analysis.py`: **Helius** sumber holder utama
  (`fetch_holders_helius`, fallback GMGN). `analyze_token` = holder
  real/dust + mid-tier + kohort. `extra_pools` + `cohort_addrs`
  untuk Meteora / kohort.
- `solscan_holders.py`: hanya kalkulasi `wallet_depth`.
- `helius_holders.py`: Scan Holder Khusus satu token.
- `holder_status.py`: snapshot `holder_status.json` → ref `holder-live`
  (ikut `history` 4 jam).
- `scripts/scan_holders.py`: cron watchlist, ingest history, publish
  snapshot; exit non-zero bila 0 holder / publish gagal.
- `gmgn_screener.py`: listing Trending/Degen.
- `pages/5_🧮_Holder.py`: Holder Analytic (di bawah CVD).
- `pages/4_📊_CVD.py`: CVD harian saja (tanpa Holder Analytic).

Watchlist di `app.py` membaca `load_holder_status()` + `holder_history`.
Trending/Degen **tidak** menganalisa holder. Scan Meteora menganalisa
holder per mint lalu filter dust ≥ 1% MC.

## Ambang

```text
dust_limit_usd        : 10.0  (real > $10; dust 0 < value <= $10)
dust BAHAYA / hide    : >= 1% marketcap
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
  holder_analysis.py holder_status.py scripts/scan_holders.py
```

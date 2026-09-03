# AGENTS.md — Wallet Depth

Dashboard token Solana. Fokus: **analisa holder dust** (jumlah + % MC,
grafik 4 jam, kohort Crab+Fish) dan **Scan Meteora DLMM**. Tidak ada
silent accumulation / flow 12 jam; Telegram hanya dipakai cron untuk alert
perubahan holder dust yang sudah dikonfirmasi volume + harga + volatilitas.

## Sumber kebenaran

- `holder_history.py`: store `holder_history.json`, freeze kohort 4 jam,
  resample grafik 4 jam, ambang dust **≥ 0,5% MC = HATI-HATI** dan
  **≥ 1% MC = BAHAYA** (hanya BAHAYA yang disembunyikan dari Meteora).
  Baseline scan FULL immutable + kronologi wallet bounded
  (`holder_chronology.py`). `calculate_volatility_metrics()` = metrik
  volatilitas 4 jam dari candle hourly (`price_stddev_4h`, `price_range_4h`,
  `intra_hour_volatility`, `missing_hours`, `stale`); candle < 2 →
  `available: False` (artinya "tidak tahu", bukan "tenang").
- `lp_watchlist.py`: card **Chart LP** — watchlist terpisah berisi token
  `source=meteora`; baris data (dust % MC, Δ poin persentase, level) +
  figure matplotlib grafik perubahan dust holder (garis ambang 0,5% / 1%)
  dan overlay semua token LP. Murni data/figure, tanpa Streamlit.
- `holder_chronology.py`: perbandingan scan FULL (balance token, kategori
  `wallet_depth`, link Solscan). Tanpa LLM. Schema lama tetap bisa dibaca.
- `meteora_screener.py`: pool-discovery Meteora 24h (`fee_ratio≥250`) +
  1h (`fee_ratio≥1`), `active_tvl≥1000`, DLMM. Pool 24h yang masih di 1h
  tetap tampil. Dust ≥ 1% MC dibuang; ⭐ di UI memakai `source=meteora`
  sehingga token masuk Chart LP.
- `holder_analysis.py`: **Helius** sumber holder utama
  (`fetch_holders_helius`, fallback GMGN). `analyze_token` = holder
  real/dust + mid-tier + kohort. `extra_pools` + `cohort_addrs`
  untuk Meteora / kohort.
- `solscan_holders.py`: hanya kalkulasi `wallet_depth`.
- `helius_holders.py`: Scan Holder Khusus satu token.
- `core.py`: config/key Helius, pasar DexScreener (`get_market` ikut
  mengembalikan `volume`, `price_change`, `txns`), candle GeckoTerminal —
  `get_hourly_candles()` (mentah, per jam) dan `get_daily_candles()`
  (agregasi hari UTC; **hari UTC yang masih berjalan ikut ter-return**,
  saring dengan `cvd_daily.completed_dates`).
- `alert_context.py`: konteks pasar untuk konfirmasi alert — volume 4 jam,
  rata-rata volume per window 4 jam selama 7 hari, perubahan harga,
  buy/sell pressure, volatilitas. `market_context_provider()` = memo per
  token; `compact_signal()` untuk disimpan ke status. Ditarik **lazy**.
- `holder_status.py`: snapshot `holder_status.json` → ref `holder-live`
  (ikut `history` 4 jam dan `market_signal` bila konteks pasar tersedia).
  `snapshot_status` **tidak merge** token lama: publish satu token akan
  menghapus token lain, jadi scan manual di halaman Holder tidak boleh
  publish. Overlay `apply_manual_scan()` / `resolve_token_view()`
  (`st.session_state[MANUAL_SCAN_KEY]`) membuat kartu metrik, badge,
  watchlist, dan Chart LP ikut scan manual yang lebih baru daripada snapshot
  cron — grafik sudah lebih dulu memuat titik itu dari `holder_history.json`.
- `scripts/scan_holders.py`: cron watchlist, evaluasi alert sebelum ingest
  history, publish snapshot; exit non-zero bila 0 holder / publish gagal.
- `telegram_alerts.py`: rule dust 4 jam (+0,25 pp dump; -0,50 pp + buyer
  akumulasi), perubahan ±1 pp dari baseline, **gerbang konfirmasi
  volume/harga/volatilitas**, dedup, dan transport Telegram. Aturan tidak
  pernah fetch: pemanggil menyuntikkan `market_context` atau
  `context_provider(mint, analysis)` yang hanya dipanggil bila ada kandidat.
- `gmgn_screener.py`: listing Trending/Degen.
- `pages/5_🧮_Holder.py`: Holder Analytic (di bawah CVD) + kronologi FULL.
- `pages/4_📊_CVD.py`: CVD harian saja (tanpa Holder Analytic).

Watchlist di `app.py` membaca `load_holder_status()` + `holder_history`
lalu dipecah `lp_watchlist.split_watchlist()`: **Chart LP** (card paling
atas, token `source=meteora`) dan watchlist holder biasa — satu token hanya
muncul di satu card. Tombol 🌊/📋 memanggil `set_watchlist_source()`
(journal op `source`), form tambah manual punya radio tujuan card.
Trending/Degen **tidak** menganalisa holder. Scan Meteora menganalisa
holder per mint lalu filter dust ≥ 1% MC.

## Ambang

```text
dust_limit_usd        : 10.0  (real > $10; dust 0 < value <= $10)
                          -> dust % MC TIDAK invariant harga: cutoff USD
                          menggeser klasifikasi wallet (TODO(alerts):
                          annotate re-klasifikasi, bukan reject)
dust HATI-HATI        : >= 0.5% marketcap
dust BAHAYA / hide    : >= 1% marketcap
grafik / kohort       : bucket 4 jam

Konfirmasi alert (setelah ambang dust di atas terpenuhi):
dump                  : volume 4 jam >= 2.0x avg_volume_7d DAN harga <= -1%
akumulasi             : volume 4 jam >= 1.5x avg_volume_7d DAN buy > sell
baseline shift +-1 pp : ikut arah perubahan (naik = dump, turun = akumulasi)
skor konfirmasi       : 0.70 dasar + <=0.15 volume + <=0.10 harga/pressure
                        + 0.20 volatilitas tinggi dengan arah mendukung
ambang skor           : 0.70; 0.80 bila price_stddev_4h > 3%
volatilitas "liar"    : price_stddev_4h > 3.0% (sample stddev close 4 jam)
avg_volume_7d         : rata-rata volume PER WINDOW 4 JAM selama 7 hari
dedup                 : bucket 4 jam (event id) + jeda minimum 1 jam
data pasar tidak ada  : alert tetap dikirim, ditandai TIDAK TERVERIFIKASI
                        (ALLOW_UNVERIFIED_ALERTS = True)
mid-tier (pilar)      : Crab+Fish = $100–$10k, freeze max 200 address
max holders/token     : 3000 (cron) / 2000 (scan UI)

Wallet depth (buckets): >$0-$10 … >$500k — default wallet murni
Tier: 🦐 Shrimp ≤$100, 🦀 Crab $100-$1k, 🐟 Fish $1k-$10k,
      🐬 Dolphin $10k-$100k, 🦈 Shark >$100k.
```

Jalankan:

```bash
python -m unittest discover tests
python -m py_compile holder_history.py holder_chronology.py meteora_screener.py \
  holder_analysis.py holder_status.py telegram_alerts.py alert_context.py \
  lp_watchlist.py core.py scripts/scan_holders.py trending_ui.py watchlist.py \
  app.py
```

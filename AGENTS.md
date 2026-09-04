# AGENTS.md — Wallet Depth

Dashboard token Solana. Fokus: **analisa holder dust** (jumlah + % MC,
grafik 4 jam, kohort Crab+Fish) dan **Scan Meteora DLMM**. Tidak ada
silent accumulation / flow 12 jam; Telegram hanya dipakai cron untuk alert
perubahan holder dust yang sudah dikonfirmasi volume + harga + volatilitas.

## Sumber kebenaran

- `holder_history.py`: store `holder_history.json` (+ backup durable
  `holder_history.json.gz`, lihat bawah), freeze kohort 4 jam,
  resample grafik 4 jam, ambang dust **≥ 0,5% MC = HATI-HATI** dan
  **≥ 1% MC = BAHAYA** (hanya BAHAYA yang disembunyikan dari Meteora).
  **`DUST_BEST_PCT = 0.1`** (badge 🏆 BEST POOL, label
  `DUST_BEST_LABEL = "BEST POOL"`) bersifat **aditif**: `dust_flag(pct,
  prev, *, holders=...)` mengembalikan `best: bool` tanpa mengubah
  level/label/hide lama; guard `_holders_valid_for_best` menolak data
  kosong/gagal (`total_fetched <= 0`, `< 40 wallet`). `MAX_POINTS = 336`
  (14 hari × 24 titik/jam, cron hourly); UI tetap memakai
  `resample_4h` (maks 84 bucket 4 jam).
  Baseline scan FULL immutable + kronologi wallet bounded
  (`holder_chronology.py`). `calculate_volatility_metrics()` = metrik
  volatilitas 4 jam dari candle hourly (`price_stddev_4h`, `price_range_4h`,
  `intra_hour_volatility`, `missing_hours`, `stale`); candle < 2 →
  `available: False` (artinya "tidak tahu", bukan "tenang").
- `lp_watchlist.py`: card **Chart LP** — watchlist terpisah berisi token
  `source=meteora`; baris data (dust % MC, Δ poin persentase, level) +
  figure matplotlib grafik perubahan dust holder (garis ambang 0,5% / 1%)
  dan overlay semua token LP. Murni data/figure, tanpa Streamlit. Badge
  🏆 BEST POOL **tidak** dirender di card ini (scope: listing Scan
  Meteora saja, keputusan user) — `build_lp_row` memanggil
  `dust_flag(pct, prev)` tanpa `holders`, jadi `best` selalu False.
- `holder_chronology.py`: perbandingan scan FULL (balance token, kategori
  `wallet_depth`, link Solscan). Tanpa LLM. Schema lama tetap bisa dibaca.
- `meteora_screener.py`: pool-discovery Meteora 24h (`fee_ratio≥250`) +
  1h (`fee_ratio≥1`), `active_tvl≥1000`, DLMM. Pool 24h yang masih di 1h
  tetap tampil. Dust ≥ 1% MC dibuang; ⭐ di UI memakai `source=meteora`
  sehingga token masuk Chart LP. Badge 🏆 BEST POOL dirender di `app.py`
  (`_dust_best_html`), bukan di modul ini.
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
  Snapshot **ramping**: peta balance alert, peta kohort, dan peta wallet
  kronologi tidak ikut (hanya jumlah + sampel movements ≤20/interval,
  ≤12 interval) — terukur 2,87 MB → **0,30 MB** untuk 36 token (−90%). Data penuh itu hidup di
  backup store (bawah). Transport-nya generik: `_github_get_bytes` /
  `_github_put_bytes` (+ pembungkus JSON) dipakai `holder_status.json` dan
  `holder_history.json.gz` (`pull_store_backup` / `push_store_backup`).
  `snapshot_status` **tidak merge** token lama: publish satu token akan
  menghapus token lain, jadi scan manual di halaman Holder tidak boleh
  publish. Overlay `apply_manual_scan()` / `resolve_token_view()`
  (`st.session_state[MANUAL_SCAN_KEY]`) membuat kartu metrik, badge,
  watchlist, dan Chart LP ikut scan manual yang lebih baru daripada snapshot
  cron — grafik sudah lebih dulu memuat titik itu dari `holder_history.json`.
- `scripts/scan_holders.py`: cron watchlist (target **1×/jam** sejak
  2026-09-04), **pull + merge backup store sebelum scan**, evaluasi alert
  sebelum ingest history, publish snapshot, **push backup store
  sesudahnya**; exit non-zero bila 0 holder / publish snapshot gagal
  (backup gagal = `WARN` saja, tidak membuat cron merah). Scope rule
  ⚡ EARLY DUMP diteruskan lewat `lp_mints` = set `split_watchlist(
  watchlist)[0]` (token pool).

### Backup durable store holder

Runner Actions & Streamlit Cloud ephemeral, jadi `holder_history.json` hilang
tiap run. Store penuh dibackup sebagai **`holder_history.json.gz`** (gzip +
JSON compact, Contents API base64) di ref `holder-live`:

- `store_backup_bytes` / `parse_store_backup` (toleran gzip & JSON polos,
  payload rusak → `None`, tidak pernah melempar).
- `merge_stores(*stores)` — **argumen belakang menang** saat timestamp seri;
  titik union (≤`MAX_POINTS`), `baseline` **paling tua** (immutable),
  `latest_detail` terbaru, kohort yang masih punya balance lalu `frozen_at`
  terbaru, interval kronologi union per `(from_ts, to_ts)` (movements
  terbanyak menang), `alert_state` snapshot terbaru + union `sent_event_ids`
  + `last_sent` maksimum. Cron: `merge_stores(lokal, durable)`; UI:
  `merge_stores(durable, lokal)` (scan manual baru tidak ditimpa backup).
- `prune_store_for_backup` — hanya bila payload > `MAX_BACKUP_BYTES`
  (3,5 MB; terukur ~901 kB untuk 55 token jadi praktis tak pernah): buang
  movements interval lama → interval di luar 6 terbaru → peta wallet
  kronologi → `points[].buckets` → titik di luar **42 bucket 4 jam
  terakhir** (titik per jam di-`resample_4h` dulu supaya backup tetap
  ~7 hari grafik, bukan 42 jam) → `latest_detail`. **Baseline scan FULL
  dibuang paling akhir.**
- `publish_holder_history` / `pull_holder_history` /
  `load_durable_holder_history` (cache `DURABLE_CACHE_TTL` 600 detik) /
  `reset_durable_cache`. Kill-switch `HOLDER_STORE_BACKUP=0`.
- `seed_from_status` tetap jadi jaring kedua: snapshot **format lama** (masih
  membawa peta wallet) dipulihkan seperti semula, snapshot ramping
  (`summary: True` / `balances` berupa angka) **tidak** menimpa store.
- `telegram_alerts.py`: rule dust 4 jam (+0,25 pp dump; -0,50 pp + buyer
  akumulasi), perubahan ±1 pp dari baseline, **gerbang konfirmasi
  volume/harga/volatilitas**, dedup, transport Telegram, dan rule
  **⚡ EARLY DUMP** (kind `early_dump`): crossing naik melewati
  `DUST_BEST_PCT` 0,1% untuk token pool (`lp_mints` → `lp_mint` di
  `evaluate_alert_events`), **tanpa gerbang volume keras**
  (`early_dump_verdict`: `allow` selalu True, konteks pasar = info di
  pesan), ulang 1× per bucket 4 jam + `MIN_RESEND_SEC`, hanya saat dust
  masih naik; marker `alert_state["early_dump"]` = `{ts, dust_pct_mc}`
  run terakhir (di-merge paling baru oleh `holder_history._merge_alert_state`,
  dipertahankan `compact_alert_state`). Pesan selalu ditutup link token
  **🔗 GMGN + 🦆 DexScreener** dari `links.token_link_lines(mint)`; bila
  event membawa `pool_addresses`, ditambah `🌊 Meteora` + `🦅 HawkFi`
  (`_pool_link_lines`) — cron belum bisa mengisinya (watchlist tidak
  menyimpan pool address). `send_test_alert()` sengaja tanpa link. Aturan
  tidak pernah fetch: pemanggil menyuntikkan `market_context` atau
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
badge BEST POOL       : < 0.1% marketcap (DUST_BEST_PCT, aditif) + data
                        holder valid: total_fetched > 0 dan >= 40 wallet
                        (DUST_BEST_MIN_HOLDERS). == 0.1% bukan BEST POOL
                        dan bukan pemicu early_dump (strict < dan >).
                        Hanya dirender di listing Scan Meteora.
grafik / kohort       : bucket 4 jam (resample_4h; titik mentah per jam,
                        MAX_POINTS 336 = 14 hari x 24 titik)

Konfirmasi alert (setelah ambang dust di atas terpenuhi):
dump                  : volume 4 jam >= 2.0x avg_volume_7d DAN harga <= -1%
akumulasi             : volume 4 jam >= 1.5x avg_volume_7d DAN buy > sell
baseline shift +-1 pp : ikut arah perubahan (naik = dump, turun = akumulasi)
early dump (LP pool)  : crossing naik > 0.1% (dibanding nilai run
                        sebelumnya, marker alert_state["early_dump"]) —
                        TANPA gerbang volume (konteks = info), sekali per
                        bucket 4 jam + jeda 1 jam, hanya saat masih naik;
                        turun ke <= 0.1% = reset
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

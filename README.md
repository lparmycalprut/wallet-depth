# Wallet Depth — 3 Sinyal Bottom

Wallet Depth adalah dashboard Streamlit dan cron harian untuk mendeteksi
**bottom** token Solana (titik terendah sebelum pump) dengan membaca hubungan
**ΔCVD (order flow)** dan **volume antar-hari**, divalidasi empiris pada 8
token pump historis (hoppy, assface, grail, bountywork, ansem, chance,
testicle, punch).

```text
ΔCVD (SOL) = Σ(buy_quote_sol) − Σ(sell_quote_sol) dalam 1 hari
Volume     = buy + sell dalam USD (amount_usd) — SELALU USD, bukan SOL
Batas hari = 00:00 UTC (= 07:00 WIB, konvensi GMGN)
```

## Tiga sinyal (bias selalu bullish)

| Sinyal | CVD (vs flush) | Volume (vs H-1) | Arti |
|---|---|---|---|
| 🟢 SELLER_EXHAUSTION | runtuh (negatif kecil) | turun ≤ 40% | panic seller habis |
| 🟣 REVERSAL | runtuh (negatif kecil) | naik ≥ 130% | penjual habis + buyer mulai masuk |
| 🔵 AKUMULASI | positif ≥ +5 SOL | naik ≥ 130% | buyer masuk diam-diam |

Detail syarat persis:

- **SELLER_EXHAUSTION**: CVD(N) < 0, harga ≤ +0.5%, ada flush (min CVD 5 hari
  sebelumnya ≤ -30 SOL), |CVD(N)| ≤ 40% |flush|, volume ≤ 40% kemarin, dan
  volume ≤ 3× marketcap close (anti wash-trade, bila MC tersedia).
- **REVERSAL**: sama dengan SELLER_EXHAUSTION, kecuali volume **naik**
  ≥ 130% dari kemarin.
- **AKUMULASI**: CVD(N) ≥ +5 SOL, harga ≤ +0.5%, volume ≥ 130% kemarin.

Urutan cek: SELLER_EXHAUSTION → REVERSAL → AKUMULASI → "—". Seluruh window
dipindai per hari (bukan hanya hari terakhir); hari pertama selalu "—".

Threshold final ada di `effort_detector.py` dan tidak boleh diubah.

## On-chain tag (info saja, bukan syarat)

Per hari diagregasi 4 penanda dari tag maker GMGN
(`maker_tags`/`maker_token_tags`/`maker_event_tags`):

- `smart_money_buy` — buy bertag axiom/padre/bluechip_owner/trojan/top_holder/smart_degen/smart_money
- `fresh_buy` — buy bertag fresh_wallet
- `bot_sell` — sell bertag bundler/paper_hands
- `mev_noise` — tx bertag sandwich_bot

Flag tambahan: `whale_driven` (top-1 wallet ≥ 40% volume) dan
`flag_divergence` (arah CVD berlawanan harga) — keduanya informatif.

## Alur data

1. Cron berjalan setiap 00:00 UTC (fetch 4 hari terakhir per token watchlist).
2. Trade GMGN dinormalisasi (SOL untuk CVD, USD untuk volume); Helius menjadi
   fallback otomatis.
3. Candle hourly GeckoTerminal digabung ke candle harian market (UTC).
4. `daily_effort.json` di-upsert idempoten per mint/tanggal (window 30 hari).
5. Telegram hanya dikirim untuk 3 sinyal (bukan "—"), satu kali per baris:
   `⚡ BOTTOM TERDETEKSI — $SYMBOL` + sinyal + hari/flush + CVD/volume +
   link GMGN.
6. Dashboard menampilkan sinyal watchlist, chart harga/CVD + volume USD,
   tabel sinyal per hari, dan CSV + rekapan teks (`# <date>  <SIGNAL> | …`).

Screener Trending/Degen tetap tersedia sebagai **listing** tanpa skor atau
verdict. Sinyal baru muncul setelah token masuk watchlist dan data harian
tersedia.

## Menjalankan lokal

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
streamlit run app.py
```

Konfigurasi opsional: `helius_api_key`, `helius_extra_keys`,
`telegram_bot_token`, dan `telegram_chat_id`. Jangan commit `config.json`.

## Pengujian

```bash
python -m unittest discover tests
python -m py_compile effort_detector.py cvd_daily.py signals.py \
  scripts/update_cvd.py app.py pages/4_📊_CVD.py
```

Semua hasil adalah heuristik validasi historis, bukan jaminan atau saran
keuangan.

# AGENTS.md — Wallet Depth

Dashboard Streamlit berbahasa Indonesia untuk mendeteksi **bottom** token
Solana — titik terendah sebelum pump — lewat hubungan ΔCVD (order flow) dan
volume antar-hari. Ini adalah satu-satunya framework deteksi. Deteksi lama
(4-pilar, effort-to-result R = |CVD|/|ΔHarga%|, multiplier M, baseline sehat,
S1–S5, ABSORBSI LANGSUNG, PENYERAPAN, retention/diamond-hands) telah dihapus
dan tidak boleh dikembalikan.

## Sumber kebenaran

- `effort_detector.py`: threshold, klasifikasi 3 sinyal, persistence.
- `daily_effort.json`: maksimal 30 baris harian per mint (storage window,
  bukan sinyal retensi holder).
- `cvd.py`: fetch dan normalisasi trade (GMGN utama, Helius fallback);
  swap diperkaya `amount_usd` + tag maker. Jangan tambahkan verdict ke layer ini.
- `cvd_daily.py`: agregasi harian ΔCVD (SOL), volume USD, dan 4 penanda
  on-chain; batas hari market 00:00 UTC.
- `scripts/update_cvd.py`: cron harian 00:00 UTC + fetch manual halaman.
- `signals.py`: transport Telegram saja.
- `app.py`: watchlist dan listing GMGN tanpa ranking.
- `pages/4_📊_CVD.py`: chart harga/CVD + volume USD dengan scan seluruh window.

## Konsep

```text
ΔCVD (SOL) = Σ(buy_quote_sol) − Σ(sell_quote_sol) dalam 1 hari
Volume     = buy + sell dalam USD (amount_usd) — SELALU USD, bukan SOL
Batas hari = 00:00 UTC (= 07:00 WIB, konvensi GMGN)
```

Volume dibandingkan dalam USD karena saat token dump nilai SOL ikut menyusut
(rasio SOL ≠ USD); volume USD konsisten dan sesuai validasi manual pada
8 token pump historis (hoppy, assface, grail, bountywork, ansem, chance,
testicle, punch).

## Tiga sinyal (bias selalu bullish)

| Sinyal | CVD (vs flush) | Volume (vs H-1) |
|---|---|---|
| SELLER_EXHAUSTION | runtuh (negatif kecil) | turun ≤ 40% |
| REVERSAL | runtuh (negatif kecil) | naik ≥ 130% |
| AKUMULASI | positif ≥ +5 SOL | naik ≥ 130% |

Urutan pengecekan persis: SELLER_EXHAUSTION → REVERSAL → AKUMULASI → "—".

### Syarat persis

🟢 SELLER_EXHAUSTION (panic seller habis): `(idx>=1)` ∧ CVD(N) < 0 ∧
priceChgPct(N) ≤ +0.5% ∧ ada flush (min CVD 5 hari sebelum N ≤ -30 SOL) ∧
|CVD(N)| ≤ 0.40 × |flushCVD| ∧ volumeUSD(N) ≤ 0.40 × volumeUSD(N-1) ∧
volumeUSD(N) ≤ 3 × marketcap_close(N) (anti wash — hanya bila MC tersedia).

🟣 REVERSAL (penjual habis + buyer mulai masuk): sama dengan
SELLER_EXHAUSTION, kecuali syarat volume: volumeUSD(N) ≥ 1.30 ×
volumeUSD(N-1).

🔵 AKUMULASI (buyer masuk diam-diam): `(idx>=1)` ∧ CVD(N) ≥ +5 SOL ∧
priceChgPct(N) ≤ +0.5% ∧ volumeUSD(N) ≥ 1.30 × volumeUSD(N-1).

### Threshold final (jangan diubah)

```python
SELLING_FLUSH_CVD = 30.0            # flush = CVD <= -30 SOL
SELLING_COLLAPSE_RATIO = 0.40
SELLING_LOOKBACK_DAYS = 5
SELLING_PRICE_CAP_PCT = 0.5
SELLING_VOLUME_SHRINK_RATIO = 0.40
REVERSAL_VOLUME_SURGE_RATIO = 1.30
ACCUM_CVD_MIN = 5.0
ACCUM_PRICE_CAP_PCT = 0.5
ACCUM_VOLUME_SURGE_RATIO = 1.30
WHALE_PCT_THRESHOLD = 40.0          # top-1 wallet >= 40% volume (flag)
VOLUME_MC_MAX_RATIO = 3.0           # anti wash-trade (bila MC tersedia)
```

`classify_all` memindai SELURUH window — tiap hari (idx ≥ 1) dievaluasi,
hari pertama = "—". `classify_effort` = verdict hari terakhir.

## On-chain tag (info, BUKAN syarat sinyal)

Per trade ditangkap `maker_tags` / `maker_token_tags` / `maker_event_tags`,
diagregasi per hari menjadi:

- `smart_money_buy`: buy dengan tag axiom, padre, bluechip_owner, trojan,
  top_holder, smart_degen, smart_money
- `fresh_buy`: buy dengan tag fresh_wallet
- `bot_sell`: sell dengan tag bundler, paper_hands
- `mev_noise`: tx dengan tag sandwich_bot

Keempatnya ikut ke CSV/export, recap dashboard, dan output detector.

## Output & alert

- Rekapan per hari (blok komentar `#` di CSV/dashboard):
  `# <date>  <SIGNAL> | Δ<+%>% | CVD <+x> | vol <y>% dari kemarin`.
- Telegram HANYA untuk 3 sinyal (bukan "—"), format konsisten:
  `⚡ BOTTOM TERDETEKSI — $SYMBOL` + emoji sinyal (🟢/🟣/🔵) + hari/flush +
  `CVD: X SOL | Volume: Y% dari kemarin` + link GMGN.
- Alert hanya untuk baris (mint, date) yang belum pernah tersimpan.

## Aturan perubahan

- Batas hari selalu market day 00:00–23:59 UTC. Jangan kembalikan WIB.
- Threshold § di atas tidak boleh diubah.
- Jangan kembalikan deteksi lama (R/M/baseline/S1–S5/absorpsi/langsung,
  retention/diamond-hands/holder lock/smart buyer).
- Volume antar-hari selalu USD (`amount_usd`), jangan SOL.
- Perbandingan volume butuh hari N-1; tanpa data USD → "—".
- Pertahankan fetch layer (Helius/GMGN/DexScreener); pin `streamlit==1.61.1`.
- Kode/docstring Inggris; UI dan komunikasi pemilik Indonesia.
- Jalankan `python -m unittest discover tests` dan `python -m py_compile ...`.
- Setelah perubahan perilaku, perbarui `docs/PROGRESS.md`.

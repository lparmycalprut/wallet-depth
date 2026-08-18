# AGENTS.md — Wallet Depth

Dashboard dan scanner token Solana dari GMGN. Sistem notifikasi utama adalah
**bidirectional realtime reversal** berbasis wash-collapse.

## Sumber kebenaran

- `reversal_engine.py`: port Python engine SMART SEROK; normalisasi trade,
  FIFO wash matcher 60 detik, clean CVD, daily/rolling aggregation, dan deteksi
  dua arah.
- `scripts/realtime_reversal.py`: fetch raw GMGN, cache incremental 31 jam,
  rolling window 6 jam vs 24 jam sebelumnya, guard, state, dan Telegram.
- `reversal_state.py`: konfirmasi 2 scan, transition-only alert, cooldown 18 jam,
  plus gate struktur (alert hanya saat `structure_state == confirmed`).
- `price_structure.py`: candle 5m dari stream trade, deteksi zona SBR dominan,
  klasifikasi higher-low/spring/breakdown, dan reclaim-by-close. Sumber gate
  struktur untuk alert Telegram; dikalibrasi pada kasus DREGG (18 Agu 2026).
- `last_scan_result.json`: state scanner (dipersist lewat Actions cache).
- `reversal_status.json`: snapshot publik untuk dashboard; scanner
  mem-publish ke ref `reversal-live` setiap scan supaya halaman utama
  Streamlit bisa menarik status tanpa menunggu redeploy `main`.
- `.github/workflows/daily-effort.yml`: scan setiap 10 menit.
- `content.js` di handoff SMART SEROK adalah referensi parity awal.

Dashboard historis masih memakai `effort_detector.py`, `daily_effort.json`, dan
`pages/4_📊_CVD.py`; jangan gunakan sinyal dashboard lama sebagai gate bagi
scanner realtime. Watchlist di `app.py` membaca `load_reversal_status()`,
bukan `classify_effort()`.

## Konsep realtime

```text
current  = 6 jam terakhir
baseline = 6–30 jam sebelum sekarang
washPct  = volume SOL yang terhapus sebagai MEV/round-trip / volume SOL

REVERSAL_UP:
  wash sekarang <= 6% dan <= 50% wash baseline
  + clean CVD sekarang positif
  + baseline punya flush (clean CVD <= -10 SOL atau harga <= -15%)

REVERSAL_DOWN:
  wash sekarang <= 6% dan <= 50% wash baseline
  + clean CVD sekarang negatif
  + baseline punya pump (clean CVD >= +10 SOL atau harga >= +15%)
```

Wash matcher memasangkan buy/sell berlawanan milik wallet yang sama secara FIFO
dalam 60 detik. Trade bertag `sandwich_bot`, `mev_bot`, atau `mev` dibuang penuh
dari clean CVD. `quote_amount` yang menghasilkan implied SOL price di luar
$10–$500 wajib diturunkan ulang sebagai `amount_usd / 160` agar parity dengan
SMART SEROK terjaga.

## Alert dan state

- Hanya `REVERSAL_UP` dan `REVERSAL_DOWN` yang dapat memicu Telegram; alert
  harian "BOTTOM TERDETEKSI" (SELLER_EXHAUSTION/REVERSAL/AKUMULASI) sudah
  dipensiunkan — pipeline harian hanya untuk dashboard.
- Kandidat harus muncul pada 2 scan beruntun.
- Alert hanya pada transisi ke state `*_FIRED`, dan hanya bila verdict
  struktur `confirmed` (zona SBR ter-reclaim by close dan bertahan). Sinyal
  flow yang belum terkonfirmasi struktur parkir di state `WATCH` — tampil di
  dashboard, tidak pernah alert.
- Cooldown default 18 jam; pengamatan berulang tidak mengirim spam.
- Token mati ditolak dengan minimum 20 tx dan 1 SOL pada current window.
- Guard umur 24 jam dan minimum liquidity diterapkan bila metadata tersedia.
- Confidence `strong` (🟢 KUAT) butuh clean CVD >= +5 SOL (UP) atau <= -5 SOL
  (DOWN) **dan** wash sekarang <= 3%; selain itu `watch` (🟡). Alert WATCH
  mencantumkan syarat yang masih kurang.
- Baris wallet alert memakai `format_wallet_lines()`: jumlah maker, smart money
  (count + net SOL), fresh wallet (count + SOL), bot-sell, lalu konsentrasi
  whale top-1/top-3, net SOL, dan churn round-trip top-1.
  `top_wallet_pct` adalah share volume buy+sell wallet terbesar, bukan holding.

## Validasi

Ground truth SISYPUSS (`sisypuss_raw.json` dari handoff): baseline 08-16 adalah
flush sekitar -22 SOL dengan wash 15.2%; current 08-17 harus menghasilkan
`REVERSAL_UP`, clean CVD sekitar +11.8 SOL dan wash sekitar 3.0%.

Jalankan:

```bash
python -m unittest discover tests
python -m py_compile reversal_engine.py reversal_state.py scripts/realtime_reversal.py
python scripts/realtime_reversal.py --fixture /path/sisypuss_raw.json \
  --mint 8HykgZKXNpMhfxQtDPb7AayRKJonZaQ8Mw1Xo3xmpump --no-alert
```

Kode/docstring Inggris; UI dan komunikasi pemilik Indonesia. Jangan commit raw
trade cache atau fixture besar.

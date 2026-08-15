# AGENTS.md — Wallet Depth

Dashboard Streamlit berbahasa Indonesia untuk mengukur **Efisiensi Anomali
(Effort vs Result)** token Solana. Ini adalah satu-satunya framework deteksi.

## Sumber kebenaran

- `effort_detector.py`: formula R, multiplier, klasifikasi S1–S5, persistence.
- `daily_effort.json`: maksimal 30 baris harian per mint.
- `cvd.py`: fetch dan normalisasi trade; jangan tambahkan verdict ke layer ini.
- `cvd_daily.py`: agregasi ΔCVD berdasarkan hari WIB.
- `scripts/update_cvd.py`: cron harian 00:00 WIB.
- `signals.py`: transport Telegram saja.
- `app.py`: watchlist dan listing GMGN tanpa ranking.
- `pages/4_📊_CVD.py`: chart harga vs CVD dan ratio tujuh hari.

## Formula tetap

`ΔPrice% = (close-open)/open*100`, `R = |ΔCVD|/|ΔPrice%|`, dan
`M = R_N/R_N-1`. Sinyal membutuhkan dua tanggal berturut-turut. Candle dengan
`|ΔPrice%| < 3%` selalu S5. Ambang M tetap 2,0 dan 0,5.

- Down, M ≥ 2: S1_PENYERAPAN (bullish)
- Down, M ≤ 0,5: S2_DUMP_DISTRIBUSI (bearish)
- Up, M ≥ 2: S3_DISTRIBUSI_KE_KUAT (bearish)
- Up, M ≤ 0,5: S4_PUMP_ASLI (bullish)
- Lainnya: S5_NETRAL

Flag divergensi hanya informasi dan tidak mengubah sinyal. Alert hanya S1–S4.

## Aturan perubahan

- Batas hari selalu Asia/Jakarta 00:00–23:59.
- Jangan menambah scoring, indikator wallet, atau threshold lain.
- Pertahankan fetch layer dan manajemen watchlist jika tidak diperlukan.
- Kode/docstring Inggris; UI dan komunikasi pemilik Indonesia.
- Jalankan `python -m unittest discover tests` dan `python -m py_compile ...`.
- Setelah perubahan perilaku, perbarui `docs/PROGRESS.md`.

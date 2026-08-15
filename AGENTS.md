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
`|ΔPrice%| < 3%` selalu S5.

Ambang M tetap 2,0 dan 0,5. Konstanta baseline tambahan:
- `MIN_BASELINE_RATIO = 0.05` (SOL/1%)
- `MIN_BASELINE_CVD_SOL = 1.0` (SOL)

Baseline dianggap stabil hanya jika:
1. Dua hari berturut-turut tersedia.
2. Ratio hari N-1 tersedia, finite, dan positif.
3. `abs(price_chg_pct hari N-1) >= 3.0`.
4. `abs(cvd_delta hari N-1) >= 1.0` SOL.
5. `ratio hari N-1 >= 0.05` SOL/1%.
6. Direction hari N sama dengan direction hari N-1 (untuk S1–S4).

Jika syarat 2–5 gagal: `baseline_status = "unstable"`, `signal = "insufficient_data"`.
Jika syarat 6 gagal: `baseline_status = "incompatible_direction"`, `signal = "insufficient_data"`.
S1–S4 hanya valid jika `baseline_status == "stable"`.

- Down, M ≥ 2 (baseline stabil): S1_PENYERAPAN (bullish)
- Down, M ≤ 0,5 (baseline stabil): S2_DUMP_DISTRIBUSI (bearish)
- Up, M ≥ 2 (baseline stabil): S3_DISTRIBUSI_KE_KUAT (bearish)
- Up, M ≤ 0,5 (baseline stabil): S4_PUMP_ASLI (bullish)
- Lainnya (atau baseline ditolak): S5_NETRAL / insufficient_data

Flag divergensi hanya informasi dan tidak mengubah sinyal. Alert hanya S1–S4.

## Aturan perubahan

- Batas hari selalu Asia/Jakarta 00:00–23:59.
- Jangan menambah scoring, indikator wallet, atau threshold lain.
- Pertahankan fetch layer dan manajemen watchlist jika tidak diperlukan.
- Kode/docstring Inggris; UI dan komunikasi pemilik Indonesia.
- Jalankan `python -m unittest discover tests` dan `python -m py_compile ...`.
- Setelah perubahan perilaku, perbarui `docs/PROGRESS.md`.

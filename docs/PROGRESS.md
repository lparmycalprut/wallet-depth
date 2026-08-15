# Progress

## 2026-08-15 — Overhaul Efisiensi Anomali

- Mengganti seluruh logika deteksi dengan R = |ΔCVD| / |ΔHarga%| per hari WIB.
- Menambahkan `effort_detector.py`, persistence idempoten 30 hari, dan S1–S5.
- Menulis ulang cron menjadi sekali sehari pukul 00:00 WIB.
- Menulis ulang Telegram sehingga hanya S1–S4 yang dikirim.
- Mengubah dashboard menjadi watchlist effort dan listing GMGN tanpa ranking.
- Menambahkan chart harga/CVD dual-axis dan chart ratio tujuh hari.
- Memangkas layer CVD menjadi fetch/normalisasi trade yang dibutuhkan saja.
- Menghapus state, detector, workflow, dokumentasi, dan test generasi lama.
- Menambahkan unit test formula, boundary, insufficient data, WIB, persistence,
  join candle/CVD, dan format Telegram.

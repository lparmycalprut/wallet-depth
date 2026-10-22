# Early Watcher

Permintaan user 2026-10-22. Page `⚡ Early Watcher` dan alert Telegram untuk pola awal arbitrase di 5 mint watchlist. Info saja. Tidak mengubah verdict, skor, `eligible`, atau filter Sweep.

## Standar

| Komponen | Nilai | Keterangan |
|---|---|---|
| Putaran (round trip) | satu wallet, satu tx, dua kaki di quote berbeda | selisih harga 2%–50%; kaki ≥ $0,10 |
| Aktif | ≥ 4 putaran dari ≥ 3 wallet dalam 60 detik | diturunkan dari 5 (2026-10-22) |
| Jual besar sebelum aktif | satu jual ≥ **$1.000** (usulan), bukan kaki putaran, dalam **10 menit** sebelum awal (naik dari 5, 2026-10-22) | dari COCK 22:42:32 WIB: ≈$1,43K, ≈6,6 juta token |
| Awal | aktif setelah ≥ 10 menit tanpa aktivitas | alert hanya pada transisi |
| Cooldown | 30 menit | |
| Poll | tiap 120 detik, lookback 180 detik, maks 7 halaman | `partial` bila terpotong |

Aktivitas tanpa jual besar tetap tercatat sebagai `AKTIF (tanpa dump)`, tanpa alert.

Field jumlah token di GMGN adalah `base_amount`. Jumlah USD adalah `amount_usd`.

## Komponen

- `early_watch.py`: logika murni. `round_trips`, `window_stats`, `big_sells`, `find_dump`, `evaluate_mint`, `run_poll`, `decision_fingerprint`, `format_alert`, `fetch_window`.
- `scripts/early_watch.py`: runner. `--duration 1500 --interval 120`. Baris terakhir `EARLY_WATCH_CHANGED=0|1`. `--no-alerts` untuk uji lokal.
- `.github/workflows/early-watch.yml`: cron `*/30`, grup concurrency `early-watch` (tidak dibatalkan), commit hanya bila fingerprint berubah lewat `scripts/commit_early_state.sh`.
- `early_ui.py`, `pages/10_⚡_Early_Watcher.py`: halaman read-only dari `early_watch_state.json`.
- `early_watch_watchlist.json`: 5 mint. Semua dipantau, termasuk yang di-mute atau tersembunyi di Sweep.

## Batasan yang diketahui

1. **Celah antar job.** Cron 30 menit dengan job ~25 menit menyisakan ~5 menit tanpa poll. Trade di celah itu tidak pernah diambil, termasuk jual besar. Perbaikan yang mungkin: lookback dinamis dari `updated` terakhir, atau job 29 menit.
2. **Frekuensi.** Workflow hanya jalan dari default branch, jadi aktif setelah merge ke `main`. Cron GitHub minimal 5 menit dan sering terlambat, sehingga loop 2 menit ada di dalam job.
3. **Deteksi terlambat.** Pada COCK 22:42:46, standar ini baru menghasilkan `AWAL AKTIF` sekitar 22:43:01, sekitar 15 detik setelah lonjakan. Harga sudah ~3x. Ini konfirmasi, bukan sinyal paling awal.
4. **Jual besar dari wallet yang sama dengan putaran.** Kaki jual putaran bot dikecualikan. Jual besar dari wallet yang juga berputar pada tx lain tetap dihitung.

## Konfirmasi yang belum ada

- `DUMP_MIN_USD = 1000` adalah usulan. `DUMP_LOOKBACK_SEC` dinaikkan dari 300 ke 600 dan `ACTIVE_MIN_TRADES` diturunkan dari 5 ke 4 (2026-10-22, permintaan user) agar klaster 5ubru 21:25 dan dump F78f 21:16 masuk kriteria. Angka mentah sebaiknya ditinjau user.
- `MIN_LEG_USD = 0.10` dan `ROUND_TRIP_MAX_SPREAD = 0.50` juga usulan (membuang artefak dust).
- Izin PR dan merge belum diminta.

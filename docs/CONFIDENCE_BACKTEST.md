# Backtest Confidence 🟢 KUAT (strong)

Jalankan: `python3 scripts/backtest_confidence.py`

## Kriteria strong (dari `reversal_engine.detect_reversal`)

Sinyal harus lolos semua gerbang REVERSAL dulu:

| Gerbang | Ambang |
| --- | --- |
| `tx_count` | ≥ 20 |
| `vol_sol` | ≥ 1 SOL |
| wash-collapse | `wash_now` ≤ 6% **dan** ≤ 50% wash konteks |
| konteks (UP) | CVD bersih prior ≤ −10 SOL **atau** harga prior ≤ −15% |
| arah | CVD bersih sekarang > 0 (UP) / < 0 (DOWN) |

Baru setelah itu upgrade `watch` → `strong` butuh **dua-duanya**:

- **|CVD bersih| ≥ 5 SOL** (`+5` untuk UP, `−5` untuk DOWN)
- **wash sekarang ≤ 3%**

Batasnya inklusif: tepat `+5.0` SOL dan `3.0%` sudah dihitung strong
(diuji di `tests/test_backtest_confidence.py`).
`ACCUMULATION`/`DISTRIBUTION` di-hardcode `watch` — tidak pernah bisa hijau.

## Hasil terhadap data historis di repo (`daily_effort.json`)

```
Baris/mint      : 92 baris · 25 token
Sinyal REVERSAL : 0
Confidence STRONG (🟢 KUAT) : 0
Gate penghalang : tanpa field wash_pct (data harian lama) — 92/92
Baris |CVD| >= 5 SOL : 78/92
```

**Kesimpulan: strong belum pernah muncul di data yang tersimpan — dan secara
struktural memang belum bisa.** `daily_effort.json` ditulis oleh pipeline lama
(`scripts/update_cvd.py`) yang hanya menyimpan `cvd_delta` mentah; kolom
`wash_pct` dan `cvd_delta_clean` tidak ada, padahal keduanya wajib untuk
mendeteksi wash-collapse. Jadi 0 strong di sini **bukan** bukti ambangnya
terlalu ketat.

Sinyal magnitudonya sendiri sebenarnya banyak: 78 dari 92 baris punya
|CVD| ≥ 5 SOL, jadi begitu wash tercatat, syarat CVD bukan penghalang utama —
yang menentukan justru gerbang `wash ≤ 3%`.

Riwayat nyata untuk scanner realtime ada di `last_scan_result.json` (state
per-token) dan cache `.cache/reversal_trades.json.gz`, keduanya masih kosong
di checkout ini, sehingga belum ada sampel live yang bisa diukur.

## Cara mengumpulkan bukti strong ke depan

1. Biarkan `scripts/realtime_reversal.py` berjalan terjadwal; tiap scan menulis
   `result.current` lengkap (termasuk `wash_pct`, `cvd_delta_clean`, dan metrik
   wallet baru) ke `last_scan_result.json`.
2. Setelah beberapa hari, hitung distribusi confidence dari state tersebut untuk
   menilai apakah ambang `5 SOL / 3%` perlu dikalibrasi.

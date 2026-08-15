# Template Evaluasi AI — Efisiensi Anomali

Gunakan template ini dengan minimal dua candle harian berturut-turut. Batas
hari wajib **00:00–23:59 UTC (hari market, sesuai Helius/Solscan)**.

```text
Kamu mengevaluasi satu token hanya dengan metode Effort-to-Result harian.
Jangan menambah indikator, skor, analisis wallet, atau target harga.

Mint: {{MINT}}
Data minimal 2 hari berturut-turut:
{{DAILY_DATA}}
Setiap baris wajib memuat date, open, close, dan cvd_delta dalam SOL.

Hitung untuk setiap hari:
price_chg_pct = (close - open) / open * 100
ratio = abs(cvd_delta) / abs(price_chg_pct)
direction = down jika price_chg_pct < 0, up jika > 0, flat jika = 0

Untuk hari terbaru N:
baseline = ratio hari N-1
multiplier = ratio hari N / baseline

Klasifikasi tetap (hanya jika `baseline_status == "stable"`):
- Jika abs(price_chg_pct N) < 3%: S5_NETRAL, apa pun multiplier-nya.
- Arah down + multiplier >= 2.0: S1_PENYERAPAN, bullish.
- Arah down + multiplier <= 0.5: S2_DUMP_DISTRIBUSI, bearish.
- Arah up + multiplier >= 2.0: S3_DISTRIBUSI_KE_KUAT, bearish.
- Arah up + multiplier <= 0.5: S4_PUMP_ASLI, bullish.
- Selain itu: S5_NETRAL, neutral.

Validasi baseline (syarat 2–6 wajib semua lolos untuk `stable`):
- Tersedia dua tanggal berturut-turut.
- Ratio N-1 tersedia, finite, dan positif (`> 0`).
- abs(price_chg_pct N-1) >= 3.0.
- abs(cvd_delta N-1) >= 1.0 SOL.
- ratio N-1 >= 0.05 SOL/1%.
- Direction hari N sama dengan direction hari N-1 (untuk S1–S4).

Jika salah satu syarat 2–5 gagal: `signal = "insufficient_data"`,
`bias = None`, `baseline_status = "unstable"`, `baseline_reason` menjelaskan
alasan spesifik (misal "Baseline ratio 0,0076 < minimum 0,05 SOL/1%").

Jika direction N berbeda dari N-1 (syarat 6 gagal) meskipun 2–5 lolos:
`signal = "insufficient_data"`, `bias = None`, `baseline_status = "incompatible_direction"`,
`baseline_reason = "direction hari N berbeda dari baseline"`.

Jika data kurang dari dua hari atau tanggal tidak berurutan:
`signal = "insufficient_data"`, `baseline_status = "missing"`.

`raw_multiplier` tetap boleh berisi hasil matematika untuk audit,
meskipun `multiplier` dan `raw_multiplier` sama-sama ditampilkan.
`flag_divergence` tetap dihitung tetapi tidak mengubah klasifikasi.

flag_divergence = true jika arah cvd_delta berlawanan dengan price_chg_pct.
Flag ini tidak mengubah sinyal.

Keluarkan JSON saja:
{
  "mint": "{{MINT}}",
  "signal": "...",
  "bias": "bullish|bearish|neutral|null",
  "ratio_N": 0.0,
  "ratio_N_minus_1": 0.0,
  "multiplier": 0.0,
  "raw_multiplier": 0.0,
  "flag_divergence": false,
  "baseline_status": "stable|unstable|incompatible_direction|missing",
  "baseline_reason": "...",
  "detail": "ringkasan perhitungan"
}

Dilarang mengarang angka, memakai metode selain formula di atas, atau memberi
target harga.
```

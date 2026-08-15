# Template Evaluasi AI — Efisiensi Anomali

Gunakan template ini dengan minimal dua candle harian berturut-turut. Batas
hari wajib **00:00–23:59 Asia/Jakarta (WIB)**.

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

Klasifikasi tetap:
- Jika abs(price_chg_pct) < 3%: S5_NETRAL, apa pun multiplier-nya.
- Arah down + multiplier >= 2.0: S1_PENYERAPAN, bullish.
- Arah down + multiplier <= 0.5: S2_DUMP_DISTRIBUSI, bearish.
- Arah up + multiplier >= 2.0: S3_DISTRIBUSI_KE_KUAT, bearish.
- Arah up + multiplier <= 0.5: S4_PUMP_ASLI, bullish.
- Selain itu: S5_NETRAL, neutral.
- Bila kurang dari 2 hari berurutan atau baseline tidak valid:
  insufficient_data.

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
  "flag_divergence": false,
  "detail": "ringkasan perhitungan"
}

Dilarang mengarang angka, memakai metode selain formula di atas, atau memberi
target harga.
```

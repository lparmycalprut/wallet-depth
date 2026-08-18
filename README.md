# Wallet Depth — Realtime Reversal Solana

Wallet Depth memantau token Solana dari GMGN dan mendeteksi reversal dua arah
melalui kombinasi **wash-collapse**, **clean CVD**, dan konteks sebelumnya.

## Sinyal realtime

- 🟢 **REVERSAL_UP**: churn bot runtuh, clean CVD berubah positif, dan window
  sebelumnya menunjukkan flush.
- 🔴 **REVERSAL_DOWN**: churn bot runtuh, clean CVD berubah negatif, dan window
  sebelumnya menunjukkan pump.
- 🔵 **ACCUMULATION** / 🟠 **DISTRIBUTION**: setup untuk dipantau; tidak memicu
  alert reversal.
- ⚪ **NEUTRAL**: bukti belum lengkap atau aktivitas terlalu tipis.

Scanner memakai rolling window 6 jam terkini dibanding 24 jam sebelumnya dan
dijalankan tiap 10 menit lewat GitHub Actions. Kandidat wajib terkonfirmasi dua
scan berturut-turut. Telegram hanya dikirim saat transisi ke reversal, lalu
cooldown 18 jam mencegah spam.

## Engine

`reversal_engine.py` merupakan port Python dari engine ekstensi SMART SEROK:

1. Normalisasi field GMGN dan re-derive SOL sebagai `amount_usd / 160` bila
   implied SOL/USD tidak masuk akal.
2. Pasangkan buy/sell wallet yang sama secara FIFO dalam 60 detik.
3. Buang round-trip serta MEV dari CVD untuk memperoleh clean CVD.
4. Hitung wash volume dan wash percentage.
5. Klasifikasikan reversal bullish maupun bearish secara simetris.

Threshold realtime awal:

```text
wash floor       <= 6%
collapse ratio   <= 50% baseline
prior context    |clean CVD| >= 10 SOL atau |harga| >= 15%
current activity >= 20 tx dan >= 1 SOL
minimum liquidity >= $5.000 (bila metadata tersedia)
```

## Menjalankan scanner

```bash
pip install -r requirements.txt
python scripts/realtime_reversal.py --no-alert
```

Secrets Telegram:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

Cache trade incremental 31 jam disimpan terkompresi di
`.cache/reversal_trades.json.gz` dan tidak masuk Git. State transisi disimpan di
`last_scan_result.json`; GitHub Actions memulihkan keduanya melalui cache.

### Validasi ground truth SISYPUSS

```bash
python scripts/realtime_reversal.py \
  --fixture /path/to/sisypuss_raw.json \
  --mint 8HykgZKXNpMhfxQtDPb7AayRKJonZaQ8Mw1Xo3xmpump \
  --no-alert
```

Hasil yang diharapkan: `REVERSAL_UP`; data daily parity menghasilkan flush
08-16 sekitar −22 SOL / wash 15.2% dan reversal 08-17 clean CVD sekitar +11.8
SOL / wash 3.0%.

## Dashboard

Halaman utama (`app.py`) menampilkan status scanner realtime per token
watchlist (sinyal, CVD bersih, wash, wallet, waktu scan). Snapshot dibaca
dari `reversal_status.json` (dipublish setiap scan ke ref `reversal-live`).

Halaman CVD dan `daily_effort.json` tetap tersedia untuk inspeksi historis
3 sinyal bottom. Jalankan:

```bash
streamlit run app.py
```

## Pengujian

```bash
python -m unittest discover tests
python -m py_compile reversal_engine.py reversal_state.py \
  scripts/realtime_reversal.py
```

Deteksi bersifat heuristik dan bukan saran keuangan.

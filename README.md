# Wallet Depth — Efisiensi Anomali

Wallet Depth adalah dashboard Streamlit dan cron harian untuk membandingkan
**effort** order flow (ΔCVD dalam SOL) dengan **result** pergerakan harga.
Sistem hanya memakai satu metrik:

```text
ΔHarga% = (close - open) / open × 100
R       = |ΔCVD| / |ΔHarga%|        # SOL per 1% gerak
M       = R hari N / R hari N-1
```

Hari menggunakan kalender Asia/Jakarta (WIB). Dua hari berturut-turut wajib
tersedia. Pergerakan di bawah 3% selalu netral.

| Kondisi hari N | Sinyal | Bias |
|---|---|---|
| Harga turun, M ≥ 2 | S1_PENYERAPAN | Bullish |
| Harga turun, M ≤ 0,5 | S2_DUMP_DISTRIBUSI | Bearish |
| Harga naik, M ≥ 2 | S3_DISTRIBUSI_KE_KUAT | Bearish |
| Harga naik, M ≤ 0,5 | S4_PUMP_ASLI | Bullish |
| 0,5 < M < 2 atau gerak <3% | S5_NETRAL | Netral |

Flag divergensi muncul bila ΔCVD dan harga berlawanan arah, tetapi tidak
mengubah klasifikasi. Semua hasil adalah heuristik, bukan jaminan atau saran
keuangan.

## Alur data

1. Cron berjalan pukul 00:00 WIB (`17:00 UTC`).
2. Trade GMGN dinormalisasi ke SOL; Helius menjadi fallback.
3. Candle hourly GeckoTerminal digabung ke candle harian WIB.
4. `daily_effort.json` di-upsert per mint/tanggal dan menyimpan 30 hari.
5. Telegram hanya dikirim untuk S1–S4.
6. Dashboard menampilkan status watchlist dan chart tujuh hari.

Screener Trending/Degen tetap tersedia sebagai **listing**. Ia tidak memberi
skor atau verdict. Sinyal baru muncul setelah token masuk watchlist dan data
harian tersedia.

## Menjalankan lokal

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
streamlit run app.py
```

Konfigurasi opsional: `helius_api_key`, `helius_extra_keys`,
`telegram_bot_token`, dan `telegram_chat_id`. Jangan commit `config.json`.

## Pengujian

```bash
python -m unittest discover tests
python -m py_compile effort_detector.py cvd_daily.py signals.py \
  scripts/update_cvd.py app.py pages/4_📊_CVD.py
```

Template evaluasi manual tersedia di `PROMPT_EFFORT_ANOMALI.md`.

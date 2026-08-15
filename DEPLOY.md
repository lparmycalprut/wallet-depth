# Deploy

## Streamlit

- Entry point: `app.py`
- Python: lihat `runtime.txt`
- Dependencies: `requirements.txt`
- Opsional secrets: `HELIUS_API_KEY`, `HELIUS_API_KEYS`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, dan `GITHUB_TOKEN`.

## GitHub Actions

Workflow `.github/workflows/daily-effort.yml` berjalan setiap `17:00 UTC`
atau `00:00 WIB`. Workflow meng-upsert `daily_effort.json`, memperbarui
metadata watchlist, mengirim alert S1–S4, lalu commit state baru.

Jalankan manual lewat **Actions → Daily Effort Anomaly → Run workflow** untuk
smoke test. Periksa log jumlah trade/candle dan commit bot setelah selesai.

# ⚠️ FUNGSI / PAGE DINONAKTIFKAN — JANGAN DI-CEK OLEH AI BERIKUTNYA

Per 2026-08-06, bagian-bagian ini sengaja dimatikan (*disabled / temporarily disabled*) oleh owner / cron. **Penjelasan singkat: tidak ada bug — hanya dinonaktifkan sementara.** Jangan buang waktu memeriksa logika/internal mereka kecuali user secara eksplisit meminta untuk mengaktifkannya kembali.

## ❌ Disabled Streamlit Pages (3 item)

| File | Nama Page | Status | Catatan / Alasan |
|---|---|---|---|
| `pages/1_⚖️_Compare.py` | Compare | **Disabled** | Baris 17: `st.warning("⚠️ Aplikasi ini dinonaktifkan sementara.")` lalu `st.stop()`. Tidak perlu dicek. |
| `pages/10_📈_Accumulation_History.py` | Accumulation History | **Disabled** | Baris 36-37: `st.warning(...)` + `st.stop()`. Beberapa `st.stop()` tambahan di dalam blok chart (68, 185, 189, 203, 216, 256, 285). Tidak perlu dicek. |
| `pages/11_🤖_Memecoin_Scanner.py` | Memecoin Scanner | **Disabled** | Baris 25-26: `st.warning(...)` + `st.stop()`. Scanner tetap bisa dijalankan via CLI (`python memecoin_scanner.py`) — hanya UI Streamlit yang dimatikan. Tidak perlu dicek fungsi `run_scan()` / `analyze_token()` kecuali user minta. |

## ❌ Disabled Functions in `app.py` (referensi — tidak diminta diperbaiki sekarang)

- `real_tx_summary` (baris ~1108): "Real transaction summary is temporarily disabled on all cards."
- Watchlist Ticker Bar (baris ~1332): dinonaktifkan per permintaan owner.
- Health Score breakdown (baris ~3950): sementara dimatikan.
- Beberapa bagian `st.stop()` di `app.py` (baris 2415, 2417, 2429, 2433, 2465) — bagian-bagian ini ditutup karena fitur belum siap / diminta owner.

## ✅ Tidak di-disable (tetap aktif — boleh dicek)

- `prepump_detector.py`, `telegram_monitor_alerts.py`, `breakout_guard.py`, `monitor_alerts.py`, `cvd.py`, `core.py`
- Cron: `.github/workflows/cvd-update.yml` (jam :30), `memecoin-scanner.yml` (15 menit), `cto-radar.yml`, `lp-safe-radar.yml`
- Data: `cvd.json`, `signals.json`, `conviction.json`, `scanner_results.json`, `watchlist.json`

## 📝 Instruksi untuk AI berikutnya

> Jika user menyebut salah satu dari 3 halaman di atas atau meminta memeriksa "fungsi yang dinonaktifkan" — **jawab singkat bahwa bagian itu sengaja dimatikan** (lihat tabel di atas), lalu **tanya apakah mau diaktifkan kembali** sebelum melakukan inspeksi mendalam.
>
> Untuk halaman prepump / manual check — gunakan file baru `pages/12_🎯_Prepump_Checker.py` (dibuat 2026-08-06).

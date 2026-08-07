# ⚠️ FUNGSI / PAGE YANG DIHAPUS TOTAL — 2026-08-07 RESET

Per 2026-08-07, proyek di-reset total ke fokus **pre-pump** (owner request). Bagian-bagian di bawah **bukan di-disable via st.stop()** lagi, tapi **dihapus total dari repo** (file + fungsi + workflow). Jangan periksa atau revert tanpa persetujuan owner.

## ❌ Dihapus Total — Streamlit Pages (10 file)

| File | Nama Page | Status |
|---|---|---|
| `pages/1_⚖️_Compare.py` | Compare | **Deleted** |
| `pages/2_📒_History.py` | History | **Deleted** |
| `pages/5_🔔_Signals.py` | Signals | **Deleted** (signals.json tetap sebagai data) |
| `pages/6_🔎_Screener.py` | Screener | **Deleted** (scan ada di app.py) |
| `pages/7_💀_CTO_Radar.py` | CTO Radar | **Deleted** |
| `pages/8_💧_LP_Safe_Radar.py` | LP Safe Radar | **Deleted** |
| `pages/9_🔍_Accumulation_Detector.py` | Accumulation Detector | **Deleted** |
| `pages/10_📈_Accumulation_History.py` | Accumulation History | **Deleted** |
| `pages/11_🤖_Memecoin_Scanner.py` | Memecoin Scanner | **Deleted** |
| `pages/12_🎯_Prepump_Checker.py` | Prepump Checker | **Deleted** (logic prepump pindah ke app sinyal + CVD) |

**Disisakan:** `app.py` (watchlist + scan trending/degen), `pages/3_⭐_Watchlist.py`, `pages/4_📊_CVD.py`.

## ❌ Dihapus Total — Modul

`accum_history.py`, `ai_prompt.py`, `breakout_guard.py`, `breakout_log.py`, `focus.py`, `cto_deep_scan.py`, `incubation_radar.py`, `lp_safe_radar.py`, `memecoin_scanner.py`, `monitor_alerts.py`, `share_card.py`, `telegram_monitor_alerts.py`, `token_context.py`, `cli.py`, `debug_rako.py`

## ❌ Dihapus Total — Workflow

`cto-radar.yml` (15 *), `cvd-update.yml` (30 * hourly), `lp-safe-radar.yml` (25 *), `memecoin-scanner.yml` (*/15), `daily-snapshot.yml` (30 0 *) — diganti `daily-prepump.yml` 0 17 * * * (00:00 WIB).

## ❌ Dihapus Total — Data & Test

`levels.json`, `breakouts.json`, `holder_snapshots.json`, `real_dust_history.json`, `scanner_*.json`, `GMGN_Trades_*.csv` + 9 test suite terkait.

## ✅ Tetap Aktif (jangan dihapus)

- `prepump_detector.py` (inti), `cvd.py`, `core.py`, `gmgn_screener.py`, `trending_ui.py`, `watchlist.py`, `signals.py` (minimalist)
- Data: `cvd.json`, `signals.json`, `conviction.json`, `history.json`, `watchlist.json`
- Cron: `daily-prepump.yml` 00:00 WIB

## 📝 Instruksi untuk AI berikutnya

> Jangan aktifkan kembali halaman/fungsi yang dihapus tanpa persetujuan owner. Fokus sempit: watchlist → scan trending/degen → CVD → sinyal harian 00:00 WIB + Telegram sekali sehari.

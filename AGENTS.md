# AGENTS.md — baca ini dulu sebelum mengubah apa pun

File ini adalah **memori antar-sesi**. Agen AI membaca `AGENTS.md` otomatis saat membuka repo.

> **Untuk agen:** setelah mengubah perilaku, perbarui file ini + `docs/PROGRESS.md` dalam commit yang sama.

---

## 1. Apa ini

Dashboard Streamlit + cron untuk deteksi **pre-pump** Solana. Bahasa pengguna: **Indonesia**. Komentar & docstring: **Inggris**.

Fokus sempit per 2026-08-07 (reset total, revisi 07:00 WIB): **watchlist → scan trending/degen → CVD → sinyal harian 07:00 WIB (00:00 UTC, GMGN candle flip) + Telegram sekali sehari dari prepump_baru**. Semua fungsi lain **dihapus total**.

Pemilik pakai untuk keputusan uang real: jangan longgarkan risiko diam-diam. Perubahan scoring harus dibuktikan kalibrasi tidak bergeser.

**Kerapian:** PEP8, hilangkan unused imports, docstring Inggris, linter, `python tests/test_*.py` atau `python -m unittest discover tests` harus tetap hijau.

---

## 2. Peta file (minimalist 2026-08-07)

| File | Isi |
|---|---|
| `app.py` | **Main page reset** — 371 baris. Urutan: watchlist vertical (kolom sinyal) → tambah manual → scan trending now → scan degen now. Tidak ada cards, tidak ada analyze di main page. Hanya tombol ⭐ Watchlist di tabel trending/degen. |
| `pages/3_⭐_Watchlist.py` | Watchlist table (history/score/holders). Tetap, tapi main page juga menampilkan watchlist. |
| `pages/4_📊_CVD.py` | **CVD Deep Analysis** — minimalist 358 baris. Input CA + window 4-72h → fetch GMGN → conviction, whale/dolphin, CVD chart, divergence, prepump 30m + multi-TF (30m/1h/4h/12h) + confluence. Tanpa ai_prompt, monitor_alerts, fresh_wallet detail. |
| `core.py` | Helius pool + DexScreener + GeckoTerminal helpers (shared). |
| `cvd.py` | Store swap 72 jam, bucket CVD, wallet profiles, conviction, candle patterns. **Tidak lagi** punya holder_snapshots / real_dust_history (dihapus karena fokus prepump). |
| `gmgn_screener.py` | Screener GMGN trending + HRHR, scoring ramp kontinu (4 pilar: t10 30, liq 30, rug 25, vol 15). Tetap semua filter. |
| `prepump_detector.py` | **Deep CVD** — 4 pilar 25 poin + multi-TF (untuk halaman CVD deep dive). |
| `prepump_baru_detector.py` | **BARU — Sinyal watchlist harian** — 7 checks validated 10 pump + LUNA (sell>buy, whale negatif, pantul>5%, CVD<10%, buyTX≥52%, 3h after low net BUY, spring≥55%). Sinyal MUNCUL jika lolos ≥6/7 (core 3 wajib). |
| `signals.py` | **Minimalist** — hanya prepump_baru_muncul (baru) + legacy imminent/forming (compat). Telegram via `requests` langsung (tanpa breakout_guard). Digest harian. |
| `trending_ui.py` | Renderer trending — dipakai app.py, tapi app sekarang render minimal (hanya Watchlist button). Enrich holder split tetap Helius-only. |
| `watchlist.py` | Watchlist helpers (load/save/add/remove + GitHub push + pending journal + cache 15s). |
| `scripts/update_cvd.py` | **Daily cron 07:00 WIB (00:00 UTC, GMGN candle flip)** — update CVD GMGN + conviction + daily snapshot history.json + evaluasi prepump + Telegram digest sekali sehari. Tidak lagi hourly. |
| `scripts/daily_snapshot.py` | Helper snapshot harian DexScreener+GMGN (dipakai update_cvd sebagai fallback). |
| `scripts/backtest_prepump.py` | Backtest prepump via CSV GMGN (offline). |
| `.github/workflows/daily-prepump.yml` | **Satu-satunya workflow** — `0 0 * * *` 07:00 WIB. Hapus: cto-radar, lp-safe, memecoin-scanner, cvd-update (hourly), daily-snapshot (07:30 WIB). |
| `tests/` | 13 suite (tambah prepump_baru_detector): test_candle_patterns, test_dexscreener_identity, test_fresh_wallet_growth, test_h4_activity, test_helius_rotation, test_holder_delta, test_holder_split (tanpa AppRealDust), test_prepump_detector, test_real_tx_summary, test_scoring_continuity, test_wallet_profiles, test_watchlist. Dihapus: test_accum_history, test_breakout_guard, test_flow_safety, test_stealth_signals, dll. |
| Data | `cvd.json` · `signals.json` · `conviction.json` · `history.json` · `watchlist.json` (di-commit daily). Dihapus: `levels.json`, `breakouts.json`, `holder_snapshots.json`, `real_dust_history.json`, `scanner_*.json`. |

---

## 3. Cron & Telegram — daily only

- **Data collection + sinyal + Telegram = sekali sehari 07:00 WIB (00:00 UTC, GMGN candle flip)** via `daily-prepump.yml` → `scripts/update_cvd.py 60`.
- Workflow lama yang **dihapus**: `cto-radar.yml` (15 *), `cvd-update.yml` (30 * hourly), `lp-safe-radar.yml` (25 *), `memecoin-scanner.yml` (*/15), `daily-snapshot.yml` (30 0 *). Jika masih ada di Settings → Actions, nonaktifkan manual atau akan auto-hilang setelah push (file terhapus).
- `update_cvd.py` sekarang: `begin_digest()` di awal, loop watchlist → `update_token_cvd(use_gmgn=True)` + `record_conviction(4h)` + `daily_snapshot` + `detect_baru_and_record` (7 checks) → `flush_telegram_digest("DAILY PRE-PUMP BARU — 07:00 WIB")`. Tidak ada breakout_guard, holder snapshot, liquidity test, growth alerts.
- **Backup sebelum reset:** history ada di git `cdcd34b` dan di `BACKUP_INFO.md` yang sempat dibuat (sekarang dihapus dari repo, tapi commit sebelum reset tetap ada). Jika perlu restore: `git checkout cdcd34b -- <file>`.

---

## 4. Halaman yang disisakan

- `app.py` — watchlist vertical + sinyal column (imminent/forming/cleared/neutral), skor, update WIB, hapus. Lalu form manual + scan trending + scan degen.
- `pages/3_⭐_Watchlist.py` — kelola watchlist (add/remove, history).
- `pages/4_📊_CVD.py` — deep CVD.

**Dihapus dari sidebar:** Compare, History, Screener, CTO Radar, LP Safe Radar, Accumulation Detector, Accumulation History, Memecoin Scanner, Prepump Checker. File + fungsi terkait dihapus total (breakout_guard, accum_history, ai_prompt, share_card, focus, cto_deep_scan, incubation_radar, lp_safe_radar, memecoin_scanner, monitor_alerts, telegram_monitor_alerts, token_context, cli, debug_rako).

---

## 5. Scoring screener — ramp kontinu

Tetap 4 pilar struktural: t10 30, liq 30, rug 25, vol 15. Price 24h/1h, holder count, age tidak dapat poin; smart/KOL dihapus. Gate: Top10>25%, liq<5% MC, rug>0.45, holder<1000, insider/bundler pressure. Penalties: bundler/insider/entrap/bot-degen/sniper/rug/t10/liq_thin/fresh_wallet/holder_conc. Continuous ramp via `CURVES`/`PENALTY_CURVES`/`CAP_CURVE`. High-risk cap 40.

**Kalau ubah scoring:** titik tengah ramp = ambang lama, jalankan `tests/test_scoring_continuity.py`, bandingkan distribusi grade.

---

## 6. Pre-Pump Radar — sumber prepump_baru

Sumber: `https://github.com/lparmycalprut/prepump_baru` — HANDOFF_WALLET_DEPTH.md + ANALISIS_POLA_PUMP.md (10 token pump + LUNA 3 hari). Pola validasi: sebelum pump, low baru + diserap, flow seimbang |CVD/vol|<10%, whale net negatif, buy TX ≥52% + avg SELL>BUY, spring candle 15m buy≥55%, volume follow-through, pantulan ≥15% dari low.

**Kalibrasi prepump_detector.py (4 pilar):**
- P1 Compression & Seller Exhaustion — hargai volume kering H-1 sebagai bullish (sleeper), jangan bearish. LUNA vol -73%.
- P2 Order-Flow Asymmetry — avg SELL>BUY + buy TX% ≥52% bobot tinggi, jangan hard-fail untuk tipe lambat (multi-hari, pakai 4h/12h).
- P3 Pure Accumulator Conviction — retention lintas hari ≥50% (bukan within-window), tag smart jangan pilar utama.
- P4 Terminal Ignition — lonjakan TX/CVD awal hari + spring 15m.
- Confluence SLEEPER (macro ≥65, micro <40) = LUNA H-1 — jangan turunkan bobot.

**Multi-TF:** 30m Micro Ignition, 1h Hourly Setup, 4h Swing/Wyckoff, 12h Macro Cycle. Confluence: golden (macro≥60 & micro≥75), dead_cat (30m≥70 & macro<35), sleeper (macro≥65 & 30m<40), normal.

---

## 7. Cara kerja & jebakan (minimalist)

```bash
python tests/test_prepump_detector.py
python tests/test_scoring_continuity.py
python tests/test_watchlist.py
python -m unittest discover tests   # hanya holder_split yang unittest, sisanya via python tests/test_*.py
```

- Runner Actions ephemeral — file tidak di-commit hilang tiap run, jadi daily workflow harus `git add cvd.json signals.json conviction.json history.json watchlist.json`.
- Field GMGN: trending_rank tidak punya insider_ratio/bundler_rate, yang benar bdrr/dhr/etpr/bdr/t70_shr/snp/fwr/t50 — lihat docs/gmgn_api.md.
- Helius pool hanya di core.py — jangan buat endpoint ?api-key= langsung.
- Jangan commit config.json (api key).

---

## 8. Status 2026-08-07 — RESET TOTAL (owner request)

**Backup:** full copy 17M + tar 3.7M dibuat sebelum perubahan (commit cdcd34b). Sudah dihapus dari repo tapi ada di history.

**Yang dihapus total:** 8 halaman + 13 modul + 5 workflow + 2 CSV besar + 9 test suite + 5 json (levels, breakouts, etc). Lihat git stat: 52 files changed, -30k deletions.

**Yang dipertahankan:** watchlist (vertical + sinyal BARU harian 07:00 WIB), scan trending/degen (semua filter) + CVD. Sinyal = prepump_baru_detector 7 checks (sell>buy, whale negatif, pantul>5%, CVD<10%, buyTX≥52%, 3h after low BUY, spring≥55%), Telegram sehari sekali 07:00 WIB via daily-prepump.yml.

**Cron baru:** `daily-prepump.yml` 0 0 * * * (07:00 WIB). Hapus: cto-radar, lp-safe, memecoin-scanner, cvd-update hourly, daily-snapshot 07:30 WIB. Jika workflow lama masih muncul di GitHub Actions, disable manual atau push sudah menghapus file.

**Perubahan app.py:** 4020 → 371 baris. Urutan: watchlist (sinyal) → manual add → scan trending → scan degen. Tidak ada cards, tidak ada analyze. Tombol di trending/degen hanya ⭐ Watchlist.

**Perubahan signals.py:** hapus breakout_guard deps, implement send_telegram langsung via requests, hanya prepump types, digest harian.

**Perubahan pages/4_📊_CVD.py:** 1961 → 358 baris, hapus ai_prompt/monitor/focus/fresh_wallet.

**Perubahan scripts/update_cvd.py:** 434 → ~180 baris, daily only, hapus holder snapshot/breakout/growth.

**Tes:** 12 suite tersisa semua PASS (custom python + unittest holder_split 18 tests). Dihapus 9 suite yang menguji fitur yang sengaja dihapus.

Lihat docs/PROGRESS.md untuk riwayat detail.


# AGENTS.md — baca ini dulu sebelum mengubah apa pun

File ini adalah **memori antar-sesi**. Agen AI membaca `AGENTS.md` otomatis saat membuka repo.

> **Untuk agen:** setelah mengubah perilaku, perbarui file ini + `docs/PROGRESS.md` dalam commit yang sama.

---

## 1. Apa ini

Dashboard Streamlit + cron untuk deteksi **pre-pump** Solana. Bahasa pengguna: **Indonesia**. Komentar & docstring: **Inggris**.

Fokus sempit per 2026-08-07 (reset total), **diperbarui 2026-08-12 ke 3-Candle Wyckoff + Grade A/B/C**: **watchlist → scan trending/degen → CVD → sinyal Wyckoff 15M** (detektor `scripts/prepump_wyckoff_cron.py` jalan tiap 15 menit via `.github/workflows/prepump-wyckoff-cron.yml` di menit 14/29/44/59 UTC). Bin candle **clock-aligned** (`ts // 900 * 900`); **Open = close candle sebelumnya** (TradingView / GMGN — gap-down yang tidak reclaim prev close = merah, bukan hijau palsu); evaluasi urutan **C1 baseline → C2 kering/LPS → C3 spring**. Hanya **Grade A** (3-candle + smart buyer, skor 95–100, wajib Telegram/Discord) dan **Grade B / SOS / trap / bearish** yang notify — **Grade C** (noise akumulasi rutin, 50–55) di-mute. `signals.json` format: `type/grade/score/volume_sol/cvd_sol/holder_lock_pct`. Cron harian 07:00 WIB, M15 swap store, dan 7 checks sudah **ditiadakan**.

Pemilik pakai untuk keputusan uang real: jangan longgarkan risiko diam-diam. Perubahan scoring harus dibuktikan kalibrasi tidak bergeser.

**Kerapian:** PEP8, hilangkan unused imports, docstring Inggris, linter, `python tests/test_*.py` atau `python -m unittest discover tests` harus tetap hijau.

---

## 2. Peta file (minimalist 2026-08-07)

| File | Isi |
|---|---|
| `app.py` | **Main page** — watchlist vertical 10 kolom (Token, CA + Links, Diamond, Real/Dust, **Top 100 Lock** (% Pure Acc dari `holder_lock_pct`), **15m Vol / CVD** (`volume_sol`/`cvd_sol`), **Sinyal Wyckoff** (🟢 ABSORPTION DIVERGENCE / 🟡 TEST SUPLAI / 🚀 SOS IGNITION / 🔴 BULL TRAP / ➖ NORMAL), **Skor** 0–100, Update, Hapus) → tambah manual → scan trending now → scan degen now. Sinyal dibaca dari entri terbaru format Wyckoff di `signals.json` (`get_signal_for_ca`). |
| `pages/3_⭐_Watchlist.py` | Watchlist table (history/score/holders). Tetap, tapi main page juga menampilkan watchlist. |
| `pages/4_📊_CVD.py` | **CVD Deep Analysis** — conviction graph fixed `24/48/72h` (growth/decline vs periode sebelumnya) + full Helius top-100 holder analysis + **fund source wallet (funder)** top-100 (rank by SOL balance, exclude exchange). Page tidak lagi merender Pre-Pump Radar, Multi-Timeframe, conviction table, CVD hourly, atau whale/dolphin held-flow. |
| `core.py` | Helius pool + DexScreener + GeckoTerminal helpers (shared). |
| `cvd.py` | Store swap 72 jam, bucket CVD, wallet profiles, conviction, candle patterns. **Tidak lagi** punya holder_snapshots / real_dust_history (dihapus karena fokus prepump). |
| `gmgn_screener.py` | Screener GMGN trending + HRHR, scoring ramp kontinu (4 pilar: t10 30, liq 30, rug 25, vol 15). Tetap semua filter. |
| `prepump_detector.py` | **Deep CVD** — 4 pilar 25 poin + multi-TF (untuk halaman CVD deep dive). |
| `prepump_baru_detector.py` | **BARU — Sinyal watchlist harian** — 7 checks validated 10 pump + LUNA (sell>buy, whale negatif, pantul>5%, CVD<10%, buyTX≥52%, 3h after low net BUY, spring≥55%). Sinyal MUNCUL jika lolos ≥6/7 (core 3 wajib). |
| `signals.py` | **Minimalist** — hanya prepump_baru_muncul (baru) + legacy imminent/forming (compat). Telegram via `requests` langsung (tanpa breakout_guard). Digest harian. |
| `trending_ui.py` | Renderer trending — dipakai app.py, tapi app sekarang render minimal (hanya Watchlist button). Enrich holder split tetap Helius-only. |
| `watchlist.py` | Watchlist helpers (load/save/add/remove + GitHub push + pending journal + cache 15s). |
| `scripts/update_cvd.py` | **Cron updater** — update CVD GMGN + conviction (4h) + holder snapshot/real-dust (`holder_snapshots.json`, `real_dust_history.json`) + daily snapshot `history.json` + evaluasi prepump + Telegram digest. |
| `scripts/daily_snapshot.py` | Helper snapshot harian DexScreener+GMGN (dipakai update_cvd sebagai fallback). |
| `scripts/backtest_prepump.py` | Backtest prepump via CSV GMGN (offline). |
| `.github/workflows/daily-prepump.yml` | **Cron Harian** — `0 0 * * *` 07:00 WIB (GMGN candle flip). |
| `.github/workflows/cvd-detail.yml` | **Cron per 4 Jam** — `0 */4 * * *` untuk update detail CVD & holder top (`holder_snapshots.json` & `real_dust_history.json`). |
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

**Multi-TF:** 30m Micro Ignition, 1h Hourly Setup, 4h Swing Channel, 12h Macro Cycle / Wyckoff Accumulation, 24h Wyckoff Accumulation. Wyckoff hanya di 12h & 24h. Confluence: golden (macro 12h/24h ≥60 & micro≥75), dead_cat (30m≥70 & macro<35), sleeper (macro≥65 & 30m<40), normal.

**Catatan UI CVD (owner request 2026-08-07):** backend `prepump_detector.py`
dan `signals.py` tetap dipakai oleh sinyal watchlist/Telegram, tetapi page
`4_📊_CVD.py` tidak lagi memanggil atau merender Pre-Pump Radar 30m maupun
Multi-Timeframe. Page hanya mengambil swap 72h untuk grafik conviction
`24/48/72h`, lalu mengambil full holder list Helius untuk Top 100:
proporsi diamond hand (sell/buy ≤10% pada window swap) dan proporsi saldo
real (nilai saldo ≥ dust limit). Wallet tanpa sell terdeteksi ditandai sebagai
no-sell-observed dan masuk hitungan diamond hand dengan batasan window yang
jelas di UI.

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

## 9. Status 2026-08-07 — CVD holder-focused UI revision

`pages/4_📊_CVD.py` sekarang mengambil satu dataset GMGN 72 jam dan hanya
merender grafik conviction untuk window `24/48/72h`. Table conviction,
CVD hourly, whale/dolphin held-flow, Pre-Pump Radar 30m, dan Multi-Timeframe
UI dihapus. `cvd.top_holder_analysis()` adalah helper network-free yang
memisahkan dua scope:
1. **Top 100 holder**: ranking saldo terbesar, analisis diamond hand (sell/buy ≤10%
   selama sample 72h; wallet tanpa sell terdeteksi ikut dihitung), dan tabel detail.
2. **Full holder list (semua holder Helius)**: metrik keseluruhan Real holder
   (`token_balance * price_usd >= dust_limit_usd`, default $5) dan Dust holder
   (`< dust_limit_usd`), termasuk total holder valid, jumlah, dan persentase Real/Dust.

Backend prepump tetap dipertahankan karena masih dipakai oleh sinyal harian dan
test suite.

Verifikasi minimum setelah perubahan: `python -m py_compile cvd.py
pages/4_📊_CVD.py` dan `python tests/test_top_holder_analysis.py`.

---

## 10. Status 2026-08-08 — Penambahan cron detail CVD & Top Holders per 4 jam

- Ditambahkan workflow `.github/workflows/cvd-detail.yml` (`0 */4 * * *`, per 4 jam) agar data `holder_snapshots.json` dan `real_dust_history.json` di-commit secara berkala.
- `scripts/update_cvd.py` kembali menghitung holder snapshot (Helius / GMGN top holders fallback) dan memperbarui metadata `watchlist.json` (`diamond_pct`, `real_holders`, `dust_holders`) sehingga UI Watchlist tidak lagi kosong (`—`).
- `app.py` pada fungsi `get_watchlist_details` membaca metadata dan memiliki fallback ke `holder_snapshots.json`, `real_dust_history.json`, serta live GMGN `token_stat`.
- `pages/4_📊_CVD.py` pada fungsi `fetch_holder_snapshot` memiliki fallback ke data cron `holder_snapshots.json` dan GMGN ketika Helius API key tidak dikonfigurasi di rahasia Streamlit.

---

## 11. Status 2026-08-10 — owner request batch

1. **CVD fund source wallet (funder) top-100** — `cvd.funder_wallet_analysis()`
   scan transfer SOL masuk ke top-100 holder (Helius Enhanced API, 20 tx/holder),
   ranking funder by **balance SOL terbesar**, **exclude exchange** via
   `cvd.EXCHANGE_WALLETS` (kurasi, + `config.json` `exchange_wallets`).
   UI di `pages/4_📊_CVD.py` (cached 15 menit). Heuristik, bukan pelacakan penuh.
2. **Conviction window CVD = 24/48/72 saja** (grafik pertumbuhan/penurunan
   vs periode sebelumnya tetap ada).
3. **Wyckoff hanya 12H & 24H** — `prepump_detector.PREPUMP_TF_CONFIGS`:
   4h → "Swing Channel" (tanpa Wyckoff), 12h → "Macro Cycle / Wyckoff
   Accumulation", tambah **24h** → "Wyckoff Accumulation (24h)".
   `PREPUMP_TF_MACRO = ('12h', '24h')`; micro tetap 30m/1h. Data 72h cukup
   untuk 24h window (prior_hours 48).
4. **Fix Diamond/Real-Dust di main app** — fallback GMGN sekarang pakai
   `price_usd` (raw GMGN → DexScreener); tambah fallback Helius live
   (`fetch_helius_top_holder_summary`) sebelum GMGN.
5. **Kolom M15 di watchlist** (app.py + pages/3) — `cvd.m15_activity_flag()`:
   flag YA jika ada candle 15 menit dengan tx **>500** DAN volume **>500 SOL**
   (strict >), dari store swap 72 jam.

Verifikasi: `python tests/test_m15_and_funder.py`,
`python tests/test_prepump_detector.py`, semua suite lama hijau, AppTest
render watchlist 12 token tanpa exception.


## 12. Status 2026-08-10 — GMGN extension CVD + priority scan

Owner meminta perhitungan sinyal harian mengikuti ekstensi `ekstensi_extract_gmgn`, bukan detector CVD/prepump lama. `cvd_daily.py` sekarang memakai matriks harian extension: buy−sell = CVD, buy+sell = volume, status KERING bila volume turun ≥40% dan rasio CVD ≤10%. Hasil harian direkam ke `cvd_daily.json` dan `signals.json` satu kali per tanggal.

Fund Source Wallet — Top 100 Holder dihapus total dari halaman CVD. Workflow detail 4-jam dihapus agar tidak membuat sinyal lama; workflow harian menjadi satu-satunya penghasil sinyal CVD. Token yang mendapat status KERING ditandai `priority` pada watchlist (sekaligus menyimpan baseline `priority_dry_hourly_sol` = volume hari kering / 24). Workflow `priority-volume.yml` memeriksa token prioritas setiap 15 menit dengan deteksi **First Buy Surge** (`cvd_daily.first_buy_surge`) — pengganti burst lama (>500 tx / ≥500 SOL). Empat kaki wajib lolos dalam jendela 15 menit: (1) volume surge ≥ +100% vs volume per jam fase kering H-1, (2) buy tx ≥ 60% dari ≥10 tx oleh ≥5 wallet unik, (3) CVD velocity Delta/Volume ≥ +20%, (4) cluster ≥3 big-buy ≥1 SOL tanpa sell besar pembalas. Alert Telegram `first_buy_surge` terkirim dengan dedupe 4 jam (config `first_buy_surge_cooldown_min`; threshold bisa dituning lewat blok `first_buy_surge` di config.json).

## 13. Status 2026-08-11 — Pre-Pump & Wyckoff 15M Cron Detector (app.py selaras)

Repo dirombak menjadi **SOLANA MEMECOIN PRE-PUMP & WYCKOFF 15M CRON DETECTOR**:
`.github/workflows/prepump-wyckoff-cron.yml` menjalankan
`scripts/prepump_wyckoff_cron.py` tiap 15 menit dan menulis sinyal format baru
ke `signals.json` (`ts/ca/symbol/type/score/price_usd/volume_sol/cvd_sol/
holder_lock_pct/detail`). Cron harian 07:00 WIB, M15 swap store, dan evaluasi
7 checks sudah ditiadakan.

`app.py` mengikuti: tabel Watchlist kini 10 kolom — Token, CA + Links,
Diamond, Real/Dust, **Top 100 Lock** (`holder_lock_pct`, "X% Pure Acc"),
**15m Vol / CVD** (`volume_sol` | `cvd_sol`), **Sinyal** (label Wyckoff:
🟢 ABSORPTION DIVERGENCE, 🟡 TEST SUPLAI, 🚀 SOS IGNITION, 🔴 BULL TRAP,
👀 PRE-PUMP POTENTIAL, ➖ NORMAL), **Skor** 0–100 (`score`), Update, Hapus.
`get_signal_for_ca()` membaca entri terbaru format Wyckoff per CA; entri lama
(`cvd_daily`, cron 6h) diabaikan. `watchlist_m15_flag`, kolom M15, kolom
AvgCost (`fetch_gmgn_avg_cost`), `live_evaluate`, dan skor "/7 checks" dihapus.
CVD Deep Analysis (`pages/4_📊_CVD.py`) tidak berubah.

### 2026-08-11 (lanjutan) — Bearish Divergence di detector

`scripts/prepump_wyckoff_cron.py` mendapat sinyal baru section 4.5:
**🔴 BEARISH DIVERGENCE (HARGA TURUN / DISTRIBUSI)** — kebalikan absorption
divergence: candle 15m MERAH (`price_change_pct < 0`) tapi CVD PLUS
(`cvd_sol >= 1.0`) → skor -30, notifikasi **selalu terkirim** dengan warning
**⚠️ HATI-HATI** (buyer diserap seller, potensi distribusi). Label CVD di
pesan dinamis: `(Net Sells Terserap!)` / `(Net Buys Dominan!)`. `app.py`
sudah mengenali tipe ini (badge merah). Test: `test_bearish_divergence` di
`tests/test_cron_top_holders.py` (save sinyal di-patch no-op supaya
`signals.json` tidak terpolusi).

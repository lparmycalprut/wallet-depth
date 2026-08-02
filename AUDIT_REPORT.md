# AUDIT TAMBAHAN — Temuan Bug / Crash / Optimasi Serupa Bagian 1

> Scope: `core.py`, `cvd.py`, `app.py`, `gmgn_screener.py`, `signals.py`, `breakout_guard.py`, `breakout_log.py`, `scripts/update_cvd.py`, `scripts/daily_snapshot.py`
> Fokus: `except Exception: pass/return None` yang menyembunyikan error, race condition pada file state yang di-commit ke repo, pemanggilan API eksternal tanpa retry/backoff/caching.

---

## 1. `core.py`

### 1.1 `get_market()` (baris ~200) — tanpa try/except, crash keras
- **Lokasi:** `def get_market(ca: str) -> dict:` — langsung `requests.get()` + `r.json()` tanpa try.
- **Skenario:** DexScreener 429 / timeout / 5xx -> `requests` raise, `r.json()` ValueError -> bubble ke `app.py` `fetch_dexscreener` yang tidak catch, menyebabkan spinner error dan `st.stop()` tapi tanpa pesan jelas apakah rate limit atau token salah.
- **Fix:** Bungkus dengan retry 2-3x + backoff, log status code, return `{}` jika gagal, dan caller bedakan empty vs error. Sama seperti `_github_push` sekarang log eksplisit.

### 1.2 `get_rugcheck()` (baris ~230) — `except Exception: pass`
- **Lokasi:** dua blok `try: r = requests.get(...); d = r.json()` dengan `except: pass`
- **Skenario:** RugCheck 429 / Cloudflare block / JSON rusak -> fungsi return `{}` atau setengah terisi (`lp_locked_pct` None). `health_score` menerima None = netral, sehingga token berbahaya bisa lolos skor tanpa warning.
- **Fix:** Logging `print(WARN: RugCheck ... status, body[:200])`, kembalikan partial tapi dengan flag `error`, dan tampilkan badge "RugCheck unavailable" di UI.

### 1.3 `get_ohlcv_daily()` (~250) — silent empty DataFrame
- **Skenario:** GeckoTerminal 429 / timeout -> `except: return pd.DataFrame()` kosong. Caller `fetch_ohlcv` cache 10 menit, jadi data kosong ter-cache lama, holder chart hilang tanpa alasan.
- **Fix:** Log, bedakan `None` (error) vs empty (memang tidak ada candle), jangan cache failure (atau TTL lebih pendek untuk error).

### 1.4 `gmgn_token_stat()` (~430) — `except Exception: return empty`
- **Skenario:** Cloudflare block `curl_cffi` raise / JSON shape berubah -> return `{"holders": [], ...}`. Caller di `scripts/daily_snapshot.py` mengira holder_count = 0, sehingga tier estimate jadi 0 dan skor jadi salah.
- **Fix:** Log error + simpan alasan ke `raw` field, return `{"error": "..."} ` atau raise dengan pesan jelas.

### 1.5 Helius key pool exhaustion (semua key 429/5xx)
- **Lokasi:** `helius_rpc_request()` & `helius_api_get()` (baris ~120-190)
- **Skenario:** User pakai 3 free key, semua kena 429. Loop `for key in _helius_candidates` set `last_error = _response_error(...)` dan continue, akhirnya `raise last_error` -> `RuntimeError: Helius RPC HTTP 429`. Di `app.py` `fetch_holders_helius` ini di-catch generik `except Exception as e: err_msgs.append(f"Helius failed: {e}")` -> user lihat "Helius failed: Helius RPC HTTP 429" tanpa tahu semua key habis, apakah perlu tunggu atau tambah key.
- **Fix:** Saat semua key gagal, raise pesan eksplisit `f"All {len(keys)} Helius keys exhausted (429/5xx). Last: {last_error}. Try adding more keys or wait 1m."`. Di UI, tampilkan petunjuk tambah key, bukan hanya raw HTTP code.

### 1.6 `_config_file()`, `load_config()`, `load_history()` — `except Exception: return {}` 
- Menyembunyikan JSON corrupt. Jika `config.json` rusak karena merge conflict (sama seperti `cvd.json`), user tidak tahu. Fix: log `WARN: failed to load config.json: exc`.

---

## 2. `cvd.py`

### 2.1 `fetch_candles()`, `fetch_price_series()`, `fetch_h4_price()` (baris ~600-800)
- **Lokasi:** `try: r = requests.get(...); lst = ...; except: return {} / []`
- **Skenario:** GeckoTerminal down -> return kosong, `get_h4_series()` / `get_series()` return None, `detect_divergence` skip, Breakout Guard tidak alert sama sekali tanpa alasan. User kira tidak ada divergence, padahal data tidak ke-fetch.
- **Fix:** Log status code + alasan, return `None` untuk error vs `{}` untuk empty, dan caller bedakan. Tambahkan retry 2x dengan backoff.

### 2.2 `_fetch_page()` (Helius Enhanced API) — `except: return None`
- **Lokasi:** `def _fetch_page(api_key, pool, before=None, retries=4): try: helius_api_get(...) except: return None`
- **Skenario:** Semua Helius key 429 -> `_fetch_page` return None, `fetch_swaps` break loop `if page is None: break` dan mengembalikan swaps parsial yang sudah terkumpul, tanpa tanda bahwa window terpotong. `update_token_cvd` menyimpan bucket parsial sebagai lengkap, `record_conviction` menghitung conviction dari data tidak lengkap, bisa false signal akumulasi/distribusi.
- **Fix:** Log eksplisit, kembalikan `([], error)` atau set flag `gap=True` dengan alasan, dan di `update_token_cvd` simpan `gap_reason` untuk ditampilkan di UI.

### 2.3 `load_cvd()`, `load_conviction()`, `load_holder_snapshots()`, `load_real_dust_history()` — silent fallback
- Semua pakai `_load_json_tolerant` yang return None jika file corrupt / conflict marker tidak bisa di-parse, lalu caller `or {}`. Jika ada merge conflict di repo (sama seperti watchlist), file bisa hilang dan history 7 hari lenyap tanpa warning.
- **Fix:** Log `WARN: file contains conflict markers, using incoming side` sudah ada di `_load_json_tolerant`, tapi untuk file lain yang tidak pakai itu (holder_snapshots, real_dust) langsung `{}`. Sarankan pakai `_load_json_tolerant` konsisten + log.

### 2.4 `record_conviction()` — re-raise setelah gagal atomic write
- Sudah bagus (komen: Callers must not report successful refresh). Tapi caller di `scripts/update_cvd.py` tidak menangani raise tersebut secara khusus: `cp = record_conviction(...)` di dalam `try` besar, sehingga jika write gagal, `except Exception as e: print unhandled error` -> conviction tidak tercatat tapi user tidak tahu retry dibutuhkan.

### 2.5 `markup_from_candles()` — aman dari division-by-zero (sudah cek `len(valid)<3` dan `price>0`), good.

### 2.6 `flow_check_panel()` dipanggil di `app.py` per watchlist CA — tanpa cache, setiap Streamlit rerun hit `load_conviction()` yang baca file + `raw.githubusercontent` (sebelum fix watchlist, ada cache 10 menit di `load_conviction`). Sekarang masih baca file tiap kali, bisa lambat untuk 30 token. Fix: cache dengan TTL 60s.

---

## 3. `app.py`

### 3.1 `load_watchlist()` dipanggil tanpa `force_refresh` di setiap rerun
- **Lokasi:** `from watchlist import load_watchlist` lalu `_wl = load_watchlist()` di top-level (baris ~1005).
- **Skenario:** Sebelum fix, setiap Streamlit rerun (setiap interaksi slider, input CA) melakukan `_github_pull()` -> 1-3 API call. Dengan 10 user interaksi = 10-30 call, memperbesar peluang 429 dan race #2. Setelah fix ada TTL 15s, sudah lebih baik, tapi `fetch_watchlist_prices` dan `fetch_watchlist_daily_candles` juga dipanggil setiap rerun dengan `st.cache_data(ttl=30/900)`, jadi masih ada jendela race jika dua tab browser menambah token bersamaan.
- **Fix:** Sudah diperbaiki dengan TTL cache di `watchlist.py`. Tambahan: gunakan `force_refresh=False` di path normal, `force_refresh=True` hanya saat user klik Add/Remove.

### 3.2 `watchlist_auto_refresh_cas` — potensi membengkak tanpa batas
- **Lokasi:** `st.session_state.setdefault("watchlist_auto_refresh_cas", set()).add(ca)` di `watchlist.py` dan `app.py` line ~1150.
- **Skenario:** User scan trending, add 20 token cepat (klik ⭐ watch 20x). Set berisi 20 CA. Klik "Force refresh now" akan loop `for _fr_ca in enumerate(_to_refresh): update_token_cvd(... max_pages=200)` -> tiap token 200 pages Helius/GMGN, total 4000 pages, bisa makan 10-20 menit dan habiskan semua Helius credit, plus Helius 429.
- **Fix:** Batasi `_to_refresh` misal `[:10]` per klik, atau proses batch 3 token per run dengan `st.session_state` queue, atau tampilkan estimasi waktu. Juga clear set setelah sukses per CA, bukan hanya global clear di awal.

### 3.3 `fetch_holder_data()` — cache failure
- **Lokasi:** `@st.cache_data(ttl=3600) def fetch_holder_data(...)` return None on failure.
- **Skenario:** Helius 429 -> return None, ter-cache 1 jam sebagai None. Selama 1 jam berikutnya, semua panel holder-delta dan real/dust bilang "waiting for snapshot baseline" padahal sebenarnya hanya rate limit sesaat.
- **Fix:** Jangan cache None, atau TTL error lebih pendek (misal 60s). Gunakan `st.cache_data` dengan `show_spinner` + log.

---

## 4. `gmgn_screener.py`

### 4.1 `fetch_trending()` — ambiguous empty vs blocked
- **Lokasi:** `def fetch_trending(timeout=25, debug=False): ... return []` pada 3 kondisi: `curl_cffi` tidak terinstall, HTTP !=200, JSON code !=0, 0 tokens.
- **Skenario:** Cloudflare block -> return [] tanpa error. Di `trending_ui.py` `run_screen()` hanya cek `if not rows and not _err:` lalu warning "GMGN returned nothing (Cloudflare block or every token filtered out)". User tidak bisa bedakan apakah memang tidak ada token yang lolos filter atau diblokir Cloudflare. README menyebut ini bisa ambigu.
- **Fix:** Kembalikan tuple `(tokens, error_reason)` seperti `fetch_gmgn_swaps` yang sudah punya `get_gmgn_last_error()`. Simpan last error di global `_gmgn_last` dan expose ke UI: "Blocked by Cloudflare (cf-challenge) — try again in 1m" vs "0 tokens after filters".

### 4.2 Tidak ada retry/backoff/caching
- **Lokasi:** `cr.post(_trending_url(), impersonate=imp, ...)` loop 3 fingerprint tanpa sleep.
- **Skenario:** GMGN rate limit -> 3 request cepat -> di-ban IP. Tidak ada TTL cache, setiap klik "Scan Trending Now" hit API lagi.
- **Fix:** Tambah `st.cache_data(ttl=120)` di `screen()` atau di `fetch_trending()`, tambah backoff 0.5s antar attempt, log last error.

### 4.3 `fetch_hrhr()` fallback ke `fetch_trending()` tanpa beda alasan
- Jika HRHR kosong karena filter terlalu ketat, fallback ke trending bisa menampilkan token yang bukan HRHR, mengaburkan definisi HRHR. Fix: jangan fallback otomatis, tampilkan pesan "HRHR kosong, coba longgarkan filter atau cek trending".

---

## 5. `signals.py`, `breakout_guard.py`, `breakout_log.py`

### 5.1 `signals.py` — race condition file state
- **Lokasi:** `def record_signal(...): sigs = load_signals(); ...; save_signals(sigs)` (baris ~80)
- **Skenario:** Cron `update_cvd.py` dan Streamlit `app.py` (Analyze) keduanya bisa memanggil `record_signal` bersamaan. Pola read-modify-write tanpa lock: A load 100 signals, B load 100 signals, A append 1 dan save 101, B append 1 dan save 101 (milik A hilang).
- **Fix:** Gunakan `atomic_write_json` sudah atomic untuk write, tapi read-modify-write tetap race. Perlu file lock (fcntl) atau retry dengan re-read seperti watchlist: load, append, save, jika gagal karena conflict (cek mtime), retry. Atau gunakan same pattern as watchlist: simpan dengan `os.replace` sudah ada, tapi perlu retry loop.

### 5.2 `signals.py` — Telegram retry tidak ada
- `send_telegram` dipanggil sekali, `except Exception: pass` -> jika Telegram down, sinyal hilang dari Telegram tapi tetap ada di `signals.json`. Tidak ada queue retry seperti `breakout_log.pending_alerts`.
- **Fix:** Simpan pending Telegram seperti di `breakout_log`, atau gunakan same `pending_alerts` file.

### 5.3 `breakout_guard.py` — `load_levels()` / `save_levels()` race
- **Lokasi:** `run_guard()` — `state = load_levels(); ...; save_levels(state)` di banyak early return (baris ~470-530)
- **Skenario:** Dua cron job overlap (misal manual trigger + scheduled) load levels.json yang sama, keduanya update `last_h4_ts` dan `pending` list, yang terakhir save menang, yang pertama hilang. `pending` list berisi event_id yang sedang di-watch untuk reclaim (5 candles window) — jika hilang, reclaim tidak pernah terdeteksi.
- **Fix:** Tambah file lock atau retry dengan re-read + merge seperti watchlist. Atau gunakan same `_github_push` retry pattern untuk levels.json jika nantinya levels.json juga di-commit ke repo (saat ini belum).

### 5.4 `breakout_log.py` — pending alerts bisa numpuk tak terbatas?
- **Lokasi:** `pending_alerts()` return list `not alerted and msg and ts >= cut`. `mark_alerted()` clear msg setelah sukses.
- **Skenario:** Jika Telegram down lama (misal 24 jam), setiap cron run (hourly) bisa menambah 1-2 event baru ke `breakouts.json`, semua dengan `alerted=False` dan `msg` penuh. `MAX_EVENTS=500` membatasi file, tapi jika down >8 jam, `RETRY_MAX_H=8` akan drop alert yang lebih tua dari 8 jam, jadi tidak infinite tetapi bisa kehilangan alert penting. Jika down 2-3 hari, file tetap 500, tapi semua pending >8 jam di-drop, tidak retry lagi -> alert hilang diam-diam.
- **Fix:** Dokumentasikan bahwa Telegram down >8h menyebabkan alert di-drop, atau naikkan `RETRY_MAX_H` + tambahkan log `WARN: dropping stale alert`. Juga `save_events()` truncate `events[-MAX_EVENTS:]` bisa memotong pending yang lama — lebih baik truncate tapi preserve `not alerted` events terlebih dahulu.

### 5.5 Dedupe logic (4h/12h)
- `signals.py` dedupe 4h per (ca, type): `for s in reversed(sigs[-200:]): if s[ca]==ca and s[type]==type and now - ts < DEDUPE_SEC: return False`
- `breakout_guard.py` dedupe 12h per (event, level): `recently(key): now - alerted.get(key) < 12*3600`
- **Race:** Jika cron jalan 2x dalam <4h (misal manual + scheduled), dedupe di file yang sama race seperti di atas, bisa menyebabkan duplicate Telegram. 
- **Fix:** Dedupe check harus dilakukan setelah load terbaru (retry) + simpan atomik.

---

## 6. `scripts/update_cvd.py` & `scripts/daily_snapshot.py`

### 6.1 Race dengan Streamlit commit (watchlist.json, cvd.json, conviction.json, dll)
- **Lokasi:** `update_cvd.py` line `wl = load_watchlist()` (baca dari GitHub) lalu di akhir `save_watchlist(wl, "auto-fix symbols")` (commit). `daily_snapshot.py` juga `load_watchlist()` + `save_watchlist(wl)`.
- **Skenario:** User di Streamlit menambah token ⭐ pada saat yang sama cron `update_cvd.py` sedang jalan. Cron load watchlist (tanpa token baru), lalu di akhir save_watchlist dengan watchlist lama (tanpa token baru) -> token baru hilang (lost-update). Sama untuk `cvd.json`, `history.json`, `signals.json`, `levels.json`, `breakouts.json`, `holder_snapshots.json`, `real_dust_history.json` — semua pakai read-modify-write tanpa lock, rentan race dengan Streamlit atau dengan cron lain.
- **Fix (sama seperti watchlist fix):** Untuk setiap file state yang di-commit ke repo, terapkan pola `GET sha + PUT dengan retry 409 + merge`. Untuk file yang tidak di-commit (cvd.json, conviction.json, dll) tapi ditulis oleh cron dan dibaca oleh Streamlit, gunakan file lock (`portalocker` atau `fcntl`) atau atomic rename sudah ada tapi tidak cukup. Minimal tambahkan `try: load -> modify -> save` dalam loop retry 3x dengan cek mtime.

### 6.2 `daily_snapshot.py` — `snapshot_one()` tanpa retry
- **Lokasi:** `def _dex_market` dan `_gmgn_token_stat` tanpa retry, langsung `requests.get`.
- **Skenario:** DexScreener 429 -> `_dex_market` return None -> `snapshot_one` raise "not found on DexScreener" -> di `main()` di-catch dan print `failed`, tapi history hari itu kosong untuk token tersebut, menyebabkan delta holder hilang.
- **Fix:** Retry 2x + log.

### 6.3 `update_cvd.py` — `_try_snapshot()` Helius + GMGN tanpa batas
- Jika Helius key habis 429, fallback ke GMGN top-10 yang hanya 10 holder, lalu `record_holder_snapshot` menyimpan top-10 sebagai snapshot lengkap. `holder_delta()` yang berbasis COUNT tier (whale = top 1%) akan menganggap top-10 = semua whale, sehingga delta jadi inflasi.
- **Fix:** Tandai snapshot GMGN dengan flag `source: gmgn_top10` dan di `holder_delta()` beri warning bahwa tier classification tidak akurat untuk top-10 only.

### 6.4 `update_cvd.py` — `max_pages` default 60, tapi loop tidak ada sleep antar CA
- Jika watchlist 30 token, 30*60=1800 pages GMGN/Helius dalam satu run, bisa kena rate limit. Sudah ada `time.sleep` di `fetch_swaps` (0.15s) tapi tidak antar CA.
- **Fix:** Tambah sleep 0.3s antar CA (sudah ada di daily_snapshot, tapi belum di update_cvd).

---

## Ringkasan Rekomendasi Umum (untuk semua file)

1. **Ganti `except Exception: pass/return {}/[]` dengan logging eksplisit** (`print WARN/ERROR status, body[:200]` ke stderr) dan bedakan error vs empty.
2. **Tambah retry + backoff + re-fetch untuk semua read-modify-write ke file yang di-commit** (watchlist sudah fix, terapkan ke `cvd.json`, `conviction.json`, `history.json`, `signals.json`, `levels.json`, `breakouts.json`, `holder_snapshots.json`, `real_dust_history.json`).
3. **Cache dengan TTL** untuk `load_watchlist()`, `load_conviction()`, `fetch_trending()` agar tidak hammer API tiap rerun.
4. **Jangan cache failure** (None/empty) dengan TTL panjang; gunakan TTL pendek untuk error.
5. **Expose last error** ke UI: `get_last_push_error()` / `get_gmgn_last_error()` sudah ada untuk watchlist & GMGN, terapkan untuk Helius pool exhaustion dan RugCheck.
6. **Batasi pertumbuhan** `watchlist_auto_refresh_cas` dan `pending_alerts`: max queue, truncate dengan prioritas, log saat drop.

---

## Next Steps (disarankan urutan)

1. **P1 (kritis):** Terapkan retry 409 + merge untuk `signals.json`, `levels.json`, `breakouts.json` (cron + Streamlit bisa tabrakan).
2. **P2 (penting):** Tambah logging eksplisit di `core.py` `get_market`, `get_rugcheck`, `gmgn_token_stat` dan bedakan empty vs blocked di `gmgn_screener.py`.
3. **P3 (optimasi):** Cache TTL untuk `load_conviction`, `fetch_trending`, dan jangan cache failure di `fetch_holder_data`.
4. **P4:** Batasi `watchlist_auto_refresh_cas` queue (max 10 per refresh) dan tambahkan warning di UI kalau pending journal >0.

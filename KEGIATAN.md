# Kegiatan — 1 September 2026

Fokus UI ke **analisa holder dust** (bukan silent 12 jam) + Scan Meteora.

1. Watchlist: buang Status/Net/Harga 12j, Real, Dust kolom lama, Scan,
   shortcut CVD. Ganti ringkasan dust (jumlah wallet + % MC), badge
   AMAN / HATI-HATI (≥1%) / DUMP (>2%), sparkline 4 jam, tombol 🧮 ke
   halaman Holder Analytic.
2. Trending/Degen: buang kolom Real/Dust/Dust%MC/12 Jam/Net 12j dan
   scan holder. Listing GMGN saja (Token, MC, 24h).
3. Halaman baru `pages/5_🧮_Holder.py` (di bawah CVD): dust, grafik 4
   jam, sisa token kohort Crab+Fish.
4. CVD: buang 🧮 Holder Analytic + kartu silent 12 jam.
5. `holder_history.py` + `holder_history.json`: catat dust/kohort tiap
   scan, resample 4 jam. Cron watchlist `include_flow=False`.
6. Scan Meteora di halaman utama: API 24h (fee_ratio≥250) + 1h (≥1),
   DLMM active_tvl≥1000. Pool 24h yang masih di 1h tetap tampil. Dust
   >2% MC disembunyikan. Shortcut Meteora DLMM + HawkFi.

# Kegiatan — 31 Agustus 2026 (lanjutan)

**Migrasi total sumber data ke Helius** (kecuali listing Trending/Degen
yang memang hanya ada di GMGN):

1. Fix bug konversi holder Helius: `amount` DAS adalah unit RAW → dibagi
   `10^decimals` mint (decimals dari DAS `getAsset`, fallback RPC
   `getTokenSupply`; per-item bila tersedia; abort bersih bila tidak
   ketemu). Sebelumnya nilai USD holder 10^decimals× lebih besar (tier
   Shark bernilai triliunan $).
2. `_fetch_holders_snapshot` & `_fetch_swaps_12h`: **Helius dulu, GMGN
   fallback**. `fetch_swaps` Enhanced API diprioritaskan juga di
   `scripts/update_cvd.py` (fetch harian CVD) dengan fallback GMGN.
3. **Solscan API dilepas total**: `solscan_holders.py` hanya tersisa
   kalkulasi `wallet_depth` (bucket/tier); `get_solscan_key` +
   `solscan_api_key` dihapus; nilai `holder_source=solscan` lama otomatis
   jatuh ke `auto` (= Helius). Opsi sumber kini `auto`/`helius`/`gmgn`.
4. Tier Helius sekarang mengecualikan LP/pool via `pair_addresses`
   DexScreener; legend/ikon UI menghilangkan 📡 Solscan.
5. Workflow `daily-effort.yml` **belum** bisa diubah via push (GitHub App
   tanpa permission `workflows`) — tambahkan manual env `HELIUS_API_KEY` /
   `HELIUS_API_KEYS` di step scan (lihat snippet di README); tanpa secret
   → otomatis fallback GMGN.

# Kegiatan — 31 Agustus 2026

Holder token watchlist diambil dari **Solscan**, plus **Wallet Depth by
Threshold** ala halaman analytics Solscan.

## Yang dikerjakan

1. `solscan_holders.py`: fetch holder Solscan — Pro API `v2.0/token/holders`
   bila `SOLSCAN_API_KEY` ada (tiap baris membawa `value` USD + `percentage`
   dari Solscan), fallback Public API `token/holders` (nilai USD =
   balance × harga app), lalu fallback GMGN/Helius. Normalisasi ke bentuk
   holder GMGN; LP/pool (dari `pair_addresses` DexScreener) ditandai bukan
   wallet.
2. `wallet_depth()`: **bucket** `>$0-$10` … `>$500k` atas semua akun
   (seperti chart Solscan) dan **tier** 🦐/🦀/🐟/🐬/🦈 atas wallet murni —
   count, total value, % marketcap per bucket/tier.
3. `silent_accumulation.analyze_token` punya `holder_source`
   (`gmgn`/`solscan`/`auto`, default config `holder_source` = `auto`):
   watchlist (cron & tombol scan lokal) Solscan dulu; listing
   Trending/Degen tetap GMGN. Saat sumber Solscan, `holders["depth"]` +
   `holders["api"]` ikut tersimpan di snapshot `silent_status`.
4. UI watchlist: ikon 📡 Solscan di kolom Real, expander per token
   "📊 Wallet Depth by Threshold" berisi dua tabel (bucket & tier).
5. Workflow cron menerima env `SOLSCAN_API_KEY` (repo secret, opsional);
   `config.example.json` + docs diperbarui. Catatan: bila GitHub App
   menolak push perubahan `.github/workflows`, tambahkan env tersebut
   manual di settings repo.

Tidak diubah: logika silent 12 jam, filter holder depth (SILENT/LP/
PUMPDUMP), listing Trending/Degen.

# Kegiatan — 19 Agustus 2026 (lanjutan)

- Token baru: fetch penuh **48 jam** (bukan incremental), lalu kirim Telegram
  untuk **semua** sinyal di window itu (historis tetap dikirim, sekali per
  `event_id`).
- Payload Telegram: hari (WIB), jam bar, range harga, range MC, R/CVD/TX,
  link GMGN + DexScreener. Tag “Historis” vs “Sinyal baru”.
- `add_to_watchlist` memanggil `request_immediate_scan()` (workflow_dispatch)
  agar 48 jam ditarik segera, lalu cron 15 menit menyambung incremental.

# Kegiatan — 19 Agustus 2026

Port sinyal ekstensi [SMART_SEROK v9.1.3](https://github.com/lparmycalprut/SMART_SEROK) ke wallet-depth.

## Yang dikerjakan

1. **Watchlist dikosongkan** (`watchlist.json` = `{}`).
2. **Symbol otomatis** saat CA manual: field ticker dihapus di form Streamlit;
   `watchlist.fetch_token_symbol()` memanggil DexScreener.
3. **Sinyal diganti** dari wash-collapse / SBR menjadi:
   - 🔴 WASPADA DUMP
   - 🟢 SIAP2 PUMP
   - ⚔️ BATTLE TERJADI
   Engine: `serok_engine.py` (bar 1 jam, R ≥10× prev + |R|≥10, battle gap ≤2.5% + P65).
4. **Scan tiap 15 menit** (intended cron `*/15`). File workflow tidak bisa
   di-push oleh GitHub App (butuh permission `workflows`) — ubah manual
   `.github/workflows/daily-effort.yml` menjadi `*/15 * * * *`. Fetch 48 jam.
5. **Telegram** rapi: judul + `$SYMBOL`, syarat, R/CVD/TX/wallet, range MC (battle),
   jam WIB, tautan GMGN + DexScreener. Satu alert per `event_id`.
6. **Tes** `tests/test_serok_engine.py`; payload Telegram & UI disesuaikan.
   `python -m unittest` untuk modul baru lulus.

Tidak diubah tanpa perlu: halaman CVD, listing Trending/Degen, fetch GMGN,
persist watchlist GitHub.

# Kegiatan — 30 Agustus 2026

Refactor besar: **buang semua sinyal + Telegram**, fokus **silent
accumulation 12 jam** dan **holder depth**.

## Yang dikerjakan

1. Hapus modul sinyal (serok, reversal, effort, price_structure), scanner
   realtime, dan transport `signals.py` (Telegram) beserta secrets.
2. `silent_accumulation.py`: fetch holder GMGN paginasi `next`
   (verified limit 1000/page, `limit=1000`), klasifikasi real holder
   (>$10 value) vs dust (0 < value <= $10), dust % dari marketcap,
   net flow 12 jam (`token_trades`), deteksi silent (net >= $50,
   >= 3 akumulator, |harga| <= 5%, bot <= 35%).
3. `silent_status.py` + `scripts/scan_silent.py`: cron tiap ~15 menit
   publish snapshot ke ref `silent-live`.
4. `app.py` & `trending_ui.py`: kolom/holder-depth langsung saat scan
   Trending/Degen (real count, dust count, dust %MC, status 12 jam).
5. Halaman CVD: chart flow harian tanpa sinyal; `daily_effort.json`
   dipertahankan sebagai agregasi murni (`daily_store.py`).
6. Workflow `daily-effort.yml` target: Silent Accumulation 12H Scanner tanpa
   `TELEGRAM_*`. Catatan: file workflow tidak bisa di-push oleh GitHub App
   (butuh permission `workflows`), jadi `scripts/realtime_reversal.py`
   dipertahankan sebagai adapter ke `scan_silent.py` agar cron tetap
   berjalan; ubah workflow manual bila ingin langsung memanggil
   `scripts/scan_silent.py`.

Tidak diubah tanpa perlu: watchlist GitHub, fetch GMGN/Helius, listing
screener.

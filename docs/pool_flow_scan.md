# Scan ALL: cara deteksi FEE PRINTER (untuk AI lain)

Dokumen ini merangkum fitur **🏆 Scan ALL** (halaman utama, `pool_flow_ui.py`,
logika di `pool_flow.py`, alert di `scripts/pool_flow_alert.py`). Tujuannya: AI lain bisa
mengulang filter, pengurutan, dan alert FEE PRINTER tanpa membaca kode.
Aturan di sini mengikuti permintaan user 2026-11-24. Kalau kode berubah, perbarui dokumen ini.

## 1. Sumber data: satu listing Meteora (24H)

Hanya satu endpoint, tanpa data per token dan tanpa scan lain.

```bash
curl -s "https://pool-discovery-api.datapi.meteora.ag/pools?page_size=50&timeframe=24h&category=top&filter_by=base_token_has_high_supply_concentration%3Dfalse%26%26base_token_has_high_single_ownership%3Dfalse%26%26pool_type%3Ddlmm%26%26base_token_market_cap%3E%3D20000%26%26base_token_created_at%3C%3D<NOW_MS>%26%26base_token_holders%3E%3D1500%26%26pool_created_at%3C%3D<NOW_MS_MINUS_24H>%26%26tvl%3E%3D30000%26%26fee_tvl_ratio%3E%3D1%26%26fee_pct%3E%3D0.5%26%26active_tvl%3E%3D10000"
```

- `<NOW_MS>` = waktu sekarang dalam milidetik. `<NOW_MS_MINUS_24H>` = `<NOW_MS>` − 86.400.000.
  Curl user berisi nilai tetap (`1795484047775` dan `1795397647775`, dibuat 2026-11-24 01:34 UTC).
  Kode **menghitung ulang** keduanya tiap scan (`pool_flow.flow_server_filter`). Nilai tetap
  membuat pool yang dibuat setelah waktu itu tidak pernah masuk.
- Tidak ada `sort_by`. Urutan dihitung lokal (lihat bagian 5).
- Halaman berikutnya memakai cursor. Ambil `after_key` dari respons, tambahkan
  `&after_key=<nilai>` ke URL yang sama. Ulangi sampai `has_more` = `false`.
- Parameter `page` diabaikan API. Jangan dipakai.
- Batas keamanan: 100 halaman × 50 baris. Cursor yang macet menghentikan pengambilan.
  Hasil ditandai `truncated` bila belum lengkap.
- Kode: `pool_flow.flow_server_filter`, `fetch_top_page`, `fetch_listing`, `scan_pools`.

Arti setiap syarat filter server:
- `base_token_has_high_supply_concentration=false`, `base_token_has_high_single_ownership=false`: buang token dengan konsentrasi supply atau kepemilikan tunggal tinggi.
- `pool_type=dlmm`: hanya DLMM.
- `base_token_market_cap>=20000`: market cap token dasar minimal $20.000.
- `base_token_created_at<=NOW`: token sudah dibuat.
- `base_token_holders>=1500`: holder token dasar minimal 1.500.
- `pool_created_at<=NOW-24h`: pool minimal 24 jam.
- `tvl>=30000`: TVL pool minimal $30.000.
- `fee_tvl_ratio>=1`: fee/TVL 24H minimal 1 %.
- `fee_pct>=0.5`: fee tier pool minimal 0,5 %.
- `active_tvl>=10000`: active TVL minimal $10.000.

## 2. Bentuk respons (field yang dipakai)

`{"total": N, "page_size": 50, "data": [ ...pool... ], "after_key": "...", "has_more": true|false}`

Setiap elemen `data` adalah satu pool. Field yang dipakai:

| Field | Arti di kode |
|---|---|
| `pool_address` | ID pool. Kunci dedupe. |
| `name` | Nama pool, mis. `FIONA-SOL`. |
| `token_x` / `token_y` | Dua sisi pool. Token non-SOL dianggap token dasar (`mint_of_pool`). |
| `token_x.address`, `.symbol`, `.name` | CA dan nama token. |
| `token_x.has_mint_authority`, `.has_freeze_authority` | `true` = **blokir**. |
| `token_x.top_holders_pct` | % top holder. > 30 blokir, > 15 peringatan. |
| `token_x.dev_balance_pct` | % saldo dev. > 5 peringatan. |
| `token_x.market_cap` | Market cap token dasar (ditampilkan). |
| `volatility` | **Volatility dalam %, window 24H.** Syarat FEE PRINTER. |
| `fee_active_tvl_ratio` | **Fee/active TVL dalam %.** Syarat FEE PRINTER dan dasar urutan. |
| `net_deposits` | **Net deposit dalam USD.** Syarat FEE PRINTER. |
| `fee_tvl_ratio` | Fee/TVL dalam %, 24H. Hanya ditampilkan. |
| `fee_pct` | Fee tier pool dalam %. Hanya ditampilkan. |
| `tvl`, `active_tvl` | TVL dan active TVL pool (USD). TVL < $50.000 mengaktifkan cek LP keluar. |
| `total_deposits`, `total_withdraws` | Dipakai untuk peringatan "LP keluar > masuk". |
| `avg_volume` | Avg volume per menit (label UI "Avg volume/menit"). Dipakai apa adanya. |
| `avg_fee` | Avg fee per menit. Dipakai untuk rasio `avg_fee ÷ tvl`. |
| `volume`, `swap_count`, `unique_traders` | Aktivitas 24H (kolom tabel). |
| `pool_created_at` | Umur pool dalam milidetik. Hanya dipakai server filter. |

## 3. Pipeline (urutan keputusan)

1. **Ambil listing** lengkap (bagian 1).
2. **Dedupe** berdasarkan `pool_address` (baris pertama menang).
3. **Blokir keamanan** (`evaluate_pool`, `security_checks`): mint authority aktif,
   freeze authority aktif, atau top holders > 30 % membuang pool dari daftar lolos.
   **Peringatan** (pool tetap, hanya label): top holders > 15 %, dev > 5 %, atau TVL < $50.000 dan
   `total_withdraws` > `total_deposits`. Field kosong tidak dihitung sebagai masalah.
4. **Syarat FEE PRINTER** (`fee_printer_ok`), semua inklusif:
   - `0,01 ≤ volatility ≤ 3` (di bawah 0,01 % dianggap tidak terukur),
   - `fee_active_tvl_ratio ≥ 2 × volatility`,
   - `net_deposits ≥ 10.000`.
   Pool tanpa salah satu nilai itu tidak lolos.
5. **Urutan** (`fee_printer_rows`): perkalian `fee_active_tvl_ratio × volatility`,
   **terbesar dulu**. Seri mengikuti urutan listing (sort stabil).

Hasil langkah 5 = tabel FEE PRINTER dan isi RINGKASAN. Tidak ada tabel atau label lain.

## 4. Yang tidak lagi dipakai (jangan dikembalikan tanpa permintaan baru)

- Filter 12H dan 4H, band `1–3 ×`, pemisahan SPOT (> 2 ×), dan listing 4H.
- Syarat umur pool 12 jam, TVL ≥ $20.000, volume/TVL ≥ 100 %, dan fee/TVL ≥ 5 %.
- HIGH RISK FEE PRINTER dan VERY HIGH RISK POOL.
- Pengurutan `|fee/TVL − volatility|` dan kolom "Fee/TVL ÷ volatility".

## 5. Pool teratas dan baris kuning

- **Baris kuning di tabel** = `most_crowded(result)` = pool dengan `avg_volume ÷ tvl`
  terbesar di seluruh `passing` (bukan hanya tabel FEE PRINTER). Ini aturan terpisah dari
  urutan tabel dan tidak diubah.
- Jika tidak ada pool FEE PRINTER, tidak ada baris kuning di tabel.

## 6. RINGKASAN dan alert Telegram

- **RINGKASAN** di halaman = `summary_rows(result)`: hanya pool FEE PRINTER, urutan sama dengan tabel.
  Kolom: Token/pool, Asal tabel (selalu `FEE PRINTER`), Fee/active TVL, Volatility, perkalian.
- **Alert Telegram** (`scripts/pool_flow_alert.py`) memakai daftar yang sama.
  - Jadwal: GitHub Actions `.github/workflows/pool-flow-best.yml`, cron `7,22,37,52 * * * *` (tiap 15 menit, UTC).
  - Pemicu utama: cron eksternal memanggil `workflow_dispatch` (GitHub API, ref `main`) tiap 15 menit.
    Jadwal GitHub di atas hanya cadangan karena sering terlewat.
  - Bila tidak ada pool FEE PRINTER, kirim heartbeat `💓 Pool Flow cron jalan` (tanpa mengubah state),
    supaya terlihat cron berjalan.
  - Scan gagal: pesan `❌ Scan gagal`, exit 1. Telegram gagal atau kredensial kosong: exit 1
    dan state tidak disimpan.
  - Setiap pesan: nama, label `[FEE PRINTER]`, tag `🆕 baru` atau `🔁 sudah pernah · alert #N`,
    fee/active TVL, volatility, net deposit, perkalian, peringatan keamanan, tautan, dan tombol 📋 CA.
  - State di `pool_flow_state.json` hanya berubah bila ada alert baru: `best_alert.next_no`,
    `best_alert.last_no[pool]`, dan `alerts` (dibatasi 300 entri).
  - Secret: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

## 7. Yang belum pasti (jangan diasumsikan)

- **Satuan `volatility`** belum terdokumentasi resmi. Kode memperlakukannya sebagai persen
  (`2,98` = 2,98 %). Rumus dan window Meteora belum dikonfirmasi (issue
  https://github.com/MeteoraAg/docs/issues/82 masih terbuka). Jangan menyamakannya dengan
  volatility accumulator on-chain.
- **Perkalian** `fee_active_tvl_ratio × volatility` (2026-11-24) adalah pilihan implementasi
  untuk "hasil perkalian". Bila user punya rumus lain, ubah `fee_active_volatility_product`.
- **Interpretasi "max volatility 3%"** = `volatility ≤ 3` (dalam persen, inklusif).
- **`avg_volume` dan `avg_fee` "per menit"** dipakai apa adanya sesuai label UI.
- **Angka ambang** (3 %, 2 ×, $10.000, dan batas filter server) adalah keputusan user.
  Ubah hanya bila user meminta.

## 8. Ringkas: langkah untuk AI lain

1. `GET` listing 24H dengan curl di bagian 1 (`NOW_MS` = sekarang). Ikuti `after_key` sampai `has_more = false`.
2. Buang duplikat `pool_address`.
3. Buang pool dengan mint/freeze authority aktif atau `top_holders_pct > 30`.
4. Ambil pool dengan `0,01 ≤ volatility ≤ 3`, `fee_active_tvl_ratio ≥ 2 × volatility`, dan `net_deposits ≥ 10.000`.
5. Urut `fee_active_tvl_ratio × volatility` terbesar dulu.
6. Tampilkan atau kirim hanya pool FEE PRINTER tersebut. Jangan memasukkan pool lain ke RINGKASAN.

## 9. Lokasi kode dan tes

- Logika: `pool_flow.py` (`FLOW_*`, `flow_server_filter`, `evaluate_pool`, `fee_printer_ok`,
  `fee_printer_rows`, `fee_active_volatility_product`, `summary_rows`, `summary_alert_text`).
- Tampilan: `pool_flow_ui.py` (`render_pool_flow_page`, `_render_scan_result`, `_render_summary`,
  `_fee_printer_table_html`).
- Alert: `scripts/pool_flow_alert.py`, `.github/workflows/pool-flow-best.yml`.
- Tes: `tests/test_pool_flow.py` (logika, tanpa jaringan), `tests/test_pool_flow_app.py` (halaman dan tabel).

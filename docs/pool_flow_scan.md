# Scan ALL: cara deteksi FEE PRINTER (untuk AI lain)

Dokumen ini merangkum cara kerja fitur **🏆 Scan ALL** (halaman utama, `pool_flow_ui.py`,
logika di `pool_flow.py`, alert di `scripts/pool_flow_alert.py`). Tujuannya: AI lain bisa
mengulang filter, pengurutan, dan penentuan pool terbaik FEE PRINTER tanpa membaca kode.
Angka dan aturan di sini mengikuti kode per commit `f359475` (main). Kalau kode berubah,
perbarui dokumen ini.

## 1. Sumber data: satu listing Meteora

Hanya satu endpoint, tanpa data per token dan tanpa scan lain.

```bash
curl -s "https://pool-discovery-api.datapi.meteora.ag/pools?page_size=50&sort_by=fee_tvl_ratio%3Adesc&timeframe=12h&category=all&filter_by=base_token_has_critical_warnings%3Dfalse%26%26quote_token_has_critical_warnings%3Dfalse%26%26base_token_has_high_supply_concentration%3Dfalse%26%26base_token_has_high_single_ownership%3Dfalse%26%26pool_type%3Ddlmm%26%26tvl%3E%3D10000%26%26fee_tvl_ratio%3E%3D2%26%26fee_pct%3E%3D0.5"
```

Halaman berikutnya memakai cursor. Ambil `after_key` dari respons, lalu tambahkan
`&after_key=<nilai>` ke URL yang sama. Ulangi sampai `has_more` = `false`.

- Parameter `page` diabaikan API dan selalu memberi pool yang sama. Jangan dipakai.
- `filter_by` memakai pemisah `&&` (sama dengan curl pengguna). Urutan parameter harus persis
  sama dengan di atas.
- Batas keamanan: 100 halaman × 50 baris. Cursor yang macet menghentikan pengambilan.
  Hasil ditandai `truncated` bila belum lengkap.
- Kode: `pool_flow.LISTING_12H`, `fetch_top_page`, `fetch_listing`.

Filter server (`FLOW_SERVER_FILTER`) hanya membuang pool yang:
- punya critical warning pada token base atau quote,
- punya konsentrasi supply tinggi atau kepemilikan tunggal tinggi pada token base,
- bukan DLMM, TVL di bawah $10.000, fee/TVL di bawah 2, atau fee tier di bawah 0,5 %.

Tidak ada filter umur token atau pool.

## 2. Bentuk respons (field yang dipakai)

`{"total": N, "page_size": 50, "data": [ ...pool... ], "after_key": "...", "has_more": true|false}`

Setiap elemen `data` adalah satu pool. Field yang dipakai:

| Field | Arti di kode |
|---|---|
| `pool_address` | ID pool. Kunci dedupe. |
| `name` | Nama pool, mis. `FOOD-SOL`. |
| `token_x` / `token_y` | Dua sisi pool. Token non-SOL dianggap token dasar (`mint_of_pool`). |
| `token_x.address`, `.symbol`, `.name` | CA dan nama token. |
| `token_x.has_mint_authority`, `.has_freeze_authority` | `true` = **blokir**. |
| `token_x.top_holders_pct` | % top holder. > 30 blokir, > 15 peringatan. |
| `token_x.dev_balance_pct` | % saldo dev. > 5 peringatan. |
| `token_x.market_cap` | Market cap token dasar (ditampilkan). |
| `fee_tvl_ratio` | **Fee/TVL dalam %, window 12H.** Dasar semua keputusan. |
| `volatility` | **Volatility dalam %.** Dasar semua keputusan. Lihat bagian 8. |
| `fee_pct` | Fee tier pool dalam %. Hanya ditampilkan. |
| `tvl`, `active_tvl` | TVL pool (USD). TVL < $50.000 mengaktifkan cek LP keluar. |
| `total_deposits`, `total_withdraws` | Dipakai untuk peringatan "LP keluar > masuk". |
| `avg_volume` | Avg volume per menit (label UI "Avg volume/menit", dipakai apa adanya). |
| `avg_fee` | Avg fee per menit. Dipakai untuk rasio `avg_fee ÷ tvl`. |
| `volume`, `swap_count`, `unique_traders` | Aktivitas 12H (kolom tabel). |
| `fee_active_tvl_ratio`, `base_token_holders` | Ditampilkan saja. Tidak dipakai untuk keputusan. |

Contoh satu pool (potongan, nilai snapshot FOOD-SOL):

```json
{"pool_address":"DQjZKw199L4788unoRUf9FMw63suJJ45hc9brXV3oQec","name":"FOOD-SOL",
 "token_x":{"address":"FTu55MyigXns96jz4nTCDDiTCjYJjyrHSceCgG9Upump","symbol":"FOOD",
            "has_mint_authority":false,"has_freeze_authority":false,
            "top_holders_pct":15.40,"dev_balance_pct":0.029,"market_cap":114667.84},
 "pool_type":"dlmm","fee_pct":2.0,"tvl":6.93,"fee_tvl_ratio":77.40,"volatility":2.67,
 "avg_volume":0.3519,"avg_fee":0.00745,"volume":253.36,"swap_count":120.0}
```

Catatan: nilai `tvl` pada contoh ini kecil karena snapshot pool itu sangat kecil. Jangan
dipakai sebagai contoh threshold.

## 3. Pipeline (urutan keputusan)

1. **Ambil listing** lengkap (bagian 1).
2. **Dedupe** berdasarkan `pool_address` (baris pertama menang).
3. **Evaluasi tiap pool** (`evaluate_pool`):
   - **BLOKIR** (pool dibuang): mint authority aktif, freeze authority aktif, atau top holders > 30 %.
   - **PERINGATAN** (pool tetap, hanya label): top holders > 15 %, dev > 5 %, atau TVL < $50.000 dan `total_withdraws` > `total_deposits`.
   - Field kosong tidak dihitung sebagai masalah.
4. **Fee/TVL minimal 5 %** (`FLOW_MIN_FEE_TVL_12H`). Pool di bawah itu, atau tanpa nilai, dibuang.
5. Hasil yang lolos = `passing`. Tabel dan RINGKASAN dibentuk dari `passing`.

## 4. Klasifikasi FEE PRINTER

Notasi: `f` = `fee_tvl_ratio` (%), `v` = `volatility` (%), `r` = `f / v`.

Syarat dasar untuk semua kategori FEE: `v` ada dan `v ≥ 0,01 %` (volatility terukur).
Pool dengan `v < 0,01` atau `v` kosong tidak masuk tabel mana pun.

| Kategori (nama di UI) | Syarat | Tampil di |
|---|---|---|
| **FEE PRINTER** (tabel SLOW, dulu "SLOW FEE PRINTER") | `1 ≤ r ≤ 3` (inklusif) di 12H **dan** di 4H (2026-11-23), **dan** `v ≥ 3 %` di 12H **dan** 4H, **dan** `f ≥ 5 %`, **dan** TVL `≥ $20.000`, **dan** volume/TVL 12H `≥ 100 %` (`volume_tvl_ratio`), **dan** umur pool `≥ 12 jam` (`pool_created_at`, 2026-11-22) | Tabel sendiri **dan RINGKASAN + alert Telegram** |
| FEE PRINTER (SPOT), internal | `r > 2` | Tidak ditampilkan (HIGH RISK dihapus 2026-11-23) |
| (tidak tampil) | `r` 2–3,5 tapi `f < 10 %`; `r > 3,5` | Tidak ditampilkan di mana pun |

Urutan pengecekan di kode (`fee_printer_split`):
1. Jika `r > 2` → FEE PRINTER (SPOT), daftar penuh. Tidak ditampilkan. Berdiri sendiri: pool di 2–3 × bisa juga masuk band (langkah 2).
2. Jika `1 ≤ r ≤ 3` dan `v ≥ 3` dan `f ≥ 5` dan TVL `≥ 20.000` (12H), dan volume/TVL 12H `≥ 100 %` (`volume_tvl_ratio`), dan umur pool `≥ 12 jam` (`pool_created_at` ms; tanpa data = tidak lolos), dan rasio 4H `1 ≤ r4 ≤ 3` dengan `v4 ≥ 3` (data 4H dari listing 4H; tanpa data = tidak lolos) → FEE PRINTER (band).

Contoh hitung (dari tes):
- `f = 10`, `v = 10` → `r = 1` → FEE PRINTER (band). Lolos.
- `f = 9,5`, `v = 3,07` → `r = 3,09` tapi `f < 10` → **tidak tampil**. Pool ini sengaja tersembunyi.
- `f = 4,9`, `v = 5` → gagal fee/TVL 5 % sebelum klasifikasi.

## 5. Pengurutan

- **Listing umum:** `sort_key` = `−(avg_volume ÷ tvl)`.
  Terbesar dulu. Seri mengikuti urutan listing (sort stabil).
- **Tabel FEE PRINTER (band) dan RINGKASAN:** `sort_key_slow` = `|f − v|` (selisih persen poin),
  **terkecil dulu**. Artinya pool yang paling seimbang (fee/TVL paling dekat volatility) di atas.
  Seri mengikuti urutan listing.
- Kolom tambahan di tabel FEE PRINTER: `Fee/TVL ÷ volatility` (`r`, tampil `1,50×`) dan
  `Selisih fee/TVL − volatility` (`f − v`, tampil `+2,00%`). Keduanya hanya tampilan.

## 6. Pool terbaik

- **Pool terbaik FEE PRINTER** = baris pertama tabel FEE PRINTER = nilai `|f − v|` terkecil
  di antara pool band. Itu pool paling seimbang.
- **Baris kuning di tabel** = `most_crowded(result)` = pool dengan `avg_volume ÷ tvl`
  terbesar di **seluruh** `passing`, bukan di tabel FEE PRINTER. Jangan tertukar dengan
  pool terbaik FEE PRINTER.
- Jika band kosong, tidak ada pool FEE PRINTER terbaik.

## 7. RINGKASAN dan alert Telegram

- **RINGKASAN** di halaman = `summary_rows(result)`: hanya pool dari band (FEE PRINTER),
  dengan urutan yang sama seperti tabel. Kolom: Token/pool, Asal tabel (selalu "FEE PRINTER"),
  Fee/TVL, Volatility.
- **Alert Telegram** (`scripts/pool_flow_alert.py`) memakai daftar yang sama.
  - Jadwal: GitHub Actions `.github/workflows/pool-flow-best.yml`, cron `7,22,37,52 * * * *` (tiap 15 menit, UTC).
  - Pemicu utama: cron eksternal memanggil `workflow_dispatch` (GitHub API, ref `main`) tiap 15 menit. Jadwal GitHub di atas hanya cadangan karena sering terlewat.
  - Bila band kosong, kirim heartbeat `💓 Pool Flow cron jalan` (tanpa mengubah state), supaya terlihat cron berjalan.
  - Scan gagal: pesan `❌ Scan gagal`, exit 1. Telegram gagal atau kredensial kosong: exit 1 dan state tidak disimpan.
  - Setiap pesan: nama, label `[FEE PRINTER]`, tag `🆕 baru` atau `🔁 sudah pernah · alert #N`,
    fee/TVL, volatility, peringatan keamanan, tautan, dan tombol 📋 CA.
  - Status tersimpan di `pool_flow_state.json`: `best_alert.next_no`, `best_alert.last_no[pool]`,
    dan `alerts` (dibatasi 300 entri).
  - Secret: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

## 8. Yang belum pasti (jangan diasumsikan)

- **Satuan dan window `volatility`** belum terdokumentasi. Kode memperlakukannya sebagai
  persen (`2,67` = 2,67 %). Rumus dan window Meteora belum dikonfirmasi (issue
  https://github.com/MeteoraAg/docs/issues/82 masih terbuka). Jangan menyamakannya dengan
  volatility accumulator on-chain.
- **`avg_volume` dan `avg_fee` "per menit"** dipakai apa adanya sesuai label UI. Pembagian
  menit untuk window 12H tidak diverifikasi ulang di sini.
- **Angka ambang** (2×, 1×, 3×, 2,5×, 3,5×, 5 % untuk fee/TVL dan volatility) adalah
  keputusan pengguna. Ubah hanya bila pengguna meminta.

## 9. Ringkas: langkah untuk AI lain

1. `GET` listing 12H dengan curl di atas. Ikuti `after_key` sampai `has_more = false`.
2. Buang duplikat `pool_address`.
3. Buang pool dengan mint/freeze authority aktif atau `top_holders_pct > 30`.
4. Buang pool dengan `fee_tvl_ratio < 5` atau kosong.
5. `r = fee_tvl_ratio / volatility`. Buang pool dengan `volatility < 0,01` atau kosong.
6. Klasifikasi sesuai bagian 4.
7. FEE PRINTER (band) = `1 ≤ r ≤ 3` (12H dan 4H), `volatility ≥ 3`, `fee_tvl_ratio ≥ 5`, TVL ≥ 20.000, volume/TVL 12H ≥ 100 %, umur pool ≥ 12 jam, dan cek yang sama di 4H (`volatility4h ≥ 3`, `1 ≤ r4 ≤ 3`).
   Urut `|fee_tvl_ratio − volatility|` terkecil dulu. Baris pertama = pool terbaik.
8. Tampilkan atau kirim hanya pool FEE PRINTER. Jangan memasukkan pool lain
   ke RINGKASAN.

## 10. Lokasi kode dan tes

- Logika: `pool_flow.py` (`FLOW_*`, `evaluate_pool`, `fee_printer_split`, 
  `sort_key`, `sort_key_slow`, `summary_rows`, `summary_alert_text`).
- Tampilan: `pool_flow_ui.py` (`render_pool_flow_page`, `_render_scan_result`, `_render_summary`).
- Alert: `scripts/pool_flow_alert.py`, `.github/workflows/pool-flow-best.yml`.
- Tes: `tests/test_pool_flow.py` (logika), `tests/test_pool_flow_app.py` (halaman dan tabel).

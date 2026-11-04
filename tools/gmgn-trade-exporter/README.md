# GMGN Trade Exporter (ekstensi Chrome)

Ekstensi Chrome (Manifest V3) untuk mengunduh riwayat trade satu token Solana dari GMGN ke **satu file CSV** untuk rentang waktu tertentu. Waktu dihitung dalam **WIB (UTC+7)**.

Kolom CSV: `waktu_wib, unix_ts, side, usd, price_usd, token_amount, quote_amount, wallet, tx_hash, row_id, tags`.

## Pasang (mode developer)

1. Buka `chrome://extensions`.
2. Aktifkan **Developer mode** (pojok kanan atas).
3. Klik **Load unpacked**, lalu pilih folder `tools/gmgn-trade-exporter/`.
4. Buka halaman token di GMGN, misalnya `https://gmgn.ai/sol/token/<CA>`.
5. Klik ikon ekstensi. CA terisi otomatis dari URL tab.
6. Isi rentang **Dari** dan **Sampai** (WIB), pilih jenis trade dan min USD, lalu klik **Ambil & unduh CSV**.

Contoh untuk buy di atas $100 pada 4 Nov 2026, 03:00–07:00 WIB: Dari `2026-11-04T03:00`, Sampai `2026-11-04T07:00`, Jenis `Buy saja`, Min USD `100`.

## Cara kerja

- Fetch dijalankan **di dalam tab GMGN** (`chrome.scripting`, world `MAIN`), jadi cookie dan header browser ikut terkirim seperti web client. Karena itu, tab GMGN harus tetap terbuka selama proses berjalan.
- Endpoint yang dipakai sama dengan `cvd.py` di repo ini: `https://gmgn.ai/vas/api/v1/token_trades/sol/{ca}` dengan `limit=100`, `from`, `to`, dan `cursor`.
- Pagination mengikuti `data.next` dari respons. `next` sama dengan `id` baris terakhir. Bila `next` tidak ada, data dianggap habis.
- Filter waktu dilakukan di sisi klien (`from` tidak selalu dihormati GMGN). `to` diperlakukan sebagai batas atas eksklusif.
- Trade duplikat dibuang berdasarkan `id` (per baris). Satu `tx_hash` bisa memuat beberapa baris (mis. multi-leg), jadi `tx_hash` tidak boleh dipakai untuk dedupe.
- Halaman GMGN berisi 50 baris (meski `limit=100`). Halaman terakhir tidak punya `next`.
- Gagal jaringan dicoba ulang 3 kali dengan jeda 1, 2, dan 4 detik. Bila tetap gagal, hasil parsial tetap ditampilkan dengan peringatan.
- Jeda 200 ms antar halaman.

## Batasan yang perlu diketahui

- **Saya belum menguji ekstensi ini di Chrome sungguhan.** Sandbox tempat kode ini ditulis tidak bisa mengakses GMGN. Logika murni (`lib.js`) sudah diuji dengan 17 tes Node (`node --test tools/gmgn-trade-exporter/lib.test.js`) dan dijalankan pada respons GMGN nyata (1.079 baris, 22 halaman, tanpa duplikat). Hasil JS dicocokkan dengan Python.
- Nama field sudah dicocokkan dengan respons GMGN nyata (`event`, `amount_usd`, `quote_amount`, `maker`, `timestamp`, `tx_hash`, `id`, `maker_tags`, `maker_token_tags`). Angka dikirim sebagai string dan sudah di-parse. Jika kolom kosong di CSV, unduh **JSON mentah (debug)** dan kirimkan.
- Jika GMGN menolak permintaan (mis. error kode non-0 atau HTTP 4xx), kemungkinan parameter perangkat yang dipakai web client hilang: `device_id`, `fp_did`, `client_id`, atau `app_ver`. Salin parameter itu dari tab Network DevTools saat halaman GMGN memuat `token_trades`, lalu tambahkan di `buildTradeUrl` pada `lib.js`.
- Ekstensi ini **tidak** mengambil saldo SOL wallet. Saldo per wallet di luar top 30 holder belum terbaca dari GMGN (endpoint `wallet_holdings` mengembalikan HTTP 500 pada tes sebelumnya).
- Ekstensi ini hanya membaca data publik yang tampil di GMGN. Tetap perhatikan ketentuan layanan GMGN dan jangan memakainya dengan frekuensi yang membebani server.

## Uji

```
node --test tools/gmgn-trade-exporter/lib.test.js
```

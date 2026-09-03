# Deploy

## Streamlit

- Entry point: `app.py`
- Python: lihat `runtime.txt`
- Dependencies: `requirements.txt`
- Secrets scanner utama: `HELIUS_API_KEY`/`HELIUS_API_KEYS` dan
  `GITHUB_TOKEN`.
- Secrets alert Telegram opsional: `TELEGRAM_BOT_TOKEN` dan
  `TELEGRAM_CHAT_ID`.

Watchlist di halaman utama menarik `holder_status.json` dari ref
`holder-live` (bukan commit `main`). Tombol **Scan holder watchlist**
menjalankan analisis holder lokal. Chart 📈 membuka halaman CVD.

## GitHub Actions

Workflow `.github/workflows/daily-effort.yml` ("Holder Dust Scanner")
berjalan setiap 15 menit dan memanggil `python scripts/scan_holders.py`.

Langkah setiap scan:

1. Analisis per token: holder Helius DAS (fallback GMGN, max 3000 wallet),
   klasifikasi real (>$10) vs dust, `dust_pct_mc`, mid-tier, dan kohort.
2. Evaluasi alert terhadap snapshot lama **sebelum** snapshot terbaru
   ditulis. Snapshot wallet disimpan secara bounded di history/status.
3. Publish `holder_status.json` ke branch `holder-live` (dibuat otomatis
   pada publish pertama) agar dashboard dan cron memakai state yang sama.

Workflow memerlukan permission berikut:

```yaml
permissions:
  contents: write
```

Environment step scanner:

```yaml
env:
  GITHUB_TOKEN: ${{ secrets.GH_TOKEN || secrets.GITHUB_TOKEN }}
  HELIUS_API_KEY: ${{ secrets.HELIUS_API_KEY }}
  HELIUS_API_KEYS: ${{ secrets.HELIUS_API_KEYS }}
  TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
  TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
```

`HELIUS_API_KEY` wajib untuk hasil holder yang andal di Actions karena GMGN
sering memblokir runner. `GH_TOKEN` opsional bila token bawaan tidak memiliki
permission publish. Scanner exit non-zero bila semua token menghasilkan nol
holder atau publish status gagal.

## Setup Telegram

1. Buat bot melalui **@BotFather** dan salin token bot.
2. Tambahkan bot ke chat/grup tujuan. Untuk grup, pastikan bot dapat mengirim
   pesan.
3. Dapatkan chat ID, misalnya dari update bot (`getUpdates`) setelah mengirim
   pesan ke bot/grup. Chat ID grup biasanya bernilai negatif.
4. Di GitHub buka **Settings → Secrets and variables → Actions → New
   repository secret**, lalu simpan dua secret terpisah:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

Jangan menaruh nilainya di repository, workflow, log, `config.json`, atau
Streamlit source. Credential kosong/tidak valid tidak menghentikan scan;
pengiriman dilewati atau dicatat sebagai warning tanpa membocorkan token.

### Test pengiriman

Setelah kedua secret tersimpan, buka **Actions → Holder Dust Scanner → Run
workflow**, aktifkan input **Kirim test alert Telegram sebelum scan**, lalu
jalankan. Workflow meneruskan flag `--telegram-test` dan mengirim pesan yang
jelas bertanda `TEST ALERT HOLDER DUST`; pesan tersebut bukan sinyal token.

Untuk environment lokal yang sudah memiliki kedua environment variable:

```bash
python scripts/scan_holders.py --telegram-test --no-push
```

Perintah itu tetap melanjutkan scan normal setelah mencoba pesan test.

> GitHub App tertentu tidak bisa mengubah file workflow tanpa permission
> `workflows`. Jika push workflow ditolak, perubahan perlu diterapkan oleh
> pemilik repository dengan permission tersebut.

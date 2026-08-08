# Workflow Patch — CVD Detail & Top Holder Snapshot per 4 Jam (manual via GitHub web)

> **Arena GitHub App tidak punya izin `workflows`**, sehingga penambahan/perubahan file di dalam direktori `.github/workflows/` tidak dapat di-push langsung via git. Owner perlu menambahkan file workflow ini secara manual melalui antarmuka web GitHub.

---

## 1. Buat workflow baru `cvd-detail.yml`

Di repo GitHub → direktori `.github/workflows/` → klik **Add file** → **Create new file**.  
Beri nama file: `.github/workflows/cvd-detail.yml` dan salin-tempel isi YAML di bawah ini:

```yaml
name: CVD Detail & Top Holders (4-Hourly)

on:
  schedule:
    - cron: "0 */4 * * *"   # 00, 04, 08, 12, 16, 20 UTC (= 07, 11, 15, 19, 23, 03 WIB)
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  update-4h:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install deps
        run: pip install requests pandas curl_cffi base58
      - name: Update 4-Hourly CVD Detail, Conviction & Holder Snapshots
        env:
          HELIUS_API_KEY: ${{ secrets.HELIUS_API_KEY }}
          HELIUS_API_KEYS: ${{ secrets.HELIUS_API_KEYS }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python scripts/update_cvd.py 60
      - name: Commit data
        run: |
          git config user.name "prepump-bot"
          git config user.email "actions@github.com"
          git stash -u || true
          git pull --rebase || true
          git stash pop || true
          for f in cvd.json signals.json conviction.json history.json watchlist.json holder_snapshots.json real_dust_history.json; do
            if grep -q "<<<<<<<" "$f" 2>/dev/null; then
              git checkout --theirs "$f" 2>/dev/null || git checkout HEAD -- "$f" || true
            fi
          done
          git add cvd.json signals.json conviction.json history.json watchlist.json 2>&1 || true
          git add holder_snapshots.json real_dust_history.json 2>&1 || true
          git add watchlist_pending.json 2>&1 || true
          git diff --cached --quiet || git commit -m "chore: cvd detail & top holders 4h $(date -u +%FT%H:%M) UTC"
          git push || (git pull --rebase && git push) || true
```

---

## 2. Update opsional pada `daily-prepump.yml`

Agar cron harian (`daily-prepump.yml`, 07:00 WIB) juga turut meng-commit file `holder_snapshots.json` dan `real_dust_history.json` jika ada update snapshot baru, edit file `.github/workflows/daily-prepump.yml` pada bagian step `Commit data` menjadi:

```yaml
          for f in cvd.json signals.json conviction.json history.json watchlist.json holder_snapshots.json real_dust_history.json; do
            if grep -q "<<<<<<<" "$f" 2>/dev/null; then
              git checkout --theirs "$f" 2>/dev/null || git checkout HEAD -- "$f" || true
            fi
          done
          git add cvd.json signals.json conviction.json history.json watchlist.json 2>&1 || true
          git add holder_snapshots.json real_dust_history.json 2>&1 || true
          git add watchlist_pending.json 2>&1 || true
```

---

## 3. Yang telah diperbarui di kode (sudah di-push via Git)

1. **`scripts/update_cvd.py`**:
   - Menjalankan kembali fungsi `_try_snapshot()` untuk mengumpulkan data top holder baik menggunakan Helius (jika API keys dikonfigurasi) maupun GMGN (`gmgn_token_stat`).
   - Menyimpan histori snapshot ke `holder_snapshots.json` dan `real_dust_history.json`.
   - Menghitung metrik Top Holder (`diamond_pct`, `real_holders`, `dust_holders`) dan mengupdate langsung ke metadata di `watchlist.json` sehingga kolom **Diamond** dan **Real/Dust** pada tabel Watchlist tidak lagi kosong (`—`).

2. **`app.py`**:
   - Fungsi `get_watchlist_details()` membaca metadata hasil perhitungan cron serta memiliki fallback lokal ke file `holder_snapshots.json`, `real_dust_history.json`, dan fallback live ke GMGN `token_stat`.

3. **`pages/4_📊_CVD.py`**:
   - Fungsi `fetch_holder_snapshot()` mendukung fallback ke snapshot cron di `holder_snapshots.json` atau GMGN jika Helius API key tidak dikonfigurasi di rahasia Streamlit.

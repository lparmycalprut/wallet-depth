# Workflow Patch — Daily Prepump 07:00 WIB (manual via GitHub web)

> **Arena GitHub App tidak punya izin `workflows`**, jadi perubahan `.github/workflows/` tidak bisa di-push via git. Owner harus lakukan manual via web GitHub.

## Yang harus dilakukan di GitHub web

### 1. Hapus 5 workflow lama

Di repo → `.github/workflows/` → hapus:

- `cto-radar.yml` (15 * * * *)
- `cvd-update.yml` (30 * * * * hourly)
- `lp-safe-radar.yml` (25 * * * *)
- `memecoin-scanner.yml` (*/15 * * * *)
- `daily-snapshot.yml` (30 0 * * * 07:30 WIB)

Cara: buka file → **Delete file** → Commit. Atau Disable via Actions.

### 2. Buat workflow baru `daily-prepump.yml`

Buat file baru `.github/workflows/daily-prepump.yml` dengan isi di bawah (copy-paste tepat):

```yaml
name: Daily Prepump BARU (07:00 WIB)

on:
  schedule:
    - cron: "0 0 * * *"   # 07:00 WIB = 00:00 UTC (GMGN candle flip)
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  daily:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install deps
        run: pip install requests pandas curl_cffi base58
      - name: Daily CVD + Prepump BARU (07:00 WIB)
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
          for f in cvd.json signals.json conviction.json history.json watchlist.json; do
            if grep -q "<<<<<<<" "$f" 2>/dev/null; then
              git checkout --theirs "$f" 2>/dev/null || git checkout HEAD -- "$f" || true
            fi
          done
          git add cvd.json signals.json conviction.json history.json watchlist.json 2>&1 || true
          git add watchlist_pending.json 2>&1 || true
          git diff --cached --quiet || git commit -m "chore: daily prepump BARU $(date -u +%FT%H:%M) 07:00 WIB"
          git push || (git pull --rebase && git push) || true
```

### 3. Verifikasi

- Actions → **Daily Prepump BARU (07:00 WIB)** → **Run workflow** untuk test.
- Cek `cvd.json`, `signals.json` (tipe `prepump_baru_muncul`), `history.json` ter-update.
- Telegram: digest **sehari sekali 07:00 WIB** jika ada sinyal BARU (bukan per jam).

## Cron lama yang harus dihapus

| File lama | Schedule | Fungsi |
|---|---|---|
| `cto-radar.yml` | `15 * * * *` | CTO radar hourly |
| `cvd-update.yml` | `30 * * * *` | CVD hourly |
| `lp-safe-radar.yml` | `25 * * * *` | LP radar hourly |
| `memecoin-scanner.yml` | `*/15 * * * *` | Memecoin 15m |
| `daily-snapshot.yml` | `30 0 * * *` | Snapshot 07:30 WIB |

Semua diganti single daily 07:00 WIB (00:00 UTC).

## File lokal yang sudah siap

`scripts/update_cvd.py` sudah di-update ke daily 07:00 WIB + `prepump_baru_detector.py` (7 checks validated). `app.py` kolom Sinyal sekarang dari `prepump_baru_detector` (bukan 4-pillar lama).

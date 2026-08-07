# Workflow Patch — Daily Prepump 00:00 WIB (manual via GitHub web)

> **Arena GitHub App tidak punya izin `workflows`**, jadi perubahan `.github/workflows/` tidak bisa di-push via git. Owner harus lakukan manual via web GitHub (Settings → Actions atau langsung edit file di repo).

## Yang harus dilakukan di GitHub web

### 1. Hapus 5 workflow lama

Di repo → tab **Actions** → atau via file browser `.github/workflows/` → hapus:

- `cto-radar.yml` (15 * * * *)
- `cvd-update.yml` (30 * * * * hourly)
- `lp-safe-radar.yml` (25 * * * *)
- `memecoin-scanner.yml` (*/15 * * * *)
- `daily-snapshot.yml` (30 0 * * * 07:30 WIB)

Cara: buka file → klik **Delete file** (ikon tong sampah) → Commit.

Atau nonaktifkan dulu: Actions → pilih workflow → **Disable workflow**.

### 2. Buat workflow baru `daily-prepump.yml`

Buat file baru `.github/workflows/daily-prepump.yml` dengan isi di bawah (copy-paste tepat):

```yaml
name: Daily Prepump (00:00 WIB)

on:
  schedule:
    - cron: "0 17 * * *"   # 00:00 WIB = 17:00 UTC
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
      - name: Daily CVD + Prepump + Telegram (00:00 WIB)
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
          git diff --cached --quiet || git commit -m "chore: daily prepump $(date -u +%FT%H:%M) 00:00 WIB"
          git push || (git pull --rebase && git push) || true
```

Commit via web: **Create new file** → paste → **Commit new file**.

### 3. Verifikasi

- Actions → **Daily Prepump (00:00 WIB)** → **Run workflow** (manual dispatch) untuk test.
- Cek `cvd.json`, `signals.json`, `conviction.json`, `history.json` ter-update.
- Cek Telegram: hanya jika ada sinyal `prepump_imminent` (≥75) atau `forming` (jika focus_mode OFF), akan ada **satu** digest per hari.

## Cron lama yang harus dihapus (detail)

| File lama | Schedule | Fungsi |
|---|---|---|
| `cto-radar.yml` | `15 * * * *` | CTO incubation radar hourly |
| `cvd-update.yml` | `30 * * * *` | CVD hourly GMGN |
| `lp-safe-radar.yml` | `25 * * * *` | LP safe radar hourly |
| `memecoin-scanner.yml` | `*/15 * * * *` | Memecoin scanner 15 menit |
| `daily-snapshot.yml` | `30 0 * * *` | Snapshot 07:30 WIB |

Semua diganti single daily 00:00 WIB.

## File lokal yang sudah siap

`scripts/update_cvd.py` sudah di-update ke daily only (00:00 WIB) di commit ini. Workflow baru akan memanggilnya.

```

cat /home/user/wallet-depth/docs/WORKFLOW_PATCH_daily_prepump.md
git -C /home/user/wallet-depth add docs/WORKFLOW_PATCH_daily_prepump.md 2>&1 | head -n 20
git -C /home/user/wallet-depth status --short 2>&1 | head -n 100

#!/usr/bin/env bash
# Commit sweep_state.json ke main dengan retry.
#
# Masalah yang diperbaiki: app (auto-refresh) juga push state ke main. Bila push
# bot ditolak karena main sudah berubah, versi lama tidak boleh dipaksakan dan
# snapshot jam tidak boleh hilang. Karena itu tiap percobaan: ambil main terbaru,
# gabung state bot dengan versi itu (merge_sweep_state.py), lalu push ulang.
set -uo pipefail

STATE=sweep_state.json
BOT_COPY=$(mktemp)
REMOTE_COPY=$(mktemp)
MERGED_COPY=$(mktemp)
cp "$STATE" "$BOT_COPY" || exit 1

for attempt in 1 2 3 4 5; do
  if ! git fetch -q origin main; then
    echo "fetch gagal (percobaan $attempt)" >&2
    sleep $((attempt * 3))
    continue
  fi
  if ! git show "origin/main:$STATE" > "$REMOTE_COPY" 2>/dev/null; then
    echo '{}' > "$REMOTE_COPY"   # berkas belum ada di main
  fi
  python scripts/merge_sweep_state.py "$BOT_COPY" "$REMOTE_COPY" "$MERGED_COPY" || exit 1
  git reset -q --hard origin/main || exit 1
  cp "$MERGED_COPY" "$STATE" || exit 1
  git add "$STATE" || exit 1
  if git diff --cached --quiet; then
    echo "Tidak ada perubahan state setelah merge."
    exit 0
  fi
  git commit -q -m "sweep: update state [skip ci]" || exit 1
  if git push -q origin HEAD:main; then
    echo "State ter-push (percobaan $attempt)."
    exit 0
  fi
  echo "Push ditolak (percobaan $attempt); ulangi dengan state terbaru." >&2
  sleep $((attempt * 3))
done

echo "Gagal push state setelah 5 percobaan." >&2
exit 1

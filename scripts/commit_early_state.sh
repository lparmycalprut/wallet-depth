#!/usr/bin/env bash
# Commit early_watch_state.json ke main dengan retry.
#
# Hanya job early-watch yang menulis berkas ini, dan grup concurrency
# `early-watch` membuat job berjalan berurutan. Karena itu tidak perlu merge
# seperti sweep_state.json. Bila push ditolak, skrip mengambil main terbaru
# lalu menimpa berkas dengan state dari job ini (state ini paling baru).
set -uo pipefail

STATE=early_watch_state.json
BOT_COPY=$(mktemp)
cp "$STATE" "$BOT_COPY" || exit 1

for attempt in 1 2 3 4 5; do
  if ! git fetch -q origin main; then
    echo "fetch gagal (percobaan $attempt)" >&2
    sleep $((attempt * 3))
    continue
  fi
  git reset -q --hard origin/main || exit 1
  cp "$BOT_COPY" "$STATE" || exit 1
  git add "$STATE" || exit 1
  if git diff --cached --quiet; then
    echo "Tidak ada perubahan state."
    exit 0
  fi
  git commit -q -m "early-watch: update state [skip ci]" || exit 1
  if git push -q origin HEAD:main; then
    echo "State ter-push (percobaan $attempt)."
    exit 0
  fi
  echo "Push ditolak (percobaan $attempt); ulangi." >&2
  sleep $((attempt * 3))
done

echo "Gagal push state setelah 5 percobaan." >&2
exit 1

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gabung ``sweep_state.json`` hasil cron dengan versi terbaru di GitHub.

Dipanggil oleh ``scripts/commit_sweep_state.sh`` saat push state ditolak karena
app (atau run lain) sudah push lebih dulu::

    python scripts/merge_sweep_state.py LOCAL REMOTE OUT

Logika penggabungan ada di :func:`sweep_store.merge_states`.
"""
from __future__ import annotations

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import sweep_store as store  # noqa: E402


def _load(path: str, *, required: bool) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        if required:
            raise
        return {}
    return data if isinstance(data, dict) else {}


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3:
        print("usage: merge_sweep_state.py LOCAL REMOTE OUT", file=sys.stderr)
        return 2
    local_path, remote_path, out_path = args
    try:
        local = _load(local_path, required=True)
    except (OSError, ValueError) as exc:
        print(f"state lokal tidak terbaca: {exc}", file=sys.stderr)
        return 1
    remote = _load(remote_path, required=False)
    merged = store.prune(store.merge_states(local, remote))
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(merged, handle, separators=(",", ":"))
    print(f"merged: {len(merged.get('snapshots') or {})} mint, "
          f"{len(merged.get('signals') or [])} sinyal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

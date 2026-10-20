# -*- coding: utf-8 -*-
"""Cek sweep manual untuk **satu** CA (permintaan user 2026-10-20).

Berbeda dengan watchlist:

- tidak menambah mint ke watchlist dan tidak menulis snapshot/view ke
  ``sweep_state.json`` (state dibaca, lalu dipakai sebagai salinan);
- tidak mengirim alert Telegram dan tidak mencatat sinyal ke statistik;
- tetap memakai riwayat tersimpan (latch shakeout permanen, latch kohort,
  riwayat harga) bila mint itu sudah pernah dipindai, supaya hasilnya sejalan
  dengan watchlist.

Vonis, kriteria, dan filter tetap datang dari :func:`sweep_scan.run_scan`.
Modul ini tidak menambah aturan baru.
"""
from __future__ import annotations

import copy
import re
import time

import sweep_scan as scan
import sweep_store as store

#: Alamat token Solana: base58, 32–44 karakter (tanpa 0, O, I, l).
_SOLANA_CA_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def parse_single_ca(raw) -> tuple:
    """Validasi input satu CA. Mengembalikan ``(mint, error)``.

    Tepat satu CA diterima. Input kosong, lebih dari satu CA, atau format
    yang bukan base58 Solana ditolak dengan pesan yang bisa ditampilkan.
    """
    mints = store.parse_mints(raw or "")
    if not mints:
        return "", "Masukkan satu CA token."
    if len(mints) > 1:
        return "", (f"Masukkan hanya satu CA (terdeteksi {len(mints)}). "
                    "Untuk banyak token gunakan halaman 🌊 Sweep.")
    mint = mints[0]
    if not _SOLANA_CA_RE.match(mint):
        return "", ("CA tidak valid: harus alamat Solana base58 "
                    "32–44 karakter.")
    return mint, ""


def check_mint(mint: str, *, now: int | None = None, state: dict | None = None,
               use_cache: bool = False) -> dict:
    """Pindai satu mint sekali jalan dan kembalikan barisnya tanpa menyimpannya.

    Hasil: ``{"ok", "error", "row", "ts", "in_watchlist"}``. ``row`` memakai
    bentuk yang sama dengan baris hasil :func:`sweep_scan.run_scan`, ditambah
    ``ts`` (waktu pemindaian) agar bisa dirender oleh komponen detail.
    """
    ts = int(now if now is not None else time.time())
    if state is None:
        # Salinan: latch dan riwayat tersimpan dibaca, tidak pernah ditulis balik.
        state = copy.deepcopy(store.load_state())
    try:
        outcome = scan.run_scan([mint], state=state, use_cache=use_cache,
                                send_alerts=False, persist=False, workers=1,
                                now=ts)
    except Exception as exc:  # noqa: BLE001 - tampilkan, jangan crash halaman
        return {"ok": False, "error": f"pemindaian gagal: {str(exc)[:160]}",
                "row": None, "ts": ts, "in_watchlist": False}

    row = next((r for r in outcome.get("rows") or []
                if r.get("mint") == mint), None)
    if row is None:
        return {"ok": False, "error": "tidak ada hasil untuk CA ini.",
                "row": None, "ts": ts, "in_watchlist": False}

    metrics = row.get("metrics") or {}
    row = {**row, "ts": ts}
    in_watchlist = mint in store.load_watchlist()
    if not metrics.get("ok"):
        return {"ok": False,
                "error": metrics.get("error") or "sumber data tidak merespons",
                "row": row, "ts": ts, "in_watchlist": in_watchlist}
    return {"ok": True, "error": "", "row": row, "ts": ts,
            "in_watchlist": in_watchlist}

# -*- coding: utf-8 -*-
"""Build a self-contained, honest CVD prompt for a free AI chat.

This module is deliberately UI-free and network-free so prompt contents can
be tested without starting Streamlit or touching production data files.
"""
from datetime import datetime, timezone
import math

from cvd import (WHALE_SOL, conviction_split, flow_report,
                 wallet_profiles)

PERIOD_COUNT = 4


def _number(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _hours(value):
    value = _number(value)
    return f"{value:.0f}" if value.is_integer() else f"{value:.1f}"


def _short_wallet(wallet):
    wallet = str(wallet or "?")
    return wallet if len(wallet) <= 16 else f"{wallet[:8]}…{wallet[-4:]}"


def _cell(value):
    return str(value or "—").replace("|", "\\|").replace("\n", " ")


def _clean_swaps(swaps):
    out = []
    for swap in swaps or []:
        try:
            side, sol, ts, wallet = swap[:4]
            sol, ts = float(sol), float(ts)
        except (IndexError, TypeError, ValueError):
            continue
        if side not in ("buy", "sell") or not math.isfinite(sol) or sol < 0:
            continue
        if not math.isfinite(ts) or ts <= 0:
            continue
        out.append((side, sol, ts, str(wallet or "?")))
    return sorted(out, key=lambda swap: swap[2])


def _timeline_table(swaps, requested_hours, now_ts, period_count):
    """Return oldest-to-newest flow periods anchored to ``now_ts``."""
    count = max(2, min(int(period_count or PERIOD_COUNT), 12))
    width = requested_hours / count
    lines = [
        "| Urutan waktu | Rentang UTC | Swap | Net CVD | Whale | Retail | "
        "Pure buy | Pure sell | Conviction |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for index in range(count):
        older_h = requested_hours - index * width
        newer_h = max(0.0, requested_hours - (index + 1) * width)
        start = now_ts - older_h * 3600
        end = now_ts - newer_h * 3600
        segment = [s for s in swaps
                   if start <= s[2] < end or
                   (index == count - 1 and start <= s[2] <= end)]
        flow = flow_report(segment)
        profiles = wallet_profiles(segment)
        conv = conviction_split(profiles, whale_min_sol=WHALE_SOL)
        start_s = datetime.fromtimestamp(start, timezone.utc).strftime(
            "%m-%d %H:%M")
        end_s = datetime.fromtimestamp(end, timezone.utc).strftime(
            "%m-%d %H:%M")
        newest = "sekarang" if newer_h == 0 else f"T-{_hours(newer_h)}h"
        label = f"T-{_hours(older_h)}h → {newest}"
        lines.append(
            f"| {label} | {start_s} → {end_s} | {flow['n']} | "
            f"{flow['net']:+.1f} | {flow['whale_net']:+.1f} | "
            f"{flow['retail_net']:+.1f} | {flow['pure_buy']:.1f} | "
            f"{flow['pure_sell']:.1f} | "
            f"{conv['conviction_pct']:.1f}% |")
    return "\n".join(lines)


def _window_table(window_stats, max_hours=None):
    lines = [
        "| Window | Swap | Net CVD | Whale | Retail | Pure buy | "
        "Pure sell | Net pure | Conviction | Verdict dashboard |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for window in sorted(window_stats or {}, reverse=True):
        if max_hours is not None and _number(window) > max_hours:
            continue
        stats = window_stats[window] or {}
        lines.append(
            f"| {_hours(window)}h | {int(_number(stats.get('swaps')))} | "
            f"{_number(stats.get('net')):+.1f} | "
            f"{_number(stats.get('whale_net')):+.1f} | "
            f"{_number(stats.get('retail_net')):+.1f} | "
            f"{_number(stats.get('pure_buy')):.1f} | "
            f"{_number(stats.get('pure_sell')):.1f} | "
            f"{_number(stats.get('net_pure')):+.1f} | "
            f"{_number(stats.get('conviction')):.1f}% | "
            f"{_cell(stats.get('verdict'))} |")
    if len(lines) == 2:
        lines.append("| — | 0 | +0.0 | +0.0 | +0.0 | 0.0 | 0.0 | "
                     "+0.0 | 0.0% | data tidak tersedia |")
    return "\n".join(lines)


def _wallet_table(wallet_rows):
    lines = [
        "| Dompet | Peran | Buy SOL | Sell SOL | Net SOL | Swap | "
        "Umur 🐣/🌱/🌳 | Flags |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for row in (wallet_rows or [])[:20]:
        buy = _number(row.get("buy"))
        sell = _number(row.get("sell"))
        age = _cell(row.get("age"))
        if not any(icon in age for icon in ("🐣", "🌱", "🌳")):
            age = "❓ tidak diketahui"
        lines.append(
            f"| {_short_wallet(row.get('wallet'))} | "
            f"{_cell(row.get('role'))} | {buy:.1f} | {sell:.1f} | "
            f"{buy - sell:+.1f} | {int(_number(row.get('swaps')))} | "
            f"{age} | {_cell(row.get('flags'))} |")
    if len(lines) == 2:
        lines.append("| — | tidak ada pure wallet ukuran-whale | 0.0 | "
                     "0.0 | +0.0 | 0 | ❓ tidak diketahui | — |")
    return "\n".join(lines)


def build_ai_prompt(*, symbol, ca, requested_hours, available_hours, swaps,
                    window_stats, wallet_rows, price_now=None,
                    market_cap=None, now_ts=None,
                    period_count=PERIOD_COUNT):
    """Build an Indonesian CVD-analysis prompt with explicit data limits.

    ``window_stats`` is the page's multi-window dictionary. ``wallet_rows``
    contains pure accumulator/distributor rows with wallet age labels. No
    fetches or file reads happen here.
    """
    requested = _number(requested_hours)
    if requested <= 0:
        raise ValueError("requested_hours must be positive")
    swaps = _clean_swaps(swaps)
    now_ts = _number(now_ts, 0.0)
    if now_ts <= 0:
        now_ts = max((s[2] for s in swaps), default=0.0)
    if now_ts <= 0:
        now_ts = datetime.now(timezone.utc).timestamp()
    available = max(0.0, _number(available_hours))
    complete = available >= requested
    periods = max(2, min(int(period_count or PERIOD_COUNT), 12))

    if complete:
        honesty = (
            f"STATUS: DATA MENCUKUPI untuk window {_hours(requested)} jam "
            f"(tersedia {_hours(available)} jam). Tetap jangan "
            "mengekstrapolasi ke luar window ini.")
    else:
        honesty = (
            f"STATUS: DATA TIDAK PENUH. Window diminta "
            f"{_hours(requested)} jam, tetapi data yang tersedia hanya "
            f"{_hours(available)} jam. DILARANG menyimpulkan tren, "
            "perubahan tekanan, atau bahwa jual/beli sudah selesai dari "
            "window yang tidak lengkap. Sebut keterbatasan ini di awal "
            "jawaban.")

    price = (_number(price_now) if price_now is not None else None)
    market_cap = (_number(market_cap)
                  if market_cap is not None else None)
    identity = [f"- Token: ${symbol or '?'}", f"- CA: `{ca or '?'}`"]
    if price is not None:
        identity.append(f"- Harga saat snapshot: ${price:.10f}")
    if market_cap is not None:
        identity.append(f"- Market cap saat snapshot: ${market_cap:,.0f}")
    identity.append(f"- Jumlah swap teramati: {len(swaps):,}")

    glossary = f"""## GLOSARIUM WAJIB

Gunakan definisi ini dan jangan membuat definisi sendiri.

- **Whale** = satu swap **≥{WHALE_SOL:g} SOL**. Di bawah ambang itu disebut
  retail untuk pemisahan flow ini; label ini berdasarkan ukuran swap, bukan
  identitas atau total kekayaan dompet.
- **Pure accumulator / pure distributor** = dompet satu arah dengan toleransi
  lawan arah maksimal **5%** dari sisi dominan pada window yang dihitung.
- **Conviction** = persentase volume beli ukuran-whale yang masih ditahan oleh
  pure accumulator: `pure buy / (pure buy + buy dari two-way wallet) × 100%`.
  Ini bukan probabilitas harga naik.
- **Net CVD** = volume buy dikurangi sell dalam SOL. Whale dan retail memakai
  ambang yang sama di seluruh tabel.
- **Umur dompet**: 🐣 kurang dari 3 hari; 🌱 3 sampai kurang dari 14 hari;
  🌳 minimal 14 hari atau dompet lama. ❓ berarti umur tidak berhasil
  dibaca.
"""

    tasks = """## TUGAS ANDA

Jawab dalam **bahasa Indonesia** dan lakukan hal berikut:

1. Ceritakan alur flow dari periode paling lama ke paling baru. Nilai apakah
   tekanan sudah selesai, masih berjalan, atau tidak dapat dipastikan.
2. Bandingkan kemungkinan skenario: **take profit, distribusi ke retail,
   rotasi antar-whale, akumulasi, shakeout, dan churn**. Jangan paksa satu
   skenario bila bukti tidak cukup; urutkan yang paling masuk akal beserta
   bukti angka yang benar-benar ada.
3. Beri penilaian tegas: **perlu panik atau tidak**, siapa yang dominan, dan
   apa alasannya. Bila data tidak penuh, jawaban tegasnya harus "belum bisa
   menilai tren", bukan tebakan.
4. Tulis syarat yang akan **membatalkan pembacaan** Anda (invalidation), dalam
   bentuk perubahan flow/conviction/perilaku dompet yang dapat diperiksa.
5. Pisahkan dengan jelas: fakta dari tabel, inferensi, dan hal yang belum
   diketahui.

ATURAN KERAS: jangan mengarang angka, definisi, identitas dompet, berita,
atau sebab transaksi. Jangan memberi target harga, prediksi harga pasti,
atau rekomendasi beli/jual. Gunakan hanya data di bawah ini.
"""

    return ("# PROMPT ANALISIS CVD UNTUK AI\n\n" + glossary + "\n" +
            "## KEJUJURAN DAN CAKUPAN DATA\n\n" + honesty + "\n\n" +
            "## IDENTITAS SNAPSHOT\n\n" + "\n".join(identity) +
            "\n\n## RINGKASAN MULTI-WINDOW\n\n" +
            _window_table(window_stats, requested) +
            f"\n\n## URUTAN WAKTU — {_hours(requested)} JAM DIBAGI "
            f"{periods} PERIODE\n\n" +
            _timeline_table(swaps, requested, now_ts, periods) +
            "\n\n## DOMPET PURE UKURAN-WHALE\n\n" +
            _wallet_table(wallet_rows) + "\n\n" + tasks)

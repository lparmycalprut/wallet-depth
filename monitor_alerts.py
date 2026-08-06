"""Shared monitor / alert logic for the 4h basis-100 dashboard and Telegram.

Reused by ``pages/4_📊_CVD.py`` (Streamlit UI) and
``telegram_monitor_alerts.py`` (cron / CLI) so the detection logic stays
identical across both surfaces.

Indicators per 4h bucket (``monitor_rows``):
    ts, accum (pure accumulator cum wallets), dist (pure distributor cum
    wallets), conviction (%), tx (count), volume (SOL), buy, sell,
    buy_sell_ratio (buy SOL / sell SOL, inf = all-buy, 0 = no trade).

Alert A — STEALTH ACCUMULATION (trigger when basis-100 shows):
    pure accumulator ↑  AND  conviction ↑  AND  buy/sell dominan BUY
    AND  pure distributor ↓  AND  TX ↓  AND  volume ↓

Alert B — DISTRIBUTION (trigger when basis-100 shows):
    pure distributor ↑  AND  pure accumulator ↓  AND  conviction ↓
    AND  buy/sell dominan SELL  AND  TX ↑  AND  volume ↑
"""
import os
import json

from cvd import (pure_accumulator_growth, pure_distributor_growth,
                 wallet_profiles)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONV_PATH = os.path.join(BASE_DIR, "conviction.json")


def load_conv_points(ca: str, hours: int, now_ts: float) -> list:
    try:
        with open(CONV_PATH, "r", encoding="utf-8") as f:
            return [p for p in (json.load(f).get(ca, []))
                    if int(p.get("ts") or 0) >= now_ts - hours * 3600]
    except (OSError, ValueError, AttributeError):
        return []


def build_monitor_rows(swaps_all, full_profiles, ca, hours, mon_bin_h,
                       now_ts) -> list:
    """Build the per-bucket monitor_rows used by the basis-100 chart + alerts.

    Mirrors the inline logic previously in pages/4 so the dashboard and the
    Telegram script produce identical series.
    """
    mon_bin_s = mon_bin_h * 3600
    start_ts = min((int(x[2]) for x in swaps_all), default=int(now_ts))
    monitor = pure_accumulator_growth(
        swaps_all, full_profiles, min_buy_sol=0.1, sell_tol=0.10,
        start_ts=start_ts, end_ts=int(now_ts), bucket_s=mon_bin_s)
    monitor_dist = pure_distributor_growth(
        swaps_all, full_profiles, min_sell_sol=0.1, buy_tol=0.10,
        start_ts=start_ts, end_ts=int(now_ts), bucket_s=mon_bin_s)
    conv_points = load_conv_points(ca, hours, now_ts)

    bucket_start = (int(start_ts) // mon_bin_s) * mon_bin_s
    bucket_end = (int(now_ts) // mon_bin_s) * mon_bin_s
    tx_buckets = {}
    for _side, _sol, _ts, _wallet in swaps_all:
        _bucket = (int(_ts) // mon_bin_s) * mon_bin_s
        _row = tx_buckets.setdefault(
            _bucket, {"tx": 0, "buy": 0.0, "sell": 0.0, "volume": 0.0})
        _row["tx"] += 1
        _row["volume"] += float(_sol)
        if _side == "buy":
            _row["buy"] += float(_sol)
        else:
            _row["sell"] += float(_sol)
    _acc_by_bucket = {r["bucket_ts"]: r for r in monitor["series"]}
    _dist_by_bucket = {r["bucket_ts"]: r for r in monitor_dist["series"]}
    monitor_rows = []
    for _bucket in range(bucket_start, bucket_end + 1, mon_bin_s):
        _acc = _acc_by_bucket.get(_bucket, {})
        _dist = _dist_by_bucket.get(_bucket, {})
        _nearest = [p for p in conv_points
                    if int(p.get("ts") or 0) <= _bucket + mon_bin_s]
        _tb = tx_buckets.get(_bucket, {})
        _buy = _tb.get("buy", 0.0)
        _sell = _tb.get("sell", 0.0)
        _bsr = (_buy / _sell) if _sell > 0 else (float("inf") if _buy > 0
                                                 else 0.0)
        monitor_rows.append({
            "ts": _bucket,
            "accum": _acc.get("cum_wallets", 0),
            "dist": _dist.get("cum_wallets", 0),
            "conviction": float(_nearest[-1].get("conviction") or 0)
            if _nearest else None,
            "tx": _tb.get("tx", 0),
            "volume": _tb.get("volume", 0.0),
            "buy": _buy, "sell": _sell,
            "buy_sell_ratio": _bsr,
        })
    return monitor_rows


def _num(v):
    return v if isinstance(v, (int, float)) and \
        v not in (float("inf"), float("-inf")) else None


def _rising(cur, prev):
    """True if a cumulative counter grew in the most recent bucket."""
    c, p = _num(cur), _num(prev)
    return (c is not None and p is not None and c > p) or \
        (p is None and (c or 0) > 0)


def _not_rising(cur, prev):
    return not _rising(cur, prev)


def detect_stealth_accumulation(rows):
    """STEALTH ACCUMULATION: accumulator↑, conviction↑, bsr buy,
    distributor↓, tx↓, volume↓."""
    if len(rows) < 2:
        return {"triggered": False, "checks": {},
                "msg": "Data bucket kurang (<2) untuk deteksi trend."}
    last, prev = rows[-1], rows[-2]

    accum_up = _rising(last.get("accum"), prev.get("accum"))

    c_u, c_p = _num(last.get("conviction")), _num(prev.get("conviction"))
    if c_u is not None and c_p is not None:
        conv_up = c_u > c_p
    elif c_u is not None:
        conv_up = c_u >= 35.0
    else:
        conv_up = False

    bsr = last.get("buy_sell_ratio")
    bsr_prev = prev.get("buy_sell_ratio")
    bsr_buy = (isinstance(bsr, (int, float)) and bsr >= 1.0) or \
        bsr == float("inf")
    if isinstance(bsr, (int, float)) and isinstance(bsr_prev, (int, float)):
        bsr_buy = bsr_buy or (bsr > bsr_prev)  # juga "naik"

    dist_down = _not_rising(last.get("dist"), prev.get("dist"))

    t_u, t_p = _num(last.get("tx")), _num(prev.get("tx"))
    tx_down = (t_u is not None and t_p is not None and t_u < t_p)
    v_u, v_p = _num(last.get("volume")), _num(prev.get("volume"))
    vol_down = (v_u is not None and v_p is not None and v_u < v_p)

    checks = {
        "Pure accumulator ↑": accum_up,
        "Conviction ↑": conv_up,
        "Buy/Sell dominan BUY": bsr_buy,
        "Pure distributor ↓": dist_down,
        "TX ↓": tx_down,
        "Volume ↓": vol_down,
    }
    missing = [k for k, v in checks.items() if not v]
    return {"triggered": not missing, "checks": checks,
            "msg": " · ".join(f"{k} {'OK' if v else 'X'}"
                              for k, v in checks.items())}


def detect_distribution(rows):
    """DISTRIBUTION: distributor↑, accumulator↓, conviction↓,
    bsr sell, tx↑, volume↑."""
    if len(rows) < 2:
        return {"triggered": False, "checks": {},
                "msg": "Data bucket kurang (<2) untuk deteksi trend."}
    last, prev = rows[-1], rows[-2]

    dist_up = _rising(last.get("dist"), prev.get("dist"))
    accum_down = _not_rising(last.get("accum"), prev.get("accum"))

    c_u, c_p = _num(last.get("conviction")), _num(prev.get("conviction"))
    if c_u is not None and c_p is not None:
        conv_down = c_u < c_p
    elif c_u is not None:
        conv_down = c_u < 35.0
    else:
        conv_down = False

    bsr = last.get("buy_sell_ratio")
    bsr_sell = isinstance(bsr, (int, float)) and bsr < 1.0

    t_u, t_p = _num(last.get("tx")), _num(prev.get("tx"))
    tx_up = (t_u is not None and t_p is not None and t_u > t_p)
    v_u, v_p = _num(last.get("volume")), _num(prev.get("volume"))
    vol_up = (v_u is not None and v_p is not None and v_u > v_p)

    checks = {
        "Pure distributor ↑": dist_up,
        "Pure accumulator ↓": accum_down,
        "Conviction ↓": conv_down,
        "Buy/Sell dominan SELL": bsr_sell,
        "TX ↑": tx_up,
        "Volume ↑": vol_up,
    }
    missing = [k for k, v in checks.items() if not v]
    return {"triggered": not missing, "checks": checks,
            "msg": " · ".join(f"{k} {'OK' if v else 'X'}"
                              for k, v in checks.items())}


def _fmt_bsr(v):
    if v == float("inf"):
        return "inf (all-buy)"
    if isinstance(v, (int, float)):
        return f"{v:.2f}"
    return str(v)


def format_alert(symbol, ca, rows, kind, result):
    """Render a Telegram/dashboard-ready message for a triggered alert."""
    last = rows[-1]
    if kind == "stealth":
        title = "🟢 STEALTH ACCUMULATION"
        body = ("Pure accumulator ↑, Conviction ↑, Buy/Sell dominan BUY, "
                "Pure distributor ↓, TAPI TX ↓ & Volume ↓.\n"
                f"accum={last['accum']} dist={last['dist']} "
                f"conv={last['conviction']} bsr={_fmt_bsr(last['buy_sell_ratio'])} "
                f"tx={last['tx']} vol={last['volume']:.1f}")
    else:
        title = "🔴 DISTRIBUSI"
        body = ("Pure distributor ↑, Pure accumulator ↓, Conviction ↓, "
                "Buy/Sell dominan SELL, TX ↑ & Volume ↑.\n"
                f"dist={last['dist']} accum={last['accum']} "
                f"conv={last['conviction']} bsr={_fmt_bsr(last['buy_sell_ratio'])} "
                f"tx={last['tx']} vol={last['volume']:.1f}")
    return (f"<b>{title}</b> ${symbol}\n"
            f"<code>{ca}</code>\n"
            f"{body}\n"
            f"checks: {result['msg']}")


def format_cleared_alert(symbol, ca, rows, kind, prev_result=None):
    """Render a Telegram message when a previously-triggered alert clears.

    Cleared = conditions that were TRUE in the previous scan are now FALSE.
    The message explicitly names the token, the kind that cleared, and the
    current bucket snapshot so the reader can verify the de-alert at a glance.
    """
    last = rows[-1] if rows else {}
    if kind == "stealth":
        title = "✅ STEALTH CLEARED"
        body = ("Stealth accumulation tidak lagi terpenuhi. "
                "Kondisi terbaru tidak lagi menunjukkan absorb senyap.\n"
                f"accum={last.get('accum', '?')} dist={last.get('dist', '?')} "
                f"conv={last.get('conviction', '?')} "
                f"bsr={_fmt_bsr(last.get('buy_sell_ratio', '?'))} "
                f"tx={last.get('tx', '?')} vol={last.get('volume', '?')}")
    else:
        title = "✅ DISTRIBUSI CLEARED"
        body = ("Tekanan distribusi mereda — kondisi distribusi tidak lagi "
                "terpenuhi pada bucket terbaru.\n"
                f"dist={last.get('dist', '?')} accum={last.get('accum', '?')} "
                f"conv={last.get('conviction', '?')} "
                f"bsr={_fmt_bsr(last.get('buy_sell_ratio', '?'))} "
                f"tx={last.get('tx', '?')} vol={last.get('volume', '?')}")
    footer = f"checks: {prev_result.get('msg', '')}" if prev_result else ""
    msg = (f"<b>{title}</b> ${symbol}\n"
           f"<code>{ca}</code>\n"
           f"{body}")
    if footer:
        msg += f"\n{footer}"
    msg += f"\n<a href='https://dexscreener.com/solana/{ca}'>chart</a>"
    return msg


def _digest_line(symbol, ca, rows, kind):
    """One compact line for the combined digest (triggered entry)."""
    last = rows[-1] if rows else {}
    if kind == "stealth":
        emo = "🟢"
        label = "STEALTH"
    else:
        emo = "🔴"
        label = "DISTRIBUSI"
    return (f"{emo} <b>${symbol}</b> {label} "
            f"acc{last.get('accum', '?')}/dist{last.get('dist', '?')} "
            f"conv{last.get('conviction', '?')} "
            f"bsr{_fmt_bsr(last.get('buy_sell_ratio', '?'))} "
            f"tx{last.get('tx', '?')} vol{last.get('volume', 0):.0f} "
            f"<a href='https://dexscreener.com/solana/{ca}'>chart</a>")


def _cleared_digest_line(symbol, ca, rows, kind):
    last = rows[-1] if rows else {}
    emo = "✅"
    label = "cleared"
    return (f"{emo} <b>${symbol}</b> {kind} {label} "
            f"acc{last.get('accum', '?')}/dist{last.get('dist', '?')} "
            f"conv{last.get('conviction', '?')} "
            f"<a href='https://dexscreener.com/solana/{ca}'>chart</a>")


def format_combined_digest(triggered=None, cleared=None, prepump=None,
                           prepump_cleared=None):
    """Render ONE combined Telegram digest for a full watchlist scan.

    Args:
        triggered: list of dicts {symbol, ca, rows, kind, result}
        cleared:   list of dicts {symbol, ca, rows, kind, prev_result}
        prepump:   list of dicts {symbol, ca, result}
        prepump_cleared: list of dicts {symbol, ca, rows}
    Returns HTML string or None when nothing to send.
    """
    triggered = triggered or []
    cleared = cleared or []
    prepump = prepump or []
    prepump_cleared = prepump_cleared or []
    if not triggered and not cleared and not prepump and not prepump_cleared:
        return None
    total = len(triggered) + len(cleared) + len(prepump) + len(prepump_cleared)
    lines = [f"<b>📊 CVD MONITOR DIGEST</b> — {total} update(s)",
             f"<i>{len(triggered)} triggered · {len(cleared)} cleared"
             f" · {len(prepump)} prepump · {len(prepump_cleared)} prepump cleared</i>",
             ""]
    if triggered:
        lines.append(f"<b>🚨 Triggered ({len(triggered)})</b>")
        for e in triggered:
            try:
                lines.append(_digest_line(e["symbol"], e["ca"], e["rows"], e["kind"]))
            except Exception:
                lines.append(f"• {e.get('symbol','?')} {e.get('kind','?')}")
        lines.append("")
    if prepump:
        lines.append(f"<b>🎯 Pre-Pump ({len(prepump)})</b>")
        for e in prepump:
            r = e.get("result") or {}
            tier = r.get("tier", "?")
            score = r.get("score", "?")
            badge = "🚨" if tier == "imminent" else "👀"
            lines.append(
                f"{badge} <b>${e.get('symbol','?')}</b> {score}/100 {tier} "
                f"<a href='https://dexscreener.com/solana/{e.get('ca','')}'>chart</a>"
                f" | <a href='https://gmgn.ai/sol/token/{e.get('ca','')}'>GMGN</a>")
        lines.append("")
    if cleared:
        lines.append(f"<b>✅ Cleared ({len(cleared)})</b>")
        for e in cleared:
            try:
                lines.append(_cleared_digest_line(e["symbol"], e["ca"], e["rows"], e["kind"]))
            except Exception:
                lines.append(f"• {e.get('symbol','?')} {e.get('kind','?')} cleared")
        lines.append("")
    if prepump_cleared:
        lines.append(f"<b>✅ Pre-Pump Cleared ({len(prepump_cleared)})</b>")
        for e in prepump_cleared:
            lines.append(
                f"✅ <b>${e.get('symbol','?')}</b> pre-pump cleared "
                f"<a href='https://dexscreener.com/solana/{e.get('ca','')}'>chart</a>")
        lines.append("")
    lines.append(f"<i>watchlist scan · {len(triggered)+len(prepump)} active · "
                 f"{len(cleared)+len(prepump_cleared)} cleared</i>")
    return "\n".join(lines).strip()

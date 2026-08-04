# -*- coding: utf-8 -*-
"""Memecoin Scanner — watchlist monitoring every 15 minutes.

Scans all tokens in watchlist.json and sends Telegram updates with:
- Price changes (1h / 6h / 24h)
- Conviction trend (rising/falling)
- Whale/retail flow summary
- Real vs dust holder changes
- Notable signals (accumulation, distribution, divergence)

Uses existing wallet-depth modules for data (CVD, conviction, holder
snapshots, signals) and the Telegram bot from breakout_guard.

State file: scanner_state.json
"""

import json
import os
import sys
import time

import requests

from core import atomic_write_json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "scanner_state.json")

# Dedupe: don't re-send the same summary within this many minutes
SUMMARY_DEDUPE_MIN = 14  # just under 15 minutes
# Signal dedupe: same signal type per token max once per 2 hours
SIGNAL_DEDUPE_SEC = 2 * 3600


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------
def load_state() -> dict:
    """Load scanner state from disk."""
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_state(state: dict) -> None:
    """Persist scanner state to disk."""
    try:
        atomic_write_json(STATE_PATH, state, separators=(",", ":"))
    except Exception as exc:
        print(f"WARN: failed to save {STATE_PATH}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Telegram (reuse breakout_guard's implementation)
# ---------------------------------------------------------------------------
def _tg_creds():
    """Telegram credentials from env/config."""
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not tok or not chat:
        try:
            with open(os.path.join(BASE_DIR, "config.json")) as f:
                cfg = json.load(f) or {}
            tok = tok or str(cfg.get("telegram_bot_token", "")).strip()
            chat = chat or str(cfg.get("telegram_chat_id", "")).strip()
        except Exception:
            pass
    return tok, chat


def send_telegram(text: str) -> bool:
    """Send a Telegram message (HTML parse mode)."""
    tok, chat = _tg_creds()
    if not tok or not chat:
        print("WARN: Telegram credentials not configured", file=sys.stderr)
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True}, timeout=15)
        return bool(r.json().get("ok"))
    except Exception as exc:
        print(f"WARN: Telegram send failed: {exc}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Data fetchers (thin wrappers over existing modules)
# ---------------------------------------------------------------------------
def fetch_dexscreener_batch(cas: list) -> dict:
    """Batch prices from DexScreener. Returns {ca: {price, chg1, chg6, chg24,
    mc, vol24, liq, symbol, pair}}."""
    out = {}
    if not cas:
        return out
    for offset in range(0, len(cas), 30):
        batch = cas[offset:offset + 30]
        try:
            r = requests.get(
                "https://api.dexscreener.com/latest/dex/tokens/" +
                ",".join(batch), timeout=20)
            pairs = (r.json() or {}).get("pairs") or []
        except Exception:
            continue
        best = {}
        for p in pairs:
            addr = (p.get("baseToken") or {}).get("address")
            liq = (p.get("liquidity") or {}).get("usd") or 0
            if addr and (addr not in best or liq > best[addr][0]):
                best[addr] = (liq, p)
        for addr, (_, p) in best.items():
            out[addr] = {
                "symbol": (p.get("baseToken") or {}).get("symbol", "?"),
                "price": float(p.get("priceUsd") or 0),
                "chg1": float((p.get("priceChange") or {}).get("h1") or 0),
                "chg6": float((p.get("priceChange") or {}).get("h6") or 0),
                "chg24": float((p.get("priceChange") or {}).get("h24") or 0),
                "mc": float(p.get("marketCap") or p.get("fdv") or 0),
                "vol24": float((p.get("volume") or {}).get("h24") or 0),
                "liq": float((p.get("liquidity") or {}).get("usd") or 0),
                "pair": p.get("pairAddress"),
                "txns24": (p.get("txns") or {}).get("h24") or {},
            }
    return out


def fetch_conviction_data(ca: str) -> dict:
    """Get latest conviction data for a CA.

    Returns {conviction, net_pure, vol, swaps, trend, prev_conviction}
    or empty dict if no data.
    """
    try:
        from cvd import load_conviction
        hist = load_conviction() or {}
        pts = hist.get(ca) or []
        if not pts:
            return {}
        last = pts[-1]
        prev = pts[-2] if len(pts) >= 2 else None
        prev2 = pts[-3] if len(pts) >= 3 else None

        cv = last["conviction"]
        prev_cv = prev["conviction"] if prev else None
        prev2_cv = prev2["conviction"] if prev2 else None

        # Trend detection
        trend = "flat"
        if prev_cv is not None:
            if cv > prev_cv:
                trend = "rising"
            elif cv < prev_cv:
                trend = "falling"

        # Multi-period trend
        consecutive_up = 0
        if cv > (prev_cv or 0):
            consecutive_up += 1
            if prev_cv is not None and prev2_cv is not None and prev_cv > prev2_cv:
                consecutive_up += 1

        return {
            "conviction": cv,
            "net_pure": last.get("net_pure", 0),
            "vol": last.get("vol", 0),
            "swaps": last.get("swaps", 0),
            "trend": trend,
            "consecutive_up": consecutive_up,
            "prev_conviction": prev_cv,
        }
    except Exception:
        return {}


def fetch_holder_delta(ca: str) -> dict:
    """Get holder snapshot delta (from the last cron snapshot).

    Returns {n_holders, delta_holders, tier_info} or empty dict.
    """
    try:
        from cvd import load_holder_snapshots, holder_delta
        snaps = load_holder_snapshots() or {}
        ca_snaps = snaps.get(ca) or {}
        if not isinstance(ca_snaps, dict) or len(ca_snaps) < 2:
            return {}

        # Sort by timestamp (newest last)
        sorted_keys = sorted(ca_snaps.keys(),
                             key=lambda k: (ca_snaps[k] or {}).get("ts", 0))
        current = ca_snaps[sorted_keys[-1]]
        previous = ca_snaps[sorted_keys[-2]]

        current_holders_raw = current.get("holders") or []
        # Normalize holders to list of (owner, ui_amount) pairs
        current_holders = []
        for h in current_holders_raw:
            if isinstance(h, (list, tuple)) and len(h) >= 2:
                current_holders.append([str(h[0]), float(h[1])])
            elif isinstance(h, dict):
                owner = h.get("owner", "")
                amt = float(h.get("ui_amount", 0))
                if owner and amt > 0:
                    current_holders.append([str(owner), amt])

        current_supply = current.get("supply", 0.0)
        previous_holders_raw = previous.get("holders") or []
        n_prev = len(previous_holders_raw)

        # Use the proper keyword-argument API
        delta_info = holder_delta(
            ca, window_h=6, current_holders=current_holders,
            current_supply=current_supply)

        n_now = len(current_holders)

        return {
            "n_holders": n_now,
            "prev_holders": n_prev,
            "delta_holders": n_now - n_prev,
            "tier_info": {
                "whale_delta": (delta_info.get("whale") or {}).get("delta_sol", 0),
                "dolphin_delta": (delta_info.get("dolphin") or {}).get("delta_sol", 0),
                "level": delta_info.get("level", "ok"),
                "summary": delta_info.get("summary", ""),
            } if delta_info.get("ok") else {},
        }
    except Exception:
        return {}


def fetch_recent_signals(ca: str, max_age_sec: int = 900) -> list:
    """Get signals recorded in the last max_age_sec seconds (default 15 min)."""
    try:
        from signals import load_signals
        sigs = load_signals()
        now = int(time.time())
        return [s for s in sigs
                if s.get("ca") == ca and
                now - (s.get("ts") or 0) < max_age_sec]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Scanner logic
# ---------------------------------------------------------------------------
def scan_token(ca: str, meta: dict, market: dict) -> dict:
    """Scan a single token and return a summary dict.

    Returns dict with all metrics + alerts, or None if scan fails.
    """
    symbol = meta.get("symbol") or market.get("symbol") or "?"
    conv = fetch_conviction_data(ca)
    hd = fetch_holder_delta(ca)
    recent_sigs = fetch_recent_signals(ca)

    # Price alert thresholds
    price_alerts = []
    chg1 = market.get("chg1", 0)
    chg6 = market.get("chg6", 0)
    chg24 = market.get("chg24", 0)

    if abs(chg1) >= 15:
        price_alerts.append(f"1h {chg1:+.1f}% 🚨")
    elif abs(chg6) >= 25:
        price_alerts.append(f"6h {chg6:+.1f}% ⚠️")
    if abs(chg24) >= 50:
        price_alerts.append(f"24h {chg24:+.1f}% 🔥")

    # Conviction alert
    conv_alerts = []
    if conv.get("consecutive_up", 0) >= 3:
        conv_alerts.append(f"🔥 Conviction naik {conv['consecutive_up']}x berturut")
    elif conv.get("trend") == "rising" and conv.get("conviction", 0) >= 60:
        conv_alerts.append(f"📈 Conviction tinggi {conv['conviction']:.0f}%")
    elif conv.get("trend") == "falling" and conv.get("conviction", 0) < 30:
        conv_alerts.append(f"📉 Conviction rendah {conv['conviction']:.0f}%")

    # Signal alerts
    sig_alerts = []
    for sig in recent_sigs:
        stype = sig.get("type", "")
        if stype in ("accumulation", "stealth_accumulation"):
            sig_alerts.append(f"💎 {stype}")
        elif stype == "distribution":
            sig_alerts.append(f"🩸 {stype}")
        elif stype in ("bullish_div", "bearish_div"):
            sig_alerts.append(f"📊 {stype}")

    # Holder alerts
    holder_alerts = []
    if hd.get("delta_holders"):
        dh = hd["delta_holders"]
        if abs(dh) >= 10:
            arrow = "📈" if dh > 0 else "📉"
            holder_alerts.append(f"{arrow} {dh:+,} holders")

    # Combine all alerts
    all_alerts = price_alerts + conv_alerts + sig_alerts + holder_alerts

    # Determine urgency
    has_urgent = bool(sig_alerts) or any(abs(x) >= 15 for x in [chg1])
    has_notable = bool(price_alerts) or bool(conv_alerts) or bool(holder_alerts)

    return {
        "ca": ca,
        "symbol": symbol,
        "price": market.get("price", 0),
        "chg1": chg1,
        "chg6": chg6,
        "chg24": chg24,
        "mc": market.get("mc", 0),
        "vol24": market.get("vol24", 0),
        "liq": market.get("liq", 0),
        "conviction": conv.get("conviction"),
        "conv_trend": conv.get("trend"),
        "net_pure": conv.get("net_pure"),
        "n_holders": hd.get("n_holders"),
        "delta_holders": hd.get("delta_holders"),
        "alerts": all_alerts,
        "has_urgent": has_urgent,
        "has_notable": has_notable,
        "signals": recent_sigs,
    }


def build_summary_message(results: list, scan_time: str) -> str:
    """Build a Telegram HTML message from scan results.

    Only includes tokens with notable changes. Returns the message string.
    """
    # Filter to tokens with alerts
    notable = [r for r in results if r.get("has_notable") or r.get("has_urgent")]
    urgent = [r for r in results if r.get("has_urgent")]

    if not notable:
        return ""

    # Sort: urgent first, then by absolute 1h change
    notable.sort(key=lambda r: (
        0 if r.get("has_urgent") else 1,
        -abs(r.get("chg1", 0))
    ))

    lines = [
        f"🔍 <b>MEMECOIN SCANNER</b>",
        f"<i>Watchlist update · {scan_time} WIB</i>",
        f"<i>{len(notable)} token(s) with notable changes</i>",
        "",
    ]

    for r in notable:
        sym = r["symbol"]
        price = r["price"]
        chg1 = r.get("chg1", 0)
        chg6 = r.get("chg6", 0)
        chg24 = r.get("chg24", 0)
        mc = r.get("mc", 0)
        conv = r.get("conviction")
        trend = r.get("conv_trend", "")
        net = r.get("net_pure")
        alerts = r.get("alerts", [])

        # Price formatting
        if price >= 1:
            price_str = f"${price:,.4f}"
        elif price >= 0.001:
            price_str = f"${price:.6f}"
        else:
            price_str = f"${price:.10f}".rstrip("0")

        # Change arrows
        def _chg_str(v, label):
            if v == 0:
                return f"{label} ➡️{v:+.1f}%"
            arrow = "🟢" if v > 0 else "🔴"
            return f"{label} {arrow}{v:+.1f}%"

        # MC formatting
        if mc >= 1e6:
            mc_str = f"${mc/1e6:.1f}M"
        elif mc >= 1e3:
            mc_str = f"${mc/1e3:.0f}K"
        else:
            mc_str = f"${mc:.0f}"

        # Urgency indicator
        if r.get("has_urgent"):
            header_emoji = "🚨"
        elif r.get("has_notable"):
            header_emoji = "⚡"
        else:
            header_emoji = "•"

        # Build token block
        block = (
            f"{header_emoji} <b>${sym}</b> — {price_str}\n"
            f"  {_chg_str(chg1, '1h')} · {_chg_str(chg6, '6h')} · {_chg_str(chg24, '24h')}\n"
            f"  MC {mc_str}"
        )

        # Conviction line
        if conv is not None:
            trend_icon = {"rising": "📈", "falling": "📉", "flat": "➡️"}.get(trend, "➡️")
            conv_str = f"  Conv {conv:.0f}% {trend_icon}"
            if net is not None:
                net_icon = "💚" if net >= 0 else "💔"
                conv_str += f" · Net {net:+.0f} {net_icon}"
            block += f"\n{conv_str}"

        # Alerts line
        if alerts:
            block += f"\n  ⚠️ {'  |  '.join(alerts)}"

        # Link
        block += f"\n  <a href='https://dexscreener.com/solana/{r['ca']}'>chart</a> · <code>{r['ca'][:8]}…</code>"

        lines.append(block)
        lines.append("")

    # Footer
    lines.append(f"<i>Total {len(results)} tokens scanned</i>")

    return "\n".join(lines)


def build_quiet_message(total_tokens: int, scan_time: str) -> str:
    """Build a minimal 'all quiet' message for when no alerts fire.

    Only sent every 4th cycle (hourly) to avoid spam.
    """
    return (
        f"🔍 <b>MEMECOIN SCANNER</b>\n"
        f"<i>Watchlist update · {scan_time} WIB</i>\n"
        f"✅ {total_tokens} token(s) scanned — no notable changes"
    )


# ---------------------------------------------------------------------------
# Main scanner runner
# ---------------------------------------------------------------------------
def run_scan(quiet_every: int = 4) -> dict:
    """Run a full scan cycle.

    Args:
        quiet_every: Send a 'quiet' message every N cycles (0 = never).

    Returns:
        {sent: bool, tokens_scanned: int, tokens_notable: int,
         message: str}
    """
    from watchlist import load_watchlist

    state = load_state()
    now = time.time()

    # Dedupe check
    last_sent = state.get("last_sent_ts", 0)
    if now - last_sent < SUMMARY_DEDUPE_MIN * 60:
        return {"sent": False, "tokens_scanned": 0,
                "tokens_notable": 0, "message": "deduped"}

    wl = load_watchlist()
    if not wl:
        return {"sent": False, "tokens_scanned": 0,
                "tokens_notable": 0, "message": "empty watchlist"}

    cas = list(wl.keys())

    # Fetch prices in batch
    markets = fetch_dexscreener_batch(cas)

    # Scan each token
    results = []
    for ca, meta in wl.items():
        market = markets.get(ca) or {}
        if not market:
            continue
        try:
            result = scan_token(ca, meta, market)
            if result:
                results.append(result)
        except Exception as exc:
            print(f"WARN: scan failed for {ca[:8]}: {exc}", file=sys.stderr)

    # Build message
    scan_time = time.strftime("%H:%M", time.gmtime(now + 7 * 3600))  # WIB
    notable_count = sum(1 for r in results if r.get("has_notable"))

    if notable_count > 0:
        message = build_summary_message(results, scan_time)
    else:
        # Quiet message only every quiet_every cycles
        cycle = state.get("cycle_count", 0) + 1
        state["cycle_count"] = cycle
        if quiet_every and cycle % quiet_every == 0:
            message = build_quiet_message(len(results), scan_time)
        else:
            # No message this cycle
            state["last_sent_ts"] = now
            save_state(state)
            return {"sent": False, "tokens_scanned": len(results),
                    "tokens_notable": 0, "message": "all quiet"}

    # Send
    sent = send_telegram(message)
    if sent:
        state["last_sent_ts"] = now
        state["last_scan_time"] = scan_time
        state["cycle_count"] = 0
    save_state(state)

    # Save scan results for the dashboard page
    try:
        scan_results_path = os.path.join(BASE_DIR, "scanner_results.json")
        atomic_write_json(scan_results_path, {
            "ts": int(now),
            "time_wib": scan_time,
            "results": results,
            "message_sent": sent,
            "notable_count": notable_count,
        }, indent=1)
    except Exception:
        pass

    return {
        "sent": sent,
        "tokens_scanned": len(results),
        "tokens_notable": notable_count,
        "message": "sent" if sent else "failed",
    }


def run_scan_cli():
    """CLI entry point for the cron job."""
    print(f"🔍 Memecoin Scanner — {time.strftime('%Y-%m-%d %H:%M:%S WIB', time.gmtime(time.time() + 7*3600))}")
    result = run_scan()
    print(f"  Scanned: {result['tokens_scanned']} tokens")
    print(f"  Notable: {result['tokens_notable']}")
    print(f"  Status: {result['message']}")
    return result


if __name__ == "__main__":
    run_scan_cli()

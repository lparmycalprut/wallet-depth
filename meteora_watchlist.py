# -*- coding: utf-8 -*-
"""Metric snapshots and alerts for the Meteora LP watchlist.

Regular Meteora rows carry two pool metrics that are more useful for an LP
watchlist than the old holder-dust alert:

* ``fee_active_tvl_ratio`` — fee generated relative to active TVL;
* ``volatility`` — the pool volatility reported by Meteora.

This module keeps the rule pure and small so the dashboard and the five-minute
scanner use exactly the same comparison. The immutable baseline is stored in
watchlist metadata when a pool is added. The current snapshot and the compact
alert state are published alongside the holder snapshot, not written to the
watchlist file on every cron run.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

METEORA_SOURCES = frozenset(("meteora", "lp", "chart_lp"))
TIMEFRAMES = ("24h", "30m")
SAFE_LP_MULTIPLIER = 5.0
RATIO_DROP_PCT = 30.0
ALERT_24H = "fee_volatility_ratio_drop"
ALERT_30M = "volatility_above_fee_ratio"


def _float(value, default=None):
    if value is None or isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _int(value, default=0) -> int:
    number = _float(value, None)
    return int(number) if number is not None else int(default)


def normalize_timeframe(value, default="24h") -> str:
    text = str(value or default).strip().lower()
    if text in ("1h", "60m", "1 hour", "30 menit", "30 min"):
        return "30m"
    if text in ("24 jam", "24 hours"):
        return "24h"
    return text if text in TIMEFRAMES else str(default)


def is_meteora_meta(meta: dict | None) -> bool:
    if not isinstance(meta, dict):
        return False
    source = str(meta.get("source") or "").strip().lower()
    return source in METEORA_SOURCES


def timeframe_for_meta(meta: dict | None, default="24h") -> str:
    meta = meta if isinstance(meta, dict) else {}
    baseline = meta.get("metric_baseline")
    baseline_timeframe = baseline.get("timeframe") if isinstance(baseline, dict) else None
    return normalize_timeframe(
        meta.get("timeframe") or meta.get("pool_timeframe")
        or meta.get("meteora_timeframe") or baseline_timeframe,
        default=default)


def metric_ratio(fee_active_tvl_ratio, volatility):
    """Return fee/volatility, or ``None`` when the payload is incomplete.

    ``math.inf`` is useful to sort a zero-volatility pool in memory; JSON
    snapshots use ``None`` for that non-finite display value (the raw fee and
    volatility remain available and the rule still compares them correctly).
    """
    fee = _float(fee_active_tvl_ratio, None)
    volatility = _float(volatility, None)
    if fee is None or volatility is None:
        return None
    if volatility == 0:
        return math.inf if fee > 0 else 0.0
    return fee / volatility


def _json_ratio(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def snapshot_from_row(row: dict | None, *, ts: int | None = None) -> dict:
    """Compact current snapshot from a normalized Meteora row."""
    row = row or {}
    fee = _float(row.get("fee_active_tvl_ratio"), None)
    volatility = _float(row.get("volatility"), None)
    timeframe = normalize_timeframe(
        row.get("timeframe") or row.get("source") or "24h")
    ratio = metric_ratio(fee, volatility)
    return {
        "ts": _int(ts, int(time.time())) or int(time.time()),
        "timeframe": timeframe,
        "source": timeframe,
        "pool_address": str(row.get("pool_address") or ""),
        "symbol": str(row.get("symbol") or "?").upper(),
        "fee_active_tvl_ratio": fee,
        "volatility": volatility,
        "fee_volatility_ratio": _json_ratio(ratio),
        "fee_active_tvl_ratio_vs_volatility": _json_ratio(ratio),
        "active_tvl": _float(row.get("active_tvl"), None),
        "tvl": _float(row.get("tvl"), None),
        "classification": str(row.get("classification") or ""),
        "classification_note": str(row.get("classification_note") or ""),
    }


def _clean_snapshot(raw, *, default_timeframe="24h") -> dict | None:
    if not isinstance(raw, dict):
        return None
    row = dict(raw)
    row.setdefault("timeframe", normalize_timeframe(
        row.get("source"), default=default_timeframe))
    return snapshot_from_row(row, ts=_int(row.get("ts"), int(time.time())))


def baseline_for_meta(meta: dict | None) -> dict | None:
    """Read the immutable add-time baseline, including legacy flat fields."""
    meta = meta if isinstance(meta, dict) else {}
    baseline = meta.get("metric_baseline")
    if isinstance(baseline, dict):
        cleaned = _clean_snapshot(baseline,
                                  default_timeframe=timeframe_for_meta(meta))
        if cleaned and (cleaned.get("fee_active_tvl_ratio") is not None
                        or cleaned.get("volatility") is not None):
            return cleaned
    # A few early/manual entries may only have flat values. Treat those as a
    # baseline without inventing a timestamp if no timestamp was recorded.
    if meta.get("fee_active_tvl_ratio") is not None \
            or meta.get("volatility") is not None:
        return _clean_snapshot({
            "ts": meta.get("metric_baseline_ts") or meta.get("added_ts") or 0,
            "timeframe": timeframe_for_meta(meta),
            "pool_address": meta.get("pool_address"),
            "symbol": meta.get("symbol"),
            "fee_active_tvl_ratio": meta.get("fee_active_tvl_ratio"),
            "volatility": meta.get("volatility"),
        }, default_timeframe=timeframe_for_meta(meta))
    return None


def classification_for_snapshot(snapshot: dict | None) -> dict:
    """Classify a snapshot for the watchlist display and alert rule."""
    snapshot = snapshot or {}
    timeframe = normalize_timeframe(snapshot.get("timeframe")
                                    or snapshot.get("source"))
    fee = _float(snapshot.get("fee_active_tvl_ratio"), None)
    volatility = _float(snapshot.get("volatility"), None)
    ratio = metric_ratio(fee, volatility)
    if fee is None or volatility is None:
        return {"show": False, "label": "", "note": "metrik belum tersedia",
                "ratio": ratio, "timeframe": timeframe}
    if timeframe == "30m":
        fee_dominant = fee > volatility
        volatility_alert = volatility > fee
        return {
            # The regular 30m listing is fee-dominant; once a watchlist
            # snapshot flips to volatility-dominant it remains a HIGH RISK
            # monitoring row and the alert rule below becomes active.
            "show": fee_dominant or volatility_alert,
            "label": "HIGH RISK LP (PANTAU)" if (fee_dominant or volatility_alert)
            else "",
            "note": ("30m: fee_active_tvl_ratio > volatility — HIGH RISK LP "
                     "(PANTAU)" if fee_dominant else
                     "30m: volatility > fee_active_tvl_ratio — HIGH RISK LP "
                     "(PANTAU)" if volatility_alert else
                     "30m: fee_active_tvl_ratio = volatility"),
            "ratio": ratio,
            "timeframe": timeframe,
        }
    safe = fee >= SAFE_LP_MULTIPLIER * volatility
    return {
        "show": fee > volatility,
        "label": "SAFE LP" if safe else "LP 24H",
        "note": (("24h: fee_active_tvl_ratio ≥ 5× volatility — SAFE LP"
                  if safe else
                  "24h: fee_active_tvl_ratio > volatility, belum 5× SAFE LP")
                 if fee > volatility else
                 "24h: volatility ≥ fee_active_tvl_ratio"),
        "ratio": ratio,
        "timeframe": timeframe,
    }


def ratio_drop_pct(baseline: dict | None, current: dict | None):
    """Relative change of fee/volatility from add baseline to current.

    A positive fee over zero volatility is an infinite quotient. If a later
    usable snapshot becomes finite, that is an unambiguous drop and is treated
    as a 100% drop rather than leaking ``Infinity`` into JSON. The reverse
    direction cannot be expressed as a finite relative change and is simply
    not an alert.
    """
    before = metric_ratio((baseline or {}).get("fee_active_tvl_ratio"),
                          (baseline or {}).get("volatility"))
    after = metric_ratio((current or {}).get("fee_active_tvl_ratio"),
                         (current or {}).get("volatility"))
    if before is None or after is None or before <= 0:
        return None
    if math.isinf(before):
        return -100.0 if math.isfinite(after) else 0.0
    if math.isinf(after):
        return None
    return (after - before) / abs(before) * 100.0


def evaluate_metric_alert(meta: dict | None, current: dict | None, *,
                          previous: dict | None = None,
                          previous_alert: dict | None = None,
                          now: int | None = None) -> dict:
    """Evaluate one new pool snapshot without sending or persisting anything."""
    meta = meta if isinstance(meta, dict) else {}
    current = _clean_snapshot(current,
                              default_timeframe=timeframe_for_meta(meta))
    if not current:
        return {"active": False, "triggered": False, "event": None,
                "baseline": baseline_for_meta(meta), "snapshot": None}
    baseline = baseline_for_meta(meta)
    baseline_created = False
    if baseline is None and (
            current.get("fee_active_tvl_ratio") is not None
            or current.get("volatility") is not None):
        baseline = dict(current)
        baseline_created = True
    timeframe = timeframe_for_meta(current, default=timeframe_for_meta(meta))
    current["timeframe"] = timeframe
    drop = ratio_drop_pct(baseline, current)
    if timeframe == "24h":
        active = bool(drop is not None and drop <= -RATIO_DROP_PCT)
        kind = ALERT_24H
        condition = (f"rasio fee/active TVL terhadap volatility turun "
                     f"{abs(drop):.1f}% sejak masuk" if drop is not None else
                     "rasio fee/active TVL terhadap volatility belum bisa dibandingkan")
    else:
        fee = _float(current.get("fee_active_tvl_ratio"), None)
        volatility = _float(current.get("volatility"), None)
        active = bool(fee is not None and volatility is not None
                      and volatility > fee)
        kind = ALERT_30M
        condition = ("volatility > fee_active_tvl_ratio"
                     if active else
                     "volatility tidak lebih besar dari fee_active_tvl_ratio")
    if previous_alert is None and isinstance(previous, dict):
        if timeframe == "30m":
            previous_fee = _float(previous.get("fee_active_tvl_ratio"), None)
            previous_volatility = _float(previous.get("volatility"), None)
            previous_active = bool(previous_fee is not None
                                  and previous_volatility is not None
                                  and previous_volatility > previous_fee)
        else:
            previous_active = bool(
                (ratio_drop_pct(baseline, previous) or 0.0)
                <= -RATIO_DROP_PCT)
    else:
        previous_active = bool((previous_alert or {}).get("active"))
    # A 24h baseline is created on the first usable snapshot and must not alert
    # immediately. A 30m watchlist is allowed to alert on its first *new*
    # violating snapshot because that is precisely the requested detection.
    triggered = bool(active and not previous_active
                     and not (baseline_created and timeframe == "24h"))
    stamp = _int(now, _int(current.get("ts"), int(time.time())))
    alert = {
        "active": active,
        "kind": kind,
        "triggered": triggered,
        "condition": condition,
        "ts": stamp,
        "baseline_ratio": _json_ratio(metric_ratio(
            (baseline or {}).get("fee_active_tvl_ratio"),
            (baseline or {}).get("volatility"))),
        "current_ratio": _json_ratio(current.get("fee_volatility_ratio")),
        "change_pct": drop,
    }
    event = None
    if triggered:
        symbol = str(current.get("symbol") or meta.get("symbol") or "?").upper()
        source = "24 jam" if timeframe == "24h" else "30 menit"
        if timeframe == "24h":
            title = "⚠️ METEORA SAFE LP MELEMAH"
            detail = (f"rasio fee/active TVL ÷ volatility turun "
                      f"{abs(drop):.1f}% sejak masuk watchlist")
        else:
            title = "🚨 HIGH RISK LP (PANTAU)"
            detail = "snapshot baru: volatility > fee_active_tvl_ratio"
        event = {
            "id": (f"meteora-metric:{meta.get('mint') or symbol}:"
                    f"{kind}:{stamp}"),
            "kind": kind,
            "title": title,
            "text": (f"{title}\n${symbol} · sumber pool {source}\n"
                     f"fee_active_tvl_ratio: {current.get('fee_active_tvl_ratio')}\n"
                     f"volatility: {current.get('volatility')}\n{detail}"),
            "mint": str(meta.get("mint") or meta.get("ca") or ""),
            "symbol": symbol,
            "timeframe": timeframe,
            "current": current,
            "baseline": baseline,
        }
    return {"active": active, "triggered": triggered, "event": event,
            "baseline": baseline, "snapshot": current, "alert": alert,
            "baseline_created": baseline_created}


def apply_metric_snapshots(watchlist: dict | None, snapshots: dict | None, *,
                           previous_tokens: dict | None = None,
                           now: int | None = None) -> dict:
    """Apply current snapshots in memory and return UI/status-ready payload.

    Return keys:
      ``watchlist`` — copy with missing add-time baselines initialized;
      ``metrics`` — compact current snapshot per Meteora watchlist mint;
      ``events`` — newly triggered metric events;
      ``baseline_changed`` — addresses whose watchlist metadata needs saving.
    """
    source = watchlist if isinstance(watchlist, dict) else {}
    snapshots = snapshots if isinstance(snapshots, dict) else {}
    previous_tokens = previous_tokens if isinstance(previous_tokens, dict) else {}
    updated = {str(mint): (dict(meta) if isinstance(meta, dict) else {})
               for mint, meta in source.items()}
    metrics: dict[str, dict] = {}
    events: list[dict] = []
    baseline_changed: list[str] = []
    for mint, meta in list(updated.items()):
        if not is_meteora_meta(meta):
            continue
        raw = snapshots.get(mint)
        if raw is None:
            continue
        previous_token = previous_tokens.get(mint) or {}
        previous_metric = previous_token.get("meteora_metrics") \
            if isinstance(previous_token, dict) else {}
        previous_snapshot = (previous_metric.get("snapshot")
                             if isinstance(previous_metric, dict) else None)
        previous_alert = (previous_metric.get("alert")
                          if isinstance(previous_metric, dict) else None)
        if not previous_alert:
            previous_alert = meta.get("metric_alert")
        result = evaluate_metric_alert(
            {**meta, "mint": mint}, raw,
            previous=previous_snapshot, previous_alert=previous_alert, now=now)
        baseline = result.get("baseline")
        if result.get("baseline_created") and baseline:
            # Baseline is immutable. Never replace it on later snapshots.
            meta["metric_baseline"] = dict(baseline)
            meta["metric_baseline_ts"] = baseline.get("ts")
            meta.setdefault("timeframe", baseline.get("timeframe"))
            if baseline.get("pool_address") and not meta.get("pool_address"):
                meta["pool_address"] = baseline.get("pool_address")
            baseline_changed.append(mint)
        current = result.get("snapshot")
        if not current:
            continue
        # Flat fields make the metadata understandable to older/manual tools;
        # the immutable baseline remains under metric_baseline.
        meta["metric_snapshot"] = dict(current)
        meta["fee_active_tvl_ratio"] = current.get("fee_active_tvl_ratio")
        meta["volatility"] = current.get("volatility")
        meta["metric_ratio"] = _json_ratio(current.get("fee_volatility_ratio"))
        alert = result.get("alert") or {}
        meta["metric_alert"] = dict(alert)
        metrics[mint] = {
            **current,
            "baseline": baseline,
            "alert": alert,
            "classification": (classification_for_snapshot(current).get("label")
                                or current.get("classification") or ""),
            "classification_note": (classification_for_snapshot(current).get("note")
                                     or current.get("classification_note") or ""),
        }
        if result.get("event"):
            event = dict(result["event"])
            event["mint"] = mint
            events.append(event)
    return {"watchlist": updated, "metrics": metrics, "events": events,
            "baseline_changed": baseline_changed}


def send_metric_alerts(events: list[dict] | None, *, mute_mints=None,
                       sender=None) -> list[dict]:
    """Send newly triggered events; rule state is already independent of send."""
    if sender is None:
        try:
            from telegram_alerts import send_telegram_message
            sender = lambda event: send_telegram_message(event.get("text") or "")
        except Exception:  # pragma: no cover - optional transport
            sender = lambda _event: {"ok": False, "skipped": True,
                                     "error": "Telegram transport unavailable"}
    muted = {str(item) for item in (mute_mints or []) if item}
    deliveries = []
    for event in events or []:
        mint = str(event.get("mint") or "")
        if mint in muted:
            deliveries.append({"event": event,
                               "delivery": {"ok": False, "skipped": True,
                                            "muted": True,
                                            "error": "telegram muted"}})
            continue
        try:
            result = sender(event)
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "skipped": False, "error": str(exc)}
        if isinstance(result, bool):
            result = {"ok": result, "skipped": False}
        if not isinstance(result, dict):
            result = {"ok": False, "skipped": False,
                      "error": "invalid sender result"}
        deliveries.append({"event": event, "delivery": result})
    return deliveries


def metric_summary(metrics: dict | None) -> dict:
    """Small status summary for logs/UI."""
    rows = list((metrics or {}).values())
    return {
        "total": len(rows),
        "safe": sum(1 for row in rows if row.get("classification") == "SAFE LP"),
        "high_risk": sum(1 for row in rows
                          if row.get("classification") == "HIGH RISK LP (PANTAU)"),
        "alerts": sum(1 for row in rows if (row.get("alert") or {}).get("active")),
    }


def snapshot_time_text(ts) -> str:
    stamp = _int(ts, 0)
    if not stamp:
        return "—"
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%d %b %H:%M UTC")

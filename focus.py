# -*- coding: utf-8 -*-
"""Focus mode: collapse non-Tier-1 signals into a single health badge.

When focus_mode is enabled (default), the dashboard shows ONLY:
  - 1 health badge (freshness/quality collapsed)
  - holder_delta panel (Tier 1)
  - breakout_guard events (Tier 1, already shown elsewhere)
  - conviction % (single number, no lh/trader split)

Non-Tier-1 things that are NOT shown when focus_mode is on:
  - flow_persistence detail (the "runs=N" badge is hidden)
  - flow_distribution detail (the warn/danger reason is hidden)
  - detect_phase (Wyckoff) — still computed but not displayed
  - detect_divergence / detect_cohort_divergences — hidden
  - lh_buy / trader_buy split in conviction — only pure_buy shown

Per klarifikasi user, ini fokus ke 2 subsistem Tier 1 (breakout_guard
+ holder_delta) untuk kurangi noise.
"""
import os
from typing import Optional

try:
    from cvd import flow_check_panel
except Exception:
    flow_check_panel = None


def is_focus_mode(config: Optional[dict] = None) -> bool:
    """Return True if focus mode is active (default: True).

    Reads ``focus_mode`` from the CONFIG dict; falls back to True so a
    fresh deploy without config also runs focused.
    """
    if not config:
        return True
    return bool(config.get("focus_mode", True))


def _load_config() -> dict:
    """Read config.json from the project root, never raising."""
    try:
        import json
        cfg_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "config.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def get_config() -> dict:
    """Return the live CONFIG (config.json or empty)."""
    return _load_config()


# ---------------------------------------------------------------------------
# Health badge — collapse 4 checks into 1
# ---------------------------------------------------------------------------
def health_badge(ca: str) -> dict:
    """Combine freshness / persistence / distribution / quality into a
    single ``{"level": "ok"|"warn"|"danger", "label": str, "reason": str}``.

    Rule (most-severe wins):
      - any "danger" → danger
      - else any "warn" → warn
      - else → ok

    Label is the worst-case check's label, prefixed with an emoji.
    """
    if flow_check_panel is None:
        return {"level": "warn", "label": "🟡 health unknown",
                "reason": "cvd module not importable"}
    try:
        panel = flow_check_panel(ca)
    except Exception as e:
        return {"level": "warn", "label": "🟡 health unknown",
                "reason": f"flow_check_panel raised: {str(e)[:60]}"}

    # Map each check to a short label and a level; "ok" checks are omitted.
    # We surface the worst one (and the first matching one) in the badge.
    labels = {
        "freshness": "data stale",
        "persistence": "direction not persistent",
        "distribution": "distribution in progress",
        "quality": "thin or concentrated flow",
    }
    order = ["freshness", "quality", "persistence", "distribution"]
    worst_level = "ok"
    worst_label = "🟢 flow healthy"
    for key in order:
        c = panel.get(key) or {}
        lvl = c.get("level", "ok")
        if lvl == "danger" and worst_level != "danger":
            worst_level = "danger"
            worst_label = f"🔴 {labels[key]}"
        elif lvl == "warn" and worst_level == "ok":
            worst_level = "warn"
            worst_label = f"🟡 {labels[key]}"

    # Concatenate reasons of non-ok checks (truncated) so the tooltip
    # still explains the full picture without overwhelming the screen.
    reason_bits = []
    for key in order:
        c = panel.get(key) or {}
        if c.get("level") in ("warn", "danger"):
            reason_bits.append(f"{labels[key]}: {c.get('reason', '')}")
    reason = " · ".join(reason_bits) if reason_bits else "all 4 checks ok"
    return {"level": worst_level, "label": worst_label, "reason": reason}


# ---------------------------------------------------------------------------
# Conviction summary — only pure_buy (Tier 1 read)
# ---------------------------------------------------------------------------
def conviction_summary(conv: dict) -> dict:
    """Reduce a conviction_split dict to the Tier 1 read:
    just pure_buy_whale + pure_buy_dolphin + conviction_pct.

    Returns ``{"conviction_pct", "pure_buy_total", "pure_buy_whale",
    "pure_buy_dolphin", "n_pure"}`` — drop lh_buy, trader_buy,
    tw_buy, pure_sell (those are Tier 2 details that confuse the
    signal-to-noise ratio in focus mode).
    """
    if not conv:
        return {}
    return {
        "conviction_pct": conv.get("conviction_pct", 0.0),
        "pure_buy_total": conv.get("pure_buy", 0.0),
        "pure_buy_whale": conv.get("pure_buy_whale", 0.0),
        "pure_buy_dolphin": conv.get("pure_buy_dolphin", 0.0),
        "n_pure": conv.get("n_pure", 0),
    }

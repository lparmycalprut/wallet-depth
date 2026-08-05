# -*- coding: utf-8 -*-
"""Fungsi fetch bersama — dipakai app.py dan pages/ (Perbandingan, Riwayat)."""
import json
import os
import tempfile
import threading

import pandas as pd
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
HISTORY_PATH = os.path.join(BASE_DIR, "history.json")
HELIUS_RPC_URL = "https://mainnet.helius-rpc.com/"
HELIUS_ENHANCED_URL = "https://api.helius.xyz"

_helius_rotation_lock = threading.Lock()
_helius_rotation_index = 0


def atomic_write_json(path: str, data, **dump_kwargs) -> None:
    """Write JSON to path atomically: write to a temp file in the same
    directory, flush+fsync, then os.replace() over the target. Prevents
    truncated/corrupt files if the process dies mid-write."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, **dump_kwargs)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def merge_helius_keys(*values) -> list[str]:
    """Normalize comma/newline-separated Helius keys and de-duplicate them.

    Values may be strings or iterables, which keeps this helper usable for
    config.json, environment variables, Streamlit secrets, and UI fields.
    The first occurrence wins so the configured primary key stays first.
    """
    keys = []

    def _add(value):
        if isinstance(value, (list, tuple, set)):
            for item in value:
                _add(item)
            return
        for key in str(value or "").replace("\r", "\n").replace(
                "\n", ",").split(","):
            key = key.strip()
            if key and key not in keys:
                keys.append(key)

    for value in values:
        _add(value)
    return keys


def _config_file() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _streamlit_helius_keys() -> list[str]:
    try:
        import streamlit as st
        return merge_helius_keys(st.secrets.get("helius_api_key", ""),
                                 st.secrets.get("helius_extra_keys", ""))
    except Exception:
        return []


def get_helius_keys(*, primary=None, extras=None, config=None) -> list[str]:
    """Return one de-duplicated Helius key pool from every supported source.

    Explicit values (for example the live sidebar fields) come first, then an
    optional config mapping, config.json, environment variables, and
    Streamlit secrets.  Reading every source instead of overriding one source
    with another ensures extra keys are never silently dropped.
    """
    passed = config or {}
    disk = _config_file()
    return merge_helius_keys(
        primary, extras,
        passed.get("helius_api_key"), passed.get("helius_extra_keys"),
        disk.get("helius_api_key"), disk.get("helius_extra_keys"),
        os.environ.get("HELIUS_API_KEY"),
        os.environ.get("HELIUS_API_KEYS"),
        _streamlit_helius_keys(),
    )


def _reset_helius_rotation() -> None:
    """Reset round-robin state (primarily useful for deterministic tests)."""
    global _helius_rotation_index
    with _helius_rotation_lock:
        _helius_rotation_index = 0


def _helius_candidates(helius_keys=None, max_attempts=None) -> list[str]:
    """Build a round-robin request order, including every configured key."""
    # Resolved tuples/lists are passed through every paginated flow; avoid
    # re-reading config.json and Streamlit secrets on every page.
    if isinstance(helius_keys, (list, tuple)):
        keys = merge_helius_keys(helius_keys)
    else:
        keys = get_helius_keys(primary=helius_keys)
    if not keys:
        raise RuntimeError("Helius API key missing")
    global _helius_rotation_index
    with _helius_rotation_lock:
        start = _helius_rotation_index % len(keys)
        _helius_rotation_index = (_helius_rotation_index + 1) % len(keys)
    attempts = max(len(keys), int(max_attempts or 0))
    return [keys[(start + offset) % len(keys)] for offset in range(attempts)]


def _transient_rpc_error(error) -> bool:
    if not isinstance(error, dict):
        return False
    code = error.get("code")
    message = str(error.get("message") or error).lower()
    return (code in (408, 425, 429, -32429) or
            "rate limit" in message or "too many requests" in message or
            "temporarily unavailable" in message or
            "service unavailable" in message or "internal error" in message)


def _response_error(response, label: str):
    # Do not surface response.url: it contains the API key query parameter.
    return RuntimeError(f"{label} HTTP {response.status_code}")


def helius_rpc_request(payload: dict, helius_keys=None, *, timeout: int = 60,
                       max_attempts=None) -> dict:
    """POST Helius JSON-RPC, rotating on HTTP 429/5xx and network errors."""
    last_error = None
    for key in _helius_candidates(helius_keys, max_attempts):
        try:
            response = requests.post(HELIUS_RPC_URL, params={"api-key": key},
                                     json=payload, timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
            continue
        if response.status_code == 429 or response.status_code >= 500:
            last_error = _response_error(response, "Helius RPC")
            continue
        response.raise_for_status()
        try:
            data = response.json()
        except (TypeError, ValueError) as exc:
            last_error = exc
            continue
        error = data.get("error") if isinstance(data, dict) else None
        if error:
            err = RuntimeError(f"Helius RPC error: {error}")
            if _transient_rpc_error(error):
                last_error = err
                continue
            raise err
        return data
    if last_error:
        raise last_error
    raise RuntimeError("Helius RPC failed without a response")


def helius_rpc(method: str, params, helius_keys=None, *, timeout: int = 60,
               max_attempts=None):
    """Call a Helius JSON-RPC method through the shared rotating key pool."""
    data = helius_rpc_request(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        helius_keys, timeout=timeout, max_attempts=max_attempts)
    if "result" not in data:
        raise RuntimeError("Helius RPC response has no result")
    return data["result"]


def helius_api_get(url: str, *, params=None, headers=None, helius_keys=None,
                   timeout: int = 40, max_attempts=None):
    """GET a Helius Enhanced API endpoint with the same rotating key pool."""
    last_error = None
    for key in _helius_candidates(helius_keys, max_attempts):
        query = dict(params or {})
        query["api-key"] = key
        try:
            response = requests.get(url, params=query, headers=headers,
                                    timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
            continue
        if response.status_code == 429 or response.status_code >= 500:
            last_error = _response_error(response, "Helius API")
            continue
        response.raise_for_status()
        try:
            return response.json()
        except (TypeError, ValueError) as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("Helius API failed without a response")


def load_config() -> dict:
    cfg = {"helius_api_key": "", "helius_extra_keys": "",
           "custom_rpc": "", "dust_limit_usd": 5,
           "cluster_warn_pct": 5, "cluster_scan_top_n": 50, "exclude_lp": True}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f) or {})
    except Exception:
        pass
    try:  # Streamlit Cloud secrets menimpa config.json
        import streamlit as st
        for k in list(cfg.keys()):
            if k in st.secrets:
                cfg[k] = st.secrets[k]
    except Exception:
        pass
    return cfg


def load_history() -> dict:
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _dex_liquidity_usd(pair: dict) -> float:
    """Return a finite, non-negative DexScreener liquidity value."""
    try:
        value = float((pair.get("liquidity") or {}).get("usd") or 0)
    except (AttributeError, TypeError, ValueError):
        return 0.0
    if value != value or value < 0 or value == float("inf"):
        return 0.0
    return value


def _dex_token_address(pair: dict, side: str) -> str:
    """Return a token address from a DexScreener pair without coercing case.

    Solana base58 addresses are case-sensitive, so this intentionally only
    strips surrounding whitespace rather than lower-casing the address.
    """
    token = pair.get(side) if isinstance(pair, dict) else None
    if not isinstance(token, dict):
        return ""
    return str(token.get("address") or "").strip()


def matching_dexscreener_pairs(pairs, ca: str) -> list:
    """Return DexScreener pairs for exactly ``ca``, in safe display order.

    ``/latest/dex/tokens/<CA>`` can include a cross-pair where the requested
    CA is the *quote* token. Picking the raw highest-liquidity response and
    reading ``baseToken`` then labels the requested token as the other side
    of that pair (for example MEMIPEDE was shown as Cyclospora).

    Exact address matches are mandatory. Pairs where the queried token is
    ``baseToken`` come first, then quote-side fallbacks; each group is sorted
    by liquidity. This keeps DexScreener's normal price/FDV semantics while
    still allowing a quote-side-only token to be identified honestly.
    """
    target = str(ca or "").strip()
    if not target:
        return []

    base_matches, quote_matches = [], []
    for pair in pairs or []:
        if not isinstance(pair, dict):
            continue
        if _dex_token_address(pair, "baseToken") == target:
            base_matches.append(pair)
        elif _dex_token_address(pair, "quoteToken") == target:
            quote_matches.append(pair)

    def _sort_key(pair):
        return (-_dex_liquidity_usd(pair),
                str(pair.get("pairAddress") or ""))

    base_matches.sort(key=_sort_key)
    quote_matches.sort(key=_sort_key)
    return base_matches + quote_matches


def select_dexscreener_pair(pairs, ca: str) -> dict | None:
    """Choose the canonical DexScreener pair for ``ca``, or ``None``.

    See :func:`matching_dexscreener_pairs` for why this must not use raw
    ``pairs[0]``.
    """
    matches = matching_dexscreener_pairs(pairs, ca)
    return matches[0] if matches else None


def dexscreener_pair_token(pair: dict, ca: str) -> dict:
    """Return metadata for ``ca`` from either side of a matched pair.

    Returning the queried side rather than unconditionally ``baseToken``
    prevents a quote-side fallback from ever borrowing another token's name
    or symbol.
    """
    target = str(ca or "").strip()
    if not target or not isinstance(pair, dict):
        return {}
    for side in ("baseToken", "quoteToken"):
        if _dex_token_address(pair, side) == target:
            token = pair.get(side)
            return dict(token) if isinstance(token, dict) else {}
    return {}


def get_market(ca: str) -> dict:
    """DexScreener market data for exactly one token contract address.

    The endpoint can return cross-pairs where ``ca`` is the quote token.
    Filter and order those responses before reading metadata so a liquid
    unrelated base token cannot replace the requested token in the UI.
    """
    r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}",
                     timeout=20)
    raw_pairs = (r.json() or {}).get("pairs") or []
    pairs = matching_dexscreener_pairs(raw_pairs, ca)
    if not pairs:
        return {}
    pair = pairs[0]
    token = dexscreener_pair_token(pair, ca)
    return {
        "name": token.get("name", "?"),
        "symbol": token.get("symbol", "?"),
        "price_usd": float(pair.get("priceUsd") or 0),
        "marketcap": float(pair.get("marketCap") or pair.get("fdv") or 0),
        "liquidity_usd": _dex_liquidity_usd(pair),
        "dex": pair.get("dexId", "?"),
        "pair_addresses": [p.get("pairAddress") for p in pairs
                           if p.get("pairAddress")],
        "url": pair.get("url", ""),
        "image": ((pair.get("info") or {}).get("imageUrl") or ""),
        "txns": pair.get("txns") or {},
        "volume": pair.get("volume") or {},
        "price_change": pair.get("priceChange") or {},
        "pair_created_at": pair.get("pairCreatedAt"),
        "pairs_detail": [{
            "dex": p.get("dexId", "?"),
            "pair": p.get("pairAddress"),
            "liq": _dex_liquidity_usd(p),
            "url": p.get("url", ""),
            "quote": (p.get("quoteToken") or {}).get("symbol", "?"),
        } for p in pairs],
    }


def get_rugcheck(ca: str) -> dict:
    """RugCheck (gratis): creator, authority, LP locked, risks, rugged."""
    out = {}
    try:
        r = requests.get(f"https://api.rugcheck.xyz/v1/tokens/{ca}/report",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
        d = r.json() or {}
        out = {
            "creator": d.get("creator"),
            "creator_balance": float(d.get("creatorBalance") or 0),
            "mint_authority": d.get("mintAuthority"),
            "freeze_authority": d.get("freezeAuthority"),
            "risks": [{"name": x.get("name"), "level": x.get("level"),
                       "desc": x.get("description")}
                      for x in (d.get("risks") or [])],
            "rugged": bool(d.get("rugged")),
            "total_lp_providers": d.get("totalLPProviders"),
            "total_market_liquidity": d.get("totalMarketLiquidity"),
        }
    except Exception:
        pass
    try:
        r = requests.get(
            f"https://api.rugcheck.xyz/v1/tokens/{ca}/report/summary",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        s = r.json() or {}
        out["lp_locked_pct"] = float(s.get("lpLockedPct") or 0)
    except Exception:
        out.setdefault("lp_locked_pct", None)
    return out


def get_ohlcv_daily(pair_address: str, limit: int = 30) -> pd.DataFrame:
    """GeckoTerminal (gratis): candle harian pair -> date, close, volume."""
    try:
        r = requests.get(
            f"https://api.geckoterminal.com/api/v2/networks/solana/pools/"
            f"{pair_address}/ohlcv/day", params={"limit": limit},
            headers={"accept": "application/json"}, timeout=20)
        lst = (((r.json() or {}).get("data") or {}).get("attributes") or {}) \
            .get("ohlcv_list") or []
    except Exception:
        return pd.DataFrame()
    import datetime as _dt
    rows = [{"date": _dt.datetime.utcfromtimestamp(x[0]).strftime("%Y-%m-%d"),
             "close": float(x[4]), "volume": float(x[5])} for x in lst]
    df = pd.DataFrame(rows)
    return df.sort_values("date").reset_index(drop=True) if not df.empty else df


def rpc(endpoint: str, method: str, params: list, timeout: int = 60):
    """Call a non-Helius/custom RPC endpoint (no key rotation available)."""
    r = requests.post(endpoint, json={"jsonrpc": "2.0", "id": 1,
                                      "method": method, "params": params},
                      timeout=timeout)
    r.raise_for_status()
    d = r.json()
    if "error" in d:
        raise RuntimeError(str(d["error"]))
    return d["result"]


def get_holders(helius_keys, ca: str) -> pd.DataFrame:
    """Semua holder (agregat per owner) via rotating Helius keys."""
    import time as _t
    owners, cursor, pages = {}, None, 0
    while True:
        params = {"mint": ca, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        res = helius_rpc("getTokenAccounts", params, helius_keys, timeout=60)
        res = res or {}
        accs = res.get("token_accounts") or []
        for account in accs:
            owner = account.get("owner")
            if owner:
                owners[owner] = owners.get(owner, 0.0) + float(
                    account.get("amount") or 0)
        pages += 1
        cursor = res.get("cursor")
        if not cursor or not accs or pages > 500:
            break
        _t.sleep(0.12)
    return pd.DataFrame({"owner": list(owners.keys()),
                         "raw_amount": list(owners.values())})


def get_supply(helius_keys, ca: str):
    res = helius_rpc("getTokenSupply", [ca], helius_keys, timeout=30)
    value = res["value"]
    return float(value["uiAmount"] or 0), int(value["decimals"])


def concentration(df: pd.DataFrame, supply: float) -> dict:
    """% of supply held by Top 1-5 / 6-10 / 11-25 / 26-50 / 51-100."""
    s = df.sort_values("ui_amount", ascending=False)["ui_amount"].values
    def seg(a, b):
        return float(s[a:b].sum()) / supply * 100 if supply and len(s) > a else 0.0
    return {"top5": seg(0, 5), "top6_10": seg(5, 10), "top11_25": seg(10, 25),
            "top26_50": seg(25, 50), "top51_100": seg(50, 100),
            "top10": seg(0, 10), "top100": seg(0, 100)}


def health_score(*, ratio_pct, real_mc_pct, top10_pct, liq_pct_mc,
                 lp_locked_pct, mint_auth, freeze_auth, holder_delta,
                 max_cluster_pct, fresh_pct) -> tuple:
    """Skor kesehatan 0-100 + rincian. Semua argumen boleh None (=netral)."""
    br = []  # (nama, poin, maks, keterangan)

    def clamp(v, lo, hi):
        return max(lo, min(hi, v))

    # 1. Rasio real/dust (maks 20)
    if ratio_pct is None:
        p = 10.0
    else:
        p = clamp((ratio_pct - 10) / (60 - 10), 0, 1) * 20
    br.append(("Real/dust ratio", p, 20,
               f"{ratio_pct:.0f}%" if ratio_pct is not None else "n/a"))
    # 2. Real % MC (maks 10)
    p = clamp((real_mc_pct or 0) / 60, 0, 1) * 10
    br.append(("Real holders % MC", p, 10, f"{real_mc_pct:.1f}% MC"))
    # 3. Konsentrasi top10 (maks 15) — makin kecil makin bagus
    p = clamp((45 - (top10_pct or 45)) / (45 - 10), 0, 1) * 15
    br.append(("Top-10 concentration", p, 15, f"{top10_pct:.1f}% supply"))
    # 4. Cluster terbesar (maks 15)
    cluster_warn_pct = 5.0
    try:
        cfg = load_config()
        cluster_warn_pct = float(cfg.get("cluster_warn_pct", 5.0))
    except Exception:
        pass

    if max_cluster_pct is None:
        p, note = 7.5, "not scanned"
    elif max_cluster_pct > cluster_warn_pct:
        p = 0.0
        note = f"{max_cluster_pct:.1f}% supply (⚠️ BUNDLER >{cluster_warn_pct:g}%)"
    else:
        p = clamp((cluster_warn_pct - max_cluster_pct) / cluster_warn_pct, 0, 1) * 7.5 + 7.5
        note = f"{max_cluster_pct:.1f}% supply"
    br.append(("Bundler/cluster", p, 15, note))
    # 5. Fresh wallet di top holder (maks 10)
    if fresh_pct is None:
        p, note = 5.0, "not scanned"
    else:
        p = clamp((60 - fresh_pct) / 60, 0, 1) * 10
        note = f"{fresh_pct:.0f}% fresh"
    br.append(("Fresh wallets", p, 10, note))
    # 6. Likuiditas vs MC (maks 10)
    p = clamp((liq_pct_mc or 0) / 12, 0, 1) * 10
    br.append(("Liquidity/MC", p, 10, f"{liq_pct_mc:.1f}%"))
    # 7. LP locked/burned (maks 0 - removed from score)
    p = 0.0
    if lp_locked_pct is None:
        note = "n/a"
    elif lp_locked_pct == 0:
        note = "⚠️ NOT LOCKED AT ALL — DANGER!"
    else:
        note = f"{lp_locked_pct:.0f}% locked"
    br.append(("LP locked", p, 0, note))
    # 8. Authority dicabut (maks 10)
    p = (5 if not mint_auth else 0) + (5 if not freeze_auth else 0)
    br.append(("Mint/freeze authority", p, 10,
               ("mint ✅" if not mint_auth else "mint ⚠️") + " · " +
               ("freeze ✅" if not freeze_auth else "freeze ⚠️")))
    # 9. Tren holder (maks 5)
    if holder_delta is None:
        p, note = 2.5, "n/a"
    else:
        p = 5.0 if holder_delta > 0 else (2.0 if holder_delta == 0 else 0.0)
        note = f"{holder_delta:+,}"
    br.append(("Holder trend", p, 5, note))

    total = round(sum(x[1] for x in br))
    return total, br


def score_color(score: int) -> str:
    return "#22c55e" if score >= 70 else ("#facc15" if score >= 45 else "#ef4444")


def score_label(score: int) -> str:
    return ("HEALTHY ✅" if score >= 70 else
            ("CAUTION ⚠️" if score >= 45 else "DANGER 🚨"))


# -----------------------------------------------------------------------------
# GMGN token_stat — public, reusable wrapper for the trending screener
# and the holder-snapshot cron. Returns the top-N holders list, the
# reported total holder count, and the (optional) total supply, all
# from a single GMGN API call.
#
# Cloudflare blocks raw `requests` calls, so we prefer `curl_cffi` to
# impersonate a real Chrome. When that package isn't installed we
# fall back to plain `requests` and accept the higher failure rate.
#
# The shape is intentionally identical to the old private
# ``scripts/update_cvd.py::_gmgn_top_holders`` so the cron refactor is
# a pure delegation (no behaviour change).
# -----------------------------------------------------------------------------
def gmgn_token_stat(ca: str, timeout: int = 15) -> dict:
    """Fetch GMGN token_stat for a Solana CA.

    Returns a dict with keys:
      - ``holders``   : list of ``[owner, ui_amount]`` pairs (largest first,
                        typically up to 10 — GMGN truncates the rest)
      - ``total_holders`` : int — GMGN-reported total holder count, or None
      - ``supply``    : float — total supply if GMGN reports it, or None
      - ``raw``       : the raw GMGN JSON for any caller-side debugging
    On any failure the function returns an empty dict (``{}``) so callers
    can use a single truthy check.
    """
    out = {"holders": [], "total_holders": None, "supply": None, "raw": None}
    try:
        try:
            from curl_cffi import requests as cr
            r = cr.get(
                f"https://gmgn.ai/api/v1/token_stat/sol/{ca}",
                headers={
                    "accept": "application/json, text/plain, */*",
                    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/150.0.0.0 Safari/537.36"),
                },
                impersonate="chrome", timeout=timeout)
        except ImportError:
            r = requests.get(
                f"https://gmgn.ai/api/v1/token_stat/sol/{ca}",
                headers={
                    "accept": "application/json, text/plain, */*",
                    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/150.0.0.0 Safari/537.36"),
                },
                timeout=timeout)
        if r.status_code != 200:
            return out
        try:
            data = r.json() or {}
        except Exception:
            return out
        if not isinstance(data, dict):
            return out
        out["raw"] = data

        # ── holders list (top-10 typically) ─────────────────────────────
        holders: list = []
        for h in (data.get("holders") or []):
            if not isinstance(h, dict):
                continue
            addr = h.get("address") or h.get("owner")
            amt = h.get("amount") or h.get("ui_amount") or h.get("balance")
            try:
                amt_f = float(amt)
            except (TypeError, ValueError):
                continue
            if addr and amt_f > 0:
                holders.append([str(addr), float(amt_f)])
        if not holders:
            for key in ("top10_holders", "top_holders", "top_holder",
                        "top_10_holders"):
                alt = data.get(key)
                if isinstance(alt, list):
                    for h in alt:
                        if not isinstance(h, dict):
                            continue
                        addr = h.get("address") or h.get("owner")
                        amt = h.get("amount") or h.get("ui_amount")
                        try:
                            amt_f = float(amt)
                        except (TypeError, ValueError):
                            continue
                        if addr and amt_f > 0:
                            holders.append([str(addr), float(amt_f)])
                    if holders:
                        break
        out["holders"] = holders

        # ── total holder count (GMGN sometimes reports this under
        # several different keys; we try them in priority order) ───────
        for key in ("holder_count", "holders_count", "total_holders",
                    "num_holders", "holderCount"):
            v = data.get(key)
            try:
                v_int = int(float(v)) if v is not None else 0
            except (TypeError, ValueError):
                continue
            if v_int > 0:
                out["total_holders"] = v_int
                break

        # ── supply (try several known fields) ──────────────────────────
        for key in ("total_supply", "supply", "totalSupply", "total"):
            try:
                v = float(data.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if v > 0:
                out["supply"] = v
                break

    except Exception:
        # Any network/parse error → empty dict; caller handles.
        return {"holders": [], "total_holders": None, "supply": None, "raw": None}
    return out


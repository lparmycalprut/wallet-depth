# -*- coding: utf-8 -*-
"""Fungsi fetch bersama — dipakai app.py dan pages/ (Perbandingan, Riwayat)."""
import json
import os

import pandas as pd
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
HISTORY_PATH = os.path.join(BASE_DIR, "history.json")


def load_config() -> dict:
    cfg = {"helius_api_key": "", "custom_rpc": "", "dust_limit_usd": 10,
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


def get_market(ca: str) -> dict:
    """DexScreener: harga, MC, likuiditas, txns buy/sell, dll."""
    r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}",
                     timeout=20)
    pairs = (r.json() or {}).get("pairs") or []
    if not pairs:
        return {}
    pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0,
               reverse=True)
    b = pairs[0]
    return {
        "name": (b.get("baseToken") or {}).get("name", "?"),
        "symbol": (b.get("baseToken") or {}).get("symbol", "?"),
        "price_usd": float(b.get("priceUsd") or 0),
        "marketcap": float(b.get("marketCap") or b.get("fdv") or 0),
        "liquidity_usd": float((b.get("liquidity") or {}).get("usd") or 0),
        "dex": b.get("dexId", "?"),
        "pair_addresses": [p.get("pairAddress") for p in pairs
                           if p.get("pairAddress")],
        "url": b.get("url", ""),
        "image": ((b.get("info") or {}).get("imageUrl") or ""),
        "txns": b.get("txns") or {},
        "volume": b.get("volume") or {},
        "price_change": b.get("priceChange") or {},
        "pair_created_at": b.get("pairCreatedAt"),
        "pairs_detail": [{
            "dex": p.get("dexId", "?"),
            "pair": p.get("pairAddress"),
            "liq": float((p.get("liquidity") or {}).get("usd") or 0),
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
    r = requests.post(endpoint, json={"jsonrpc": "2.0", "id": 1,
                                      "method": method, "params": params},
                      timeout=timeout)
    d = r.json()
    if "error" in d:
        raise RuntimeError(str(d["error"]))
    return d["result"]


def get_holders(helius_key: str, ca: str) -> pd.DataFrame:
    """Semua holder (agregat per owner) via Helius getTokenAccounts."""
    import time as _t
    endpoint = f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
    owners, cursor, pages = {}, None, 0
    while True:
        params = {"mint": ca, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        d = requests.post(endpoint, json={
            "jsonrpc": "2.0", "id": 1, "method": "getTokenAccounts",
            "params": params}, timeout=60).json()
        if "error" in d:
            raise RuntimeError(str(d["error"]))
        res = d.get("result") or {}
        accs = res.get("token_accounts") or []
        for a in accs:
            owners[a["owner"]] = owners.get(a["owner"], 0.0) + float(a["amount"])
        pages += 1
        cursor = res.get("cursor")
        if not cursor or not accs or pages > 500:
            break
        _t.sleep(0.12)
    return pd.DataFrame({"owner": list(owners.keys()),
                         "raw_amount": list(owners.values())})


def get_supply(helius_key: str, ca: str):
    res = rpc(f"https://mainnet.helius-rpc.com/?api-key={helius_key}",
              "getTokenSupply", [ca], timeout=30)
    v = res["value"]
    return float(v["uiAmount"] or 0), int(v["decimals"])


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
    if max_cluster_pct is None:
        p, note = 7.5, "not scanned"
    else:
        p = clamp((10 - max_cluster_pct) / 10, 0, 1) * 15
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
    # 7. LP locked/burned (maks 5)
    if lp_locked_pct is None:
        p, note = 2.5, "n/a"
    else:
        p = clamp(lp_locked_pct / 80, 0, 1) * 5
        note = f"{lp_locked_pct:.0f}% locked"
    br.append(("LP locked", p, 5, note))
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

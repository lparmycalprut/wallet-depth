# -*- coding: utf-8 -*-
"""
Wallet Depth by Threshold — Solana Token Holder Analyzer
Free data sources: DexScreener, Helius (free key), Solscan internal, RugCheck,
GeckoTerminal.   Run:  streamlit run app.py
"""

import base64
import json
import os
import struct
import time
import urllib.parse
from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components

from core import (concentration, health_score, score_color, score_label,
                  get_rugcheck, get_ohlcv_daily)

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
HISTORY_PATH = os.path.join(BASE_DIR, "history.json")
DEFAULT_CONFIG = {"helius_api_key": "", "custom_rpc": "", "dust_limit_usd": 10,
                  "cluster_warn_pct": 5, "cluster_scan_top_n": 50,
                  "exclude_lp": True}
DUST_LIMIT_USD = 10.0
REAL_RATIO_OK = 0.50       # healthy: real >= 50% of dust
REAL_RATIO_MIN = 0.30      # acceptable floor (yellow) if real also controls MC
TIERS = [(">$10", 10.0), (">$100", 100.0), (">$1K", 1e3),
         (">$10K", 1e4), (">$100K", 1e5), (">$1M", 1e6)]
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
KNOWN_CEX_FUNDERS = {
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9": "Binance",
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "Binance 2",
    "AC5RDfQFmDS1deWZos921JfqscXdByf8BKHs5ACWjtW2": "Bybit",
    "H8sMJSCQxfKiFTCfDR3DUMLPwcRbM61LGFJ8N4dK3WjS": "Coinbase 2",
    "FWznbcNXWQuHTawe9RxvQ2LdCENssh12dsznf4RiouN5": "Kraken",
    "5VCwKtCXgCJ6kit5FybXjvriW3xELsFDhYrPSqtJNmcD": "OKX",
    "GJRs4FwHtemZ5ZE9x3FNvJ8TMwitKTh21yxdRPqn7npE": "Coinbase Hot",
    "ASTyfSima4LLAdDgoFGkgqoKowG1LZFDr9fAQrg7iaJZ": "MEXC",
    "u6PJ8DtQuPFnfmwHbGFULQ4u4EgjDiyYKjVEsynXq2w": "Gate.io",
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f) or {})
    except FileNotFoundError:
        save_config(cfg)
    except Exception:
        pass
    return cfg


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


CONFIG = load_config()
try:
    for _k in DEFAULT_CONFIG:
        if _k in st.secrets:
            CONFIG[_k] = st.secrets[_k]
except Exception:
    pass


def load_history() -> dict:
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_snapshot(ca: str, snap: dict) -> dict:
    hist = load_history()
    hist.setdefault(ca, {})[date.today().isoformat()] = snap
    try:
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(hist, f, indent=1)
    except Exception:
        pass
    return hist


st.set_page_config(page_title="Wallet Depth by Threshold", page_icon="📊",
                   layout="wide", initial_sidebar_state="collapsed")

# ----------------------------------------------------------------------------
# Fetchers (cached)
# ----------------------------------------------------------------------------
@st.cache_data(ttl=60, show_spinner=False)
def fetch_dexscreener(ca: str) -> dict:
    from core import get_market
    return get_market(ca)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_rugcheck(ca: str) -> dict:
    return get_rugcheck(ca)


@st.cache_data(ttl=600, show_spinner=False)
def fetch_ohlcv(pair_address: str) -> pd.DataFrame:
    return get_ohlcv_daily(pair_address)


def rpc_call(endpoint: str, method: str, params: list, timeout: int = 120):
    r = requests.post(endpoint, json={"jsonrpc": "2.0", "id": 1,
                                      "method": method, "params": params},
                      timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return data["result"]


@st.cache_data(ttl=300, show_spinner=False)
def fetch_supply(endpoint: str, ca: str):
    res = rpc_call(endpoint, "getTokenSupply", [ca], timeout=30)
    v = res["value"]
    return float(v["uiAmount"] or 0), int(v["decimals"])


@st.cache_data(ttl=600, show_spinner=False)
def fetch_mint_info(endpoint: str, ca: str) -> dict:
    try:
        res = rpc_call(endpoint, "getAccountInfo",
                       [ca, {"encoding": "jsonParsed"}], timeout=30)
        info = res["value"]["data"]["parsed"]["info"]
        return {"mint_authority": info.get("mintAuthority"),
                "freeze_authority": info.get("freezeAuthority")}
    except Exception:
        return {"mint_authority": None, "freeze_authority": None}


@st.cache_data(ttl=600, show_spinner=False)
def fetch_holders_helius(api_key: str, ca: str) -> pd.DataFrame:
    endpoint = f"https://mainnet.helius-rpc.com/?api-key={api_key}"
    owners, cursor, pages = {}, None, 0
    while True:
        params = {"mint": ca, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        r = requests.post(endpoint, json={"jsonrpc": "2.0", "id": 1,
                                          "method": "getTokenAccounts",
                                          "params": params}, timeout=60)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"Helius error: {data['error']}")
        result = data.get("result") or {}
        accounts = result.get("token_accounts") or []
        for acc in accounts:
            owner = acc.get("owner")
            if owner:
                owners[owner] = owners.get(owner, 0.0) + float(acc.get("amount") or 0)
        pages += 1
        cursor = result.get("cursor")
        if not cursor or not accounts or pages > 500:
            break
        time.sleep(0.15)
    return pd.DataFrame({"owner": list(owners.keys()),
                         "raw_amount": list(owners.values())})


@st.cache_data(ttl=120, show_spinner=False)
def fetch_holders_gpa(endpoint: str, ca: str) -> pd.DataFrame:
    owners = {}
    for program in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
        size = 165 if program == TOKEN_PROGRAM else None
        filters = [{"memcmp": {"offset": 0, "bytes": ca}}]
        if size:
            filters.insert(0, {"dataSize": size})
        try:
            res = rpc_call(endpoint, "getProgramAccounts",
                           [program, {"encoding": "base64",
                                      "dataSlice": {"offset": 32, "length": 40},
                                      "filters": filters}], timeout=240)
        except Exception:
            if program == TOKEN_PROGRAM:
                raise
            continue
        import base58
        for acc in res:
            raw = base64.b64decode(acc["account"]["data"][0])
            owner = base58.b58encode(raw[:32]).decode()
            amount = struct.unpack("<Q", raw[32:40])[0]
            owners[owner] = owners.get(owner, 0.0) + float(amount)
    return pd.DataFrame({"owner": list(owners.keys()),
                         "raw_amount": list(owners.values())})


@st.cache_data(ttl=600, show_spinner=False)
def fetch_solscan_holder_history(ca: str) -> pd.DataFrame:
    """Daily holder count history from Solscan's internal analytics endpoint."""
    try:
        from curl_cffi import requests as creq
    except ImportError:
        return pd.DataFrame()
    try:
        r = creq.get(
            "https://api-v2.solscan.io/v2/analytics/token/his-token-holders",
            params={"address": ca}, impersonate="safari17_0",
            headers={"origin": "https://solscan.io",
                     "referer": "https://solscan.io/"}, timeout=20)
        data = (r.json() or {}).get("data") or []
    except Exception:
        return pd.DataFrame()
    rows = []
    for it in data:
        d = str(it.get("d_date", ""))
        if len(d) == 8:
            rows.append({"date": f"{d[:4]}-{d[4:6]}-{d[6:]}",
                         "holders": int(it.get("num_holder") or 0),
                         "source": "Solscan"})
    df = pd.DataFrame(rows)
    return df.sort_values("date").reset_index(drop=True) if not df.empty else df


# ----------------------------------------------------------------------------
# Persistent funder cache — a wallet's first funder / first-tx time NEVER
# changes, so cache it on disk forever. Saves a lot of Helius credits.
# ----------------------------------------------------------------------------
FUNDERS_PATH = os.path.join(BASE_DIR, "funders_cache.json")


def load_funder_cache() -> dict:
    try:
        with open(FUNDERS_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_funder_cache(cache: dict) -> None:
    try:
        with open(FUNDERS_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, separators=(",", ":"))
    except Exception:
        pass


@st.cache_data(ttl=900, show_spinner=False)
def find_funder(endpoint: str, wallet: str, max_pages: int = 5):
    """Return (first funder wallet, first tx blockTime). Old wallets skipped."""
    before, last_sig, last_bt = None, None, None
    for _ in range(max_pages):
        params = [wallet, {"limit": 1000}]
        if before:
            params[1]["before"] = before
        try:
            res = rpc_call(endpoint, "getSignaturesForAddress", params, timeout=30)
        except Exception:
            return None, None
        if not res:
            break
        last_sig = res[-1]["signature"]
        last_bt = res[-1].get("blockTime")
        if len(res) < 1000:
            break
        before = last_sig
    else:
        return None, None
    if not last_sig:
        return None, None
    try:
        tx = rpc_call(endpoint, "getTransaction",
                      [last_sig, {"encoding": "jsonParsed",
                                  "maxSupportedTransactionVersion": 0}],
                      timeout=30)
    except Exception:
        return None, last_bt
    if not tx:
        return None, last_bt
    try:
        keys = tx["transaction"]["message"]["accountKeys"]
        fee_payer = keys[0]["pubkey"] if isinstance(keys[0], dict) else keys[0]
    except Exception:
        return None, last_bt
    if fee_payer and fee_payer != wallet:
        return fee_payer, last_bt
    try:
        for ins in tx["transaction"]["message"].get("instructions", []):
            parsed = ins.get("parsed") or {}
            info = parsed.get("info") or {}
            if parsed.get("type") == "transfer" and info.get("destination") == wallet:
                src = info.get("source")
                if src and src != wallet:
                    return src, last_bt
    except Exception:
        pass
    return None, last_bt


def detect_clusters(endpoint, top_holders, supply, progress_cb=None,
                    max_pages=5):
    funders, first_time = {}, {}
    wallets = top_holders["owner"].tolist()
    disk = load_funder_cache()
    new_entries = 0
    for i, w in enumerate(wallets):
        if w in disk:                      # immutable -> free lookup
            f, bt = disk[w][0], disk[w][1]
        else:
            f, bt = find_funder(endpoint, w, max_pages=max_pages)
            disk[w] = [f, bt]
            new_entries += 1
            time.sleep(0.1)                # rate-limit only on real calls
        funders[w], first_time[w] = f, bt
        if progress_cb:
            progress_cb((i + 1) / len(wallets), w)
    if new_entries:
        save_funder_cache(disk)
    groups = {}
    for w, f in funders.items():
        if f:
            groups.setdefault(f, []).append(w)
    amt = dict(zip(top_holders["owner"], top_holders["ui_amount"]))
    rows = []
    for funder, members in groups.items():
        total_ui = sum(amt.get(m, 0.0) for m in members)
        if funder in amt and funder not in members:
            members = members + [funder]
            total_ui += amt[funder]
        rows.append({"funder": funder,
                     "cex": KNOWN_CEX_FUNDERS.get(funder, ""),
                     "wallets": len(members), "members": members,
                     "total_tokens": total_ui,
                     "pct_supply": total_ui / supply * 100 if supply else 0.0})
    cdf = pd.DataFrame(rows)
    if not cdf.empty:
        cdf = cdf.sort_values("pct_supply", ascending=False).reset_index(drop=True)
    info = pd.DataFrame({"owner": wallets,
                         "first_tx_time": [first_time.get(w) for w in wallets]})
    return cdf, info


def sol_link(addr: str) -> str:
    return f"https://solscan.io/account/{addr}"


# ----------------------------------------------------------------------------
# Sidebar (settings)
# ----------------------------------------------------------------------------
st.sidebar.title("⚙️ Settings")
st.sidebar.caption("Defaults are loaded from `config.json` — paste your API key "
                   "there, or edit here and click **Save**.")
helius_key = st.sidebar.text_input("Helius API Key", type="password",
                                   value=str(CONFIG.get("helius_api_key") or ""))
custom_rpc = st.sidebar.text_input("Custom RPC URL (optional)",
                                   value=str(CONFIG.get("custom_rpc") or ""),
                                   placeholder="https://...")
exclude_lp = st.sidebar.checkbox("Exclude liquidity-pool wallets (DexScreener)",
                                 value=bool(CONFIG.get("exclude_lp", True)))
dust_limit = st.sidebar.number_input(
    "Dust holder threshold (USD)",
    value=float(CONFIG.get("dust_limit_usd", DUST_LIMIT_USD)),
    min_value=0.1, step=1.0)

st.sidebar.divider()
st.sidebar.markdown("**🕸️ Bundler / Cluster detection**")
scan_clusters = st.sidebar.checkbox("Enable bundler/cluster scan", value=True)
n_scan = st.sidebar.slider("Top holders to scan", 20, 100,
                           int(CONFIG.get("cluster_scan_top_n", 50)), step=10)
cluster_warn_pct = st.sidebar.number_input(
    "Cluster warning threshold (% supply)",
    value=float(CONFIG.get("cluster_warn_pct", 5.0)), min_value=0.5, step=0.5)

st.sidebar.divider()
st.sidebar.markdown("**⚡ Speed / API-credit filters**")
scan_mode = st.sidebar.radio(
    "Scan mode", ["Fast", "Balanced", "Deep"], index=1, horizontal=True,
    help="Fast: top-30 holders, 2 pages of tx history per wallet, skips "
         "holders <0.1% supply. Balanced: your slider, 3 pages. "
         "Deep: your slider, 5 pages (old behaviour).")
min_holder_pct = st.sidebar.number_input(
    "Skip cluster-scan for holders below (% supply)", value=0.05,
    min_value=0.0, step=0.05, format="%.2f",
    help="Wallets this small can't form a dangerous cluster — skipping them "
         "saves credits & time.")
run_cvd_auto = st.sidebar.checkbox(
    "Auto-run CVD analysis after Analyze", value=True,
    help="Fetches live swaps (12h window by default). Disable to save "
         "credits on quick checks.")
_mode_cfg = {"Fast": {"pages": 2, "cap": 30},
             "Balanced": {"pages": 3, "cap": None},
             "Deep": {"pages": 5, "cap": None}}[scan_mode]

st.sidebar.divider()
if st.sidebar.button("💾 Save to config.json", use_container_width=True):
    save_config({"helius_api_key": helius_key, "custom_rpc": custom_rpc,
                 "dust_limit_usd": dust_limit,
                 "cluster_warn_pct": cluster_warn_pct,
                 "cluster_scan_top_n": n_scan, "exclude_lp": exclude_lp})
    st.sidebar.success("Saved ✅")

@st.cache_data(ttl=30, show_spinner=False)
def fetch_watchlist_prices(cas: tuple) -> dict:
    """Batch price fetch for the watchlist ticker (DexScreener, 1 request)."""
    out = {}
    if not cas:
        return out
    try:
        r = requests.get("https://api.dexscreener.com/latest/dex/tokens/" +
                         ",".join(cas[:30]), timeout=15)
        pairs = (r.json() or {}).get("pairs") or []
    except Exception:
        return out
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
            "chg24": float((p.get("priceChange") or {}).get("h24") or 0),
            "mc": float(p.get("marketCap") or p.get("fdv") or 0),
        }
    return out


def _fmt_price(v: float) -> str:
    if v >= 1:
        return f"${v:,.2f}"
    s = f"{v:.10f}".rstrip("0")
    return f"${s}"


# ----------------------------------------------------------------------------
# Main input
# ----------------------------------------------------------------------------
st.title("📊 Wallet Depth by Threshold")
st.caption("Solscan-style holder analytics — Dust vs Real holders for any "
           "Solana token. ⚙️ Settings live in the **sidebar** (» top-left).")

# Watchlist ticker bar — scrollable, clickable, live prices (30s cache)
from watchlist import load_watchlist, add_to_watchlist, remove_from_watchlist

_wl = load_watchlist()
if _wl:
    _prices = fetch_watchlist_prices(tuple(_wl.keys()))
    chips = []
    for _ca, _meta in _wl.items():
        p = _prices.get(_ca)
        sym = (p or {}).get("symbol") or _meta.get("symbol", "?")
        if p:
            chg = p["chg24"]
            chg_col = "#22c55e" if chg >= 0 else "#ef4444"
            arrow = "▲" if chg >= 0 else "▼"
            body = (f"<span style='color:#e2e8f0;font-weight:700;'>{sym}</span>"
                    f"<span style='color:#94a3b8;margin-left:6px;'>"
                    f"{_fmt_price(p['price'])}</span>"
                    f"<span style='color:{chg_col};margin-left:6px;"
                    f"font-weight:700;'>{arrow}{abs(chg):.1f}%</span>")
        else:
            body = (f"<span style='color:#e2e8f0;font-weight:700;'>{sym}</span>"
                    f"<span style='color:#64748b;margin-left:6px;'>n/a</span>")
        chips.append(
            f"<a href='?ca={_ca}' target='_self' style='text-decoration:none;'>"
            f"<span style='display:inline-flex;align-items:center;"
            f"background:#161b26;border:1px solid #2d3748;border-radius:9px;"
            f"padding:5px 12px;margin-right:8px;font-size:0.8rem;"
            f"white-space:nowrap;cursor:pointer;'>⭐ {body}</span></a>")
    st.markdown(
        "<div style='display:flex;overflow-x:auto;padding:4px 2px 8px 2px;"
        "scrollbar-width:thin;-webkit-overflow-scrolling:touch;'>"
        + "".join(chips) + "</div>",
        unsafe_allow_html=True)

# clicking a ticker chip sets ?ca=... -> prefill + auto-analyze
qp_ca = st.query_params.get("ca", "").strip()

ca = st.text_input("Solana token Contract Address (CA)", value=qp_ca,
                   placeholder="e.g. AkchGAUdXXRGHt3HXaHbTvw3JLGUwtJRmYnkG66wpump"
                   ).strip()
analyze = st.button("🔍 Analyze", type="primary", use_container_width=True)
if ca and qp_ca == ca:
    analyze = True  # auto-run when opened from the ticker

# Watchlist controls (below Analyze — add only tokens that pass your criteria)
wcol1, wcol2 = st.columns([1, 3])
if ca and ca in _wl:
    if wcol1.button("💔 Remove from watchlist", use_container_width=True):
        remove_from_watchlist(ca)
        st.rerun()
    wcol2.caption(f"⭐ This CA is on your watchlist (added "
                  f"{_wl[ca].get('added', '?')}) — snapshotted daily by the "
                  f"cron. Manage it on the **⭐ Watchlist** page.")
elif ca:
    if wcol1.button("⭐ Add to watchlist", use_container_width=True):
        _sym = "?"
        try:
            _m = fetch_dexscreener(ca)
            _sym = (_m or {}).get("symbol", "?")
        except Exception:
            pass
        add_to_watchlist(ca, symbol=_sym)
        st.rerun()
    wcol2.caption("Add only if the token passes your criteria — watchlisted "
                  "CAs get a daily automatic snapshot (00:00 WIB).")

if not ca:
    st.info("Paste a Solana token Contract Address (CA) and click **Analyze**.")
    st.stop()
if not analyze and "last_ca" not in st.session_state:
    st.stop()
if analyze:
    st.session_state["last_ca"] = ca

# ----------------------------------------------------------------------------
# Fetch
# ----------------------------------------------------------------------------
with st.spinner("Fetching price & marketcap from DexScreener..."):
    try:
        market = fetch_dexscreener(ca)
    except Exception as e:
        st.error(f"DexScreener fetch failed: {e}")
        st.stop()
if not market:
    st.error("Token not found on DexScreener. Check the CA and make sure the "
             "token has an active pair.")
    st.stop()

price = market["price_usd"]
marketcap = market["marketcap"]
rpc_for_supply = (f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
                  if helius_key else
                  (custom_rpc or "https://solana-rpc.publicnode.com"))
try:
    supply, decimals = fetch_supply(rpc_for_supply, ca)
except Exception:
    supply, decimals = (marketcap / price if price else 0), 6

holders_df, err_msgs = None, []
if helius_key:
    with st.spinner("Fetching all holders via Helius (10–60s)..."):
        try:
            holders_df = fetch_holders_helius(helius_key, ca)
        except Exception as e:
            err_msgs.append(f"Helius failed: {e}")
if holders_df is None and custom_rpc:
    with st.spinner("Fetching holders via custom RPC (getProgramAccounts)..."):
        try:
            holders_df = fetch_holders_gpa(custom_rpc, ca)
        except Exception as e:
            err_msgs.append(f"Custom RPC failed: {e}")
if holders_df is None or holders_df.empty:
    for m in err_msgs:
        st.warning(m)
    st.error("Could not fetch the holder list. Add a **Helius API key** "
             "(free at helius.dev) in the sidebar, or a custom RPC that "
             "supports `getProgramAccounts`.")
    st.stop()

# ----------------------------------------------------------------------------
# Compute
# ----------------------------------------------------------------------------
df = holders_df.copy()
df["ui_amount"] = df["raw_amount"] / (10 ** decimals)
df = df[df["ui_amount"] > 0]
lp_wallets = set(market.get("pair_addresses") or [])
df["is_lp"] = df["owner"].isin(lp_wallets)
lp_value_usd = float((df.loc[df["is_lp"], "ui_amount"] * price).sum())
if exclude_lp:
    df = df[~df["is_lp"]]
df["usd_value"] = df["ui_amount"] * price
df["pct_supply"] = df["ui_amount"] / supply * 100 if supply else 0.0

total_holders = len(df)
dust = df[df["usd_value"] < dust_limit]
real = df[df["usd_value"] >= dust_limit]
n_dust, n_real = len(dust), len(real)
dust_usd, real_usd = dust["usd_value"].sum(), real["usd_value"].sum()
dust_mc_pct = dust_usd / marketcap * 100 if marketcap else 0
real_mc_pct = real_usd / marketcap * 100 if marketcap else 0
ratio = (n_real / n_dust) if n_dust else float("inf")

tier_counts = {label: int((df["usd_value"] > thr).sum()) for label, thr in TIERS}
snapshot = {"total_holders": int(total_holders), "dust": int(n_dust),
            "real": int(n_real), "real_mc_pct": float(real_mc_pct),
            "dust_mc_pct": float(dust_mc_pct), "marketcap": float(marketcap),
            "price": float(price), "tiers": tier_counts,
            "ts": datetime.now().isoformat(timespec="seconds")}
history = save_snapshot(ca, snapshot)
ca_hist = history.get(ca, {})
today_key = date.today().isoformat()
prev_days = sorted(k for k in ca_hist.keys() if k < today_key)
prev_key = prev_days[-1] if prev_days else None
prev = ca_hist.get(prev_key) if prev_key else None

with st.spinner("Fetching daily holder history from Solscan..."):
    solscan_hist = fetch_solscan_holder_history(ca)

holder_delta, holder_delta_src = None, None
if len(solscan_hist) >= 2:
    holder_delta = int(solscan_hist.iloc[-1]["holders"] -
                       solscan_hist.iloc[-2]["holders"])
    holder_delta_src = (f"Solscan: {solscan_hist.iloc[-2]['date']} → "
                        f"{solscan_hist.iloc[-1]['date']}")
elif prev:
    holder_delta = int(total_holders - prev["total_holders"])
    holder_delta_src = f"local snapshot {prev_key}"

rpc_endpoint = (f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
                if helius_key else custom_rpc)

with st.spinner("Fetching security data (RugCheck) & price history..."):
    rug = fetch_rugcheck(ca)
    mint_info = fetch_mint_info(rpc_endpoint, ca) if rpc_endpoint else {}
    pair0 = (market.get("pair_addresses") or [None])[0]
    ohlcv = fetch_ohlcv(pair0) if pair0 else pd.DataFrame()

mint_auth = mint_info.get("mint_authority") or rug.get("mint_authority")
freeze_auth = mint_info.get("freeze_authority") or rug.get("freeze_authority")
creator = rug.get("creator")
creator_balance = rug.get("creator_balance") or 0.0
creator_pct = creator_balance / (10 ** decimals) / supply * 100 if supply else 0
lp_locked_pct = rug.get("lp_locked_pct")
liq_pct_mc = (market["liquidity_usd"] / marketcap * 100) if marketcap else 0
conc = concentration(df, supply)

# Cluster scan + fresh wallets
clusters, wallet_info, bundles = None, None, None
max_cluster_pct, fresh_pct = None, None
if scan_clusters and rpc_endpoint:
    eff_n = min(n_scan, _mode_cfg["cap"] or n_scan)
    top_n = df.sort_values("ui_amount", ascending=False).head(eff_n)
    # speed filter: skip wallets too small to matter for clusters
    if min_holder_pct > 0:
        top_n = top_n[top_n["pct_supply"] >= min_holder_pct]
    cache_key = f"clusters::{ca}::{eff_n}::{scan_mode}::{min_holder_pct}"
    if cache_key not in st.session_state:
        pbar = st.progress(0.0, text="🕸️ Scanning clusters & wallet age...")

        def _cb(frac, wallet):
            pbar.progress(frac, text=f"🕸️ Cluster & fresh-wallet scan... "
                                     f"{frac*100:.0f}%")

        st.session_state[cache_key] = detect_clusters(
            rpc_endpoint, top_n[["owner", "ui_amount"]], supply,
            progress_cb=_cb, max_pages=_mode_cfg["pages"])
        pbar.empty()
    clusters, wallet_info = st.session_state[cache_key]
    bundles = (clusters[(clusters["wallets"] >= 2) & (clusters["cex"] == "")]
               if clusters is not None and not clusters.empty else clusters)
    max_cluster_pct = (float(bundles.iloc[0]["pct_supply"])
                       if bundles is not None and not bundles.empty else 0.0)
    if wallet_info is not None and not wallet_info.empty:
        known = wallet_info.dropna(subset=["first_tx_time"])
        if len(known) > 0:
            fresh_n = int((time.time() - known["first_tx_time"] < 7 * 86400).sum())
            fresh_pct = fresh_n / len(wallet_info) * 100

# Health score
tx24 = (market.get("txns") or {}).get("h24") or {}
tx1 = (market.get("txns") or {}).get("h1") or {}
buys, sells = int(tx24.get("buys") or 0), int(tx24.get("sells") or 0)
bs_ratio = buys / sells if sells else float("inf")
vol24 = float((market.get("volume") or {}).get("h24") or 0)

ratio_pct_val = ratio * 100 if n_dust else 100.0
score, score_parts = health_score(
    ratio_pct=ratio_pct_val, real_mc_pct=real_mc_pct, top10_pct=conc["top10"],
    liq_pct_mc=liq_pct_mc, lp_locked_pct=lp_locked_pct, mint_auth=mint_auth,
    freeze_auth=freeze_auth, holder_delta=holder_delta,
    max_cluster_pct=max_cluster_pct, fresh_pct=fresh_pct)
s_color, s_label = score_color(score), score_label(score)

snapshot.update({"score": score, "top10_pct": round(conc["top10"], 2),
                 "liq_pct_mc": round(liq_pct_mc, 2),
                 "max_cluster_pct": (round(max_cluster_pct, 2)
                                     if max_cluster_pct is not None else None),
                 "symbol": market.get("symbol", "?"),
                 "buys24": buys, "sells24": sells, "vol24": vol24,
                 "top5_pct": round(conc["top5"], 2),
                 "top100_pct": round(conc["top100"], 2)})
history = save_snapshot(ca, snapshot)

# ----------------------------------------------------------------------------
# Compact CSS
# ----------------------------------------------------------------------------
st.markdown("""<style>
.block-container {padding-top: 1.2rem; padding-bottom: 1rem; max-width: 1400px;}
h1 {font-size: 1.3rem !important; margin-bottom: 0 !important;}
h2, h3 {font-size: 1.0rem !important; margin: 0.2rem 0 !important; padding: 0 !important;}
[data-testid="stMetric"] {padding: 0.2rem 0.5rem; background: rgba(128,128,128,0.07);
        border-radius: 8px;}
[data-testid="stMetricLabel"] {font-size: 0.72rem !important;}
[data-testid="stMetricValue"] {font-size: 1.15rem !important;}
[data-testid="stMetricDelta"] {font-size: 0.72rem !important;}
[data-testid="stCaptionContainer"] {font-size: 0.7rem !important; margin: 0 !important;
        line-height: 1.2;}
hr {margin: 0.4rem 0 !important;}
[data-testid="stExpander"] summary {font-size: 0.8rem;}
div[data-testid="stAlert"] {padding: 0.4rem 0.75rem; font-size: 0.82rem;
        margin-bottom: 0.25rem;}
div[data-testid="stAlert"] p {font-size: 0.82rem; margin: 0;}
</style>""", unsafe_allow_html=True)


def strip(color, border, textcolor, html):
    st.markdown(f"""<div style="background:{color};border:1px solid {border};
        border-radius:8px;padding:6px 12px;color:{textcolor};
        font-size:0.85rem;margin-bottom:6px;">{html}</div>""",
                unsafe_allow_html=True)


def red_strip(html):
    strip("#7f1d1d", "#ef4444", "#fecaca", html)


def green_strip(html):
    strip("#14532d", "#22c55e", "#bbf7d0", html)


def info_strip(html):
    strip("rgba(56,189,248,0.08)", "rgba(56,189,248,0.5)", "inherit", html)


WALLET_COL = st.column_config.LinkColumn(
    "Wallet", display_text=r"https://solscan\.io/account/(.{6}).*")
FUNDER_COL = st.column_config.LinkColumn(
    "Funder", display_text=r"https://solscan\.io/account/(.{6}).*")

# ----------------------------------------------------------------------------
# ROW 1 — Score + token header + key metrics
# ----------------------------------------------------------------------------
hs, h0, h1c, h2c, h3c, h4c, h5c, h6c = st.columns(
    [1.1, 0.5, 1.9, 1.2, 1.3, 1.3, 1.3, 1.4])
with hs:
    st.markdown(
        f"""<div style="text-align:center;border:2px solid {s_color};
        border-radius:10px;padding:4px 2px;">
        <div style="font-size:1.5rem;font-weight:800;color:{s_color};
        line-height:1;">{score}</div>
        <div style="font-size:0.62rem;color:{s_color};font-weight:700;">
        {s_label}</div>
        <div style="font-size:0.55rem;opacity:0.6;">Health Score</div>
        </div>""", unsafe_allow_html=True)
with h0:
    if market.get("image"):
        st.image(market["image"], width=44)
with h1c:
    st.markdown(f"**{market['name']} (${market['symbol']})**  \n"
                f"<span style='font-size:0.65rem;opacity:0.6'>"
                f"<a href='https://solscan.io/token/{ca}' target='_blank' "
                f"style='color:inherit'>`{ca[:20]}…`</a></span>",
                unsafe_allow_html=True)
with h2c:
    st.metric("Price", f"${price:,.8f}".rstrip("0").rstrip("."))
with h3c:
    st.metric("Marketcap", f"${marketcap:,.0f}")
with h4c:
    st.metric("Total Holders", f"{total_holders:,}",
              delta=(f"{holder_delta:+,}" if holder_delta is not None else None))
with h5c:
    st.metric(f"🪙 Dust <${dust_limit:g}", f"{n_dust:,}",
              (f"{n_dust - prev['dust']:+,}" if prev else f"{dust_mc_pct:.1f}% MC"),
              delta_color="inverse" if prev else "off")
with h6c:
    st.metric(f"💎 Real ≥${dust_limit:g}", f"{n_real:,}",
              (f"{n_real - prev['real']:+,}" if prev else f"{real_mc_pct:.1f}% MC"),
              delta_color="normal" if prev else "off")

# ----------------------------------------------------------------------------
# ROW 2 — Verdict + Security checklist + Liquidity health donut
# ----------------------------------------------------------------------------
pools = market.get("pairs_detail") or []
total_pool_liq = sum(p["liq"] for p in pools) or 1

col_left, col_liq = st.columns([2.1, 1])

with col_left:
    # --- Holder verdict (3 tiers: green / yellow / red) ----------------------
    if n_dust == 0 or ratio >= REAL_RATIO_OK:
        green_strip(
            f"✅ <b>HOLDERS OK</b> — Real holders ({n_real:,}) = "
            f"<b>{ratio*100:,.1f}%</b> of dust holders ({n_dust:,}), above the "
            f"{REAL_RATIO_OK*100:.0f}% threshold. Real holders control "
            f"<b>{real_mc_pct:.2f}%</b> of MC, dust only {dust_mc_pct:.2f}%. "
            f"Healthy distribution.")
    elif ratio >= REAL_RATIO_MIN and real_mc_pct >= 70:
        strip("#3f3411", "#facc15", "#fef08a",
              f"⚠️ <b>ACCEPTABLE (borderline)</b> — Real/dust ratio is only "
              f"<b>{ratio*100:,.1f}%</b> (below the {REAL_RATIO_OK*100:.0f}% "
              f"healthy bar), BUT real holders still control "
              f"<b>{real_mc_pct:.1f}%</b> of MC — the dust crowd is noisy but "
              f"economically irrelevant. Watch the trend.")
    else:
        red_strip(
            f"🚨 <b>WARNING — UNHEALTHY HOLDER BASE</b> — Real holders "
            f"({n_real:,}) are only <b>{ratio*100:,.1f}%</b> of dust holders "
            f"({n_dust:,}), below the {REAL_RATIO_OK*100:.0f}% threshold. Most "
            f"'holders' are dust wallets (&lt;${dust_limit:g}) from airdrops/"
            f"bundling — the holder count is <b>inflated</b>. Real holders "
            f"control just <b>{real_mc_pct:.2f}%</b> of MC. Be careful!")

    # --- Security checklist card ---------------------------------------------
    checks = []   # (ok: True/False/None, label)
    if rug.get("rugged"):
        checks.append((False, "RugCheck: flagged as RUGGED"))
    checks.append((not mint_auth,
                   "Mint authority revoked" if not mint_auth else
                   f"Mint authority ACTIVE ({str(mint_auth)[:6]}…)"))
    checks.append((not freeze_auth,
                   "Freeze authority revoked" if not freeze_auth else
                   "Freeze authority ACTIVE"))
    if creator is not None:
        if creator_pct > 5:
            checks.append((False, f"Dev still holds {creator_pct:.1f}% supply"))
        else:
            checks.append((True, f"Dev holds {creator_pct:.2f}% supply"))
    checks.append((conc["top10"] <= 30,
                   f"Top-10 = {conc['top10']:.1f}% of supply" +
                   ("" if conc["top10"] <= 30 else " (concentrated!)")))
    if fresh_pct is not None:
        checks.append((fresh_pct <= 50,
                       f"Fresh wallets {fresh_pct:.0f}% of top holders"))
    for r in (rug.get("risks") or [])[:4]:
        if (r.get("level") or "").lower() in ("danger", "warn", "warning"):
            checks.append((False, f"RugCheck: {r['name']}"))
    n_fail = sum(1 for ok, _ in checks if ok is False)
    items_html = "".join(
        f"<div style='flex:0 0 49%;padding:3px 6px;font-size:0.82rem;"
        f"color:{'#bbf7d0' if ok else '#fecaca'};'>"
        f"{'✅' if ok else '❌'} {lab}</div>"
        for ok, lab in checks)
    hdr_col = "#22c55e" if n_fail == 0 else "#ef4444"
    st.markdown(
        f"""<div style="background:{'#14261b' if n_fail == 0 else '#2a1517'};
        border:1px solid {hdr_col};border-radius:10px;padding:8px 12px;
        margin-bottom:6px;">
        <div style="font-size:0.85rem;font-weight:700;color:{hdr_col};
        margin-bottom:4px;">🛡️ Security checklist —
        {('all ' + str(len(checks)) + ' passed') if n_fail == 0
         else f'{n_fail} issue(s) found'}</div>
        <div style="display:flex;flex-wrap:wrap;">{items_html}</div>
        </div>""", unsafe_allow_html=True)

with col_liq:
    # --- Liquidity health donut ----------------------------------------------
    liq_health = ("HEALTHY" if liq_pct_mc >= 10 else
                  ("MODERATE" if liq_pct_mc >= 5 else "THIN"))
    liq_col = ("#22c55e" if liq_pct_mc >= 10 else
               ("#facc15" if liq_pct_mc >= 5 else "#ef4444"))
    active_pools = [p for p in pools if p["liq"] > total_pool_liq * 0.005]
    figl = go.Figure(go.Pie(
        labels=[f"{p['dex'].capitalize()} ({p['quote']})"
                for p in active_pools],
        values=[p["liq"] for p in active_pools], hole=0.62,
        marker=dict(colors=["#38bdf8", "#a78bfa", "#4ade80", "#facc15",
                            "#fb923c"]),
        textinfo="label+percent", textfont=dict(size=10),
        hovertemplate="<b>%{label}</b><br>$%{value:,.0f} "
                      "(%{percent})<extra></extra>"))
    figl.add_annotation(
        text=f"<b style='font-size:17px'>{liq_pct_mc:.1f}%</b><br>"
             f"<span style='font-size:10px'>of MC</span><br>"
             f"<span style='font-size:11px;color:{liq_col}'>"
             f"<b>{liq_health}</b></span>",
        showarrow=False)
    figl.update_layout(height=205, showlegend=False,
                       margin=dict(t=24, b=2, l=8, r=8),
                       title=dict(text="💧 Liquidity vs MC",
                                  font=dict(size=13)))
    st.plotly_chart(figl, use_container_width=True,
                    config={"displayModeBar": False})
    lock_txt = (f"LP locked/burned: {lp_locked_pct:.0f}% (main pool)"
                if lp_locked_pct is not None else "LP lock: n/a")
    st.caption(f"Total ${market['liquidity_usd']:,.0f} across "
               f"{len(active_pools)} pool(s) · {lock_txt} · health bar: "
               f"≥10% MC healthy, 5-10% moderate, <5% thin")

# ----------------------------------------------------------------------------
# ROW 3 — 3 charts side by side
# ----------------------------------------------------------------------------
CHART_H = 240
col_a, col_b, col_c = st.columns([1.5, 1, 1.4])

with col_a:
    st.markdown("**📶 Wallet Depth by Threshold**")
    rows = []
    for label, thr in [("> $0", 0.0)] + TIERS:
        sub = df[df["usd_value"] > thr]
        usd = sub["usd_value"].sum()
        rows.append({"Tier": label, "Wallets": len(sub),
                     "% Holders": len(sub) / total_holders * 100 if total_holders else 0,
                     "USD Value": usd,
                     "% MC": usd / marketcap * 100 if marketcap else 0})
    tier_df = pd.DataFrame(rows)
    bar = go.Figure(go.Bar(
        x=tier_df["Tier"], y=tier_df["Wallets"],
        text=[f"{w:,}" for w in tier_df["Wallets"]], textposition="outside",
        marker=dict(color=["#38bdf8", "#4ade80", "#a3e635", "#facc15",
                           "#fb923c", "#f87171", "#c084fc"]),
        customdata=tier_df[["% MC", "USD Value"]].values,
        hovertemplate=("<b>%{x}</b><br>Wallets: %{y:,}<br>"
                       "Value: $%{customdata[1]:,.0f}<br>"
                       "%{customdata[0]:.2f}% of MC<extra></extra>")))
    bar.update_layout(height=CHART_H, margin=dict(t=10, b=0, l=0, r=0),
                      yaxis=dict(visible=False),
                      xaxis=dict(tickfont=dict(size=9)))
    st.plotly_chart(bar, use_container_width=True,
                    config={"displayModeBar": False})

with col_b:
    st.markdown("**🧮 Dust vs Real**")
    fig = go.Figure(go.Pie(
        labels=["Dust", "Real"], values=[n_dust, n_real], hole=0.55,
        marker=dict(colors=["#64748b", "#22c55e"]),
        textinfo="label+percent", textfont=dict(size=10)))
    fig.add_annotation(text=f"{ratio*100:,.0f}%" if n_dust else "∞",
                       showarrow=False, font=dict(size=16))
    fig.update_layout(height=CHART_H, margin=dict(t=10, b=0, l=0, r=0),
                      showlegend=False)
    st.plotly_chart(fig, use_container_width=True,
                    config={"displayModeBar": False})
    st.caption(f"Real/dust ratio: {ratio*100:,.1f}% (needs "
               f">{REAL_RATIO_OK*100:.0f}%) | Real: {real_mc_pct:.1f}% MC, "
               f"Dust: {dust_mc_pct:.1f}% MC")

with col_c:
    st.markdown("**📈 Holders Day-by-Day**")
    hist_rows = []
    if not solscan_hist.empty:
        hist_rows += solscan_hist.to_dict("records")
    known_dates = {r["date"] for r in hist_rows}
    for dkey in sorted(ca_hist.keys()):
        if dkey not in known_dates:
            hist_rows.append({"date": dkey,
                              "holders": ca_hist[dkey]["total_holders"],
                              "source": "Local"})
    hist_df = pd.DataFrame(hist_rows).sort_values("date").reset_index(drop=True)

    if len(hist_df) >= 2:
        hist_df["delta"] = hist_df["holders"].diff()
        latest_delta = int(hist_df["delta"].iloc[-1])
        pct_chg = (latest_delta / hist_df["holders"].iloc[-2] * 100
                   if hist_df["holders"].iloc[-2] else 0)
        figh = go.Figure()
        figh.add_trace(go.Scatter(
            x=hist_df["date"], y=hist_df["holders"], mode="lines+markers",
            name="Holders", line=dict(color="#38bdf8", width=2.5)))
        if not ohlcv.empty:
            oh = ohlcv[ohlcv["date"].isin(set(hist_df["date"]))]
            if len(oh) >= 2:
                figh.add_trace(go.Scatter(
                    x=oh["date"], y=oh["close"], mode="lines", name="Price",
                    yaxis="y3", line=dict(color="#facc15", width=1.5,
                                          dash="dot")))
        figh.add_trace(go.Bar(
            x=hist_df["date"], y=hist_df["delta"].fillna(0), yaxis="y2",
            opacity=0.55, name="Δ",
            marker=dict(color=["#22c55e" if (v or 0) >= 0 else "#ef4444"
                               for v in hist_df["delta"].fillna(0)]),
            text=[f"{int(v):+,}" if pd.notna(v) and v else ""
                  for v in hist_df["delta"]], textposition="outside",
            textfont=dict(size=9)))
        figh.update_layout(height=CHART_H - 30, showlegend=False,
                           margin=dict(t=10, b=0, l=0, r=0),
                           yaxis=dict(tickfont=dict(size=9)),
                           yaxis2=dict(overlaying="y", side="right", visible=False),
                           yaxis3=dict(overlaying="y", side="right", visible=False),
                           xaxis=dict(tickfont=dict(size=9)))
        st.plotly_chart(figh, use_container_width=True,
                        config={"displayModeBar": False})
        arrow = "📈" if latest_delta > 0 else ("📉" if latest_delta < 0 else "➖")
        color = ("#22c55e" if latest_delta > 0 else
                 ("#ef4444" if latest_delta < 0 else "#94a3b8"))
        extra = ""
        if not ohlcv.empty and len(ohlcv) >= 2:
            price_chg = ohlcv["close"].iloc[-1] - ohlcv["close"].iloc[-2]
            if latest_delta > 0 and price_chg < 0:
                extra = (" · ⚠️ divergence: holders ↑ price ↓ — see "
                         "🔬 Divergence Check below")
            elif latest_delta < 0 and price_chg > 0:
                extra = (" · divergence: holders ↓ price ↑ — see "
                         "🔬 Divergence Check below")
        st.markdown(f"<span style='color:{color};font-size:0.85rem'>"
                    f"{arrow} <b>{latest_delta:+,}</b> ({pct_chg:+.2f}%) vs "
                    f"previous day{extra}</span>", unsafe_allow_html=True)
    else:
        st.caption("No 2+ days of history yet. Today's snapshot is saved — "
                   "deltas appear from tomorrow.")

# ----------------------------------------------------------------------------
# ROW 3.5 — Buy/Sell pressure + concentration + market info
# ----------------------------------------------------------------------------
b1, b2, b3, b4, b5, b6 = st.columns(6)
b1.metric("🟢 Buys 24h", f"{buys:,}", f"1h: {int(tx1.get('buys') or 0):,}",
          delta_color="off")
b2.metric("🔴 Sells 24h", f"{sells:,}", f"1h: {int(tx1.get('sells') or 0):,}",
          delta_color="off")
b3.metric("Buy/Sell Ratio", f"{bs_ratio:.2f}" if sells else "∞",
          "buy pressure" if bs_ratio >= 1 else "sell pressure",
          delta_color="normal" if bs_ratio >= 1 else "inverse")
b4.metric("Vol 24h", f"${vol24:,.0f}")
b5.metric("Top-10 Holders", f"{conc['top10']:.1f}%",
          "of supply" + (" ⚠️" if conc['top10'] > 30 else ""), delta_color="off")
b6.metric("Liquidity", f"${market['liquidity_usd']:,.0f}",
          f"{liq_pct_mc:.1f}% MC", delta_color="off")

# ----------------------------------------------------------------------------
# ROW 3.7 — 🔬 Divergence Check: accumulation or not?
# ----------------------------------------------------------------------------
div_type = None
div_holder_delta, div_price_pct = None, None
if len(hist_df) >= 2 and not ohlcv.empty and len(ohlcv) >= 2:
    div_holder_delta = int(hist_df["holders"].diff().iloc[-1])
    _pc0, _pc1 = float(ohlcv["close"].iloc[-2]), float(ohlcv["close"].iloc[-1])
    div_price_pct = (_pc1 / _pc0 - 1) * 100 if _pc0 else 0.0
    if div_holder_delta < 0 and div_price_pct > 0:
        div_type = "accumulation"     # holders down, price up
    elif div_holder_delta > 0 and div_price_pct < 0:
        div_type = "distribution"     # holders up, price down

if div_type:
    evidence = []   # (check, value, reading, +1 supports / -1 against / 0)
    thesis = ("WHALE ACCUMULATION" if div_type == "accumulation"
              else "DISTRIBUTION / EXIT")

    # -- 1) WHO left/joined: dust vs real (needs previous local snapshot) ----
    if prev:
        d_dust = n_dust - prev["dust"]
        d_real = n_real - prev["real"]
        d_total = (d_dust + d_real) or 1
        dust_share = abs(d_dust) / (abs(d_dust) + abs(d_real) or 1) * 100
        val = (f"dust {d_dust:+,} · real {d_real:+,} "
               f"(vs snapshot {prev_key})")
        if div_type == "accumulation":
            if d_real < 0 and abs(d_real) > abs(d_dust):
                evidence.append(("Who left?", val,
                                 "mostly REAL holders exited → their supply "
                                 "was absorbed by bigger buyers", +1))
            elif d_dust < 0 and dust_share >= 70:
                evidence.append(("Who left?", val,
                                 f"~{dust_share:.0f}% of the change is dust "
                                 f"wallets → just churn, weak signal", -1))
            else:
                evidence.append(("Who left?", val,
                                 "mixed dust/real exits", 0))
        else:  # distribution
            if d_dust > 0 and dust_share >= 70:
                evidence.append(("Who joined?", val,
                                 f"~{dust_share:.0f}% of new holders are dust "
                                 f"→ airdrop/bot inflation, supports "
                                 f"distribution", +1))
            elif d_real > 0 and abs(d_real) > abs(d_dust):
                evidence.append(("Who joined?", val,
                                 "mostly REAL money entering → argues "
                                 "against pure distribution", -1))
            else:
                evidence.append(("Who joined?", val, "mixed inflow", 0))
    else:
        evidence.append(("Who left/joined?", "n/a",
                         "needs a previous local snapshot — scan this CA "
                         "daily to unlock this check", 0))

    # -- 2) Top-10 concentration change ---------------------------------------
    prev_top10 = prev.get("top10_pct") if prev else None
    if prev_top10 is not None:
        d_conc = conc["top10"] - float(prev_top10)
        val = f"{float(prev_top10):.1f}% → {conc['top10']:.1f}% ({d_conc:+.2f}pp)"
        if div_type == "accumulation":
            if d_conc > 0.5:
                evidence.append(("Top-10 concentration", val,
                                 "whales' share GREW → supply consolidating "
                                 "into big hands", +1))
            elif d_conc < -0.5:
                evidence.append(("Top-10 concentration", val,
                                 "whales' share SHRANK → absorber isn't the "
                                 "top holders", -1))
            else:
                evidence.append(("Top-10 concentration", val,
                                 "flat → no visible whale consolidation", 0))
        else:
            if d_conc < -0.5:
                evidence.append(("Top-10 concentration", val,
                                 "whales' share SHRANK → top holders are "
                                 "offloading to retail", +1))
            elif d_conc > 0.5:
                evidence.append(("Top-10 concentration", val,
                                 "whales still adding → not classic "
                                 "distribution", -1))
            else:
                evidence.append(("Top-10 concentration", val, "flat", 0))
    else:
        evidence.append(("Top-10 concentration", f"{conc['top10']:.1f}% today",
                         "no previous snapshot to compare — scan daily", 0))

    # -- 3) Top-100 concentration change --------------------------------------
    prev_top100 = prev.get("top100_pct") if prev else None
    if prev_top100 is not None:
        d_c100 = conc["top100"] - float(prev_top100)
        val = f"{float(prev_top100):.1f}% → {conc['top100']:.1f}% ({d_c100:+.2f}pp)"
        if div_type == "accumulation":
            sup = +1 if d_c100 > 0.5 else (-1 if d_c100 < -0.5 else 0)
        else:
            sup = +1 if d_c100 < -0.5 else (-1 if d_c100 > 0.5 else 0)
        evidence.append(("Top-100 concentration", val,
                         "broader smart-money share " +
                         ("grew" if d_c100 > 0 else
                          ("shrank" if d_c100 < 0 else "flat")), sup))

    # -- 4) Buy/Sell ratio ------------------------------------------------------
    val = f"{bs_ratio:.2f} ({buys:,} buys / {sells:,} sells 24h)"
    if div_type == "accumulation":
        if bs_ratio >= 1.05:
            evidence.append(("Buy/Sell ratio", val,
                             "net buy pressure → consistent with real "
                             "accumulation", +1))
        elif bs_ratio <= 0.95:
            evidence.append(("Buy/Sell ratio", val,
                             "net SELL pressure → price rise likely thin/"
                             "manipulated, not broad accumulation", -1))
        else:
            evidence.append(("Buy/Sell ratio", val, "balanced flow", 0))
    else:
        if bs_ratio <= 0.95:
            evidence.append(("Buy/Sell ratio", val,
                             "net sell pressure → supports distribution", +1))
        elif bs_ratio >= 1.05:
            evidence.append(("Buy/Sell ratio", val,
                             "net buy pressure → argues against "
                             "distribution", -1))
        else:
            evidence.append(("Buy/Sell ratio", val, "balanced flow", 0))

    # -- 5) Volume health --------------------------------------------------------
    vol_mc = vol24 / marketcap * 100 if marketcap else 0
    val = f"${vol24:,.0f} = {vol_mc:.0f}% of MC"
    if vol_mc >= 20:
        evidence.append(("Volume health", val,
                         "healthy, liquid volume → the move is 'real', not "
                         "a few thin trades", +1 if div_type == "accumulation"
                         else 0))
    elif vol_mc < 5:
        evidence.append(("Volume health", val,
                         "very thin volume → price move is unreliable, "
                         "could be a single wallet painting the chart", -1))
    else:
        evidence.append(("Volume health", val, "moderate volume", 0))

    # -- 6) Volume vs previous day ------------------------------------------------
    prev_vol = prev.get("vol24") if prev else None
    if prev_vol:
        d_vol = (vol24 / float(prev_vol) - 1) * 100
        val = f"${float(prev_vol):,.0f} → ${vol24:,.0f} ({d_vol:+.0f}%)"
        if div_type == "accumulation":
            sup = +1 if d_vol > 30 else (0 if d_vol > -30 else -1)
            note = ("rising volume with rising price → conviction" if sup > 0
                    else ("volume fading → move losing steam" if sup < 0
                          else "volume roughly flat"))
        else:
            sup = +1 if d_vol > 30 else 0
            note = ("volume spike on the way down → active exit" if sup > 0
                    else "no volume spike")
        evidence.append(("Volume vs prev day", val, note, sup))

    # -- verdict --------------------------------------------------------------
    score_ev = sum(e[3] for e in evidence)
    n_for = sum(1 for e in evidence if e[3] > 0)
    n_against = sum(1 for e in evidence if e[3] < 0)
    if score_ev >= 2:
        v_txt = f"EVIDENCE LEANS: {thesis}"
        if div_type == "accumulation":
            v_bg, v_col, v_fg = "#14532d", "#22c55e", "#bbf7d0"
        else:
            v_bg, v_col, v_fg = "#7f1d1d", "#ef4444", "#fecaca"
    elif score_ev <= -1:
        v_txt = (f"LIKELY NOT {thesis} — probably dust churn / noise"
                 if div_type == "accumulation" else
                 f"LIKELY NOT {thesis} — inflow looks organic")
        v_bg, v_col, v_fg = "#1e293b", "#94a3b8", "#cbd5e1"
    else:
        v_txt = f"INCONCLUSIVE — mixed evidence for {thesis.lower()}"
        v_bg, v_col, v_fg = "#3f3411", "#facc15", "#fef08a"

    st.markdown("**🔬 Divergence Check — accumulation or not?**")
    dir_txt = ("holders ↓ " + f"{div_holder_delta:+,}" +
               f" while price ↑ {div_price_pct:+.1f}%"
               if div_type == "accumulation" else
               "holders ↑ " + f"{div_holder_delta:+,}" +
               f" while price ↓ {div_price_pct:+.1f}%")
    st.markdown(
        f"""<div style="background:{v_bg};border:2px solid {v_col};
        border-radius:10px;padding:10px 16px;color:{v_fg};font-size:0.9rem;
        margin-bottom:6px;">
        <b style="color:{v_col};">{v_txt}</b> &nbsp;·&nbsp; {dir_txt}
        &nbsp;·&nbsp; {n_for} check(s) for, {n_against} against
        </div>""", unsafe_allow_html=True)

    ev_df = pd.DataFrame([{
        "Verdict": ("✅ supports" if s > 0 else
                    ("❌ against" if s < 0 else "➖ neutral")),
        "Check": c, "Value": v, "Reading": r,
    } for c, v, r, s in evidence])
    st.dataframe(ev_df, use_container_width=True, hide_index=True)
    st.caption(
        "How to read this: a holder/price divergence alone proves nothing. "
        "It only becomes an accumulation signal when concentration rises, "
        "buy pressure and volume confirm it, AND the wallets leaving are "
        "real holders (not dust churn). Checks marked 'n/a' unlock after "
        "you scan this CA on consecutive days. Heuristic — always DYOR.")
elif len(hist_df) >= 2 and not ohlcv.empty:
    st.caption("🔬 Divergence Check: no holder/price divergence today "
               "(holders and price moved the same direction).")

# ----------------------------------------------------------------------------
# ROW 4 — Cluster strip
# ----------------------------------------------------------------------------
if scan_clusters and rpc_endpoint:
    if bundles is None or bundles.empty:
        fresh_txt = (f" · Fresh wallets: {fresh_pct:.0f}%"
                     if fresh_pct is not None else "")
        green_strip(f"🕸️ <b>Clusters:</b> ✅ No bundlers detected among the top "
                    f"{len(top_n)} scanned holders.{fresh_txt}")
    else:
        worst = bundles.iloc[0]
        bundled_supply = bundles["pct_supply"].sum()
        fresh_txt = (f" · Fresh wallets: {fresh_pct:.0f}% of top holders"
                     if fresh_pct is not None else "")
        if worst["pct_supply"] > cluster_warn_pct:
            red_strip(
                f"🕸️ 🚨 <b>BUNDLER DETECTED</b> — largest cluster: "
                f"<b>{int(worst['wallets'])} wallets</b> (funder "
                f"<a href='{sol_link(worst['funder'])}' target='_blank' "
                f"style='color:#fca5a5'><code>{worst['funder'][:6]}…</code></a>) "
                f"holding <b>{worst['pct_supply']:.2f}%</b> of supply (threshold "
                f"{cluster_warn_pct:g}%). {len(bundles)} clusters total = "
                f"{bundled_supply:.2f}% of supply. One entity could dump "
                f"anytime!{fresh_txt}")
        else:
            green_strip(
                f"🕸️ <b>Clusters:</b> ✅ {len(bundles)} small cluster(s), largest "
                f"holds {worst['pct_supply']:.2f}% of supply (threshold "
                f"{cluster_warn_pct:g}%). Total {bundled_supply:.2f}% — "
                f"acceptable.{fresh_txt}")
elif scan_clusters:
    st.caption("🕸️ Cluster scan: needs a Helius API key / custom RPC.")

# ----------------------------------------------------------------------------
# Share to X (formatted text) + dashboard screenshot in one flow
# ----------------------------------------------------------------------------
verdict_emoji = "✅" if (n_dust == 0 or ratio > REAL_RATIO_OK) else "🚨"
cluster_txt_share = ""
if bundles is not None and not bundles.empty:
    w0 = bundles.iloc[0]
    cluster_txt_share = (f"🕸️ Largest cluster: {int(w0['wallets'])} wallets "
                         f"= {w0['pct_supply']:.1f}% supply\n")
elif bundles is not None:
    cluster_txt_share = "🕸️ No bundlers detected\n"

share_text = (
    f"${market['symbol']} — Holder Analysis {verdict_emoji}\n\n"
    f"🧬 Health Score: {score}/100 ({s_label.split()[0]})\n"
    f"👥 Holders: {total_holders:,}"
    + (f" ({holder_delta:+,} vs yesterday)" if holder_delta is not None else "")
    + "\n"
    f"💎 Real (≥${dust_limit:g}): {n_real:,} ({real_mc_pct:.1f}% MC)\n"
    f"🪙 Dust (<${dust_limit:g}): {n_dust:,}\n"
    f"📊 Top-10: {conc['top10']:.1f}% supply · Liq: {liq_pct_mc:.1f}% MC\n"
    + cluster_txt_share +
    f"💰 MC: ${marketcap:,.0f}\n\n"
    f"{ca}"
)
share_url = ("https://twitter.com/intent/tweet?text=" +
             urllib.parse.quote(share_text))

# --- Build the custom share card image (self-designed, always renders clean)
from share_card import build_share_card

hist_dates_share = list(hist_df["date"].tail(7)) if len(hist_df) else []
hist_holders_share = ([int(v) for v in hist_df["holders"].tail(7)]
                      if len(hist_df) else [])
cluster_card_txt = ""
if bundles is not None and not bundles.empty:
    _w0 = bundles.iloc[0]
    cluster_card_txt = (f"Largest cluster {int(_w0['wallets'])} wallets = "
                        f"{_w0['pct_supply']:.1f}% supply")
elif bundles is not None:
    cluster_card_txt = "No bundlers detected"

try:
    card_png = build_share_card(
        symbol=market["symbol"], name=market["name"], ca=ca,
        score=score, score_label=s_label.split()[0],
        holders=total_holders, holder_delta=holder_delta,
        n_real=n_real, n_dust=n_dust,
        ratio_pct=(ratio * 100 if n_dust else 100.0),
        real_mc_pct=real_mc_pct, marketcap=marketcap,
        liquidity_usd=market["liquidity_usd"], liq_pct_mc=liq_pct_mc,
        top10_pct=conc["top10"],
        tier_labels=[t[0] for t in [(">$0", 0)] + TIERS],
        tier_counts=[int((df["usd_value"] > thr).sum())
                     for _, thr in [(">$0", 0)] + TIERS],
        hist_dates=hist_dates_share, hist_holders=hist_holders_share,
        buys24=buys, sells24=sells,
        cluster_txt=cluster_card_txt,
        verdict_ok=(n_dust == 0 or ratio > REAL_RATIO_OK))
except Exception as _e:
    card_png = None
    st.caption(f"Share card generation failed: {_e}")

if card_png:
    sc1, sc2 = st.columns([1.1, 1])
    with sc1:
        st.image(card_png, caption="Share card preview (1200×675 — X ready)")
    with sc2:
        st.download_button("⬇️ Download share card (PNG)", data=card_png,
                           file_name=f"{market['symbol']}_holder_card.png",
                           mime="image/png", use_container_width=True)
        st.link_button("𝕏 Share to X (opens composer)", share_url,
                       use_container_width=True)
        st.caption("1️⃣ Download the card · 2️⃣ Click 𝕏 Share — the composer "
                   "opens with the stats text pre-filled · 3️⃣ Attach the "
                   "downloaded card image. (X doesn't allow auto-attaching "
                   "images from websites.)")

# ----------------------------------------------------------------------------
# ROW 4.5 — 📊 Live CVD analysis (auto-runs with Analyze)
# ----------------------------------------------------------------------------
st.markdown("**📊 On-chain CVD — live swap flow (Helius)**")
cvd_c1, cvd_c2, cvd_c3 = st.columns([1, 1, 3])
cvd_window = cvd_c1.selectbox("Window", [6, 12, 24], index=1,
                              format_func=lambda h: f"last {h}h",
                              key="cvd_win")
cvd_bucket = cvd_c2.selectbox("Candle", [30, 60, 240], index=1,
                              format_func=lambda m: f"{m}m" if m < 60
                              else f"{m//60}h", key="cvd_bkt")

if run_cvd_auto and rpc_endpoint:
    from cvd import classify_swap as _cls, MIN_SOL as _MINSOL, \
        WHALE_SOL as _WHSOL, detect_divergence as _detdiv

    @st.cache_data(ttl=600, show_spinner=False)
    def fetch_live_swaps(ca: str, pool: str, hours: int,
                         max_pages: int = 40):
        """Live swap fetch, newest-first, capped pages to protect credits."""
        cutoff = int(time.time()) - hours * 3600
        swaps, before = [], None
        for _pg in range(max_pages):
            params = {"api-key": helius_key, "limit": 100, "type": "SWAP"}
            if before:
                params["before"] = before
            try:
                rr = requests.get(
                    f"https://api.helius.xyz/v0/addresses/{pool}/transactions",
                    params=params, headers={"User-Agent": "Mozilla/5.0"},
                    timeout=40)
                if rr.status_code != 200:
                    break
                page = rr.json()
            except Exception:
                break
            if not page:
                break
            done = False
            for tx in page:
                if (tx.get("timestamp") or 0) <= cutoff:
                    done = True
                    break
                s = _cls(tx, pool, ca)
                if s and s[1] >= _MINSOL:
                    swaps.append(s)
            if done:
                break
            before = page[-1].get("signature")
            time.sleep(0.1)
        return swaps

    with st.spinner(f"Fetching live swaps (last {cvd_window}h, max 40 "
                    f"pages)…"):
        live_swaps = fetch_live_swaps(ca, pair0, cvd_window) if pair0 else []

    if live_swaps:
        ldf = pd.DataFrame(live_swaps,
                           columns=["side", "sol", "ts", "wallet"])
        ldf["dt"] = pd.to_datetime(ldf["ts"], unit="s")
        ldf["signed"] = ldf.apply(
            lambda r: r["sol"] if r["side"] == "buy" else -r["sol"], axis=1)
        covered_h = (ldf["dt"].max() - ldf["dt"].min()).total_seconds() / 3600
        v_buy = float(ldf.loc[ldf["side"] == "buy", "sol"].sum())
        v_sell = float(ldf.loc[ldf["side"] == "sell", "sol"].sum())
        lnet = v_buy - v_sell
        lwh = ldf[ldf["sol"] >= _WHSOL]
        lwh_net = float(lwh["signed"].sum())
        lrt_net = lnet - lwh_net

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Swaps analyzed", f"{len(ldf):,}",
                  f"{covered_h:.1f}h covered", delta_color="off")
        k2.metric("Net CVD", f"{lnet:+,.1f} SOL",
                  "net buying" if lnet >= 0 else "net selling",
                  delta_color="normal" if lnet >= 0 else "inverse")
        k3.metric(f"🐋 Whale net (≥{_WHSOL:g} SOL)", f"{lwh_net:+,.1f} SOL",
                  f"{len(lwh):,} swaps",
                  delta_color="normal" if lwh_net >= 0 else "inverse")
        k4.metric("🐟 Retail net", f"{lrt_net:+,.1f} SOL", delta_color="off")
        k5.metric("Buy/Sell vol", f"{v_buy:,.0f} / {v_sell:,.0f}",
                  "SOL", delta_color="off")

        if (lwh_net >= 0) != (lrt_net >= 0) and \
                max(abs(lwh_net), abs(lrt_net)) >= 5:
            if lwh_net >= 0:
                green_strip("⚡ <b>Whales buy what retail sells — possible "
                            "stealth accumulation.</b> Verify: consistent "
                            "across windows? Who are the buyers (CVD page → "
                            "top wallets)?")
            else:
                red_strip("⚡ <b>Whales sell into retail buying — "
                          "distribution to retail.</b> Big tickets are "
                          "using retail liquidity to exit.")

        # chart with chosen bucket
        lfreq = f"{cvd_bucket}min"
        lg = ldf.set_index("dt").sort_index()
        lagg = lg.groupby([pd.Grouper(freq=lfreq), "side"])["sol"].sum() \
            .unstack(fill_value=0.0)
        lagg["buy"] = lagg.get("buy", 0.0)
        lagg["sell"] = lagg.get("sell", 0.0)
        lagg["delta"] = lagg["buy"] - lagg["sell"]
        lagg["cvd"] = lagg["delta"].cumsum()
        lwagg = (lg[lg["sol"] >= _WHSOL]
                 .groupby([pd.Grouper(freq=lfreq), "side"])["sol"].sum()
                 .unstack(fill_value=0.0)).reindex(lagg.index, fill_value=0.0)
        lagg["wcvd"] = (lwagg.get("buy", 0.0) -
                        lwagg.get("sell", 0.0)).cumsum()
        lagg["rcvd"] = lagg["cvd"] - lagg["wcvd"]

        lx = lagg.index
        figv = go.Figure()
        figv.add_trace(go.Scatter(x=lx, y=lagg["cvd"], name="CVD (all)",
                                  line=dict(color="#38bdf8", width=3)))
        figv.add_trace(go.Scatter(x=lx, y=lagg["wcvd"], name="🐋 Whale",
                                  line=dict(color="#c084fc", width=2)))
        figv.add_trace(go.Scatter(x=lx, y=lagg["rcvd"], name="🐟 Retail",
                                  line=dict(color="#64748b", width=1.5,
                                            dash="dot")))
        figv.add_bar(x=lx, y=lagg["delta"], name="Δ", yaxis="y2",
                     opacity=0.3,
                     marker=dict(color=["#22c55e" if v >= 0 else "#ef4444"
                                        for v in lagg["delta"]]))
        figv.update_layout(height=280, margin=dict(t=10, b=0, l=0, r=0),
                           legend=dict(orientation="h", font=dict(size=10)),
                           yaxis=dict(title="SOL", tickfont=dict(size=9)),
                           yaxis2=dict(overlaying="y", side="right",
                                       visible=False))
        st.plotly_chart(figv, use_container_width=True,
                        config={"displayModeBar": False})

        # divergence vs price on same buckets
        try:
            from cvd import fetch_price_series
            pmap = fetch_price_series(pair0, max(1, cvd_bucket // 60)) \
                if cvd_bucket >= 60 else {}
            if pmap:
                pser, lastp = [], None
                for t in lx:
                    key = int(t.timestamp())
                    lastp = pmap.get(key, lastp)
                    pser.append(lastp)
                if pser and pser[0] is None:
                    fv = next((p for p in pser if p is not None), None)
                    pser = [fv if p is None else p for p in pser]
                if all(p is not None for p in pser) and len(pser) >= 7:
                    ldivs = _detdiv(pser, list(lagg["cvd"]))
                    ldivs += [dict(dv, src="whale") for dv in
                              _detdiv(pser, list(lagg["wcvd"]))]
                    seen_d = set()
                    for dv in ldivs:
                        kk = (dv["type"], dv["kind"], dv.get("src", "a"))
                        if kk in seen_d:
                            continue
                        seen_d.add(kk)
                        src = ("Whale CVD" if dv.get("src") == "whale"
                               else "CVD")
                        if dv["type"] == "bullish":
                            green_strip(f"📈 <b>{dv['kind'].upper()} BULLISH "
                                        f"divergence ({src})</b> — "
                                        f"{dv['detail']}")
                        else:
                            red_strip(f"📉 <b>{dv['kind'].upper()} BEARISH "
                                      f"divergence ({src})</b> — "
                                      f"{dv['detail']}")
        except Exception:
            pass

        if covered_h < cvd_window * 0.9:
            st.caption(f"⚠️ Very active token: page cap reached "
                       f"{covered_h:.1f}h of the requested {cvd_window}h. "
                       f"Open the 📊 CVD page for a deeper fetch.")
        st.caption(f"Swaps <{_MINSOL:g} SOL filtered · whale ≥{_WHSOL:g} SOL "
                   f"· cached 10 min · full analysis (top wallets, biggest "
                   f"swaps, size brackets) on the **📊 CVD** page.")
    else:
        st.caption("No swaps found in the window (or fetch failed).")
elif not run_cvd_auto:
    st.caption("Auto CVD is off (sidebar → ⚡ filters). Use the 📊 CVD page "
               "for on-demand analysis.")



# ----------------------------------------------------------------------------
# DETAILS — open by default
# ----------------------------------------------------------------------------
ex1, ex2 = st.columns(2)
with ex1:
    with st.expander("📶 Wallet Depth table", expanded=True):
        show = tier_df.copy()
        show["% Holders"] = show["% Holders"].map(lambda v: f"{v:.2f}%")
        show["USD Value"] = show["USD Value"].map(lambda v: f"${v:,.0f}")
        show["% MC"] = show["% MC"].map(lambda v: f"{v:.2f}%")
        show["Wallets"] = show["Wallets"].map(lambda v: f"{v:,}")
        st.dataframe(show, use_container_width=True, hide_index=True)
    with st.expander("🏆 Top 20 Holders", expanded=True):
        top = df.sort_values("usd_value", ascending=False).head(20).copy()
        top["Wallet"] = top["owner"].map(sol_link)
        top["Tokens"] = top["ui_amount"].map(lambda v: f"{v:,.0f}")
        top["USD"] = top["usd_value"].map(lambda v: f"${v:,.2f}")
        top["% Supply"] = top["pct_supply"].map(lambda v: f"{v:.2f}%")
        st.dataframe(top[["Wallet", "Tokens", "USD", "% Supply"]],
                     use_container_width=True, hide_index=True,
                     column_config={"Wallet": WALLET_COL})
        st.caption("Click a wallet to open it on Solscan.")
    with st.expander("🎯 Holder Concentration & Dev info", expanded=True):
        cc = pd.DataFrame([
            {"Group": "Top 1-5", "% Supply": f"{conc['top5']:.2f}%"},
            {"Group": "Top 6-10", "% Supply": f"{conc['top6_10']:.2f}%"},
            {"Group": "Top 11-25", "% Supply": f"{conc['top11_25']:.2f}%"},
            {"Group": "Top 26-50", "% Supply": f"{conc['top26_50']:.2f}%"},
            {"Group": "Top 51-100", "% Supply": f"{conc['top51_100']:.2f}%"},
            {"Group": "TOTAL Top-100", "% Supply": f"{conc['top100']:.2f}%"},
        ])
        st.dataframe(cc, use_container_width=True, hide_index=True)
        if creator:
            st.markdown(
                f"**👨‍💻 Dev/Creator:** "
                f"[`{creator[:8]}…{creator[-4:]}`]({sol_link(creator)})  \n"
                f"Remaining holding: **{creator_pct:.2f}%** of supply · "
                f"Mint auth: {'⚠️ ACTIVE' if mint_auth else '✅ revoked'} · "
                f"Freeze auth: {'⚠️ ACTIVE' if freeze_auth else '✅ revoked'}")
        if rug.get("risks"):
            st.caption("RugCheck risks: " + "; ".join(
                f"{r['name']} ({r.get('level', '?')})"
                for r in rug["risks"][:8]))
        if wallet_info is not None and not wallet_info.empty:
            known = wallet_info.dropna(subset=["first_tx_time"])
            if len(known) > 0:
                ages = (time.time() - known["first_tx_time"]) / 86400
                n7, n30 = int((ages < 7).sum()), int((ages < 30).sum())
                st.caption(f"🐣 Fresh wallets (top {len(wallet_info)} holders): "
                           f"{n7} wallets < 7 days old, {n30} < 30 days. Old "
                           f"wallets (>5k txs) have no age data.")
with ex2:
    with st.expander("📈 Holders Day-by-Day table", expanded=True):
        if len(hist_df) >= 1:
            tbl = hist_df.copy()
            if "delta" not in tbl:
                tbl["delta"] = tbl["holders"].diff()
            tbl["Holders"] = tbl["holders"].map(lambda v: f"{int(v):,}")
            tbl["Δ"] = tbl["delta"].map(
                lambda v: f"{int(v):+,}" if pd.notna(v) else "—")
            tbl["%"] = (tbl["delta"] / tbl["holders"].shift(1) * 100).map(
                lambda v: f"{v:+.2f}%" if pd.notna(v) else "—")
            st.dataframe(tbl[["date", "Holders", "Δ", "%", "source"]].rename(
                columns={"date": "Date", "source": "Source"}),
                use_container_width=True, hide_index=True)
            st.caption("Sources: Solscan (last ~7 days) + local snapshots. "
                       "Solscan counts every token account, so numbers can "
                       "differ slightly from ours (per-owner, LP excluded).")
        else:
            st.caption("No history yet.")
    with st.expander("🕸️ Bundler / Cluster table", expanded=True):
        if bundles is not None and not bundles.empty:
            show_c = bundles.copy()
            show_c["Funder"] = show_c["funder"].map(sol_link)
            show_c["Wallets"] = show_c["wallets"]
            show_c["Members"] = show_c["members"].map(
                lambda ms: ", ".join(m[:6] + "…" for m in ms[:8]) +
                           (f" (+{len(ms)-8})" if len(ms) > 8 else ""))
            show_c["Tokens"] = show_c["total_tokens"].map(lambda v: f"{v:,.0f}")
            show_c["% Supply"] = show_c["pct_supply"].map(lambda v: f"{v:.2f}%")
            show_c["⚠️"] = show_c["pct_supply"].map(
                lambda v: "🚨" if v > cluster_warn_pct else "")
            st.dataframe(show_c[["⚠️", "Funder", "Wallets", "Tokens",
                                 "% Supply", "Members"]],
                         use_container_width=True, hide_index=True,
                         column_config={"Funder": FUNDER_COL})
            if clusters is not None and not clusters.empty:
                cex_rows = clusters[clusters["cex"] != ""]
                if not cex_rows.empty:
                    st.caption("ℹ️ CEX-funded (not a bundle): " + "; ".join(
                        f"{r['cex']}: {int(r['wallets'])} wallets "
                        f"({r['pct_supply']:.2f}%)"
                        for _, r in cex_rows.iterrows()))
            st.caption("Method: first-funder heuristic. Old wallets (>5k txs) "
                       "are skipped. Multi-hop bundlers may evade detection.")
        else:
            st.caption("No clusters detected / scan disabled.")
    with st.expander("🧬 Health Score breakdown", expanded=True):
        sp = pd.DataFrame(
            [{"Component": n, "Points": f"{p:.1f}", "Max": m, "Value": ket}
             for n, p, m, ket in score_parts])
        st.dataframe(sp, use_container_width=True, hide_index=True)
        st.caption("Score = sum of components. ≥70 HEALTHY · 45-69 CAUTION · "
                   "<45 DANGER. Heuristic only — not financial advice, DYOR!")

# Footer
foot = (f"DexScreener (price/MC) · Helius (holders) · Solscan (history) · "
        f"RugCheck (security) · GeckoTerminal (OHLC) | Supply: {supply:,.0f} | "
        f"Dec: {decimals}")
if exclude_lp and lp_wallets:
    foot += f" | {len(lp_wallets)} LP wallet(s) excluded (≈${lp_value_usd:,.0f})"
if holder_delta_src:
    foot += f" | Holder Δ: {holder_delta_src}"
st.caption(foot)

# After analysis finishes, scroll back to the top so the header isn't cut off
if analyze:
    components.html("""<script>
    const doc = window.parent.document;
    const scroller = doc.querySelector('[data-testid="stAppViewContainer"] > .main')
                  || doc.querySelector('[data-testid="stMain"]')
                  || doc.querySelector('[data-testid="stAppViewContainer"]');
    if (scroller) { setTimeout(() => scroller.scrollTo({top: 0}), 300); }
    window.parent.scrollTo({top: 0});
    </script>""", height=0)

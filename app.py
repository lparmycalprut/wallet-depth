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
REAL_RATIO_OK = 0.30
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


@st.cache_data(ttl=120, show_spinner=False)
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


def detect_clusters(endpoint, top_holders, supply, progress_cb=None):
    funders, first_time = {}, {}
    wallets = top_holders["owner"].tolist()
    for i, w in enumerate(wallets):
        f, bt = find_funder(endpoint, w)
        funders[w], first_time[w] = f, bt
        if progress_cb:
            progress_cb((i + 1) / len(wallets), w)
        time.sleep(0.12)
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
if st.sidebar.button("💾 Save to config.json", use_container_width=True):
    save_config({"helius_api_key": helius_key, "custom_rpc": custom_rpc,
                 "dust_limit_usd": dust_limit,
                 "cluster_warn_pct": cluster_warn_pct,
                 "cluster_scan_top_n": n_scan, "exclude_lp": exclude_lp})
    st.sidebar.success("Saved ✅")

# ----------------------------------------------------------------------------
# Main input
# ----------------------------------------------------------------------------
st.title("📊 Wallet Depth by Threshold")
st.caption("Solscan-style holder analytics — Dust vs Real holders for any "
           "Solana token. ⚙️ Settings live in the **sidebar** (» top-left).")

ca = st.text_input("Solana token Contract Address (CA)", value="",
                   placeholder="e.g. AkchGAUdXXRGHt3HXaHbTvw3JLGUwtJRmYnkG66wpump"
                   ).strip()
analyze = st.button("🔍 Analyze", type="primary", use_container_width=True)

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
    top_n = df.sort_values("ui_amount", ascending=False).head(n_scan)
    cache_key = f"clusters::{ca}::{n_scan}"
    if cache_key not in st.session_state:
        pbar = st.progress(0.0, text="🕸️ Scanning clusters & wallet age...")

        def _cb(frac, wallet):
            pbar.progress(frac, text=f"🕸️ Cluster & fresh-wallet scan... "
                                     f"{frac*100:.0f}%")

        st.session_state[cache_key] = detect_clusters(
            rpc_endpoint, top_n[["owner", "ui_amount"]], supply, progress_cb=_cb)
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
                 "symbol": market.get("symbol", "?")})
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
# ROW 2 — Verdict strips
# ----------------------------------------------------------------------------
if n_dust == 0 or ratio > REAL_RATIO_OK:
    green_strip(
        f"✅ <b>HOLDERS OK</b> — Real holders ({n_real:,}) = "
        f"<b>{ratio*100:,.1f}%</b> of dust holders ({n_dust:,}), above the "
        f"{REAL_RATIO_OK*100:.0f}% threshold. Real holders control "
        f"<b>{real_mc_pct:.2f}%</b> of MC, dust only {dust_mc_pct:.2f}%. "
        f"Healthy distribution.")
else:
    red_strip(
        f"🚨 <b>WARNING — UNHEALTHY HOLDER BASE</b> — Real holders ({n_real:,}) "
        f"are only <b>{ratio*100:,.1f}%</b> of dust holders ({n_dust:,}), below "
        f"the {REAL_RATIO_OK*100:.0f}% threshold. Most 'holders' are dust "
        f"wallets (&lt;${dust_limit:g}) from airdrops/bundling — the holder "
        f"count is <b>inflated</b>. Real holders control just "
        f"<b>{real_mc_pct:.2f}%</b> of MC. Be careful!")

# --- Security strip (facts that are clearly red flags only) ------------------
sec_bad, sec_ok = [], []
if rug.get("rugged"):
    sec_bad.append("<b>RUGCHECK: token flagged as RUGGED!</b>")
if mint_auth:
    sec_bad.append(f"mint authority ACTIVE (<code>{str(mint_auth)[:6]}…</code>)")
else:
    sec_ok.append("mint auth revoked")
if freeze_auth:
    sec_bad.append("freeze authority ACTIVE")
else:
    sec_ok.append("freeze auth revoked")
if creator is not None:
    if creator_pct > 5:
        sec_bad.append(f"dev still holds {creator_pct:.1f}% of supply")
    elif creator_pct > 0:
        sec_ok.append(f"dev holds {creator_pct:.2f}%")
    else:
        sec_ok.append("dev balance 0")
if conc["top10"] > 30:
    sec_bad.append(f"Top-10 holders control {conc['top10']:.1f}% of supply")
else:
    sec_ok.append(f"Top-10 = {conc['top10']:.1f}% supply")
if fresh_pct is not None and fresh_pct > 50:
    sec_bad.append(f"{fresh_pct:.0f}% of top holders are fresh wallets (<7d)")
elif fresh_pct is not None:
    sec_ok.append(f"fresh wallets {fresh_pct:.0f}%")
for r in rug.get("risks") or []:
    if (r.get("level") or "").lower() in ("danger", "warn", "warning"):
        sec_bad.append(f"RugCheck: {r['name']}")

if sec_bad:
    red_strip("🛡️ <b>Security:</b> ⚠️ " + " · ".join(sec_bad) +
              (("<span style='opacity:0.7'> | ✅ " + " · ".join(sec_ok) +
                "</span>") if sec_ok else ""))
else:
    green_strip("🛡️ <b>Security:</b> ✅ " + " · ".join(sec_ok))

# --- Liquidity strip: neutral, per-pool detail (LP can be split across DEXes)
pools = market.get("pairs_detail") or []
total_pool_liq = sum(p["liq"] for p in pools) or 1
pool_txt = " · ".join(
    f"<a href='{p['url']}' target='_blank' style='color:inherit'>"
    f"{p['dex'].capitalize()}</a> ${p['liq']:,.0f} "
    f"(<b>{p['liq']/total_pool_liq*100:.1f}%</b>, {p['quote']})"
    for p in pools[:6] if p["liq"] > 0)
lp_lock_txt = (f" · LP locked/burned (main pool per RugCheck): "
               f"<b>{lp_locked_pct:.0f}%</b>" if lp_locked_pct is not None else "")
info_strip(
    f"💧 <b>Liquidity:</b> total <b>${market['liquidity_usd']:,.0f}</b> "
    f"({liq_pct_mc:.1f}% of MC) across {len([p for p in pools if p['liq']>0])} "
    f"pool(s): {pool_txt}{lp_lock_txt}. "
    f"<span style='opacity:0.7'>Note: LP can be spread across multiple DEXes "
    f"(e.g. Meteora, PumpSwap) — verify each pool before judging.</span>")

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
                extra = " · ⚠️ holders up but price down (distribution?)"
            elif latest_delta < 0 and price_chg > 0:
                extra = " · holders down, price up (whale accumulation?)"
        st.markdown(f"<span style='color:{color};font-size:0.85rem'>"
                    f"{arrow} <b>{latest_delta:+,}</b> ({pct_chg:+.2f}%) vs "
                    f"previous day{extra}</span>", unsafe_allow_html=True)
    else:
        st.caption("No 2+ days of history yet. Today's snapshot is saved — "
                   "deltas appear from tomorrow.")

# ----------------------------------------------------------------------------
# ROW 3.5 — Buy/Sell pressure + concentration + market info
# ----------------------------------------------------------------------------
tx24 = (market.get("txns") or {}).get("h24") or {}
tx1 = (market.get("txns") or {}).get("h1") or {}
buys, sells = int(tx24.get("buys") or 0), int(tx24.get("sells") or 0)
bs_ratio = buys / sells if sells else float("inf")
vol24 = float((market.get("volume") or {}).get("h24") or 0)

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
# ROW 4 — Cluster strip
# ----------------------------------------------------------------------------
if scan_clusters and rpc_endpoint:
    if bundles is None or bundles.empty:
        fresh_txt = (f" · Fresh wallets: {fresh_pct:.0f}%"
                     if fresh_pct is not None else "")
        green_strip(f"🕸️ <b>Clusters:</b> ✅ No bundlers detected among the top "
                    f"{n_scan} holders.{fresh_txt}")
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

components.html(f"""
<div style="display:flex;gap:8px;font-family:sans-serif;">
<button onclick="shareX()" style="background:#000;color:#fff;border:1px solid #333;
border-radius:8px;padding:7px 16px;font-size:13px;font-weight:700;
cursor:pointer;">𝕏 Share (text + screenshots)</button>
<button onclick="capture(false)" style="background:#1d4ed8;color:#fff;border:none;
border-radius:8px;padding:7px 16px;font-size:13px;font-weight:700;
cursor:pointer;">📸 Screenshot full page (PNG)</button>
<span id="msg" style="font-size:12px;color:#94a3b8;align-self:center;"></span>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
<script>
const SHARE_URL = {json.dumps(share_url)};
const FNAME = '{market["symbol"]}_holder_analysis';
// max height of one image slice, in CSS pixels (before 2x scale).
// ~ one screen worth of content -> long pages become several images.
const PAGE_H_CSS = 900;

function capture(thenShare) {{
  const msg = document.getElementById('msg');
  msg.textContent = 'Rendering full page…';
  const doc = window.parent.document;
  const target = doc.querySelector('[data-testid="stAppViewContainer"] .main')
                 || doc.querySelector('[data-testid="stAppViewContainer"]')
                 || doc.body;
  const fullH = Math.max(target.scrollHeight, target.offsetHeight);
  const fullW = target.scrollWidth;
  html2canvas(target, {{
      useCORS: true, allowTaint: true, scale: 2,
      backgroundColor: getComputedStyle(doc.body).backgroundColor,
      width: fullW, height: fullH,
      windowWidth: fullW, windowHeight: fullH,
      scrollX: 0, scrollY: 0
  }})
  .then(function(canvas) {{
    const scale = 2;
    const pageH = PAGE_H_CSS * scale;
    const pages = Math.max(1, Math.ceil(canvas.height / pageH));
    let firstBlob = null, done = 0;

    function saveSlice(i) {{
      const sliceH = Math.min(pageH, canvas.height - i * pageH);
      const c = document.createElement('canvas');
      c.width = canvas.width;
      c.height = sliceH;
      const ctx = c.getContext('2d');
      ctx.fillStyle = getComputedStyle(doc.body).backgroundColor || '#0e1117';
      ctx.fillRect(0, 0, c.width, c.height);
      ctx.drawImage(canvas, 0, i * pageH, canvas.width, sliceH,
                    0, 0, canvas.width, sliceH);
      c.toBlob(function(blob) {{
        const a = document.createElement('a');
        a.download = pages > 1 ? FNAME + '_' + (i + 1) + 'of' + pages + '.png'
                               : FNAME + '.png';
        a.href = URL.createObjectURL(blob);
        a.click();
        if (i === 0) firstBlob = blob;
        done++;
        msg.textContent = 'Saved ' + done + '/' + pages + ' image(s)…';
        if (done === pages) finish();
        else setTimeout(function() {{ saveSlice(i + 1); }}, 350);
      }}, 'image/png');
    }}

    function finish() {{
      try {{
        navigator.clipboard.write(
          [new ClipboardItem({{'image/png': firstBlob}})]);
        msg.textContent = pages + ' image(s) saved · first one copied — '
          + (thenShare ? 'paste (Ctrl+V) into the X composer, then attach the rest!'
                       : 'paste anywhere with Ctrl+V.');
      }} catch(e) {{
        msg.textContent = pages + ' image(s) saved! Attach them to your X post.';
      }}
      if (thenShare) {{
        setTimeout(function() {{ window.open(SHARE_URL, '_blank'); }}, 600);
      }}
    }}

    saveSlice(0);
  }}).catch(function(e) {{ msg.textContent = 'Failed: ' + e; }});
}}
function shareX() {{ capture(true); }}
</script>
""", height=42)
st.caption("📸 captures the ENTIRE page top-to-bottom (like Streamlit's print) "
           "and splits it into numbered PNGs (~1 screen each, X-friendly). "
           "𝕏 Share also opens the composer with formatted stats — the first "
           "image is on your clipboard, press Ctrl+V to attach, then add the "
           "rest from your downloads.")

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
    with st.expander("💧 Liquidity pools detail", expanded=True):
        if pools:
            active = [p for p in pools if p["liq"] > 0]
            pl = pd.DataFrame([{
                "DEX": p["dex"].capitalize(),
                "Pool": sol_link(p["pair"]) if p["pair"] else "",
                "Quote": p["quote"],
                "Liquidity": f"${p['liq']:,.0f}",
                "% of Total LP": f"{p['liq']/total_pool_liq*100:.1f}%",
                "Chart": p["url"],
            } for p in active])
            st.dataframe(pl, use_container_width=True, hide_index=True,
                         column_config={
                             "Pool": st.column_config.LinkColumn(
                                 "Pool", display_text=r"account/(.{6}).*"),
                             "Chart": st.column_config.LinkColumn(
                                 "Chart", display_text="DexScreener")})
            # LP distribution — donut chart (clear % labels per DEX)
            if len(active) > 1:
                dist = go.Figure(go.Pie(
                    labels=[f"{p['dex'].capitalize()} ({p['quote']})"
                            for p in active],
                    values=[p["liq"] for p in active],
                    hole=0.5,
                    marker=dict(colors=["#38bdf8", "#a78bfa", "#4ade80",
                                        "#facc15", "#fb923c", "#f87171"]),
                    texttemplate="<b>%{label}</b><br>%{percent} · $%{value:,.0f}",
                    textposition="outside",
                    textfont=dict(size=12),
                    hovertemplate="<b>%{label}</b><br>$%{value:,.0f} "
                                  "(%{percent})<extra></extra>"))
                dist.add_annotation(
                    text=f"<b>${total_pool_liq:,.0f}</b><br>"
                         f"<span style='font-size:10px'>total LP</span>",
                    showarrow=False, font=dict(size=13))
                dist.update_layout(height=260, showlegend=False,
                                   margin=dict(t=30, b=30, l=80, r=80))
                st.plotly_chart(dist, use_container_width=True,
                                config={"displayModeBar": False})
            st.caption((f"Total: ${total_pool_liq:,.0f} across {len(active)} "
                        f"pool(s). LP locked/burned (main pool, RugCheck): "
                        f"{lp_locked_pct:.0f}%") if lp_locked_pct is not None
                       else f"Total: ${total_pool_liq:,.0f} across "
                            f"{len(active)} pool(s). LP lock data unavailable.")
        else:
            st.caption("No pool data.")
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

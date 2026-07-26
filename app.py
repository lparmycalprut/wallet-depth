# -*- coding: utf-8 -*-
"""
Wallet Depth by Threshold — Solana Token Holder Analyzer
=========================================================
Meniru fitur "Wallet Depth by Threshold" di Solscan Analytics, plus
analisa Dust Holder vs Real Holder.

Sumber data (semua gratis):
  - DexScreener API (tanpa API key)  -> harga & marketcap
  - Helius RPC (free API key)        -> daftar SEMUA holder (getTokenAccounts)
  - Custom RPC (opsional)            -> fallback via getProgramAccounts

Jalankan:  streamlit run app.py
"""

import base64
import json
import os
import struct
import time

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# ----------------------------------------------------------------------------
# Config file — edit config.json untuk ganti API key dll.
# ----------------------------------------------------------------------------
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
DEFAULT_CONFIG = {
    "helius_api_key": "",
    "custom_rpc": "",
    "dust_limit_usd": 10,
    "cluster_warn_pct": 5,
    "cluster_scan_top_n": 50,
    "exclude_lp": True,
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f) or {})
    except FileNotFoundError:
        save_config(cfg)  # buat file template saat pertama kali
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

# ----------------------------------------------------------------------------
# History — snapshot holder per hari (disimpan di history.json)
# ----------------------------------------------------------------------------
HISTORY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")


def load_history() -> dict:
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_snapshot(ca: str, snap: dict) -> dict:
    """Simpan snapshot hari ini (overwrite jika hari yang sama dianalisa ulang)."""
    from datetime import date
    hist = load_history()
    hist.setdefault(ca, {})[date.today().isoformat()] = snap
    try:
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(hist, f, indent=1)
    except Exception:
        pass
    return hist


def delta_str(cur, prev, pct=False):
    """Format perubahan: +123 / -45 / 0."""
    if prev is None:
        return None
    d = cur - prev
    sign = "+" if d > 0 else ""
    return f"{sign}{d:,.2f}%" if pct else f"{sign}{d:,.0f}"


@st.cache_data(ttl=600, show_spinner=False)
def fetch_solscan_holder_history(ca: str) -> pd.DataFrame:
    """Riwayat jumlah holder per hari dari endpoint internal Solscan
    (sama dengan grafik 'Token Holder' di halaman analytics).
    Butuh curl_cffi dengan impersonasi Safari untuk melewati Cloudflare.
    Riwayat yang tersedia biasanya ±7 hari terakhir."""
    try:
        from curl_cffi import requests as creq
    except ImportError:
        return pd.DataFrame()
    try:
        r = creq.get(
            "https://api-v2.solscan.io/v2/analytics/token/his-token-holders",
            params={"address": ca},
            impersonate="safari17_0",
            headers={"origin": "https://solscan.io",
                     "referer": "https://solscan.io/"},
            timeout=20,
        )
        data = (r.json() or {}).get("data") or []
    except Exception:
        return pd.DataFrame()
    rows = []
    for it in data:
        d = str(it.get("d_date", ""))
        if len(d) == 8:
            rows.append({
                "date": f"{d[:4]}-{d[4:6]}-{d[6:]}",
                "holders": int(it.get("num_holder") or 0),
                "source": "Solscan",
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("date").reset_index(drop=True)
    return df


# Di Streamlit Cloud, API key disimpan di Secrets (bukan di repo).
# Secrets menimpa config.json jika ada.
try:
    for _k in DEFAULT_CONFIG:
        if _k in st.secrets:
            CONFIG[_k] = st.secrets[_k]
except Exception:
    pass  # tidak ada secrets.toml (jalan lokal) -> pakai config.json saja

# ----------------------------------------------------------------------------
# Konstanta
# ----------------------------------------------------------------------------
DUST_LIMIT_USD = 10.0          # < $10 = dust holder
REAL_RATIO_OK = 0.30           # real holder > 30% dari dust holder => OK

# Tier ala Solscan "Wallet Depth by Threshold" (kumulatif)
TIERS = [
    (">$10",   10.0),
    (">$100",  100.0),
    (">$1K",   1_000.0),
    (">$10K",  10_000.0),
    (">$100K", 100_000.0),
    (">$1M",   1_000_000.0),
]

TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

st.set_page_config(
    page_title="Wallet Depth by Threshold",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",  # sidebar tersembunyi, buka via tombol >>
)

# Wallet CEX/hot-wallet terkenal — pendanaan dari sini BUKAN bundler
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

# ----------------------------------------------------------------------------
# Helper API
# ----------------------------------------------------------------------------
@st.cache_data(ttl=60, show_spinner=False)
def fetch_dexscreener(ca: str) -> dict:
    """Ambil harga, marketcap, info token dari DexScreener (gratis, tanpa key)."""
    url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    pairs = (r.json() or {}).get("pairs") or []
    if not pairs:
        return {}
    # Ambil pair dengan likuiditas terbesar
    pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, reverse=True)
    best = pairs[0]
    return {
        "name": (best.get("baseToken") or {}).get("name", "?"),
        "symbol": (best.get("baseToken") or {}).get("symbol", "?"),
        "price_usd": float(best.get("priceUsd") or 0),
        "marketcap": float(best.get("marketCap") or best.get("fdv") or 0),
        "liquidity_usd": float((best.get("liquidity") or {}).get("usd") or 0),
        "dex": best.get("dexId", "?"),
        "pair_addresses": [p.get("pairAddress") for p in pairs if p.get("pairAddress")],
        "url": best.get("url", ""),
        "image": ((best.get("info") or {}).get("imageUrl") or ""),
    }


def rpc_call(endpoint: str, method: str, params: list, timeout: int = 120):
    r = requests.post(
        endpoint,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return data["result"]


@st.cache_data(ttl=300, show_spinner=False)
def fetch_supply(endpoint: str, ca: str) -> tuple[float, int]:
    res = rpc_call(endpoint, "getTokenSupply", [ca], timeout=30)
    v = res["value"]
    return float(v["uiAmount"] or 0), int(v["decimals"])


@st.cache_data(ttl=120, show_spinner=False)
def fetch_holders_helius(api_key: str, ca: str) -> pd.DataFrame:
    """Ambil SEMUA token account via Helius getTokenAccounts (paginated).
    Free tier Helius mendukung method ini."""
    endpoint = f"https://mainnet.helius-rpc.com/?api-key={api_key}"
    owners: dict[str, float] = {}
    cursor = None
    pages = 0
    while True:
        params: dict = {"mint": ca, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        r = requests.post(
            endpoint,
            json={"jsonrpc": "2.0", "id": 1,
                  "method": "getTokenAccounts", "params": params},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"Helius error: {data['error']}")
        result = data.get("result") or {}
        accounts = result.get("token_accounts") or []
        for acc in accounts:
            owner = acc.get("owner")
            amount = float(acc.get("amount") or 0)
            if owner:
                owners[owner] = owners.get(owner, 0.0) + amount
        pages += 1
        cursor = result.get("cursor")
        if not cursor or not accounts or pages > 500:
            break
        time.sleep(0.15)  # jaga rate limit free tier
    df = pd.DataFrame(
        {"owner": list(owners.keys()), "raw_amount": list(owners.values())}
    )
    return df


@st.cache_data(ttl=120, show_spinner=False)
def fetch_holders_gpa(endpoint: str, ca: str) -> pd.DataFrame:
    """Fallback: getProgramAccounts (butuh RPC yang mengizinkan, mis. Helius/
    QuickNode/Alchemy free plan endpoint milikmu sendiri)."""
    owners: dict[str, float] = {}
    for program in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
        size = 165 if program == TOKEN_PROGRAM else None
        filters = [{"memcmp": {"offset": 0, "bytes": ca}}]
        if size:
            filters.insert(0, {"dataSize": size})
        try:
            res = rpc_call(
                endpoint, "getProgramAccounts",
                [program, {
                    "encoding": "base64",
                    "dataSlice": {"offset": 32, "length": 40},  # owner(32)+amount(8)
                    "filters": filters,
                }],
                timeout=240,
            )
        except Exception:
            if program == TOKEN_PROGRAM:
                raise
            continue
        import base58  # type: ignore
        for acc in res:
            raw = base64.b64decode(acc["account"]["data"][0])
            owner = base58.b58encode(raw[:32]).decode()
            amount = struct.unpack("<Q", raw[32:40])[0]
            owners[owner] = owners.get(owner, 0.0) + float(amount)
    return pd.DataFrame(
        {"owner": list(owners.keys()), "raw_amount": list(owners.values())}
    )


# ----------------------------------------------------------------------------
# Bundler / Cluster detection
# ----------------------------------------------------------------------------
@st.cache_data(ttl=900, show_spinner=False)
def find_funder(endpoint: str, wallet: str, max_pages: int = 5):
    """Cari wallet yang PERTAMA KALI mendanai `wallet` (fee payer transaksi
    tertua). Wallet hasil bundling biasanya masih baru (sedikit transaksi),
    jadi kita batasi max_pages — wallet lama/organik dilewati."""
    before, last_sig = None, None
    for _ in range(max_pages):
        params = [wallet, {"limit": 1000}]
        if before:
            params[1]["before"] = before
        try:
            res = rpc_call(endpoint, "getSignaturesForAddress", params, timeout=30)
        except Exception:
            return None
        if not res:
            break
        last_sig = res[-1]["signature"]
        if len(res) < 1000:
            break
        before = last_sig
    else:
        return None  # > max_pages*1000 transaksi -> wallet lama, skip
    if not last_sig:
        return None
    try:
        tx = rpc_call(
            endpoint, "getTransaction",
            [last_sig, {"encoding": "jsonParsed",
                        "maxSupportedTransactionVersion": 0}],
            timeout=30,
        )
    except Exception:
        return None
    if not tx:
        return None
    try:
        keys = tx["transaction"]["message"]["accountKeys"]
        fee_payer = keys[0]["pubkey"] if isinstance(keys[0], dict) else keys[0]
    except Exception:
        return None
    if fee_payer and fee_payer != wallet:
        return fee_payer
    # fee payer = wallet itu sendiri -> cari pengirim SOL di instruksi
    try:
        for ins in tx["transaction"]["message"].get("instructions", []):
            parsed = ins.get("parsed") or {}
            info = parsed.get("info") or {}
            if parsed.get("type") == "transfer" and info.get("destination") == wallet:
                src = info.get("source")
                if src and src != wallet:
                    return src
    except Exception:
        pass
    return None


def detect_clusters(endpoint: str, top_holders: pd.DataFrame, supply: float,
                    progress_cb=None) -> pd.DataFrame:
    """Kelompokkan top holder berdasarkan wallet pendana pertama yang sama."""
    funders: dict[str, str | None] = {}
    wallets = top_holders["owner"].tolist()
    for i, w in enumerate(wallets):
        funders[w] = find_funder(endpoint, w)
        if progress_cb:
            progress_cb((i + 1) / len(wallets), w)
        time.sleep(0.12)  # jaga rate limit Helius free tier (10 req/s)

    groups: dict[str, list[str]] = {}
    for w, f in funders.items():
        if f:
            groups.setdefault(f, []).append(w)

    amt = dict(zip(top_holders["owner"], top_holders["ui_amount"]))
    rows = []
    for funder, members in groups.items():
        total_ui = sum(amt.get(m, 0.0) for m in members)
        # jika funder sendiri juga holder, masukkan ke cluster
        if funder in amt and funder not in members:
            members = members + [funder]
            total_ui += amt[funder]
        rows.append({
            "funder": funder,
            "cex": KNOWN_CEX_FUNDERS.get(funder, ""),
            "wallets": len(members),
            "members": members,
            "total_tokens": total_ui,
            "pct_supply": total_ui / supply * 100 if supply else 0.0,
        })
    cdf = pd.DataFrame(rows)
    if not cdf.empty:
        cdf = cdf.sort_values("pct_supply", ascending=False).reset_index(drop=True)
    return cdf


# ----------------------------------------------------------------------------
# UI — Sidebar
# ----------------------------------------------------------------------------
st.sidebar.title("⚙️ Pengaturan")
st.sidebar.caption(f"Setelan awal dibaca dari `config.json` — tinggal copy-paste "
                   f"API key di file itu, atau ubah di sini lalu klik **Simpan**.")
st.sidebar.markdown(
    "**Sumber holder data** (pilih salah satu):\n"
    "1. **Helius API key** (disarankan) — daftar gratis di "
    "[helius.dev](https://www.helius.dev), free tier cukup.\n"
    "2. **Custom RPC URL** yang mengizinkan `getProgramAccounts`."
)
helius_key = st.sidebar.text_input(
    "Helius API Key", type="password",
    value=str(CONFIG.get("helius_api_key") or ""),
    help="Diisi otomatis dari config.json. Dipakai untuk mengambil semua holder.")
custom_rpc = st.sidebar.text_input(
    "Custom RPC URL (opsional)",
    value=str(CONFIG.get("custom_rpc") or ""),
    placeholder="https://...")
exclude_lp = st.sidebar.checkbox(
    "Kecualikan wallet liquidity pool (dari DexScreener)",
    value=bool(CONFIG.get("exclude_lp", True)))
dust_limit = st.sidebar.number_input(
    "Batas dust holder (USD)",
    value=float(CONFIG.get("dust_limit_usd", DUST_LIMIT_USD)),
    min_value=0.1, step=1.0)

st.sidebar.divider()
st.sidebar.markdown("**🕸️ Deteksi Bundler / Cluster**")
scan_clusters = st.sidebar.checkbox(
    "Aktifkan scan bundler/cluster", value=True,
    help="Melacak wallet pendana pertama tiap top holder. Wallet yang didanai "
         "oleh pendana yang sama dianggap 1 cluster/bundle.")
n_scan = st.sidebar.slider(
    "Jumlah top holder yang discan", 20, 100,
    int(CONFIG.get("cluster_scan_top_n", 50)), step=10,
    help="Makin banyak makin akurat tapi makin lama (±0.3 dtk/wallet).")
cluster_warn_pct = st.sidebar.number_input(
    "Ambang warning cluster (% supply)",
    value=float(CONFIG.get("cluster_warn_pct", 5.0)),
    min_value=0.5, step=0.5)

st.sidebar.divider()
if st.sidebar.button("💾 Simpan ke config.json", use_container_width=True):
    save_config({
        "helius_api_key": helius_key,
        "custom_rpc": custom_rpc,
        "dust_limit_usd": dust_limit,
        "cluster_warn_pct": cluster_warn_pct,
        "cluster_scan_top_n": n_scan,
        "exclude_lp": exclude_lp,
    })
    st.sidebar.success("Tersimpan ✅")

# ----------------------------------------------------------------------------
# UI — Input utama
# ----------------------------------------------------------------------------
st.title("📊 Wallet Depth by Threshold")
st.caption("Analisa holder ala Solscan Analytics — Dust vs Real Holder untuk token Solana. "
           "⚙️ Pengaturan ada di **sidebar** (klik tanda » di kiri atas untuk buka/sembunyikan).")

ca = st.text_input(
    "Contract Address (CA) token Solana",
    value="",  # input pertama dikosongkan sesuai permintaan
    placeholder="Contoh: AkchGAUdXXRGHt3HXaHbTvw3JLGUwtJRmYnkG66wpump",
).strip()

analyze = st.button("🔍 Analisa", type="primary", use_container_width=True)

if not ca:
    st.info("Masukkan Contract Address (CA) token Solana lalu klik **Analisa**.")
    st.stop()

if not analyze and "last_ca" not in st.session_state:
    st.stop()
if analyze:
    st.session_state["last_ca"] = ca

# ----------------------------------------------------------------------------
# Fetch data
# ----------------------------------------------------------------------------
with st.spinner("Mengambil harga & marketcap dari DexScreener..."):
    try:
        market = fetch_dexscreener(ca)
    except Exception as e:
        st.error(f"Gagal mengambil data DexScreener: {e}")
        st.stop()

if not market:
    st.error("Token tidak ditemukan di DexScreener. Pastikan CA benar dan token "
             "sudah punya pair/likuiditas.")
    st.stop()

price = market["price_usd"]
marketcap = market["marketcap"]

rpc_for_supply = (f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
                  if helius_key else (custom_rpc or "https://solana-rpc.publicnode.com"))
try:
    supply, decimals = fetch_supply(rpc_for_supply, ca)
except Exception:
    supply, decimals = (marketcap / price if price else 0), 6

# --- holders
holders_df = None
err_msgs = []
if helius_key:
    with st.spinner("Mengambil semua holder via Helius (bisa 10–60 detik)..."):
        try:
            holders_df = fetch_holders_helius(helius_key, ca)
        except Exception as e:
            err_msgs.append(f"Helius gagal: {e}")
if holders_df is None and custom_rpc:
    with st.spinner("Mengambil holder via custom RPC (getProgramAccounts)..."):
        try:
            holders_df = fetch_holders_gpa(custom_rpc, ca)
        except Exception as e:
            err_msgs.append(f"Custom RPC gagal: {e}")

if holders_df is None or holders_df.empty:
    for m in err_msgs:
        st.warning(m)
    st.error(
        "Tidak bisa mengambil daftar holder. Masukkan **Helius API key** "
        "(gratis, daftar di helius.dev) di sidebar, atau custom RPC yang "
        "mendukung `getProgramAccounts`."
    )
    st.stop()

# ----------------------------------------------------------------------------
# Hitung
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

# --- Snapshot harian + perbandingan dengan hari sebelumnya -------------------
from datetime import date, datetime

tier_counts = {}
for label, thr in TIERS:
    tier_counts[label] = int((df["usd_value"] > thr).sum())

snapshot = {
    "total_holders": int(total_holders),
    "dust": int(n_dust),
    "real": int(n_real),
    "real_mc_pct": float(real_mc_pct),
    "dust_mc_pct": float(dust_mc_pct),
    "marketcap": float(marketcap),
    "price": float(price),
    "tiers": tier_counts,
    "ts": datetime.now().isoformat(timespec="seconds"),
}
history = save_snapshot(ca, snapshot)

ca_hist = history.get(ca, {})
today_key = date.today().isoformat()
prev_days = sorted(k for k in ca_hist.keys() if k < today_key)
prev_key = prev_days[-1] if prev_days else None
prev = ca_hist.get(prev_key) if prev_key else None

# --- Riwayat holder harian dari Solscan (grafik "Token Holder") --------------
with st.spinner("Mengambil riwayat holder harian dari Solscan..."):
    solscan_hist = fetch_solscan_holder_history(ca)

# delta holder vs kemarin: prioritas data Solscan, fallback snapshot lokal
holder_delta = None
holder_delta_src = None
if len(solscan_hist) >= 2:
    holder_delta = int(solscan_hist.iloc[-1]["holders"] - solscan_hist.iloc[-2]["holders"])
    holder_delta_src = f"Solscan: {solscan_hist.iloc[-2]['date']} → {solscan_hist.iloc[-1]['date']}"
elif prev:
    holder_delta = int(total_holders - prev["total_holders"])
    holder_delta_src = f"snapshot lokal {prev_key}"

# ----------------------------------------------------------------------------
# CSS compact — semua muat 1 halaman
# ----------------------------------------------------------------------------
st.markdown("""<style>
.block-container {padding-top: 1.2rem; padding-bottom: 1rem; max-width: 1400px;}
h1 {font-size: 1.3rem !important; margin-bottom: 0 !important;}
h2, h3 {font-size: 1.0rem !important; margin: 0.2rem 0 0.2rem 0 !important;
        padding: 0 !important;}
[data-testid="stMetric"] {padding: 0.2rem 0.5rem; background: rgba(128,128,128,0.07);
        border-radius: 8px;}
[data-testid="stMetricLabel"] {font-size: 0.72rem !important;}
[data-testid="stMetricValue"] {font-size: 1.15rem !important;}
[data-testid="stMetricDelta"] {font-size: 0.72rem !important;}
[data-testid="stCaptionContainer"] {font-size: 0.7rem !important;
        margin: 0 !important; line-height: 1.2;}
hr {margin: 0.4rem 0 !important;}
[data-testid="stExpander"] summary {font-size: 0.8rem;}
div[data-testid="stAlert"] {padding: 0.4rem 0.75rem; font-size: 0.82rem;
        margin-bottom: 0.25rem;}
div[data-testid="stAlert"] p {font-size: 0.82rem; margin: 0;}
</style>""", unsafe_allow_html=True)


def strip(color: str, border: str, textcolor: str, html: str):
    st.markdown(
        f"""<div style="background:{color};border:1px solid {border};
        border-radius:8px;padding:6px 12px;color:{textcolor};
        font-size:0.85rem;margin-bottom:6px;">{html}</div>""",
        unsafe_allow_html=True)


def red_strip(html):
    strip("#7f1d1d", "#ef4444", "#fecaca", html)


def green_strip(html):
    strip("#14532d", "#22c55e", "#bbf7d0", html)


# ----------------------------------------------------------------------------
# BARIS 1 — Header token + metrics utama (1 baris)
# ----------------------------------------------------------------------------
h0, h1c, h2c, h3c, h4c, h5c, h6c = st.columns([0.5, 2.2, 1.3, 1.4, 1.4, 1.4, 1.6])
with h0:
    if market.get("image"):
        st.image(market["image"], width=44)
with h1c:
    st.markdown(f"**{market['name']} (${market['symbol']})**  \n"
                f"<span style='font-size:0.65rem;opacity:0.6'>`{ca[:20]}…`</span>",
                unsafe_allow_html=True)
with h2c:
    st.metric("Harga", f"${price:,.8f}".rstrip("0").rstrip("."))
with h3c:
    st.metric("Marketcap", f"${marketcap:,.0f}")
with h4c:
    st.metric("Total Holder", f"{total_holders:,}",
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
# BARIS 2 — Verdict strips (ringkas)
# ----------------------------------------------------------------------------
if n_dust == 0 or ratio > REAL_RATIO_OK:
    green_strip(
        f"✅ <b>HOLDER OK</b> — Real holder ({n_real:,}) = "
        f"<b>{ratio*100:,.1f}%</b> dari dust ({n_dust:,}), di atas ambang "
        f"{REAL_RATIO_OK*100:.0f}%. Real pegang <b>{real_mc_pct:.2f}%</b> MC, "
        f"dust hanya {dust_mc_pct:.2f}% MC. Distribusi sehat.")
else:
    red_strip(
        f"🚨 <b>PERINGATAN — HOLDER TIDAK SEHAT</b> — Real holder ({n_real:,}) "
        f"hanya <b>{ratio*100:,.1f}%</b> dari dust ({n_dust:,}), di bawah ambang "
        f"{REAL_RATIO_OK*100:.0f}%. Mayoritas holder = wallet debu (&lt;${dust_limit:g}) "
        f"dari airdrop/bundling — holder count <b>semu</b>. Real hanya pegang "
        f"<b>{real_mc_pct:.2f}%</b> MC. Hati-hati!")

# ----------------------------------------------------------------------------
# BARIS 3 — 3 kolom: Depth chart | Dust vs Real pie | Day-by-day
# ----------------------------------------------------------------------------
CHART_H = 240
col_a, col_b, col_c = st.columns([1.5, 1, 1.4])

with col_a:
    st.markdown("**📶 Wallet Depth by Threshold**")
    rows = []
    for label, thr in [("> $0", 0.0)] + TIERS:
        sub = df[df["usd_value"] > thr]
        usd = sub["usd_value"].sum()
        rows.append({"Tier": label, "Wallet": len(sub),
                     "% Holder": len(sub) / total_holders * 100 if total_holders else 0,
                     "Nilai USD": usd,
                     "% MC": usd / marketcap * 100 if marketcap else 0})
    tier_df = pd.DataFrame(rows)
    bar = go.Figure(go.Bar(
        x=tier_df["Tier"], y=tier_df["Wallet"],
        text=[f"{w:,}" for w in tier_df["Wallet"]], textposition="outside",
        marker=dict(color=["#38bdf8", "#4ade80", "#a3e635", "#facc15",
                           "#fb923c", "#f87171", "#c084fc"]),
        customdata=tier_df[["% MC", "Nilai USD"]].values,
        hovertemplate=("<b>%{x}</b><br>Wallet: %{y:,}<br>"
                       "Nilai: $%{customdata[1]:,.0f}<br>"
                       "%{customdata[0]:.2f}% MC<extra></extra>")))
    bar.update_layout(height=CHART_H, margin=dict(t=10, b=0, l=0, r=0),
                      yaxis=dict(visible=False),
                      xaxis=dict(tickfont=dict(size=9)))
    st.plotly_chart(bar, use_container_width=True,
                    config={"displayModeBar": False})

with col_b:
    st.markdown("**🧮 Dust vs Real**")
    fig = go.Figure(go.Pie(
        labels=[f"Dust", f"Real"], values=[n_dust, n_real], hole=0.55,
        marker=dict(colors=["#64748b", "#22c55e"]),
        textinfo="label+percent", textfont=dict(size=10)))
    fig.add_annotation(text=f"{ratio*100:,.0f}%" if n_dust else "∞",
                       showarrow=False, font=dict(size=16))
    fig.update_layout(height=CHART_H, margin=dict(t=10, b=0, l=0, r=0),
                      showlegend=False)
    st.plotly_chart(fig, use_container_width=True,
                    config={"displayModeBar": False})
    st.caption(f"Rasio real/dust: {ratio*100:,.1f}% (ambang "
               f">{REAL_RATIO_OK*100:.0f}%) | Real: {real_mc_pct:.1f}% MC, "
               f"Dust: {dust_mc_pct:.1f}% MC")

with col_c:
    st.markdown("**📈 Holder Day-by-Day**")
    hist_rows = []
    if not solscan_hist.empty:
        hist_rows += solscan_hist.to_dict("records")
    known_dates = {r["date"] for r in hist_rows}
    for dkey in sorted(ca_hist.keys()):
        if dkey not in known_dates:
            hist_rows.append({"date": dkey,
                              "holders": ca_hist[dkey]["total_holders"],
                              "source": "Lokal"})
    hist_df = pd.DataFrame(hist_rows).sort_values("date").reset_index(drop=True)

    if len(hist_df) >= 2:
        hist_df["delta"] = hist_df["holders"].diff()
        latest_delta = int(hist_df["delta"].iloc[-1])
        pct_chg = (latest_delta / hist_df["holders"].iloc[-2] * 100
                   if hist_df["holders"].iloc[-2] else 0)
        figh = go.Figure()
        figh.add_trace(go.Scatter(
            x=hist_df["date"], y=hist_df["holders"], mode="lines+markers",
            name="Holder", line=dict(color="#38bdf8", width=2.5)))
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
                           yaxis2=dict(overlaying="y", side="right",
                                       visible=False),
                           xaxis=dict(tickfont=dict(size=9)))
        st.plotly_chart(figh, use_container_width=True,
                        config={"displayModeBar": False})
        arrow = "📈" if latest_delta > 0 else ("📉" if latest_delta < 0 else "➖")
        color = "#22c55e" if latest_delta > 0 else ("#ef4444" if latest_delta < 0 else "#94a3b8")
        st.markdown(f"<span style='color:{color};font-size:0.85rem'>"
                    f"{arrow} <b>{latest_delta:+,}</b> ({pct_chg:+.2f}%) vs hari "
                    f"sebelumnya</span>", unsafe_allow_html=True)
    else:
        st.caption("Belum ada riwayat ≥2 hari. Snapshot hari ini tercatat — "
                   "delta muncul mulai besok.")

# ----------------------------------------------------------------------------
# BARIS 4 — Bundler / Cluster (strip ringkas + tabel di expander)
# ----------------------------------------------------------------------------
rpc_endpoint = (f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
                if helius_key else custom_rpc)
clusters = None
bundles = None
if scan_clusters and rpc_endpoint:
    top_n = df.sort_values("ui_amount", ascending=False).head(n_scan)
    cache_key = f"clusters::{ca}::{n_scan}"
    if cache_key not in st.session_state:
        pbar = st.progress(0.0, text="🕸️ Melacak funder top holder...")

        def _cb(frac, wallet):
            pbar.progress(frac, text=f"🕸️ Scan cluster... {frac*100:.0f}%")

        st.session_state[cache_key] = detect_clusters(
            rpc_endpoint, top_n[["owner", "ui_amount"]], supply, progress_cb=_cb)
        pbar.empty()
    clusters = st.session_state[cache_key]
    bundles = (clusters[(clusters["wallets"] >= 2) & (clusters["cex"] == "")]
               if clusters is not None and not clusters.empty else clusters)

    if bundles is None or bundles.empty:
        green_strip(f"🕸️ <b>Cluster:</b> ✅ Tidak terdeteksi bundler di antara "
                    f"{len(top_n)} top holder.")
    else:
        worst = bundles.iloc[0]
        bundled_supply = bundles["pct_supply"].sum()
        if worst["pct_supply"] > cluster_warn_pct:
            red_strip(
                f"🕸️ 🚨 <b>BUNDLER TERDETEKSI</b> — cluster terbesar: "
                f"<b>{int(worst['wallets'])} wallet</b> (funder "
                f"<code>{worst['funder'][:6]}…</code>) pegang "
                f"<b>{worst['pct_supply']:.2f}%</b> supply (ambang "
                f"{cluster_warn_pct:g}%). Total {len(bundles)} cluster = "
                f"{bundled_supply:.2f}% supply. Bisa dump kapan saja!")
        else:
            green_strip(
                f"🕸️ <b>Cluster:</b> ✅ {len(bundles)} cluster kecil, terbesar "
                f"{worst['pct_supply']:.2f}% supply (ambang {cluster_warn_pct:g}%). "
                f"Total {bundled_supply:.2f}% — wajar.")
elif scan_clusters:
    st.caption("🕸️ Cluster scan: butuh Helius API key / custom RPC.")

# ----------------------------------------------------------------------------
# DETAIL — semua tabel di dalam expander (klik untuk buka)
# ----------------------------------------------------------------------------
ex1, ex2 = st.columns(2)
with ex1:
    with st.expander("📶 Tabel Wallet Depth"):
        show = tier_df.copy()
        show["% Holder"] = show["% Holder"].map(lambda v: f"{v:.2f}%")
        show["Nilai USD"] = show["Nilai USD"].map(lambda v: f"${v:,.0f}")
        show["% MC"] = show["% MC"].map(lambda v: f"{v:.2f}%")
        show["Wallet"] = show["Wallet"].map(lambda v: f"{v:,}")
        st.dataframe(show, use_container_width=True, hide_index=True)
    with st.expander("🏆 Top 20 Holder"):
        top = df.sort_values("usd_value", ascending=False).head(20).copy()
        top["Wallet"] = top["owner"]
        top["Token"] = top["ui_amount"].map(lambda v: f"{v:,.0f}")
        top["USD"] = top["usd_value"].map(lambda v: f"${v:,.2f}")
        top["% Supply"] = top["pct_supply"].map(lambda v: f"{v:.2f}%")
        st.dataframe(top[["Wallet", "Token", "USD", "% Supply"]],
                     use_container_width=True, hide_index=True)
with ex2:
    with st.expander("📈 Tabel Holder Day-by-Day"):
        if len(hist_df) >= 1:
            tbl = hist_df.copy()
            if "delta" not in tbl:
                tbl["delta"] = tbl["holders"].diff()
            tbl["Holder"] = tbl["holders"].map(lambda v: f"{int(v):,}")
            tbl["Δ"] = tbl["delta"].map(
                lambda v: f"{int(v):+,}" if pd.notna(v) else "—")
            tbl["%"] = (tbl["delta"] / tbl["holders"].shift(1) * 100).map(
                lambda v: f"{v:+.2f}%" if pd.notna(v) else "—")
            st.dataframe(tbl[["date", "Holder", "Δ", "%", "source"]].rename(
                columns={"date": "Tanggal", "source": "Sumber"}),
                use_container_width=True, hide_index=True)
            st.caption("Sumber: Solscan (±7 hari) + snapshot lokal. Angka Solscan "
                       "hitung semua token account, bisa sedikit beda.")
        else:
            st.caption("Belum ada data riwayat.")
    with st.expander("🕸️ Tabel Bundler / Cluster"):
        if bundles is not None and not bundles.empty:
            show_c = bundles.copy()
            show_c["Funder"] = show_c["funder"]
            show_c["Wallet"] = show_c["wallets"]
            show_c["Anggota"] = show_c["members"].map(
                lambda ms: ", ".join(m[:6] + "…" for m in ms[:8]) +
                           (f" (+{len(ms)-8})" if len(ms) > 8 else ""))
            show_c["Token"] = show_c["total_tokens"].map(lambda v: f"{v:,.0f}")
            show_c["% Supply"] = show_c["pct_supply"].map(lambda v: f"{v:.2f}%")
            show_c["⚠️"] = show_c["pct_supply"].map(
                lambda v: "🚨" if v > cluster_warn_pct else "")
            st.dataframe(show_c[["⚠️", "Funder", "Wallet", "Token",
                                 "% Supply", "Anggota"]],
                         use_container_width=True, hide_index=True)
            if clusters is not None and not clusters.empty:
                cex_rows = clusters[clusters["cex"] != ""]
                if not cex_rows.empty:
                    st.caption("ℹ️ Didanai CEX (bukan bundle): " + "; ".join(
                        f"{r['cex']}: {int(r['wallets'])} wallet "
                        f"({r['pct_supply']:.2f}%)"
                        for _, r in cex_rows.iterrows()))
            st.caption("Metode: first-funder heuristic. Wallet lama (>5rb tx) "
                       "dilewati. Bundler multi-hop bisa lolos.")
        else:
            st.caption("Tidak ada cluster terdeteksi / scan dimatikan.")

# Footer ringkas
foot = (f"DexScreener (harga/MC) + Helius (holder) + Solscan (riwayat) | "
        f"Supply: {supply:,.0f} | Dec: {decimals}")
if exclude_lp and lp_wallets:
    foot += f" | {len(lp_wallets)} LP wallet dikecualikan (≈${lp_value_usd:,.0f})"
if holder_delta_src:
    foot += f" | Δ holder: {holder_delta_src}"
st.caption(foot)

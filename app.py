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
        "txns": best.get("txns") or {},
        "volume": best.get("volume") or {},
        "price_change": best.get("priceChange") or {},
    }


@st.cache_data(ttl=300, show_spinner=False)
def fetch_rugcheck(ca: str) -> dict:
    from core import get_rugcheck
    return get_rugcheck(ca)


@st.cache_data(ttl=600, show_spinner=False)
def fetch_ohlcv(pair_address: str) -> pd.DataFrame:
    from core import get_ohlcv_daily
    return get_ohlcv_daily(pair_address)


@st.cache_data(ttl=600, show_spinner=False)
def fetch_mint_info(endpoint: str, ca: str) -> dict:
    """Mint & freeze authority langsung dari chain."""
    try:
        res = rpc_call(endpoint, "getAccountInfo",
                       [ca, {"encoding": "jsonParsed"}], timeout=30)
        info = res["value"]["data"]["parsed"]["info"]
        return {"mint_authority": info.get("mintAuthority"),
                "freeze_authority": info.get("freezeAuthority")}
    except Exception:
        return {"mint_authority": None, "freeze_authority": None}


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
    """Cari (wallet pendana pertama, blockTime tx pertama).
    Wallet lama (> max_pages*1000 tx) -> (None, None)."""
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
        return None, None  # wallet lama/organik, skip
    if not last_sig:
        return None, None
    try:
        tx = rpc_call(
            endpoint, "getTransaction",
            [last_sig, {"encoding": "jsonParsed",
                        "maxSupportedTransactionVersion": 0}],
            timeout=30,
        )
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
    # fee payer = wallet itu sendiri -> cari pengirim SOL di instruksi
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


def detect_clusters(endpoint: str, top_holders: pd.DataFrame, supply: float,
                    progress_cb=None):
    """Kelompokkan top holder berdasarkan wallet pendana pertama yang sama.
    Return (cluster_df, wallet_info_df dengan first_tx_time)."""
    funders: dict = {}
    first_time: dict = {}
    wallets = top_holders["owner"].tolist()
    for i, w in enumerate(wallets):
        f, bt = find_funder(endpoint, w)
        funders[w] = f
        first_time[w] = bt
        if progress_cb:
            progress_cb((i + 1) / len(wallets), w)
        time.sleep(0.12)  # jaga rate limit Helius free tier (10 req/s)

    groups: dict = {}
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
    info = pd.DataFrame({"owner": wallets,
                         "first_tx_time": [first_time.get(w) for w in wallets]})
    return cdf, info


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

# --- Data tambahan: RugCheck, mint authority, OHLCV, konsentrasi -------------
from core import concentration, health_score, score_color, score_label

rpc_endpoint = (f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
                if helius_key else custom_rpc)

with st.spinner("Mengambil data keamanan (RugCheck) & harga historis..."):
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

# --- Cluster scan + fresh wallet (dipindah ke awal agar masuk skor) ----------
clusters, wallet_info, bundles = None, None, None
max_cluster_pct, fresh_pct = None, None
if scan_clusters and rpc_endpoint:
    top_n = df.sort_values("ui_amount", ascending=False).head(n_scan)
    cache_key = f"clusters::{ca}::{n_scan}"
    if cache_key not in st.session_state:
        pbar = st.progress(0.0, text="🕸️ Scan cluster & umur wallet...")

        def _cb(frac, wallet):
            pbar.progress(frac, text=f"🕸️ Scan cluster & fresh wallet... {frac*100:.0f}%")

        st.session_state[cache_key] = detect_clusters(
            rpc_endpoint, top_n[["owner", "ui_amount"]], supply, progress_cb=_cb)
        pbar.empty()
    clusters, wallet_info = st.session_state[cache_key]
    bundles = (clusters[(clusters["wallets"] >= 2) & (clusters["cex"] == "")]
               if clusters is not None and not clusters.empty else clusters)
    if bundles is not None and not bundles.empty:
        max_cluster_pct = float(bundles.iloc[0]["pct_supply"])
    else:
        max_cluster_pct = 0.0
    # fresh wallet: first tx < 7 hari
    if wallet_info is not None and not wallet_info.empty:
        now_ts = time.time()
        known = wallet_info.dropna(subset=["first_tx_time"])
        if len(known) > 0:
            fresh_n = int((now_ts - known["first_tx_time"] < 7 * 86400).sum())
            fresh_pct = fresh_n / len(wallet_info) * 100
            fresh_wallets_n = fresh_n
        else:
            fresh_wallets_n = 0

# --- Skor Kesehatan 0-100 -----------------------------------------------------
ratio_pct_val = ratio * 100 if n_dust else 100.0
score, score_parts = health_score(
    ratio_pct=ratio_pct_val, real_mc_pct=real_mc_pct, top10_pct=conc["top10"],
    liq_pct_mc=liq_pct_mc, lp_locked_pct=lp_locked_pct, mint_auth=mint_auth,
    freeze_auth=freeze_auth, holder_delta=holder_delta,
    max_cluster_pct=max_cluster_pct, fresh_pct=fresh_pct)
s_color, s_label = score_color(score), score_label(score)

# update snapshot dengan skor & data baru (untuk page Riwayat)
snapshot.update({"score": score, "top10_pct": round(conc["top10"], 2),
                 "liq_pct_mc": round(liq_pct_mc, 2),
                 "max_cluster_pct": (round(max_cluster_pct, 2)
                                     if max_cluster_pct is not None else None),
                 "symbol": market.get("symbol", "?")})
history = save_snapshot(ca, snapshot)

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
# BARIS 1 — Skor + header token + metrics utama (1 baris)
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
        <div style="font-size:0.55rem;opacity:0.6;">Skor Kesehatan</div>
        </div>""", unsafe_allow_html=True)
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

# --- Strip keamanan gabungan: dev, authority, LP, konsentrasi, fresh ---------
sec_bad, sec_ok = [], []
if rug.get("rugged"):
    sec_bad.append("<b>RUGCHECK: token ditandai RUGGED!</b>")
if mint_auth:
    sec_bad.append(f"mint authority AKTIF (<code>{str(mint_auth)[:6]}…</code>)")
else:
    sec_ok.append("mint auth dicabut")
if freeze_auth:
    sec_bad.append("freeze authority AKTIF")
else:
    sec_ok.append("freeze auth dicabut")
if creator is not None:
    if creator_pct > 5:
        sec_bad.append(f"dev masih pegang {creator_pct:.1f}% supply")
    elif creator_pct > 0:
        sec_ok.append(f"dev pegang {creator_pct:.2f}%")
    else:
        sec_ok.append("dev balance 0")
if lp_locked_pct is not None:
    if lp_locked_pct < 50:
        sec_bad.append(f"LP locked/burned hanya {lp_locked_pct:.0f}%")
    else:
        sec_ok.append(f"LP locked {lp_locked_pct:.0f}%")
if liq_pct_mc < 3:
    sec_bad.append(f"likuiditas tipis ({liq_pct_mc:.1f}% MC — susah exit)")
else:
    sec_ok.append(f"likuiditas {liq_pct_mc:.1f}% MC")
if conc["top10"] > 30:
    sec_bad.append(f"Top-10 holder pegang {conc['top10']:.1f}% supply")
else:
    sec_ok.append(f"Top-10 = {conc['top10']:.1f}% supply")
if fresh_pct is not None and fresh_pct > 50:
    sec_bad.append(f"{fresh_pct:.0f}% top holder = wallet fresh (<7 hari)")
elif fresh_pct is not None:
    sec_ok.append(f"fresh wallet {fresh_pct:.0f}%")
for r in rug.get("risks") or []:
    if (r.get("level") or "").lower() in ("danger", "warn", "warning"):
        sec_bad.append(f"RugCheck: {r['name']}")

if sec_bad:
    red_strip("🛡️ <b>Keamanan:</b> ⚠️ " + " · ".join(sec_bad) +
              (("<span style='opacity:0.7'> | ✅ " + " · ".join(sec_ok) +
                "</span>") if sec_ok else ""))
else:
    green_strip("🛡️ <b>Keamanan:</b> ✅ " + " · ".join(sec_ok))

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
        # overlay harga (GeckoTerminal) di tanggal yang sama -> deteksi divergensi
        if not ohlcv.empty:
            oh = ohlcv[ohlcv["date"].isin(set(hist_df["date"]))]
            if len(oh) >= 2:
                figh.add_trace(go.Scatter(
                    x=oh["date"], y=oh["close"], mode="lines", name="Harga",
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
                           yaxis2=dict(overlaying="y", side="right",
                                       visible=False),
                           yaxis3=dict(overlaying="y", side="right",
                                       visible=False),
                           xaxis=dict(tickfont=dict(size=9)))
        st.plotly_chart(figh, use_container_width=True,
                        config={"displayModeBar": False})
        arrow = "📈" if latest_delta > 0 else ("📉" if latest_delta < 0 else "➖")
        color = "#22c55e" if latest_delta > 0 else ("#ef4444" if latest_delta < 0 else "#94a3b8")
        extra = ""
        # divergensi: holder naik tapi harga turun (atau sebaliknya)
        if not ohlcv.empty and len(ohlcv) >= 2:
            price_chg = ohlcv["close"].iloc[-1] - ohlcv["close"].iloc[-2]
            if latest_delta > 0 and price_chg < 0:
                extra = " · ⚠️ holder naik tapi harga turun (distribusi?)"
            elif latest_delta < 0 and price_chg > 0:
                extra = " · holder turun, harga naik (akumulasi whale?)"
        st.markdown(f"<span style='color:{color};font-size:0.85rem'>"
                    f"{arrow} <b>{latest_delta:+,}</b> ({pct_chg:+.2f}%) vs hari "
                    f"sebelumnya{extra}</span>", unsafe_allow_html=True)
    else:
        st.caption("Belum ada riwayat ≥2 hari. Snapshot hari ini tercatat — "
                   "delta muncul mulai besok.")

# ----------------------------------------------------------------------------
# BARIS 3.5 — Buy/Sell pressure + konsentrasi + info pasar (1 baris metrics)
# ----------------------------------------------------------------------------
tx24 = (market.get("txns") or {}).get("h24") or {}
tx1 = (market.get("txns") or {}).get("h1") or {}
buys, sells = int(tx24.get("buys") or 0), int(tx24.get("sells") or 0)
bs_ratio = buys / sells if sells else float("inf")
vol24 = float((market.get("volume") or {}).get("h24") or 0)

b1, b2, b3, b4, b5, b6 = st.columns(6)
b1.metric("🟢 Buy 24h", f"{buys:,}",
          f"1h: {int(tx1.get('buys') or 0):,}", delta_color="off")
b2.metric("🔴 Sell 24h", f"{sells:,}",
          f"1h: {int(tx1.get('sells') or 0):,}", delta_color="off")
b3.metric("Buy/Sell Ratio", f"{bs_ratio:.2f}" if sells else "∞",
          "tekanan beli" if bs_ratio >= 1 else "tekanan jual",
          delta_color="normal" if bs_ratio >= 1 else "inverse")
b4.metric("Vol 24h", f"${vol24:,.0f}")
b5.metric("Top-10 Holder", f"{conc['top10']:.1f}%",
          "supply" + (" ⚠️" if conc['top10'] > 30 else ""), delta_color="off")
b6.metric("Likuiditas", f"${market['liquidity_usd']:,.0f}",
          f"{liq_pct_mc:.1f}% MC" + (
              f" | LP lock {lp_locked_pct:.0f}%" if lp_locked_pct is not None
              else ""), delta_color="off")

# ----------------------------------------------------------------------------
# BARIS 4 — Cluster strip (hasil scan yang sudah dilakukan di atas)
# ----------------------------------------------------------------------------
if scan_clusters and rpc_endpoint:
    if bundles is None or bundles.empty:
        fresh_txt = (f" · Fresh wallet: {fresh_pct:.0f}%"
                     if fresh_pct is not None else "")
        green_strip(f"🕸️ <b>Cluster:</b> ✅ Tidak terdeteksi bundler di antara "
                    f"{n_scan} top holder.{fresh_txt}")
    else:
        worst = bundles.iloc[0]
        bundled_supply = bundles["pct_supply"].sum()
        fresh_txt = (f" · Fresh wallet: {fresh_pct:.0f}% dari top holder"
                     if fresh_pct is not None else "")
        if worst["pct_supply"] > cluster_warn_pct:
            red_strip(
                f"🕸️ 🚨 <b>BUNDLER TERDETEKSI</b> — cluster terbesar: "
                f"<b>{int(worst['wallets'])} wallet</b> (funder "
                f"<code>{worst['funder'][:6]}…</code>) pegang "
                f"<b>{worst['pct_supply']:.2f}%</b> supply (ambang "
                f"{cluster_warn_pct:g}%). Total {len(bundles)} cluster = "
                f"{bundled_supply:.2f}% supply. Bisa dump kapan saja!{fresh_txt}")
        else:
            green_strip(
                f"🕸️ <b>Cluster:</b> ✅ {len(bundles)} cluster kecil, terbesar "
                f"{worst['pct_supply']:.2f}% supply (ambang {cluster_warn_pct:g}%). "
                f"Total {bundled_supply:.2f}% — wajar.{fresh_txt}")
elif scan_clusters:
    st.caption("🕸️ Cluster scan: butuh Helius API key / custom RPC.")

# ----------------------------------------------------------------------------
# BARIS 5 — Quick links + Share ke X
# ----------------------------------------------------------------------------
verdict_emoji = "✅" if (n_dust == 0 or ratio > REAL_RATIO_OK) else "🚨"
cluster_txt_share = ""
if bundles is not None and not bundles.empty:
    w0 = bundles.iloc[0]
    cluster_txt_share = (f"🕸️ Cluster terbesar: {int(w0['wallets'])} wallet "
                         f"= {w0['pct_supply']:.1f}% supply\n")
elif bundles is not None:
    cluster_txt_share = "🕸️ Tidak ada bundler terdeteksi\n"

share_text = (
    f"${market['symbol']} — Holder Analysis {verdict_emoji}\n\n"
    f"🧬 Skor Kesehatan: {score}/100 ({s_label.split()[0]})\n"
    f"👥 Holder: {total_holders:,}"
    + (f" ({holder_delta:+,} vs kemarin)" if holder_delta is not None else "")
    + "\n"
    f"💎 Real (≥${dust_limit:g}): {n_real:,} ({real_mc_pct:.1f}% MC)\n"
    f"🪙 Dust (<${dust_limit:g}): {n_dust:,}\n"
    f"📊 Top-10: {conc['top10']:.1f}% supply · Liq: {liq_pct_mc:.1f}% MC\n"
    + cluster_txt_share +
    f"💰 MC: ${marketcap:,.0f}\n\n"
    f"{ca}"
)
import urllib.parse as _up
share_url = "https://twitter.com/intent/tweet?text=" + _up.quote(share_text)

lk = st.columns([1.2, 1, 1, 1, 1, 1, 2.8])
lk[0].markdown(
    f"""<a href="{share_url}" target="_blank" style="text-decoration:none;">
    <div style="background:#000;border:1px solid #333;border-radius:8px;
    padding:5px 10px;text-align:center;color:#fff;font-size:0.8rem;
    font-weight:700;">𝕏 Share</div></a>""", unsafe_allow_html=True)


def _link_btn(col, label, url):
    col.markdown(
        f"""<a href="{url}" target="_blank" style="text-decoration:none;">
        <div style="background:rgba(128,128,128,0.12);border:1px solid
        rgba(128,128,128,0.3);border-radius:8px;padding:5px 8px;
        text-align:center;font-size:0.75rem;">{label}</div></a>""",
        unsafe_allow_html=True)


_link_btn(lk[1], "GMGN", f"https://gmgn.ai/sol/token/{ca}")
_link_btn(lk[2], "DexScreener", market.get("url") or
          f"https://dexscreener.com/solana/{ca}")
_link_btn(lk[3], "Solscan", f"https://solscan.io/token/{ca}#analytics_holder")
_link_btn(lk[4], "RugCheck", f"https://rugcheck.xyz/tokens/{ca}")
_link_btn(lk[5], "Birdeye", f"https://birdeye.so/token/{ca}?chain=solana")

with st.expander("🧬 Rincian Skor Kesehatan"):
    sp = pd.DataFrame(
        [{"Komponen": n, "Poin": f"{p:.1f}", "Maks": m, "Nilai": ket}
         for n, p, m, ket in score_parts])
    st.dataframe(sp, use_container_width=True, hide_index=True)
    st.caption("Skor = penjumlahan komponen. ≥70 SEHAT · 45-69 WASPADA · "
               "<45 BAHAYA. Heuristik — bukan nasihat finansial, DYOR!")

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
    with st.expander("🎯 Holder Concentration & Dev Info"):
        cc = pd.DataFrame([
            {"Grup": "Top 1-5", "% Supply": f"{conc['top5']:.2f}%"},
            {"Grup": "Top 6-10", "% Supply": f"{conc['top6_10']:.2f}%"},
            {"Grup": "Top 11-25", "% Supply": f"{conc['top11_25']:.2f}%"},
            {"Grup": "Top 26-50", "% Supply": f"{conc['top26_50']:.2f}%"},
            {"Grup": "Top 51-100", "% Supply": f"{conc['top51_100']:.2f}%"},
            {"Grup": "TOTAL Top-100", "% Supply": f"{conc['top100']:.2f}%"},
        ])
        st.dataframe(cc, use_container_width=True, hide_index=True)
        if creator:
            st.markdown(
                f"**👨‍💻 Dev/Creator:** `{creator}`  \n"
                f"Sisa holding: **{creator_pct:.2f}%** supply · "
                f"Mint auth: {'⚠️ AKTIF' if mint_auth else '✅ dicabut'} · "
                f"Freeze auth: {'⚠️ AKTIF' if freeze_auth else '✅ dicabut'}")
        if rug.get("risks"):
            st.caption("RugCheck risks: " + "; ".join(
                f"{r['name']} ({r.get('level','?')})"
                for r in rug["risks"][:8]))
        if wallet_info is not None and not wallet_info.empty:
            known = wallet_info.dropna(subset=["first_tx_time"])
            if len(known) > 0:
                import datetime as _dt2
                fresh_tbl = known.copy()
                fresh_tbl["umur_hari"] = ((time.time() -
                                           fresh_tbl["first_tx_time"]) / 86400)
                n7 = int((fresh_tbl["umur_hari"] < 7).sum())
                n30 = int((fresh_tbl["umur_hari"] < 30).sum())
                st.caption(f"🐣 Fresh wallet (top {len(wallet_info)} holder): "
                           f"{n7} wallet < 7 hari, {n30} wallet < 30 hari. "
                           f"Wallet lama (>5rb tx) tidak terdata umurnya.")

# Footer ringkas
foot = (f"DexScreener (harga/MC) + Helius (holder) + Solscan (riwayat) | "
        f"Supply: {supply:,.0f} | Dec: {decimals}")
if exclude_lp and lp_wallets:
    foot += f" | {len(lp_wallets)} LP wallet dikecualikan (≈${lp_value_usd:,.0f})"
if holder_delta_src:
    foot += f" | Δ holder: {holder_delta_src}"
st.caption(foot)

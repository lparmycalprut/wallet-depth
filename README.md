# Wallet Depth — Holder Analytic (Dust)

Wallet Depth memantau token Solana dan berfokus pada **analisa holder
dust** sebagai jejak dump, plus **Scan Meteora DLMM**. Semua sinyal
(silent accumulation 12 jam, reversal, Telegram) sudah dihapus dari UI.

## Konsep

1. **Dust holder** — wallet murni dengan `0 < nilai ≤ $10`:
   - **dust % MC** = total nilai dust / marketcap × 100,
   - ≥ **1% MC** → BAHAYA (disembunyikan dari Scan Meteora).
   Dust yang nambah pesat = holder sebelumnya sudah distribusi / bag
   merosot jadi sisa.
2. **Kohort mid-tier (Crab+Fish, $100–$10k)** — daftar address di-freeze
   4 jam, lalu diukur **sisa token** (bukan dollar) supaya dump harga
   tidak ketiru sebagai exit.
3. **Grafik 4 jam** — setiap scan mencatat titik ke `holder_history.json`,
   ditampilkan per bucket 4 jam (watchlist sparkline + halaman Holder).
4. **Wallet Depth by Threshold** — Helius DAS `getTokenAccounts`, bucket
   `>$0-$10` … `>$500k` atas wallet murni (LP/pool DexScreener disingkirkan).
   Tier 🦐/🦀/🐟/🐬/🦈 selalu wallet murni.

## Sumber data

**Helius** = sumber utama holder (DAS `getTokenAccounts`). **GMGN** hanya
listing Trending/Degen + fallback. **Meteora** pool-discovery API untuk
Scan Meteora. Harga/MC dari DexScreener. Solscan dilepas.

| `holder_source` | Perilaku |
|---|---|
| `auto` (default) | Helius dulu → fallback GMGN. |
| `helius` | Paksa Helius → fallback GMGN. |
| `gmgn` | GMGN saja (listing Trending/Degen), fallback Helius. |

Scan Holder Khusus (halaman utama) dan cron butuh `HELIUS_API_KEY`
(config / env / Streamlit secrets). Tanpa key, fallback GMGN.

## Scan Meteora Pool

- 24 jam: `pool_type=dlmm && active_tvl≥1000 && fee_active_tvl_ratio≥250`
- 1 jam: `pool_type=dlmm && active_tvl≥1000 && fee_active_tvl_ratio≥1`
- Pool 24 jam yang masih muncul di 1 jam **tetap ditampilkan**
- Dust holder **≥ 1% MC** (BAHAYA) disembunyikan
- Shortcut: [Meteora DLMM](https://app.meteora.ag/dlmm/) + [HawkFi](https://www.hawkfi.ag/meteora/)

## Modul

| File | Peran |
|---|---|
| `holder_history.py` | Pencatatan dust/kohort, resample 4 jam, sparkline |
| `meteora_screener.py` | Listing DLMM 24h+1h, enrich holder, filter dust ≥1% |
| `holder_analysis.py` | Fetch holder Helius/GMGN, klasifikasi real/dust/mid |
| `solscan_holders.py` | Kalkulasi wallet_depth (bucket & tier) |
| `helius_holders.py` | Scan Holder Khusus satu token + bar chart |
| `holder_status.py` | Snapshot dashboard (ref `holder-live`) + history ringkas |
| `scripts/scan_holders.py` | Cron watchlist: holder only, catat history |
| `trending_ui.py` | Listing Trending/Degen (tanpa analisa holder) |
| `pages/4_📊_CVD.py` | Chart CVD harian |
| `pages/5_🧮_Holder.py` | Holder Analytic: dust, grafik 4 jam, kohort |

## Menjalankan

```bash
pip install -r requirements.txt
streamlit run app.py
```

Cron GitHub Actions ~15 menit (`.github/workflows/daily-effort.yml`)
menjalankan `scripts/scan_holders.py`. Snapshot dibaca dari
`holder_status.json` (ref `holder-live`). Lihat `DEPLOY.md` untuk env
yang wajib (`HELIUS_API_KEY`, `GITHUB_TOKEN`).

## Pengujian

```bash
python -m unittest discover tests
python -m py_compile holder_history.py meteora_screener.py \
  holder_analysis.py holder_status.py scripts/scan_holders.py
```

Analisis bersifat heuristik dan bukan saran keuangan.

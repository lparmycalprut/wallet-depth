# Wallet Depth — Holder Analytic (Dust)

Wallet Depth memantau token Solana dan berfokus pada **analisa holder
dust** sebagai jejak dump, plus **Scan Meteora DLMM**. Cron holder dapat
mengirim alert Telegram khusus perubahan dust; sinyal lama seperti silent
accumulation 12 jam dan reversal tetap tidak digunakan.

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
5. **Kronologi Holder (scan FULL)** — snapshot awal disimpan sekali dan
   tidak ditimpa. Scan FULL berikutnya membandingkan **balance token**
   (bukan hanya nilai USD) untuk melihat wallet dust yang membesar, turun
   kategori, baru teramati, atau saldo menjadi nol. Kenaikan harga tanpa
   kenaikan balance tidak dianggap pembelian. Perubahan saldo tidak dapat
   membedakan swap dengan transfer — tautan Solscan disediakan untuk
   verifikasi. Payload wallet dibatasi (sampel deterministik); hasil
   sampled/truncated tidak disebut daftar lengkap. Kronologi baru muncul
   setelah scan FULL kedua.
6. **Alert Telegram holder dust** — membandingkan `dust_pct_mc` terbaru
   dengan anchor sekitar 4 jam sebelumnya menggunakan perubahan **poin
   persentase**:
   - naik minimal `+0.25` poin → indikasi dump;
   - turun minimal `-0.50` poin **dan** ada wallet lama yang saldo tokennya
     meningkat → kemungkinan akumulasi;
   - berubah minimal `±1.00` poin dari snapshot awal → alert pemeriksaan
     pergerakan wallet dust (membesar/keluar dust, jual habis/hilang,
     mengecil/masuk dust, atau wallet dust baru).

   Snapshot saldo dibatasi maksimum 300 wallet per anchor dan event yang
   sukses dikirim dideduplikasi per bucket 4 jam.

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
| `holder_history.py` | Pencatatan dust/kohort, resample 4 jam, baseline FULL, kronologi |
| `holder_chronology.py` | Snapshot wallet bounded, klasifikasi pergerakan, narasi kronologi |
| `meteora_screener.py` | Listing DLMM 24h+1h, enrich holder, filter dust ≥1% |
| `holder_analysis.py` | Fetch holder Helius/GMGN, klasifikasi real/dust/mid |
| `solscan_holders.py` | Kalkulasi wallet_depth (bucket & tier) |
| `helius_holders.py` | Scan Holder Khusus satu token + bar chart |
| `holder_status.py` | Snapshot dashboard (ref `holder-live`) + history ringkas |
| `scripts/scan_holders.py` | Cron watchlist: holder, alert, catat history |
| `telegram_alerts.py` | Rule dust 4 jam/baseline, dedup, Telegram Bot API |
| `trending_ui.py` | Listing Trending/Degen + Add All Watchlist |
| `pages/4_📊_CVD.py` | Chart CVD harian |
| `pages/5_🧮_Holder.py` | Holder Analytic: dust, grafik 4 jam, kohort, kronologi FULL |

## Menjalankan

```bash
pip install -r requirements.txt
streamlit run app.py
```

Cron GitHub Actions ~15 menit (`.github/workflows/daily-effort.yml`)
menjalankan `scripts/scan_holders.py`. Snapshot dibaca dari
`holder_status.json` (ref `holder-live`). Lihat `DEPLOY.md` untuk env
scanner (`HELIUS_API_KEY`, `GITHUB_TOKEN`) dan setup alert opsional
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). Tanpa credential Telegram,
scan tetap berjalan dan pengiriman alert dilewati dengan aman.

## Pengujian

```bash
python -m unittest discover tests
python -m py_compile holder_history.py holder_chronology.py meteora_screener.py \
  holder_analysis.py holder_status.py telegram_alerts.py \
  scripts/scan_holders.py trending_ui.py watchlist.py
```

Analisis bersifat heuristik dan bukan saran keuangan.

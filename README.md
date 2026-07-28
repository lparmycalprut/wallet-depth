# 📊 Wallet Depth by Threshold — Solana Holder Analyzer

Meniru fitur **Wallet Depth by Threshold** di Solscan Analytics, plus analisa
**Dust Holder vs Real Holder** untuk token Solana apa pun.

## Kenapa butuh API key Helius?

Data yang **100% gratis tanpa key**:
- ✅ Harga, marketcap, likuiditas → **DexScreener API** (dipakai otomatis)
- ✅ Supply & decimals → RPC publik Solana

Data yang butuh key (tetap **gratis**):
- Daftar **SEMUA holder** sebuah token. RPC publik Solana memblokir
  `getProgramAccounts` untuk token program (terlalu berat), dan API internal
  Solscan/GMGN dilindungi Cloudflare. Solusi gratis yang paling stabil:
  **Helius free tier** — daftar di [helius.dev](https://www.helius.dev)
  (tanpa kartu kredit), free tier dapat jutaan credit/bulan, lebih dari cukup.

Alternatif: isi **Custom RPC URL** (QuickNode/Alchemy/dll free tier milikmu)
yang mengizinkan `getProgramAccounts`.

## ⚙️ Konfigurasi — `config.json`

API key dan setelan awal disimpan di **`config.json`** (satu folder dengan
`app.py`). Tinggal copy-paste key kamu di situ:

```json
{
  "helius_api_key": "API-KEY-KAMU-DISINI",
  "custom_rpc": "",
  "dust_limit_usd": 10,
  "cluster_warn_pct": 5,
  "cluster_scan_top_n": 50,
  "exclude_lp": true
}
```

- Dashboard & CLI **otomatis membaca** file ini saat start.
- Kamu juga bisa mengubah setelan dari sidebar lalu klik
  **💾 Simpan ke config.json** agar permanen.
- Jika file terhapus, template kosong dibuat ulang otomatis saat app dijalankan.

## ⏰ Daily snapshot cron (GitHub Actions)

Watchlisted CAs are snapshotted **automatically every day at 00:00 WIB**
by `.github/workflows/daily-snapshot.yml` — history keeps building even if
you never open the dashboard.

**One-time setup:** add your Helius key as a repo secret:
GitHub → repo **Settings → Secrets and variables → Actions →
New repository secret** → Name: `HELIUS_API_KEY`, Value: your key.

- Manual run: GitHub → **Actions → Daily watchlist snapshot → Run workflow**.
- The job commits `history.json` + `watchlist.json` back to the repo.
- Manage the list on the **⭐ Watchlist** page (add note / remove when done),
  or with the **⭐ Add to watchlist** button under Analyze.

## Instalasi

```bash
pip install -r requirements.txt
```

## Menjalankan dashboard

```bash
streamlit run app.py
```

1. Masukkan **Helius API key** di sidebar (sekali saja per sesi).
2. Masukkan **CA** token → klik **Analisa**. (Input pertama sengaja kosong.)

## Menjalankan versi CLI

```bash
python cli.py <CA>              # key otomatis dari config.json
python cli.py <CA> --helius-key <API_KEY>   # atau override manual
```

## File

- `app.py` — dashboard Streamlit
- `cli.py` — versi terminal
- `config.json` — API key & setelan awal (edit di sini)
- `requirements.txt` — dependensi

## Fitur

- **🔥 Scan Trending Now** — satu tombol di halaman utama. Hasilnya tampil
  **lengkap langsung di situ** (tabel yang sama persis dengan halaman
  **🔎 Screener**): Fit + grade, MC, likuiditas, T10, smart money, holder,
  perubahan 24 jam, umur token, catatan, dan banner merah untuk token
  berisiko. Tiap baris punya tombol **Analyze →** (langsung analisa CA itu)
  dan **⭐ watch**.
- **Scoring screener ketat** — skor Fit 0-100 dari 8 pilar (base harga 22 ·
  konsentrasi T10 20 · likuiditas 15 · smart money 14 · rug score 12 ·
  kewajaran volume 9 · jumlah holder 4 · umur 4), **dikurangi penalti**
  untuk tekanan insider/bundler, rug risk, dan likuiditas tipis.
  Satu pilar rusak saja (sudah pump >25%, T10 >25%, likuiditas <5% MC,
  smart money <10, holder <1000, umur <2 hari) langsung membatasi skor
  di **54**, dan red flag keras membatasi di **40** — jadi
  **🟢 PRIME (≥75) memang jarang** dan berarti semua pilar bersih.
  🟡 OK 55-74 · ⚪ WEAK 35-54 · POOR <35.
- **Sidebar bisa disembunyikan** — default tertutup; klik tanda **»** di kiri
  atas untuk buka, **×** untuk tutup. Semua pengaturan ada di sana.
- **Dust vs Real holder** + verdict OK / peringatan merah.
- **Wallet Depth by Threshold** dengan tier ala Solscan.
- **🕸️ Bundler / Cluster detection** — melacak *wallet pendana pertama* dari
  tiap top holder (default 50 teratas, bisa 20–100). Wallet-wallet yang didanai
  oleh pendana yang sama = 1 cluster/bundle:
  - Jika 1 cluster memegang **> 5% total supply** (ambang bisa diubah) →
    **warning merah**.
  - Pendanaan dari CEX terkenal (Binance, Bybit, OKX, dll.) ditandai dan
    **tidak** dihitung sebagai bundle.
  - Wallet lama (> 5.000 transaksi) dilewati — bukan tipikal wallet bundle.
  - Catatan: ini heuristik; bundler canggih dengan multi-hop funding bisa lolos.

## Logika analisa

| Hal | Aturan |
|---|---|
| **Dust holder** | nilai holding **< $10** (bisa diubah di sidebar) |
| **Real holder** | nilai holding **≥ $10** |
| **✅ HOLDER OK** | jumlah real holder **> 30%** dari jumlah dust holder |
| **🚨 Peringatan merah** | jika rasio ≤ 30% → holder count kemungkinan besar semu (airdrop/bundle) |
| **% marketcap** | total nilai USD yang dipegang tiap kelompok ÷ marketcap |
| **Tier** | sama seperti Solscan: `>$10`, `>$100`, `>$1K`, `>$10K`, `>$100K`, `>$1M` (kumulatif) |

Wallet **liquidity pool** (dari DexScreener) otomatis dikecualikan agar tidak
mendistorsi angka (bisa dimatikan di sidebar).


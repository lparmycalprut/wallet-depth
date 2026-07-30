# Wallet Depth — Analisis Holder, Order Flow, dan Risiko Token Solana

Wallet Depth adalah dashboard Streamlit dan rangkaian cron untuk memeriksa
kesehatan token Solana sebelum trade atau menyediakan likuiditas. Program ini
menggabungkan struktur holder, keamanan token, perilaku wallet, swap on-chain,
CVD, level harga D1/H4, watchlist, screener GMGN, dan notifikasi Telegram.

Program ini membantu menjawab pertanyaan seperti:

- Apakah jumlah holder terlihat organik atau didominasi dust wallet?
- Seberapa terkonsentrasi supply di holder dan cluster yang saling terhubung?
- Apakah whale sedang akumulasi, distribusi ke retail, atau hanya churn?
- Apakah token sudah terlalu jauh naik dari low 30 hari untuk entry/LP baru?
- Apakah breakout benar-benar terkonfirmasi pada close H4?
- Apa yang berubah pada token di watchlist sejak snapshot sebelumnya?

> **Peringatan:** seluruh skor, fase, sinyal, dan prompt AI di repo ini adalah
> heuristik. Tidak ada fitur yang menjamin arah harga atau menggantikan
> verifikasi transaksi dan manajemen risiko.

## Alur kerja program

```text
CA token
  ├─ DexScreener / GeckoTerminal / RugCheck
  │    └─ harga, market cap, likuiditas, OHLC, keamanan
  ├─ Helius / RPC Solana
  │    └─ seluruh holder, supply, swap, umur dan funder wallet
  ├─ Analisis dashboard
  │    ├─ dust vs real holder + wallet depth
  │    ├─ health score + konsentrasi + cluster
  │    ├─ CVD + whale/retail + pure wallet
  │    └─ laporan, share card, dan Prompt to AI
  └─ Watchlist + GitHub Actions
       ├─ snapshot holder/history
       ├─ update CVD dan conviction tiap jam
       ├─ Signal Monitor
       └─ Breakout Guard + Telegram
```

## Fitur utama

### 1. Analisis holder dan keamanan

Halaman utama mengambil seluruh holder token, menggabungkan akun berdasarkan
owner, menghapus wallet LP bila opsi aktif, lalu menghitung:

- **Dust vs real holder** — ambang default `$10`, dapat diubah di sidebar.
- **Wallet Depth by Threshold** — jumlah dan nilai wallet pada tier `>$10`,
  `>$100`, `>$1K`, `>$10K`, `>$100K`, dan `>$1M`.
- **Konsentrasi supply** — Top 5, Top 10, Top 25, Top 50, dan Top 100.
- **Health score 0–100** — menggabungkan kualitas holder, konsentrasi,
  likuiditas/MC, LP lock, authority, pertumbuhan holder, cluster, dan umur
  wallet. Skor ini adalah ringkasan heuristik, bukan probabilitas sukses.
- **Security check** — mint/freeze authority, status rugged, risiko RugCheck,
  dan LP lock/liquidity.
- **Buy/sell dan divergence check** — membandingkan holder, harga, volume,
  konsentrasi, dan flow untuk mencari perubahan yang tidak sejalan.

Interpretasi rasio holder pada dashboard:

| Rasio real terhadap dust | Pembacaan |
|---|---|
| `≥50%` | sehat |
| `30–<50%` | borderline |
| `<30%` | holder count berisiko semu/noisy |

### 2. Cluster, funder, dan umur wallet

Top holder dapat dipindai berdasarkan transaksi/funder pertamanya:

- wallet dengan funder sama dikelompokkan sebagai cluster;
- cluster yang melewati ambang supply menyalakan warning;
- funder CEX yang dikenal ditandai dan tidak otomatis dianggap bundle;
- wallet baru diberi umur 🐣, 🌱, atau 🌳;
- mode **Fast / Balanced / Deep** mengatur jumlah wallet dan kedalaman scan
  agar pemakaian API dapat dikontrol.

Deteksi ini tidak dapat menjamin bundler multi-hop atau wallet yang sengaja
memutus jejak pendanaan akan ditemukan.

### 3. CVD dan atribusi order flow

CVD dibangun dari swap pool on-chain, bukan dari tebakan aggressor seperti
pada order book CEX. Transfer token keluar pool dibaca sebagai buy; transfer
masuk pool dibaca sebagai sell. Quote SOL, USDC, dan USDT dinormalisasi ke
SOL-equivalent.

Definisi penting:

- **Whale** = satu swap `≥3 SOL`.
- **Retail** = swap di bawah ambang whale.
- **Pure accumulator/distributor** = wallet satu arah dengan toleransi lawan
  arah maksimal `5%` pada window yang dihitung.
- **Conviction** = persentase buy ukuran-whale yang masih ditahan oleh pure
  accumulator; bukan peluang harga akan naik.

Halaman **📊 CVD Deep Analysis** menyediakan:

- satu dropdown window `4/6/8/12/24/36/48 jam`;
- nested window yang selalu berada di dalam data yang benar-benar dipilih;
- net CVD total, whale, retail, pure buy/sell, dan conviction;
- chart CVD per jam dan divergence harga/CVD;
- daftar pure accumulator/distributor beserta umur dan same-funder flag;
- ekspor Markdown/CSV;
- tombol **Prompt to AI**.

### 4. Prompt to AI

Tombol **Prompt to AI** membuat teks siap salin untuk layanan chat seperti
DeepSeek. Data tidak dikirim otomatis. Prompt berisi:

1. glosarium dan ambang angka sebelum metrik;
2. status kejujuran cakupan data;
3. ringkasan multi-window;
4. alur waktu dari periode lama ke terbaru;
5. tabel pure wallet dengan umur 🐣/🌱/🌳;
6. tugas untuk membandingkan take profit, distribusi ke retail, rotasi
   antar-whale, akumulasi, shakeout, dan churn;
7. verdict panik/tidak dan syarat yang membatalkan pembacaan.

Jika data lebih pendek daripada window yang diminta, prompt menandai periode
**tidak tercakup/sebagian** dan melarang AI menyimpulkan tren. Prompt juga
melarang AI mengarang angka atau memberi target harga.

### 5. Watchlist, LP Radar, dan markup safety

Watchlist menampilkan harga live dan menjadi sumber token untuk cron.

- **LP Radar** hanya menggambar card saat conviction naik dibanding cron
  sebelumnya. Dua kenaikan berturut-turut menghasilkan green glow.
- Badge **HIGH** dan **EXTREME** menunjukkan conviction tinggi; badge itu
  bukan indikator kenaikan harga.
- Shortcut card membuka DexScreener, GMGN, atau halaman CVD.
- **Markup safety** berjalan terpisah dari filter conviction. Semua token
  watchlist diperiksa dari 30 candle harian:
  - `+150%` dari low 30D = warning;
  - `+300%` dari low 30D = danger dan banner merah.

Pemisahan ini penting: token yang sudah naik +300% tetap diperingatkan walau
conviction datar sehingga tidak mempunyai card LP Radar.

### 6. GMGN trending screener

Screener mengambil daftar trending GMGN lalu memberi **Fit score 0–100**
berdasarkan delapan pilar: price action, konsentrasi Top 10, likuiditas,
smart money, rug score, volume/MC, jumlah holder, dan umur token.

Penalti mencakup insider, bundler, entrapment, bot-degen, sniper, rug risk,
konsentrasi, dan likuiditas tipis. Kurva skor menggunakan interpolasi linear,
bukan tangga `if/elif`, agar perubahan kecil pada input tidak menyebabkan
lompatan puluhan poin.

Grade: `PRIME ≥75`, `OK 55–74`, `WEAK 35–54`, dan `POOR <35`. Hard risk
mendapat `AVOID` dan dibatasi maksimal 40.

Endpoint GMGN bersifat tidak resmi dan dapat berubah atau diblokir
Cloudflare. Hasil kosong tidak selalu berarti tidak ada token.

### 7. Signal Monitor dan Breakout Guard

Cron menghasilkan dua jenis pesan yang sengaja dipisahkan:

| Sistem | Dasar | Dedupe |
|---|---|---|
| 📊 **CVD MONITOR** | flow 6 jam + divergence H1 | 4 jam per token/tipe |
| 🛡️ **BREAKOUT GUARD** | level D1 + close H4 | 12 jam per level |

Breakout Guard hanya menilai candle H4 yang sudah close. Level berasal dari
pivot harian, digabung bila berjarak kurang dari 1,5%, maksimal enam level per
sisi. Event yang dicatat:

- `breakout`;
- `failed_breakout`;
- `breakdown`;
- `spring`;
- `reclaim` maksimal lima candle H4 setelah breakdown.

Pesan menyebut whale vs retail, jumlah wallet, pure flow, aktor dominan, dan
langkah kehati-hatian. Event disimpan di `breakouts.json` dengan hubungan
parent/outcome. Alert Telegram yang gagal disimpan dan dicoba lagi pada cron
berikutnya.

## Halaman dashboard

| Halaman | Fungsi |
|---|---|
| `app.py` | holder/security, cluster, CVD, LP Radar, dan screener inline |
| ⚖️ Compare | membandingkan 2–3 token tanpa cluster scan |
| 📒 History | jurnal hasil analisis dan snapshot per tanggal |
| ⭐ Watchlist | menambah, memberi catatan, dan menghapus token |
| 📊 CVD | analisis flow mendalam, ekspor, dan Prompt to AI |
| 🔔 Signals | filter dan timeline signal CVD/guard |
| 🔎 Screener | GMGN trending dengan Fit score |

## Sumber data

| Sumber | Digunakan untuk |
|---|---|
| DexScreener | harga, market cap, likuiditas, pair, transaksi, volume |
| Helius Enhanced API/RPC | seluruh holder, supply, transaksi, dan swap |
| GeckoTerminal | candle harga harian/H1/H4 |
| RugCheck | authority, LP lock, rugged, dan security risks |
| GMGN | trending/risk fields dan fallback trade terkini |
| Solscan | riwayat holder dan link verifikasi wallet |
| GitHub | penyimpanan durable watchlist/history dan GitHub Actions |

Helius API key diperlukan untuk fitur holder dan CVD penuh. Isi
`helius_extra_keys` dengan key tambahan yang dipisahkan koma; holder, supply,
mint info, cluster/bundler, Compare, dan CVD memakai pool yang sama dan
otomatis beralih ke key berikutnya ketika Helius mengembalikan HTTP 429/5xx.
Pool juga menggabungkan `HELIUS_API_KEY`, `HELIUS_API_KEYS`, config, dan
Streamlit Secrets tanpa duplikat. Custom RPC yang mengizinkan
`getProgramAccounts` dapat dipakai
untuk holder, tetapi tidak menggantikan seluruh endpoint Enhanced API CVD.

## Instalasi lokal

Disarankan memakai virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.json config.json
```

Isi `config.json` dengan key milik sendiri. File ini sudah diabaikan Git:

```json
{
  "helius_api_key": "PASTE-KEY-DI-SINI",
  "custom_rpc": "",
  "dust_limit_usd": 10,
  "cluster_warn_pct": 5,
  "cluster_scan_top_n": 50,
  "exclude_lp": true,
  "helius_extra_keys": "",
  "telegram_bot_token": "",
  "telegram_chat_id": ""
}
```

Jalankan dashboard:

```bash
streamlit run app.py
```

Versi CLI hanya menjalankan analisis dasar dust/real dan wallet depth:

```bash
python cli.py <CONTRACT_ADDRESS>
python cli.py <CONTRACT_ADDRESS> --helius-key <KEY> --dust 10
```

## Deploy dan otomatisasi

Panduan Streamlit Cloud ada di [`DEPLOY.md`](DEPLOY.md). Jangan pernah
menaruh API key di README, source code, atau file yang di-commit. Gunakan
Streamlit Secrets dan GitHub Actions Secrets.

Workflow yang tersedia:

- `.github/workflows/cvd-update.yml` — tiap jam pada menit `:20`; memperbarui
  `cvd.json`, `conviction.json`, `signals.json`, `levels.json`, dan
  `breakouts.json`.
- `.github/workflows/daily-snapshot.yml` — runner setiap enam jam; menyimpan
  snapshot watchlist ke `history.json` dengan satu entri per token/tanggal
  (run berikutnya pada tanggal yang sama memperbarui entri itu).

Secrets GitHub Actions yang dipakai:

- `HELIUS_API_KEY` atau `HELIUS_API_KEYS`;
- `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID` bila notifikasi diaktifkan.

Agar perubahan watchlist dari Streamlit Cloud langsung persisten ke repo,
`github_token` dapat ditambahkan ke Streamlit Secrets. Tanpa token, perubahan
lokal cloud dapat hilang saat redeploy; pending journal hanya membantu selama
filesystem instance masih hidup.

## File data dan modul penting

File data berikut sengaja di-commit agar state cron bertahan antar-run:

- `watchlist.json`;
- `history.json`;
- `cvd.json`;
- `conviction.json`;
- `signals.json`;
- `levels.json`;
- `breakouts.json`.

Modul utama:

- `core.py` — fetcher dan health score;
- `cvd.py` — swap store, CVD, wallet profile, phase, divergence, level, dan
  markup safety;
- `ai_prompt.py` — prompt CVD network-free;
- `gmgn_screener.py` — fetch dan scoring trending;
- `signals.py` — deteksi/log CVD Monitor;
- `breakout_guard.py` dan `breakout_log.py` — level event dan retry Telegram;
- `watchlist.py` — watchlist lokal/GitHub dan pending journal;
- `scripts/update_cvd.py` — cron order flow;
- `scripts/daily_snapshot.py` — cron snapshot holder.

## Menjalankan tes

Suite tidak membutuhkan pytest dan tidak melakukan request jaringan:

```bash
python tests/test_breakout_guard.py
python tests/test_scoring_continuity.py
python tests/test_markup_ai_prompt.py
```

Tes memindahkan seluruh path file state ke temporary directory agar
`cvd.json`, `signals.json`, dan data produksi lain tidak tersentuh.

## Batasan yang harus dipahami

- Data API dapat terlambat, kosong, berubah format, atau terkena rate limit.
- CVD menunjukkan flow swap pada pool yang dipilih, bukan seluruh niat pasar.
- Label whale berdasarkan ukuran swap, bukan kekayaan/identitas wallet.
- Conviction tinggi dapat muncul saat harga sudah terlalu jauh naik; karena
  itu markup safety dinilai terpisah.
- Cluster/funder dan market phase adalah heuristik, bukan bukti identitas.
- Periode tanpa cakupan data tidak sama dengan periode tanpa transaksi.
- Selalu cek CA, pool, chart, transaksi wallet, likuiditas, dan keamanan secara
  manual sebelum mengambil keputusan uang sungguhan.

Untuk aturan pengembangan dan riwayat keputusan, baca [`AGENTS.md`](AGENTS.md)
dan [`docs/PROGRESS.md`](docs/PROGRESS.md).

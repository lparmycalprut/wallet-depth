# Page 🌊 Sweep — kelayakan sweep, alert, dan tabel statistik

Halaman terpisah dari **🏆 Scan Best Pool Meteora** (permintaan user 2026-10-12).
`app.py` tidak disentuh; entri halamannya `pages/8_🌊_Sweep.py`.

## Alur

| Berkas | Isi |
| --- | --- |
| `sweep_screen.py` | mesin skrining murni (tanpa jaringan): 6 kriteria, deteksi sweep, rumus biaya, ringkasan statistik |
| `sweep_data.py` | DexScreener + RugCheck + GMGN `token_stat` + GeckoTerminal OHLCV, cache 90/120 detik |
| `sweep_store.py` | watchlist manual, state (snapshot per jam, sinyal, hasil 72 jam), gate alert, push GitHub |
| `sweep_alert.py` | Telegram berlapis `st.secrets` → env → `config.json` |
| `sweep_scan.py` | satu putaran scan: ambil → snapshot → skrining → alert → prune |
| `sweep_ui.py` | badan halaman Streamlit |
| `scripts/scan_sweep.py` | runner cron, mencetak `SWEEP_STATE_CHANGED=0\|1` |

## Enam kriteria

1. **liq/MC** di bawah ambang (lihat bagian Ambang di bawah).
2. **LP terkunci** ≥ 85% + authority mint/freeze sudah dilepas. Ambangnya 85%
   (bukan 90%) karena token acuan COCKROACH sendiri hanya 89,8%.
3. **Float tersebar**: top-10 < 25% **dan** tiap holder < 3%, akun pool AMM
   dikecualikan. Kontrak: `top10_holder_pct` **selalu persen** — GMGN mengirim
   `top_10_holder_rate` sebagai fraksi 0-1 dan `sweep_data` yang mengonversi.
4. **Akumulasi (proxy)**: net tekanan beli > 0 dengan harga sideways (< 25%),
   dari snapshot. Ini **proxy**, bukan CVD level wallet — CVD sebenarnya butuh
   Helius dan tidak diklaim di sini.
5. **Ekspansi volume**: volume naik ≥ 3× dari titik tersepi, sementara harga
   belum lari (< 3× dari titik tersepi).
6. **Shakeout + higher low**: satu bar turun ≥ 30%, lalu low berikutnya lebih
   tinggi. Perlu ≥ 3 bar; bar terakhir tidak pernah dinilai sebagai shakeout
   karena butuh bar setelahnya sebagai bukti.

Kriteria yang belum bisa dinilai berstatus **▫️ belum ada data** dan tidak
dihukum (tidak dihitung gagal).

## Vonis

`LAYAK SWEEP` = trio struktural (1+2+3) lulus **dan** minimal
`min(4, jumlah kriteria yang ada datanya)` lulus. Ambangnya menyesuaikan karena
di deploy baru hanya trio struktural yang punya data — menuntut 4 dari 3 akan
membuat halaman tidak pernah memberi alert. Begitu riwayat terkumpul, syaratnya
otomatis naik menjadi "struktural + minimal satu bukti".

## Ambang liq/MC (bisa diatur, default 15%)

15% **bukan batas alam**. Yang menentukan biaya sweep adalah

```
biaya/MC = (akar(m) − 1) × (liq/MC)      m = target kelipatan harga
leverage = (akar(m) + 1) / (liq/MC)      paper MC per $1 net masuk
```

| liq/MC | naik 2× | naik 3× | naik 5× | naik 10× | leverage @3× |
| --- | --- | --- | --- | --- | --- |
| 5% | 2,1% MC | 3,7% MC | 6,2% MC | 10,8% MC | 54,6× |
| 10% | 4,1% | 7,3% | 12,4% | 21,6% | 27,3× |
| **15%** | 6,2% | 11,0% | 18,5% | 32,4% | 18,2× |
| 20% | 8,3% | 14,6% | 24,7% | 43,2% | 13,7× |
| 25% | 10,4% | 18,3% | 30,9% | 54,1% | 10,9× |
| 30% | 12,4% | 22,0% | 37,1% | 64,9% | 9,1× |
| 40% | 16,6% | 29,3% | 49,4% | 86,5% | 6,8× |
| 50% | 20,7% | 36,6% | 61,8% | **108,1%** | 5,5× |

Batas **fisik**: naik 10× melewati 100% MC di liq/MC **46,2%**, naik 5× di
**80,9%**. Di atas 50% biaya sweep sudah melebihi kapitalisasi pasarnya sendiri.
Karena itu slider dibatasi 5%–60%:

- di bawah **5%** likuiditas terlalu tipis untuk masuk/keluar posisi;
- di atas **60%** kriterianya kehilangan arti (naik 2× pun perlu 21% MC).

Nilai disimpan di `sweep_state.json` (`settings.liq_mc_max`) supaya halaman,
cron, dan riwayat alert memakai ambang yang sama. Menggeser slider **tidak**
memanggil jaringan lagi: baris yang sudah ada dinilai ulang dari data di memori
(`sweep_scan.rescore_rows`).

## Alert

Hanya saat **transisi status**, bukan tiap scan:

- kelayakan muncul (cooldown 6 jam);
- sweep mulai terjadi (cooldown 30 menit).

Isi alert memuat angka yang membuatnya bisa ditinjau: liq/MC + biaya sweep,
tabel biaya beberapa target, untuk alert sweep juga `vol_x`, `price_mult`,
biaya dorong, dan churn.

### Angka teoretis vs terukur — jangan dicampur

| Nama | Arti | COCKROACH 1 Okt |
| --- | --- | --- |
| `est_cost_usd` | biaya dorong **minimum** `(akar(m)−1) × liq` | $24.067 |
| `net_inflow_usd` | **terukur**: Δ likuiditas antar snapshot | $58.778 |
| `churn_x` | volume ÷ biaya teoretis | 51,6× |
| `churn_net_x` | volume ÷ inflow terukur | 21,1× |

Kalau snapshot pembanding belum ada, inflow nyata `None` dan yang dipakai adalah
**acuan berlabel** (`REF_NET_COST_MULT = 2,44` dari satu event terukur) — UI dan
alert selalu menyebutnya "acuan 1 event", tidak pernah sebagai pengukuran.

## Statistik

Tiap alert meninggalkan baris sinyal: harga entry, `base_price`,
`max_up_pct` / `max_down_pct` (dilacak 72 jam), `from_base_up_pct`, churn,
biaya dorong, dan status. Ringkasannya: jumlah sinyal, hit ≥100% / ≥300%,
median naik/turun, dan break-even hit rate 13,0% (menang +200% / kalah −30%).

## Runtime

Keduanya aktif:

- **cron GitHub Actions** `.github/workflows/sweep-scan.yml`, `*/5 * * * *`,
  memakai secrets `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`. Commit hanya saat
  `store.fingerprint()` berubah (snapshot jam baru / sinyal baru / pengaturan
  baru) — tanpa gate itu cron 5 menitan membuat ~288 commit/hari.
  Jadwal GitHub Actions hanya berjalan dari **default branch**.
- **auto-refresh halaman** 5 menit selama tab terbuka (`st.fragment(run_every)`).

## Penyimpanan

| Berkas | Status |
| --- | --- |
| `sweep_watchlist.json` | di-commit |
| `sweep_state.json` | di-commit (snapshot, sinyal, pengaturan) |
| `sweep_cache.json` | `.gitignore` (TTL 90-120 detik) |

Kalau commit GitHub gagal, UI memberi tahu bahwa daftar baru tersimpan lokal dan
menulis cadangan ke `config.json` (`sweep_watchlist`) — filesystem Streamlit
Cloud ephemeral, jadi daftar yang tidak di-commit akan hilang saat restart.

## Test

```bash
python -m unittest tests.test_sweep_screen tests.test_sweep_store \
                   tests.test_sweep_alert tests.test_sweep_scan
```

Semuanya offline. `tests/test_sweep_scan.py` memakai data COCKROACH asli
(1 Okt 2026) sebagai fixture.

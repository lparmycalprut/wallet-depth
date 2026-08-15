# PROMPT — OVERHAUL TOTAL LOGIKA DETEKSI → "EFISIENSI ANOMALI (EFFORT vs RESULT)"

> Repo target: `lparmycalprut/wallet-depth` (branch `main`).
> Sifat pekerjaan: **PEROMBAKAN TOTAL**. Ini bukan tambahan — ini PENGGANTIAN seluruh
> logika deteksi yang ada. Jangan menumpuk di atas logika lama.

---

## 0. INTI PERUBAHAN (baca dulu, jangan dilewati)

Ganti **seluruh** framework deteksi pre-pump yang ada sekarang ("setup emas",
4-pilar golden rules, 7-checks `prepump_baru`, absorption detection, Fit score,
conviction, smart-buyer, holder-lock, whale-net, dll) menjadi SATU framework baru:

> **EFISIENSI ANOMALI = perbandingan antara EFFORT (SOL yang dikeluarkan, diukur
> dari ΔCVD) dan RESULT (pergerakan harga dalam %) per candle harian.**

Anomali terjadi ketika harga butuh **SOL yang jauh lebih banyak / jauh lebih
sedikit** dari biasanya (hari sebelumnya) untuk bergerak 1%.

Konteks validasi (sudah dibuktikan pada token nyata, HOPPY / pump.fun):
- Hari dump: harga -73% hanya butuh CVD -34.7 SOL → **0.475 SOL per 1%**.
- Hari sebelum pump: harga -52% butuh CVD -50.5 SOL → **0.964 SOL per 1%**.
- Kesimpulan: di hari sebelum pump, penjual "bekerja 2× lebih keras" tapi harga
  tidak mau jatuh → ada pembeli yang menyerap (absorption) → sinyal beli.

---

## 1. HAPUS SEMUA DETEKSI LAMA (WAJIB, TUNTAS)

Lakukan `grep -rn` lalu HAPUS (jangan sekadar disable) seluruh referensi,
fungsi, variabel, konstanta, dan file yang terkait:

### 1a. Nama-nama sinyal/framework lama yang harus hilang total
- `prepump_baru`, `prepump_baru_detector`, `prepump_baru_muncul`, skor `0-7`
- `prepump_detector` (multi-TF), `prepump_imminent`, `prepump_forming`,
  `prepump_cleared`, `prepump_neutral`
- "4 pilar", `4-pillar`, `four_pillar`, `GOLDEN RULES`, `setup emas`, `pilar`
- `CVD/Vol absorption` (|CVD/Vol| < 3%), `order size discrepancy` (avg SELL > avg BUY),
  `buy TX dominance` (≥52%), `whale net`, `volume kering / LPS` (drop -40%..-70%)
- 7-checks: `sell_gt_buy`, `whale_negative`, `pantul_gt_5`, `cvd_flat`,
  `buy_tx_ge_52`, `after_low_net_buy`, `spring_55`, `CORE_REQUIRED`, `MIN_LOLOS`
- `absorption`, `penyerapan`, `deteksi penyerapan`, `export penyerapan`,
  `smart_buyer`, `holder_lock`, `holder_lock_pct`, `pure_accumulators`,
  `top 100 lock`
- `Fit score` (4 pilar struktural GMGN screener), `conviction`, `conviction.json`
- `breakout guard`, `breakout`, `failed_breakout`, `spring`, `reclaim`,
  `levels.json`, `breakouts.json` (bila beririsan dengan deteksi)

### 1b. File yang harus dibersihkan / ditulis ulang
- `signals.py` → hapus seluruh logika sinyal lama & digest lama; sisakan hanya
  fungsi `send_telegram()`.
- `scripts/update_cvd.py` → tulis ulang: cron harian baru (lihat §4).
- Modul detektor prepump (temukan semua file yang memuat `prepump` di namanya /
  isinya) → HAPUS, ganti dengan `effort_detector.py` baru (lihat §2).
- `PROMPT_PREPUMP_BARU.md` → HAPUS, ganti dengan template prompt baru (§7).
- `app.py` → hapus render sinyal watchlist lama (imminent/forming/cleared/neutral
  & skor 0-7/0-100); ganti dengan render sinyal efisiensi (§6).
- `cvd.py` / `cvd_daily.py` → sisakan hanya fungsi **akumulasi CVD harian** yang
  dipakai detector baru; hapus divergence H1/4h/conviction bila tidak dipakai.
- `gmgn_screener.py` → hapus Fit score 4-pilar; screener trending boleh tetap
  (hanya listing), tapi TANPA skor struktural.
- JSON lama yang sudah tidak dipakai (`conviction.json`, `signals.json`,
  `levels.json`, `breakouts.json`) → hapus dari repo & dari alur cron.
- Perbarui `AGENTS.md`, `DISABLED.md`, `README.md` agar tidak lagi menyebut
  framework lama, dan catat framework baru sebagai satu-satunya sumber kebenaran.

### 1c. Aturan "jangan menyisakan"
Setelah bersih, jalankan `grep -rn` untuk istilah di §1a dan pastikan hasilnya
0 (nol) kecuali di file dokumentasi yang sudah kamu tulis ulang.

---

## 2. MODUL BARU: `effort_detector.py`

Buat satu modul baru dengan satu tanggung jawab: menghitung **Effort-to-Result
Ratio (R)** dan mengklasifikasikannya ke **5 sinyal**.

### 2a. Definisi metrik (WAJIB persis seperti ini)

Untuk satu **candle harian** (24 jam, acuan waktu Asia/Jakarta, 00:00–23:59 WIB):

```
ΔPrice%  = (Close − Open) / Open × 100        # dari candle harian (DexScreener/GeckoTerminal/GMGN)
ΔCVD     = Σ(delta_sol) sepanjang hari itu     # delta = +buy_quote_sol, −sell_quote_sol, dari history trade
Direction = sign(ΔPrice%)                       # "down" jika ΔPrice% < 0, "up" jika > 0
R        = |ΔCVD| / |ΔPrice%|                   # "SOL agresif yang dibutuhkan per 1% gerak harga"
```

Simpan per token per hari (key = mint + tanggal):
```json
{
  "mint": "...", "date": "2026-07-19",
  "open": 0.00007545, "close": 0.00004496, "price_chg_pct": -40.41,
  "cvd_delta": -31.21, "direction": "down", "ratio": 0.772
}
```
Catatan: `ratio` di atas = 31.21 / 40.41 = 0.772 SOL per 1% (pakai nilai |.|,
selalu positif; arah disimpan terpisah di `direction`).

### 2b. Perbandingan 2 hari (deteksi "per 2 hari")

Deteksi HANYA boleh jalan bila tersedia **≥ 2 candle harian berturut-turut**
(hari N dan hari N−1). Tanpa 2 hari, output = `"insufficient_data"`, JANGAN
memunculkan sinyal.

```
baseline = ratio hari N−1
M        = ratio hari N / baseline     # "multiplier effort"
```

### 2c. Klasifikasi 5 sinyal (threshold TETAP, jangan diubah)

Ambang anomali = **2×** (M ≥ 2.0) dan kebalikannya **0.5×** (M ≤ 0.5).

**Arah harga HARI N turun (direction == "down"):**
| # | Kondisi | Sinyal | Makna | Bias |
|---|---------|--------|-------|------|
| S1 | M ≥ 2.0 | `S1_PENYERAPAN` | Butuh SOL jauh LEBIH BANYAK utk menurunkan harga → buyer menyerap supply | **BULLISH** |
| S2 | M ≤ 0.5 | `S2_DUMP_DISTRIBUSI` | Butuh SOL LEBIH SEDIKIT utk menurunkan harga → buyer absen, harga jatuh bebas | **BEARISH** |

**Arah harga HARI N naik (direction == "up"):**
| # | Kondisi | Sinyal | Makna | Bias |
|---|---------|--------|-------|------|
| S3 | M ≥ 2.0 | `S3_DISTRIBUSI_KE_KUAT` | Butuh SOL jauh LEBIH BANYAK utk menaikkan harga → seller menyerap demand (overhead supply) | **BEARISH** |
| S4 | M ≤ 0.5 | `S4_PUMP_ASLI` | Butuh SOL LEBIH SEDIKIT utk menaikkan harga → seller absen, pump murni | **BULLISH** |

**Netral:**
| # | Kondisi | Sinyal | Makna |
|---|---------|--------|-------|
| S5 | 0.5 < M < 2.0 ATAU |ΔPrice%| < 3.0 (ranging) | `S5_NETRAL` | Tidak ada anomali efisiensi |

### 2d. Flag penguat (bukan sinyal baru, hanya penanda tambahan)
Tambahkan field `flag_divergence = true` bila arah ΔCVD **berlawanan** dengan
arah ΔPrice% (mis. harga turun tapi CVD naik). Ini memperkuat S1/S3, tapi TIDAK
mengubah jumlah sinyal (tetap 5).

### 2e. Output fungsi
```python
{
  "mint": str, "date": str, "direction": "down"|"up"|"flat",
  "ratio_N": float, "ratio_N_minus_1": float, "multiplier": float,
  "signal": "S1_PENYERAPAN"|"S2_DUMP_DISTRIBUSI"|"S3_DISTRIBUSI_KE_KUAT"|"S4_PUMP_ASLI"|"S5_NETRAL"|"insufficient_data",
  "bias": "bullish"|"bearish"|"neutral"|None,
  "flag_divergence": bool
}
```

---

## 3. PENYIMPANAN & DATA

- File baru `daily_effort.json` → daftar {mint, tanggal, open, close,
  price_chg_pct, cvd_delta, direction, ratio} per token, minimal simpan riwayat
  **30 hari** per token (untuk chart & baseline).
- CVD harian diambil dari history trade (GMGN `/token_trades/sol/{mint}` dengan
  `event=buy&event=sell`, aggregasi `quote_amount` per hari) — REUSE fetch layer
  yang sudah ada, jangan tulis ulang API client.
- Candle harian dari DexScreener/GeckoTerminal daily candles (open/close). Bila
  tidak tersedia, fallback: harga open = harga tx pertama hari itu, close = harga
  tx terakhir hari itu.

---

## 4. CRON BARU

- **Cadence:** harian, sekali per hari pukul **00:00 WIB (17:00 UTC)** —
  pertahankan pola workflow `daily` yang sudah ada (`.github/workflows/...`,
  `scripts/update_cvd.py`), tapi isi langkah kerjanya diganti total:
  1. Untuk tiap mint di watchlist: tarik trade harian + candle harian.
  2. Hitung R, simpan ke `daily_effort.json` (append/merge per tanggal, idempoten).
  3. Bila ≥ 2 hari → klasifikasi 5 sinyal.
  4. Kirim Telegram (format §5) HANYA untuk sinyal S1–S4. S5 & insufficient → diam.
  5. Update chart harian (render ulang data chart, §6).
- Watchlist tetap dari `watchlist.json` / penyimpanan GitHub yang sudah ada.
- Secrets tetap: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `HELIUS_API_KEY(s)`.

---

## 5. FORMAT ALERT TELEGRAM (GANTI TOTAL)

Hapus format lama. Format baru (persis):

```
⚡ ANOMALI EFISIENSI — ${SYMBOL}
Sinyal: ${S1_PENYERAPAN (bullish)} | ${S2_DUMP (bearish)} | ${S3_DISTRIBUSI (bearish)} | ${S4_PUMP (bullish)}
Hari: ${date} (vs ${date_N_minus_1})
Ratio: ${ratio_N} SOL/1% vs ${ratio_N_minus_1} SOL/1%  (×${multiplier})
ΔHarga: ${price_chg_pct}% | ΔCVD: ${cvd_delta} SOL
${flag_divergence ? "⚠️ divergensi arah CVD" : ""}
https://gmgn.ai/sol/token/${CA}
```

- Emoji sesuai bias: 🟢 untuk bullish (S1, S4), 🔴 untuk bearish (S2, S3).
- Hapus semua field lama di alert (skor /100, 4 pilar, 7 checks, holder lock,
  smart buyer, grade A/B/C, Fit, CVD/Vol%, dll).

---

## 6. CHART "HARGA vs CVD HARIAN" (WAJIB, di dashboard)

Tambahkan chart di halaman CVD (atau halaman baru "Efisiensi"):
- **Panel utama (dual axis):** sumbu X = tanggal (**7 hari terakhir**), sumbu Y kiri
  = harga (USD), sumbu Y kanan = CVD kumulatif harian (SOL). Dua garis berbeda
  warna. Buat dengan matplotlib (bukan CDN).
- **Panel kedua (opsional tapi disarankan):** bar/line `ratio` per hari,
  dengan marker warna untuk hari S1–S4 (hijau=bullish, merah=bearish), plus
  garis horizontal referensi baseline.
- Hari dengan sinyal S1–S4 ditandai jelas (dot/annotation).
- Chart dirender ulang setiap cron harian dari `daily_effort.json`.

---

## 7. TEMPLATE PROMPT AI BARU (ganti PROMPT_PREPUMP_BARU.md)

Tulis `PROMPT_EFFORT_ANOMALI.md` yang isinya template copy-paste untuk evaluasi
token via AI (ChatGPT/Claude/DeepSeek), berisi:
- Definisi R, baseline, multiplier, dan 5 sinyal (persis §2).
- Data input yang diminta: candle harian (open/close per hari) + delta CVD harian
  untuk ≥ 2 hari.
- Output JSON `{mint, signal, bias, ratio_N, ratio_N_minus_1, multiplier,
  flag_divergence, detail}`.
- Larangan: TIDAK boleh memakai kriteria lama (4 pilar / 7 checks / Fit /
  absorption / whale / holder lock), TIDAK boleh mengarang angka, TIDAK boleh
  memberi target harga.

---

## 8. CRITERIA SELESAI (definition of done)

1. `grep -rn` seluruh istilah §1a = 0 di kode aktif.
2. `effort_detector.py` menghasilkan 5 sinyal persis §2c dengan threshold tetap.
3. Deteksi menolak (insufficient) bila < 2 candle harian.
4. Cron harian 17:00 UTC jalan, simpan `daily_effort.json`, kirim Telegram hanya
   S1–S4 dengan format §5.
5. Chart harga vs CVD harian tampil di dashboard & update tiap hari.
6. `PROMPT_EFFORT_ANOMALI.md` menggantikan `PROMPT_PREPUMP_BARU.md`.
7. `tests/` diperbarui: minimal unit test untuk (a) hitung R, (b) klasifikasi
   5 sinyal + threshold 2×/0.5×, (c) insufficient_data saat < 2 hari, (d) merge
   idempoten `daily_effort.json`. Semua test PASS.
8. Jangan ubah lapisan fetch data (Helius/GMGN/DexScreener) & manajemen watchlist
   bila tidak perlu. Jangan sentuh pin `streamlit>=1.39`.

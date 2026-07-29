# AGENTS.md — baca ini dulu sebelum mengubah apa pun

File ini adalah **memori antar-sesi**. Agen AI (Arena, Claude Code, Cursor,
Copilot, dll.) membaca `AGENTS.md` secara otomatis saat membuka repo, jadi
sesi baru tidak perlu diberi konteks ulang dari nol.

> **Untuk agen:** setelah menyelesaikan pekerjaan yang mengubah perilaku,
> perbarui file ini + `docs/PROGRESS.md` dalam commit yang sama. Kalau tidak,
> sesi berikutnya akan mengulang pertanyaan yang sudah dijawab.

---

## 1. Apa ini

Dashboard Streamlit + cron untuk cek kesehatan token Solana sebelum
trade/LP. Bahasa pengguna: **Indonesia**. Komentar & docstring kode:
**Inggris** (ikuti gaya yang sudah ada).

Pemilik memakai ini untuk keputusan uang sungguhan. Jadi: **jangan pernah
melonggarkan kriteria risiko diam-diam**, dan kalau mengubah scoring,
buktikan kalibrasinya tidak bergeser (lihat §5).

## 2. Peta file

| File | Isi |
|---|---|
| `app.py` | dashboard utama (besar, ~110KB) |
| `pages/` | halaman Streamlit tambahan |
| `core.py` | helper Helius/DexScreener/GeckoTerminal |
| `cvd.py` | store swap, bucket CVD, profil wallet, **level D1**, **flow attribution** |
| `gmgn_screener.py` | screener GMGN + **scoring ramp kontinu** |
| `breakout_guard.py` | **Breakout Guard**: level D1 + konfirmasi close H4 |
| `breakout_log.py` | log event level → `breakouts.json` |
| `signals.py` | log sinyal CVD → `signals.json` + notif Telegram |
| `scripts/update_cvd.py` | entry point cron (tiap jam, menit :20) |
| `tests/` | 2 suite, **jalan tanpa pytest & tanpa jaringan** |

**File data yang di-commit cron** (jangan di-`.gitignore`):
`cvd.json` · `signals.json` · `conviction.json` · `levels.json` ·
`breakouts.json`

## 3. Dua jenis notifikasi Telegram — JANGAN tertukar

Keduanya lewat `send_telegram()` di `breakout_guard.py`, tapi beda sumber
dan beda caption. Caption itu wajib ada supaya pembaca tahu yang mana.

| Caption | Modul | Dasar | Dedupe |
|---|---|---|---|
| 📊 **CVD MONITOR** | `signals.py` | flow 6 jam + divergensi H1 | 4 jam per `(ca, tipe)` |
| 🛡️ **BREAKOUT GUARD** | `breakout_guard.py` | level **D1**, konfirmasi **close H4** | 12 jam per level |

Guard juga menulis ke `signals.json` (`src="guard"`, tipe `guard_*`) untuk
riwayat, tapi **tidak** memicu pesan CVD — terkunci dua lapis: tipe `guard_*`
tidak ada di peta emoji, dan `src != "cron"`. Jangan hapus salah satu kunci
itu tanpa sadar; nanti tiap breakout kirim dua pesan.

## 4. Breakout Guard — aturan yang sudah disepakati

Pemilik trading di **H4**, tapi memakai level **D1**. Itu disengaja.

- Level dari candle **harian** (`cvd.daily_levels`), pivot konfirmasi 2 bar
  kiri-kanan, level berjarak <1,5% digabung, maks 6 per sisi.
- Keputusan **hanya saat candle H4 CLOSE** (`closed_h4_candles` membuang
  candle berjalan). Jangan pernah pakai harga tick.
- Lima event: `breakout` · `failed_breakout` · `breakdown` · `spring` ·
  `reclaim` (maks **5 candle H4** setelah break).
- **Tiap notifikasi wajib menyebut siapa pelakunya** (whale vs retail, jumlah
  wallet, pure accum vs distributor). Ini permintaan eksplisit pemilik —
  "harga break" saja tidak actionable.
- Event tersimpan di `breakouts.json` dengan `parent_id` + `outcome`
  (`reclaimed`/`failed`/`held`/`no_reclaim`) supaya spring/reclaim bisa
  dianalisa terhadap break sebelumnya.

Konstanta (`breakout_guard.py`): `RECLAIM_MAX_CANDLES=5` ·
`ALERT_DEDUPE_H=12` · `ALERT_FRESH_H=8` · `MIN_PENETRATION=0.0015` ·
`MIN_WICK_RATIO=0.20`. Whale = swap ≥ `WHALE_SOL` (3.0 SOL) di `cvd.py`.

## 5. Scoring screener — ramp kontinu, bukan tangga

Dulu tumpukan `if/elif` sehingga 1 smart wallet membalik skor 54→77.
Sekarang interpolasi linear lewat `CURVES` / `PENALTY_CURVES` / `CAP_CURVE`.

**Kalau mengubah scoring, wajib:**
1. Titik tengah tiap ramp = ambang lama (jaga kalibrasi).
2. Jalankan `tests/test_scoring_continuity.py` — gagal kalau ada lompatan
   >4 poin antar-langkah input.
3. Bandingkan distribusi grade lama vs baru di token sintetis. Patokan
   terakhir: PRIME ~1,7%→2,9%, flag high-risk **100% identik**.

## 6. Cara kerja & jebakan

```bash
python tests/test_breakout_guard.py       # 67 assertion
python tests/test_scoring_continuity.py
```

Tanpa pytest, tanpa jaringan. **Tes wajib mem-patch semua path file**
(`LOG_PATH`, `LEVELS_PATH`, `signals.SIGNALS_PATH`) ke tmpdir — pernah
bocor menulis ke `signals.json` asli.

Jebakan yang sudah pernah menggigit:

- **Runner Actions ephemeral.** File yang tidak di-commit hilang tiap run.
  Karena itu `breakouts.json` ada di `git add` workflow — tanpa itu
  `reclaim`/`failed_breakout` tidak akan pernah terdeteksi.
- **Agen tidak bisa mengubah `.github/workflows/`.** GitHub App tidak punya
  izin `workflows`; `git push`, Contents API, dan Git Data API semuanya 403.
  Kalau perlu ubah workflow, **minta pemilik** melakukannya lewat web GitHub.
- **Field GMGN.** Payload `trending_rank` TIDAK punya `insider_ratio` /
  `bundler_rate`. Yang benar: `bdrr` `dhr` `etpr` `bdr` `t70_shr` `snp`.
  Lihat `docs/gmgn_api.md`.
- **Jangan commit `config.json`** (berisi API key, sudah di `.gitignore`).

## 7. Status & langkah berikutnya

Lihat `docs/PROGRESS.md` untuk riwayat keputusan dan daftar yang belum
terverifikasi.

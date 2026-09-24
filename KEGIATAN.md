# Kegiatan — 24 September 2026 (🏆 Best Pool: F/V di bawah 2× lenyap total — tidak muncul di "dilewati" maupun di mana pun)

Permintaan user (verbatim, satu pesan): *"jangan tampilkan sama sekali pool
yang F/V nya kurang dari 2 di pool yang dilewati atau dimanapun"*.

## Yang berubah
- **`meteora_screener.py`**:
  - Konstanta baru `BEST_FV_HIDE_MIN = 2.0` + helper `row_fv_under_hide()`
    (mengembalikan rasio bila `< 2×`, selain itu `None`) dan `fv_hide_label()`
    (`"F/V < 2×"`, dipakai teks UI supaya tidak bisa basi).
  - `row_best_dropped()` memanggil lantai ini **paling akhir** (sesudah
    Top10/volatility/LPs) — baris F/V 0–2× langsung **dibuang total**, bukan
    sekadar di-skip dari fetch holder. Jadi listing "▶ N pool dilewati" hanya
    memuat F/V **2×–5×**, baris **Fee/TVL** tipis, dan metrik tidak valid.
  - Batas eksklusif di sisi buang: **tepat 2,0× masih tampil** di "dilewati".
    Angka F/V tanpa bukti (metrik hilang/nonfinite, volatility 0/∞) bukan
    "kurang dari 2" — vol-0 dibuang lewat `row_volatility_zero`, metrik tidak
    valid tetap muncul dengan alasannya sendiri.
  - Counter audit baru `dropped_fv` di hasil `scan_best_lane()` + pesan Log
    Aktivitas (`N pool F/V < 2× dibuang`). Teks alasan gugur tidak berubah
    (`24H: F/V < 5×`) — lantai hanya memutuskan pembuangan.
  - Semua pembaca ikut bersih tanpa kode baru: `scan_best_lane()`
    (`hidden_rows`), `filter_best_rows()` (hitungan pill/caption), dan
    render ulang hasil scan **lama** di `best_pool_ui` (session/cache) —
    jadi hasil lama pun langsung bersih saat halaman dibuka, tanpa scan ulang.
- **`best_pool_ui.py`**: tooltip judul card menyebut lantai + kutipan verbatim
  permintaan user, help tombol scan menulis "F/V di bawah 2× dibuang total",
  help tombol "▶ N pool dilewati" menegaskan isinya `F/V (2×–5×) atau
  Fee/TVL`; bullet aturan baru di docstring modul. Fallback error
  `_run_lane_scan` membawa `dropped_fv`/`dropped_lps`/`dropped_top10`/
  `dropped_total` = 0.
- **`tests/`**: `FvHideFloorTest` (7 tes) + `FvHideFloorUiTest` (1 tes AppTest)
  di `tests/test_best_pool_scan.py`;
  `LaneEnrichmentTest.test_fv_di_bawah_2_dibuang_total_tanpa_scan_holder` di
  `tests/test_best_fv_prefilter.py`. **7 dari 9 tes baru diverifikasi gagal
  pada kode lama** (`git archive HEAD` → `/tmp/baseline`); 2 sisanya penjaga
  perilaku yang memang tidak berubah. Fixture tes lama yang dulu memakai
  F/V < 2 sebagai contoh "gugur F/V tapi tampil di dilewati" dinaikkan ke
  2×–5× (`_fv(2.0, 6.0)` → `_fv(20.0, 6.0)`, `ratio=1.0` → `ratio=20.0`,
  `_pool(ratio=1.0, volatility=2.0)` → `ratio=6.0`).
- **Suite**: `python -m unittest discover -s tests` → **1252 tes**, 18 failed
  + 1 error — nama kegagalan **identik baseline** `/tmp/baseline` HEAD
  `7788539` (1243 tes, 18 failed + 1 error), jadi bukan regresi.
- **Dokumentasi**: README (tabel gate + tabel ambang `BEST_FV_HIDE_MIN` +
  ringkasan modul), AGENTS.md (entri ini + blok "🏆 Scan Best Pool" di
  bagian Ambang), dan `docs/PROGRESS.md` ikut diperbarui.

# Kegiatan — 23 September 2026 (🏆 Best Pool: Fee/TVL minimal 30% — di bawah itu tidak ditampilkan di hasil)

Permintaan user (verbatim, tiga pesan berurutan): *"ok, kita perketat filter
yang boleh di show di hasil"* · *"**Fee/TVL minimal 30%**"* · *"dibawah itu
jangan show"*. Klarifikasi di sesi yang sama (dijawab user): baris di bawah
ambang **masuk listing "▶ N pool dilewati"** (bukan hilang total seperti
Top10 / volatility / LPs), dan aturannya **hanya** untuk card 🏆 Scan Best
Pool Meteora — 🌊 Scan Meteora regular tidak ikut berubah.

## Yang berubah
- **`meteora_screener.py`**:
  - Konstanta baru `BEST_FEE_TVL_MIN = 30.0` + helper `row_fee_tvl_pct()` /
    `row_fee_tvl_under()` / `row_fee_tvl_ok()` (satu sumber angka untuk
    saringan, teks alasan, dan kolom **Fee/TVL**).
  - `row_best_gaps()`: saringan baru dieksekusi **sesudah** ambang F/V dan
    **sebelum** Top10 — jadi baris yang gagal keduanya tetap beralasan
    `24H: F/V < 5×` (teks lama tidak berubah arti), sedangkan pool ber-Fee/TVL
    tipis dengan F/V lolos menulis `24H: Fee/TVL 20% < 30% — fee pool terlalu
    kecil`. Batas inklusif di sisi tampil: tepat 30,0% lolos. Fee hilang /
    negatif / nonfinite sudah gugur lebih dulu di cabang "metrik F/V tidak
    tersedia".
  - `BEST_GAP_CATEGORIES` dapat jarum `"Fee/TVL"` (rekap tabel kosong menyebut
    `1 Fee/TVL`, bukan `1 F/V`), dan `row_best_dropped()` **sengaja tidak**
    ikut membuang total alasan ini — docstringnya mencatat keputusan user.
  - Semua saringan tetap jalan **sebelum** `enrich_pools`, jadi pool di bawah
    30% tidak membakar kuota Helius; docstring modul + `filter_best_rows` +
    `scan_best_lane` diperbarui (sekalian mengoreksi kalimat basi yang masih
    menyebut likuiditas GMGN sebagai saringan).
- **`best_pool_ui.py`**: tooltip card dapat aturan "(5) Fee/TVL di bawah 30%
  gugur" (angkanya dibaca dari konstanta, jadi tooltip tidak bisa basi), help
  tombol scan menulis `+ Fee/TVL ≥ 30%`, help tombol "▶ N pool dilewati"
  menyebut `F/V atau Fee/TVL`, docstring modul dapat bullet sendiri. Render
  ulang hasil scan **lama** di `session_state`/cache ikut tersaring karena
  jalurnya memang `row_best_gaps` + `row_best_dropped` (tanpa scan ulang).
- **`tests/`**: `FeeTvlPrefilterTest` (5 tes, urutan eksekusi + tidak ada
  fetch holder + bukan pembuangan total + ambang dibaca dari konstanta) di
  `tests/test_best_fv_prefilter.py`; `FeeTvlFilterTest` (7 tes: helper, batas
  30% inklusif, teks ikut konstanta, `hidden_metric`, `scan_best_lane`,
  tooltip, scope regular scan) + `FeeTvlUiTest` (1 tes AppTest: pool tipis
  hilang dari tabel hasil, muncul di "dilewati" dengan alasannya) di
  `tests/test_best_pool_scan.py`. Dua fixture tes lama disesuaikan karena
  angka live-nya kini di bawah ambang (bukan karena bug): PAID
  (`tests/test_gmgn_liquidity.py`, Fee/TVL 23,39% → `ratio` 30,0 untuk tes
  regresi GMGN, dan snapshot live-nya di-pin di tes baru
  `test_paid_snapshot_live_kena_ambang_fee_tvl`) dan CATE-USDC
  (`tests/test_meteora_active_range.py`, 19,54% → 39,54% supaya tes tetap
  menguji render **Active Range**).

## Tes
- `python -m unittest discover -s tests` → **1228 tes, 18 failed + 1 error** —
  jumlah & nama kegagalan **identik baseline** sebelum perubahan (1214 tes,
  18 failed + 1 error; semuanya di `test_lp_card_ui`, `test_manual_scan_alerts`,
  `test_meteora_screener`, `test_scan_holders` dan sudah gagal di HEAD bersih).
  +14 tes baru hijau, **tidak ada regresi**.
- 4 dari 5 tes baru `FeeTvlPrefilterTest` **gagal pada kode lama** (diverifikasi
  dengan snapshot `git archive HEAD` + file tes baru), jadi tesnya benar-benar
  menangkap aturan baru, bukan hiasan.

# Kegiatan — 22 September 2026 (🏆 Best Pool: gugur Top10 & volatility lenyap total + tabel disembunyikan urut F/V lalu Fee/TVL)

Dua permintaan user untuk halaman 🏆 Best Pool:
1. *"hasil yang gugur karena gugur: Top10, gugur: volatility langsung sembunyikan total, tidak ditampilkana dimanapun"*
2. *"di hasil pool yang disembunyikan, urutkan menurut F/V terbesar, Fee/TVL terbesar"*

## Yang berubah
- **`meteora_screener.py`**:
  - `row_best_dropped(row, *, lane=None)`: mengembalikan True jika pool gugur karena Top10 atau volatility.
  - `scan_best_lane`: pool yang gugur Top10 / volatility tidak dimasukkan ke `hidden_rows` (dibuang total).
  - `sort_hidden_best_rows`: sorting khusus tabel disembunyikan dengan urutan F/V terbesar lalu Fee/TVL terbesar.
  - `filter_best_rows`: menghitung `row_best_dropped` sebagai `dropped`, sehingga counter `hidden_metric` hanya mencatat pool yang benar-benar tampil di tabel dilewati.
- **`best_pool_ui.py`**:
  - `render_best_pool_scan`: memfilter `stored_rows` dan `hidden_rows` dengan `not row_best_dropped(...)` agar data scan lama di session langsung bersih tanpa perlu scan ulang.
  - Menggunakan `sort_hidden_best_rows` untuk merender tabel disembunyikan ("▶ N pool dilewati").
  - Menyesuaikan tooltip card dan help button.
- **`tests/test_best_pool_scan.py` & `tests/test_best_fv_prefilter.py`**:
  - Ditambahkan unit test untuk `row_best_dropped`, `sort_hidden_best_rows`, dan integrasi UI `test_tabel_disembunyikan_urut_fv_lalu_fee_tvl_dan_top10_volat_lenyap`.

# Kegiatan — 17 September 2026 (🚨 background STOP DEGEN merah, tulisan tetap biru)

Permintaan terbaru: *"background nya ganti warna merah, tulisan tetap biru"*.
Panel `.degen-stop-header` di halaman utama sekarang memakai gradien merah gelap
`#450a0a → #7f1d1d → #450a0a`. Tulisan tetap biru royal `#3b82f6`, dan border,
glow biru, animasi berkedip, ukuran besar, serta perilaku reduced-motion tidak
diubah. Tes regresi header diperbarui untuk mem-pin kombinasi warna tersebut.

# Kegiatan — 17 September 2026 (🚨 header STOP DEGEN jadi biru + likuiditas < $500K ditulis merah)

Dua permintaan lanjutan di hari yang sama, keduanya **hanya soal warna**:

1. *"ganti tulisan warna warning kita menjadi warna biru, efek tetap"* — header
   alarm 🚨 STOP DEGEN yang baru dibuat sore harinya (merah menyala berkedip)
   dipindah ke palet **biru royal**; animasi kelip + glow, ukuran huruf, dan
   posisinya tidak disentuh.
2. *"lalu, tambahkan jika total likuiditas dibawah 500K, kasih warna merah
   bagian tulisan likuiditasnya"* — angka likuiditas total GMGN di kolom
   **RugCheck** (🏆 Scan Best Pool) yang tadi hanya duastatus (hijau di atas
   $500K, hitam sisanya) jadi tiga sisi: **hijau > $500K**, **merah < $500K**,
   **hitam** tepat di ambang / bila angkanya tidak terukur.

## Yang berubah

- **`dashboard_components.render_styles()`** — blok CSS `degen-stop-*`:
  teks `#ff2d2d` → `#3b82f6`, panel `#450a0a→#7f1d1d` → `#0a1e45→#1e3a8a`,
  border `#dc2626` → `#2563eb`, ketiga lapis `text-shadow` dan `box-shadow`
  `@keyframes degen-stop-glow` ikut ke biru (rgba 59,130,246 / 37,99,235 /
  29,78,216). **Angka geraknya identik**: `1s ease-in-out infinite`,
  `opacity:.3` di tengah siklus, `clamp(1.4rem,3.6vw,2.6rem)`, dan
  `prefers-reduced-motion` yang mematikan animasi (teks tetap biru menyala).
  Nama class tidak diganti — ada tes yang menghitung kemunculan string class
  chip emas di seluruh body halaman.
- **`gmgn_liquidity.py`** — ambang $500K yang sudah jadi ambang warna
  (`MIN_TOTAL_LIQ_USD`) dapat pasangan barunya: `LIQ_RED_MAX_USD`,
  `LIQ_RED_COLOR = "#dc2626"` (merah standar repo: delta negatif, verdict RUG,
  pill "perlu tindakan"), `liq_is_red()` (strict di sisi bawah, jadi tepat
  $500K tidak merah dan tidak hijau) dan `liq_color()` sebagai **satu sumber
  aturan** yang mengembalikan hex atau string kosong.
- **`rugchecker.cell_parts()`** — baris kecil kolom RugCheck tidak lagi
  mengimpor `liq_is_green` + merangkai span sendiri; ia tanya `liq_color` dan
  memakai hex itu untuk angka likuiditas (span hijaunya byte-per-byte sama
  dengan sebelumnya). `gmgn_liquidity` tidak terbaca → tanpa warna. Warna hanya
  di sel; tooltip tetap menulis angka polos tanpa markup.
- **Teks** — `best_pool_ui.best_pool_tooltip()` (dua tempat) sekarang menyebut
  "HIJAU bila > $500K, MERAH bila < $500K, tepat di ambang tetap hitam",
  ambangnya dibaca dari `meteora_screener.gmgn_min_label()`; komentar
  `app.py`, docstring `render_degen_stop_header()`, README (bagian halaman +
  tabel gate + tabel konstanta) ikut dikoreksi — tabel gate README juga
  mencatat bahwa saringan likuiditas sudah dicabut, bukan lagi "dibuang".

## Tes

- `tests/test_degen_header.py`: pin warna → `color:#3b82f6`,
  `border:3px solid #2563eb`, `background:#0a1e45`; kasus baru
  `test_palet_merah_hilang_tapi_efek_tetap` memastikan token merah lama
  (`#ff2d2d`, `#450a0a`, `rgba(255,45,45`, `rgba(239,68,68`, `rgba(220,38,38`)
  tidak ada lagi di body halaman **dan** tiap animasi masih muncul tepat sekali
  dengan `1s ease-in-out infinite` + `opacity:.3` di `50%`.
- `tests/test_gmgn_liquidity.py`: `test_warna_merah_strict_di_bawah_500k`,
  `test_liq_color_satu_sumber_aturan` (tidak ada nilai yang hijau+merah
  sekaligus), `test_angka_gmgn_dibawah_ambang_merah` (sumber gmgn & rugchecker,
  plus sisi ambang: 153K/0 → span merah, $500K persis → tanpa span, $500K+0,01
  → span hijau), dan `test_pool_tipis_tidak_gugur_hanya_hitam` →
  `…_hanya_merah`.
- Pin sub-line ditulis ulang ke span merah: `tests/test_rugchecker.py`
  ($219.2K dan $500) dan `tests/test_best_pool_scan.py` ($103.3K di kolom
  RugCheck tabel utama).

`python -m unittest discover -s tests` → **1119 tes**, 18 failed + 1 error;
daftar nama kegagalannya **identik dengan baseline** di HEAD sebelum perubahan
ini (1115 tes, 18 + 1 — semuanya tes store/network), jadi tidak ada regresi.

# Kegiatan — 17 September 2026 (🏆 Scan: copy link HawkFi, ⭐ & kolom Dust %MC dihapus, garis vertikal antar kolom)

Empat permintaan user sekaligus untuk tabel **🏆 Scan Best Pool Meteora** di
halaman utama:

1. *"tambahkan copy link hawkfi dibagian scan"* — kolom **Pool** kini memuat
   tombol **📋 copy link HawkFi** di samping tautan 🌊Meteora/🦅HawkFi.
   Helper baru `links.hawkfi_copy_html()`: `<button>` HTML murni dengan
   `navigator.clipboard.writeText` (+ fallback `execCommand("copy")` untuk
   konteks non-https) dan umpan balik ikon ✓ 1,2 detik — **bukan**
   `st.button`, jadi klik tidak memicu rerun (pola `onclick` inline yang
   sudah dipakai `holder_analytic_link_html`). Gaya tombol hidup di
   `dashboard_components.render_styles()` (`.pool-links .hawkfi-copy-btn`).
2. *"hapus tombol favorit / watchlist"* — kolom **⭐** (tombol yang
   memasukkan token ke Watchlist Meteora) dicabut dari tabel utama maupun
   tabel "dilewati"; impor `add_to_watchlist`/`LP_SOURCE` ikut hilang dari
   `best_pool_ui.py`. Watchlist tetap dikelola dari halaman 📦 TEMP.
3. *"batasi per kolom dengan garis naik turun"* — tiap kolom tabel kini
   dibatasi **garis vertikal**: marker tak-kasatmata `.bp-cols-next`
   disisipkan tepat sebelum header `st.columns` dan sebelum tiap baris
   data (pola yang sama dengan `.mobile-hide-next`), lalu CSS
   `:has()` + adjacent-sibling memberi `border-right` ke semua kolom
   kecuali yang terakhir. Selector diverifikasi langsung dari bundle
   frontend **Streamlit 1.61.1**: markdown dibungkus
   `div[data-testid="stElementContainer"]`, blok kolom
   `div[data-testid="stHorizontalBlock"]` adalah saudara langsungnya di
   dalam `stVerticalBlock` (blok tidak dibungkus element-container), dan
   kolomnya ber-`data-testid="stColumn"`. Garis hanya aktif di layar
   > 768 px — di mobile kolom tabel wrap menjadi kartu 2 kolom.
4. *"hapus kolom dust %"* — kolom **Dust %MC** (sel + header + tooltip-nya)
   dicabut dari tabel. Angkanya tetap dihitung backend
   (`sort_best_rows`) sebagai tie-break urutan terakhir; filter dust sudah
   lama nonaktif. Helper `_pct_txt` yang hanya dipakai sel ini ikut
   dihapus.

Dampak susunan: 15 → **13 kolom** — Token, F/V, Fee/TVL, Volat, Active
Range, LPs, Fee %, MC, A.TVL, Vol 24h, Top10, RugCheck, Pool (bobot Pool
0,8 → 1,05 untuk tiga ikon). Tooltip judul card dan semua docstring kolom
diperbarui.

**Perbaikan sampingan**: saat menjalankan suite ditemukan
`test_detail_karakteristik_di_tooltip_bukan_caption` sudah merah sebelum
perubahan ini — tooltip card masih menulis query server dengan flag
`base_token_has_critical_warnings=false&&quote_token_has_critical_warnings=false`
(ikut di-`"&&".join(JUPITER_SAFEGUARD_FILTERS)`), padahal filter server itu
sudah dimatikan default-nya pagi harinya. Tooltip dikoreksi ke
`pool_type=dlmm&&active_tvl>=50000` + catatan safeguard nonaktif default
(kwarg `safeguard=True` tetap tersedia), dan pin test-nya disesuaikan —
tidak ada lagi frasa "likuiditas total GMGN di bawah $500K" yang sudah
dicabut malam sebelumnya.

Tes: tiga pin layout di `test_best_pool_scan.py` + dua di
`test_meteora_active_range.py` ditulis ulang ke spesifikasi 17 kolom-baru;
tiga kasus `hawkfi_copy_html` ditambah ke `test_links.py`. Suite penuh:
**tidak ada kegagalan baru** (19 gagal pra-eksisting di
`lp_card_ui`/`manual_scan_alerts`/`meteora_screener`/`scan_holders` tidak
berubah) dan satu gagal pra-eksisting ikut sembuh.
# Kegiatan — 17 September 2026 (🚨 Header "STOP DEGEN" merah menyala berkedip di halaman utama)

Permintaan user (verbatim): *"tambahkan header di page app"* — teksnya:

> **STOP DEGEN, GAK BISA**
>
> **SUDAH KALAH BERTUBI2 AKUI KALAU KAMU GAK BISA**

dengan gaya *"merah menyala berkedip, tulisan besar, ada emoticon warning"*.

## Yang berubah

- **`dashboard_components.py`** — fungsi baru `render_degen_stop_header()` +
  konstanta `DEGEN_STOP_LINES` / `DEGEN_STOP_EMOJI`. Outputnya satu blok
  `<div class="degen-stop-header" role="alert">` berisi dua
  `<span class="degen-stop-line">`; tiap baris diapit emoticon warning — 🚨 di
  "STOP DEGEN, GAK BISA" dan ⚠️ di "SUDAH KALAH BERTUBI2 AKUI KALAU KAMU GAK
  BISA". Teks dipin **verbatim** (termasuk "BERTUBI2": itu kalimat user, bukan
  salah tulis yang perlu diperbaiki) dan dilewatkan `html.escape` supaya aman
  dirender sebagai HTML.
- **CSS di `render_styles()`** (`degen-stop-*`; gaya tidak bisa inline karena
  `st.markdown` men-sanitasi atribut `style`):
  - *merah menyala*: panel merah gelap `#450a0a → #7f1d1d → #450a0a`, border
    `#dc2626`, teks `#ff2d2d` + `text-shadow` glow merah tiga lapis;
  - *tulisan besar*: `font-size: clamp(1.4rem, 3.6vw, 2.6rem)` (±22–42 px,
    otomatis mengecil di layar sempit) dan `font-weight: 900`;
  - *berkedip*: `@keyframes degen-stop-blink` (opacity + glow turun di tengah
    siklus, 1 detik, `infinite`) + `@keyframes degen-stop-glow` untuk kilau
    panelnya — pola yang sama dengan kelip `.scan-best-gold`, tapi ini alarm
    merah, bukan pujian emas;
  - `@media (prefers-reduced-motion: reduce)` mematikan animasinya (teks tetap
    merah menyala). Nama class sengaja bukan turunan `scan-best-gold`/
    `dust-best`, karena ada tes yang menghitung kemunculan string class chip
    emas itu di seluruh body halaman.
- **`app.py`** — memanggil `render_degen_stop_header()` **setelah**
  `render_styles()` dan **sebelum** card 🏆 Scan Best Pool, jadi header ini
  elemen paling atas halaman utama. Halaman 🧮 Holder dan 📦 TEMP **tidak** ikut
  menampilkannya (user minta "di page app"); kalau nanti mau ikut, cukup satu
  baris panggilan di halaman itu.

## Tes

File baru **`tests/test_degen_header.py`** (4 tes, AppTest di `app.py`):

1. header terpasang & posisinya di **atas** card 🏆 Scan Best Pool
   (`role="alert"` ikut di-pin);
2. dua baris **verbatim** + emoticon 🚨/⚠️ + konstanta `DEGEN_STOP_LINES`;
3. pin gaya: `color:#ff2d2d`, `animation:degen-stop-blink … infinite`, kedua
   `@keyframes`, `font-size:clamp(1.4rem,3.6vw,2.6rem)`, `opacity:.3`
   (berkedip, bukan warna statis) dan `prefers-reduced-motion`;
4. halaman lain tidak memanggil fungsi/HTML-nya (📦 TEMP tetap bersih).

`python -m unittest discover -s tests` → **1112 tes**, 19 failed + 1 error —
daftar nama kegagalan **identik dengan baseline sebelum perubahan** (1108 tes,
19 failed + 1 error), jadi bukan regresi.

# Kegiatan — 17 September 2026 (🏆 Best Pool: tabel kosong → ambang likuiditas GMGN $1M diturunkan ke $500K)

Laporan user: *"Tidak ada pool 24H yang lolos filter Best Pool (atau listing
kosong)."* lalu *"lah, poolnya kok jadi kosong, padahal token PAID harusnya
masuk"* + mint `98kfF7rmsg1QDUEoCqNE7g7M1FdrTt92TEp2CLzypump`.

## Diagnosa (bukan dugaan — diukur dari endpoint yang dipakai app)

1. **Listing-nya ada, bukan kosong.** `pool-discovery-api.datapi.meteora.ag/pools`
   dengan filter server app (Jupiter safeguard + `pool_type=dlmm` +
   `active_tvl>=50000`, `timeframe=24h`, `category=top`) mengembalikan
   `total: 203`; dipersempit `volatility>=1&&volatility<=10` → `total: 70`.
2. **Pool PAID lolos tiga saringan metrik.** Query
   `filter_by=…&&pool_address=Gc5hVCBydc6k3Z7oc2cQEW4GThFQi2Fqk5HfKABqa2q8`
   → `total: 1`, dengan `fee_active_tvl_ratio` 23,394 / `volatility` 2,989
   (**F/V 7,8×** ≥ 5×), volatility 2,99% (dalam 1–10%), `top_holders_pct`
   **15,18%** (< 20%), `active_tvl` $494.560.
3. **Yang membuang PAID hanya saringan likuiditas GMGN** yang dipasang pagi
   harinya: `GET gmgn.ai/api/v1/token_info/sol/98kf…pump` →
   `liquidity = 884.912,398` USD → `< MIN_TOTAL_LIQ_USD (1.000.000)` →
   `row_gmgn_gap` memberi alasan → baris masuk `hidden_rows`, tidak pernah
   sampai ke tabel. Kandidat lain juga jauh di bawah $1M: pill
   (`Dvdm…pump`) $153.496, ELON (`GY9m…pump`) $149.542 — karena itu tabelnya
   kosong total, bukan cuma kehilangan PAID.
4. Catatan pagi *"PAID ~$1,9M di halaman gmgn.ai"* **sudah basi**: ada Remove
   LP (pool PAID `net_deposits` −$229.608, withdraw > deposit) sehingga angka
   GMGN-nya turun ke ±$885K. Angka $885K itu juga cocok dengan jumlah tiga
   pool Meteora PAID versi DexScreener ($510.271 + $282.887 + $92.438 =
   $885.596), jadi sumbernya benar — yang terlalu tinggi ambangnya.

## Yang diubah

- **`gmgn_liquidity.py`**: `MIN_TOTAL_LIQ_USD` `1_000_000` → **`500_000`**;
  helper `_label_usd` (label `$500K`, bukan `$0.5M`) → `MIN_LABEL`; docstring
  + komentar konstanta mencatat pengukuran PAID/pill/ELON sebagai alasan
  kalibrasi. Aturan tidak berubah bentuk: **di bawah** ambang gugur, tepat
  ambang lolos, tanpa bukti GMGN tidak pernah menyaring.
- **`meteora_screener.py`**: `gmgn_min_label()` (baca `MIN_LABEL` tiap
  dipanggil — teks log/UI tidak bisa tertinggal bila ambang diubah lagi) +
  `BEST_GAP_CATEGORIES` / `row_best_gap_label` / `best_gap_counts` /
  `best_gap_summary` untuk merekap alasan gugur per kategori; docstring
  `row_best_gaps`/`scan_best_lane` dan teks log aktivitas tidak lagi menulis
  "$1M" hardcoded.
- **`best_pool_ui.py`**: pesan tabel kosong kini menyebut penyebabnya —
  *"Tidak ada pool 24H yang lolos filter Best Pool (atau listing kosong). 3
  pool dilewati: 2 likuiditas GMGN · 1 Top10 — buka '▶ 3 pool dilewati' di
  atas untuk alasan tiap baris."*; help tombol scan + tombol "dilewati"
  membaca ambang dari `gmgn_min_label()`.
- **`rugchecker.py`**: docstring menyebut ambang lewat
  `gmgn_liquidity.MIN_TOTAL_LIQ_USD` (bukan "$1M").
- **Tooltip judul card ikut menyebut saringan keempat.** `best_pool_tooltip()`
  selama ini hanya menulis (1) F/V, (2) volatility, (3) Top10 — saringan
  likuiditas GMGN (yang justru mengosongkan tabel) tidak tertulis, dan kalimat
  penutup kolom RugCheck masih mengklaim *"saringannya tetap F/V + volat +
  Top10 + safeguard Jupiter"*. Keduanya dilengkapi: poin **(4) likuiditas
  total GMGN di bawah `$500K` gugur** (label dibaca `gmgn_min_label()`) +
  daftar saringan penutup ikut menyebut `likuiditas GMGN ≥ $500K`.
- **Teks alasan mepet ambang** (konfirmasi user *"ok, kita buat minimal 500K
  likuiditas saja, biar pool lebih longgar"*): `compact_usd` membulatkan ke
  satu desimal, jadi $499.999,99 terbaca `$500.0K` dan alasannya jadi
  "$500.0K < $500K" — helper `_gap_amount` menulis angka persis
  (`$499,999.99`) hanya bila pembulatannya menabrak label ambang.
- **Tes** (+12 → 1105): `tests/test_gmgn_liquidity.py` — `AmbangTest` (pin
  $500K + angka terukur PAID $884.912,398 / pill $153.496,33 / ELON
  $149.542,09 + pin bahwa $1M memang akan membuang PAID),
  `ScanLaneGmgnTest.test_paid_tidak_ikut_terbuang` (regresi end-to-end: pool
  PAID dengan metrik aslinya harus ada di `rows`, `hidden_rows` kosong),
  `GapTest` diarahkan ke ambang baru; `tests/test_best_pool_scan.py` —
  `BestGapSummaryTest` (5) + `test_tabel_kosong_menyebut_alasan_gugurnya`
  (AppTest: pesan info memuat rekap alasan) + pin tooltip (poin (4) + ambang
  ikut `MIN_LABEL` bila di-patch).
  `python -m unittest discover -s tests` → **1105 tes**, `18 failed + 1 error`
  — **nama kegagalan identik baseline** (diverifikasi dua arah: runner
  kanonik maupun runner pembanding; bukan regresi).

Catatan operasional: angka GMGN bergerak cepat (menit). Bila user menaikkan
ambang lagi, ubah **satu** konstanta `MIN_TOTAL_LIQ_USD` — label, teks UI, log
dan alasan gugur mengikutinya; `AmbangTest` akan mengingatkan bahwa PAID
($885K saat diukur) ikut terbuang di atas angka itu.

---

# Kegiatan — 17 September 2026 (🏆 Best Pool: likuiditas dari GMGN + saringan < $1M)

Permintaan user (lanjutan riset token PAID dari gmgn.ai): *"kita rubah info
liquidititas dari rugchecker.cc ke gmgn saja"* + *"jika grand total liquiditas
kurang dari 1M, jangan tampilkan di hasil scan"*. Riset di hulu: endpoint
públik GMGN tanpa API key yang membawa **likuiditas total** (angka yang sama
dengan halaman token gmgn.ai) adalah `POST /api/v1/mutil_window_token_info`
(sumber data halaman token — batch banyak mint dalam satu request); field
`liquidity` di endpoint rank (`/defi/quotation/v1/rank/sol/swaps/24h`) adalah
angka lain (likuiditas DEX utama, mis. PAID $860K di rank vs ~$1.9M di
halaman) sehingga dipakai **hanya sebagai fallback** — dan karena rank itu
cap 100 entri dengan cutoff ~$15K, mint yang tidak masuk daftar pasti
berlikuiditas di bawah cutoff → aman dianggap < $1M.

## Yang diubah

- **`gmgn_liquidity.py`** (baru): `fetch_total_liquidity` (POST batch 10 mint
  per request via curl_cffi impersonate → fallback `requests`; kegagalan satu
  batch hanya batch itu yang turun ke rank; cache berkas per-mint TTL 300/120
  s), `attach_total_liquidity` (menempel `row["gmgn_liq"]`, mutasi di tempat),
  `row_gmgn_gap` (alasan gugur bila total **< $1M** — tepat $1M lolos; tanpa
  bukti tidak pernah menyaring). `MIN_TOTAL_LIQ_USD = 1_000_000`.
- **`meteora_screener.py`**: `scan_best_lane` (+ kwarg `gmgn=True`, diteruskan
  `scan_best_meteora`) menempel likuiditas GMGN **sebelum** alasan gugur
  dihitung, hanya pada kandidat yang sudah lolos F/V/volat/Top10 (baris gugur
  lain tidak membakar request); `row_best_gaps` menambah saringan TERAKHIR
  "likuiditas GMGN < $1M" (urutan: vol-0 → volat 1–10% → F/V → Top10 → GMGN),
  jadi baris < $1M masuk `hidden_rows`/tabel "dilewati" dengan alasan di
  `best_gaps` dan **tidak pernah** membakar kuota Helius; hasil scan kini
  membawa `gmgn_failed` (kandidat tak terbaca — tidak disaring) + entri log
  aktivitas.
- **`rugchecker.py`**: `summarize` (+ `gmgn_total_usd`), `check_tokens`
  (+ `gmgn_by_mint`), `attach_to_rows` (membaca `row["gmgn_liq"]`) — angka
  likuiditas kolom RugCheck kini **total GMGN** (`liquidity_source: "gmgn"`,
  sub-line `$1.90M liq` tanpa penghitung pool, tooltip "likuiditas total
  (sumber: gmgn.ai)"); rincian per-DEX rugchecker.cc tidak lagi ditampilkan,
  share pool di catatan metode tambahan dihitung terhadap total GMGN. Fallback
  ke total per-DEX rugchecker.cc bila angka GMGN tak terbaca. Verdict +
  bendera tetap milik rugchecker.cc.
- **`best_pool_ui.py`**: help tombol + toggle "dilewati" + docstring menyebut
  saringan likuiditas GMGN ≥ $1M; kolom RugCheck tidak berubah strukturnya
  (satu sumber angka kini di summary).
- **`.gitignore`**: `gmgn_liquidity_cache.json`.
- **Tes**: baru `tests/test_gmgn_liquidity.py` (34 tes: parse kedua endpoint,
  batch + fallback rank + cutoff, cache, ambang persis $1M, alasan gugur,
  integrasi `row_best_gaps`, format kolom GMGN/fallback, alur scan offline);
  `ScanLaneTest`/`ScanRugCheckTest` (test_best_pool_scan), `LaneEnrichmentTest`
  (test_best_fv_prefilter), `test_meteora_screener` di-patch offline untuk
  `gmgn_liquidity.attach_total_liquidity`. `python -m unittest discover -s
  tests` → **1093 tes** (1059 baseline + 34 baru), `18 failed + 1 error` —
  **nama kegagalan identik baseline** (diverifikasi via worktree HEAD: 19/19
  sama; bukan regresi).

Catatan operasional: PAID (`98kf…pump`) saat riset = **rank #10 likuiditas**
GMGN; angkanya bergerak cepat (ada transaksi Remove LP), dan field `liquidity`
rank ≠ angka halaman — untuk "grand total" yang user lihat di gmgn.ai sumber
resminya `mutil_window_token_info` (yang dipakai modul ini).

---

# Kegiatan — 16 September 2026 (🏆 Best Pool Meteora: satu lane 24H + 📦 TEMP + kolom RugCheck)

Batch kedua di hari yang sama, sembilan permintaan user sekaligus: **🌊
Watchlist Meteora** dan **🛰 Scan Holder Solana** pindah ke halaman baru **📦
TEMP**; **scan 30 menit dihapus** (sisa 24 jam saja); **Active Range** digeser ke
kanan **Volat** dan **LPs** ke kanan Active Range; **Top10 `>= 20%` dibuang**
(batas pindah ke sisi buang, mengoreksi batch pagi yang `> 20%`); **LPs hijau
bila > 100**; **volat < 1 dan > 10 disembunyikan**; **safeguard Jupiter**
(`base|quote_token_has_critical_warnings=false`) ditambahkan ke query scan; dan
kolom baru **RugCheck** dari **`https://www.rugchecker.cc/api/honeypot/checker`**
(koreksi user: bukan rugcheck.xyz, tanpa API key) **dalam versi yang lebih
ringkas**, plus "metode tambahan" saya sendiri (kedalaman pool, share
likuiditas, konsentrasi pasar) sebagai penjelasan ringkas.

## Yang diubah

- **Halaman & pemindahan**: `app.py` jadi 2 card (🏆 Best Pool + 🧾 Log);
  `temp_ui.py` (baru, 669 baris) + `pages/6_📦_TEMP.py` (wrapper) memuat
  auto-refresh, card 🌊 Watchlist Meteora, dan section 🛰 Scan Holder Solana;
  `page_router` mengenal slug `temp`/`6`. Fungsi yang dipatch tes dipanggil
  lewat modulnya (`wl.`/`hs.`/`hh.`/…) supaya mock suite lama tetap kena.
- **Satu lane**: `scan_best_lane`/`best_filter_by`/`_lane_titles` hanya 24H;
  `normalize_best_lane` memetakan alias lama ke `24h` supaya hasil sesi/cache
  lama dirender ulang dengan aturan baru (bukan dibuang); tombol 30M, kolom
  **Src**, `best_rows_from_lanes()`, `best_pool_scan_30m`, `best_pool_lane`
  dihapus.
- **Saringan** `row_best_gaps` (dieksekusi sebelum `enrich_pools`, kuota Helius
  aman): volat `1%–10%` inklusif (baru: `BEST_VOL_SHOW_MIN/MAX`) → F/V `>= 5×` →
  Top10 `>= 20%` **dibuang** (sebelumnya `> 20%`). V=0 tetap dibuang total.
- **15 kolom** dari satu `_COL_SPEC`: Active Range indeks 4, LPs 5 (hijau
  `#16a34a` bold bila `> 100`), RugCheck 12 sebelum Pool.
- **`rugchecker.py`** (baru): `fetch_raw` (1 request publik, header browser,
  tanpa cookie), `summarize` (RUG/BERISIKO/WASPADA/AMAN/`—` + likuiditas ringkas
  + 3 catatan metode tambahan, `market_cap` dari pool terbesar saja),
  `check_tokens` (paralel 6, cache berkas TTL 1800/300 s + LRU 400),
  `attach_to_rows` (menempel, tidak menyaring), `cell_parts` (angka/sub/tooltip
  — UI tidak merakit ulang teks). Cache `rugchecker_cache.json` di-gitignore.
- **Safeguard Jupiter** di `best_filter_by()` saja; `filter_by()` watchlist
  tetap seperti dulu.
- **Tes**: baru `tests/test_rugchecker.py` (33) + `tests/test_temp_page_ui.py`
  (9); `tests/test_best_pool_scan.py` (80) dan `tests/test_best_fv_prefilter.py`
  (13) diretarget ke satu lane; 4 file tes UI lama dijalankan lewat halaman
  📦 TEMP; pin usang (dua tombol, `Src`, `> 20%`, 11 kolom) dihapus.
  `python -m unittest discover -s tests` → **1059 tes**, `18 failed + 1 error`
  dengan **nama kegagalan identik baseline `dd644c6`** (bukan regresi batch ini).

---

# Kegiatan — 16 September 2026 (🏆 Best Pool Meteora: Top10 di atas 20% dibuang)

Permintaan user: *"scan meteora, TOP 10 diatas 20% jangan ditampilkan lagi"*.
Top10 = kolom **Top10** di card 🏆 Scan Best Pool Meteora, angkanya
`top_holders_pct` dari API Meteora (persen supply token base di 10 wallet
teratas). Sejak hari ini pool yang **terbukti** berkonsentrasi di atas 20%
tidak masuk listing lagi — di kedua tombol (24H dan 30M).

## Yang diubah

- `meteora_screener.py`: konstanta **`BEST_TOP10_MAX_PCT = 20.0`** + helper
  `row_top10_pct()` / `row_top10_over()` / `row_top10_ok()`. Saringannya
  ditempel di **`row_best_gaps()`**, tepat setelah ambang F/V lane lolos, jadi
  ia ikut jalur saringan yang sudah ada: jalan **sebelum** `enrich_pools()`
  (holder pool gugur tidak pernah di-fetch — kuota Helius aman), berlaku untuk
  scan per-lane (`scan_best_lane`) **dan** untuk hasil lama/cache yang
  dirender ulang card, dan kandidat gugur masuk `hidden_rows` dengan alasan
  `"24H: Top10 45% > 20% — holder terpusat"`.
- Keputusan batas: **inklusif** — tepat 20,0% masih tampil (yang dibuang hanya
  yang *di atas* 20%, sesuai kalimat user). Baris **tanpa angka** Top10
  (`None`, hasil scan lama) tetap lolos dan tampil `—`: tanpa data tidak ada
  bukti konsentrasi. (Ini beda dari metrik F/V, yang justru gugur bila angkanya
  hilang — di sana syarat tidak terbukti terpenuhi, di sini larangan tidak
  terbukti kena.)
- `best_pool_ui.py`: tooltip judul card tidak lagi menulis "Top10 bukan syarat
  kelolosan" — sekarang menyebut batas 20% **dari konstanta**
  (`BEST_TOP10_MAX_PCT`), plus status `None`; tooltip sel Top10 berubah dari
  "hanya informasi, bukan saringan lagi sejak 2026-09-11" menjadi saringan
  sejak 2026-09-16; help tombol "▶ N pool dilewati" menyebut dua alasan skip.
  Kolom Top10 itu sendiri tetap ada — yang hilang cuma barisnya.
- Log aktivitas (`scan-best-pool`): angka rekap kini "N gagal saringan
  (F/V/Top10) tanpa scan holder".
- Nama `BEST_TOP10_MAX_PCT` **bukan** rule lama yang dihidupkan balik: saringan
  lama "top 10 holder < 30%" tetap dicabut (2026-09-11) dan `BEST_FEE_RATIO_MIN`
  / `BEST_TOTAL_LPS_MIN` tetap mati — hanya namanya yang dipakai ulang dengan
  angka + arah baru, dan itu dijelaskan di docstring + AGENTS.md.
- Dok: `README.md` (baris tabel syarat kelolosan per lane + penjelasan sebelum
  `enrich_pools` + tabel ambang), `AGENTS.md` (blok "Sumber kebenaran" +
  **Ambang** + blok update paling atas).

## Verifikasi

`python3 -m unittest discover tests` → **1012 tes, 18 failed + 1 error**.
Baseline HEAD `2b273ed` (worktree terpisah) → **1002 tes, 18 failed + 1 error**
dengan **daftar nama kegagalan yang identik** (diff kosong), jadi tidak ada
regresi; 10 tes baru semuanya hijau:

- `BestGatesTest`: batas inklusif 19,999/20,0 lolos vs 20,01/45/100 gugur,
  `None`/`NaN`/string lolos, alasan gap di 24H **dan** 30M, gap Top10 hanya
  muncul kalau F/V sudah lolos, mock `BEST_TOP10_MAX_PCT` mengubah angka teks
  sekaligus kelolosan, dan `filter_best_rows` menghitung gugur Top10 sebagai
  "dilewati" (vol-0 tetap tidak dihitung);
- `ScanLaneTest`: `enrich_pools` tidak pernah menerima pool > 20% (dan yang
  tepat 20% tetap lolos), gugur juga di lane 30M;
- `BestPoolCardTest` (AppTest): baris Top10 45% hilang dari tabel 24H tapi
  muncul di listing "dilewati" dengan teks `gugur: Top10 45% > 20%`, tabel 30M
  tidak menampilkannya sama sekali + caption jumlah ikut berubah.
  `test_saringan_lama_tetap_mati` disesuaikan (Top10 dicabut dari daftar
  saringan mati).

Catatan sesi: sandbox tidak punya egress ke `pool-discovery-api.datapi.meteora.ag`
(TLS dipotong), jadi scan live tidak bisa dijalankan dari sini — filter diverifikasi
dengan payload API yang di-mock, dan akan langsung berlaku saat scan berikutnya di
deployment.

# Kegiatan — 15 September 2026 (🏆 Best Pool: F/V ekstrem, Token = pasangan pool, urut Fee/TVL)

Permintaan user: *"coba cek last scan"* → *"gold menunjukkan 6328266.1 F/V"* →
*"perbaiki"*, disusul *"lalu, juga kolom Token sekarang akan menunjukkan
pasangan pairnya, misal ALLINU/SOL"*, ditutup *"sebentar, kita urutkan fee/TVL
paling besar dulu"* + *"baru perkalian f/v"*.

## 1 · F/V juta-an: angka benar, formatnya yang salah

Pool live yang dimaksud: `GOLD-XAUt0`
(`C4LZ1YcqVbbCh3WqDuig7zQpG24o4UUDXwdJjhoy7PjR`, lane 24H, fee_pct 0,1%,
active TVL 114.004,5 USD, MC ~2,47 juta) — `fee_active_tvl_ratio`
0,013025137688422304 ÷ `volatility` 2,057951587445997e-09 =
**6.329.175,9×**. Angka user (6.328.266,1) adalah sampel lain dari pool yang
sama; keduanya sah. Penyebab tampilannya: `best_pool_ui._fv_cell` menulis
`f"{ratio:.1f}×"` untuk **semua** besaran, jadi rasio jutaan terbaca
`6329175.9×` — tanpa pemisah ribuan, dan digit di belakang koma tidak berarti.

- `meteora_screener.format_fv_ratio()` (baru) + konstanta
  `FV_DISPLAY_DECIMALS = 1` / `FV_PLAIN_MAX = 100.0`: `< 100×` → satu desimal
  (`10.1×`), `>= 100×` → bulat + pemisah ribuan (`6,328,266×`), `inf` → `∞`,
  `None`/NaN → `None` (UI menulis `—`).
- Saringan **tidak berubah**: `row_best_gaps` tetap `24H F/V ≥ 5×` /
  `30M F/V > 1×`; rasio kecil tetap tampil apa adanya, rasio ekstrem hanya
  dirapikan teksnya.
- Tooltip sel: helper baru `_pct_full()` supaya persen sangat kecil tidak
  dibulatkan jadi `0.00%` — sekarang `volatility 2.06e-09%` (3 angka penting
  di bawah 0,005%), itu justru angka yang menjelaskan rasio jutaan.

## 2 · Kolom Token menulis pasangan pool

`meteora_screener.row_pair_label(row)` mengambil nama pool dari API Meteora
(`pool_name`, disimpan `_row_from_pool`) **apa adanya** — uppercase, spasi
ganda dirapatkan, pemisahnya dibiarkan seperti API: `ALLINU/SOL`, `TOK-SOL`.
Pasangan tidak ditebak dari simbol (pool USDC tetap `TOK-USDC`, bukan dipaksa
`TOK/SOL`); kalau `pool_name` kosong, baris pasangan tidak ditampilkan sama
sekali (hasil scan lama) — bukan dikarang. Sel Token kini: `$SIMBOL` → pasangan
pool (`.watchlist-pair`, CSS baru di `dashboard_components.render_styles`) →
alamat mint + link GMGN/Dex. Lebar kolom disesuaikan (`_COL_SPEC`: F/V
0,7 → 1,0; Token 1,4 → 1,45) supaya angka ribuan dan pasangan muat; jumlah
kolom tetap 14.

## 3 · Urutan tabel: Fee/TVL dulu, baru F/V

Permintaan susulan user: *"sebentar, kita urutkan fee/TVL paling besar dulu"*,
*"baru perkalian f/v"* — kunci urut `meteora_screener.sort_best_rows` jadi
**Fee/TVL** (`fee_active_tvl_ratio`) terbesar → **F/V** (`row_fv_ratio`)
terbesar → `row_vol_tvl_ratio` terbesar → dust % MC terkecil (3 desimal
tampilan) → simbol. Sebelumnya F/V yang memimpin (aturan 2026-09-13).

- Fee/TVL **bukan saringan**: `row_best_gaps` tidak disentuh — kelolosan tetap
  `24H F/V ≥ 5×` / `30M F/V > 1×`; Fee/TVL hanya menentukan siapa di atas.
- Baris tanpa angka di sebuah kunci turun ke bawah **di kunci itu** saja:
  Fee/TVL hilang = paling bawah, F/V hilang = di bawah pemilik F/V di kelompok
  Fee/TVL yang sama. ∞ (vol-0) tetap teratas di kelompoknya, tapi tidak lagi
  melompati Fee/TVL yang lebih besar.
- Teks ikut disesuaikan: tooltip Fee/TVL jadi "kunci urut pertama (terbesar
  dulu, permintaan user 2026-09-15), bukan saringan", sel F/V "kunci urut
  kedua", sel Vol "kunci urut ketiga … setelah Fee/TVL & F/V", docstring sel
  judul card "Urutan tiap tabel: Fee/TVL terbesar, lalu F/V terbesar, …".

## Verifikasi

`python3 -m pytest tests -q` → **983 passed / 19 failed**. Baseline HEAD
`8df2ca6` (worktree terpisah) → **973 passed / 19 failed** dengan daftar
kegagalan yang **persis sama**, jadi tidak ada regresi; 10 tes baru
(`FvDisplayTest` 6 tes + 3 AppTest pasangan/format + 1 tes urutan baru
`test_fee_tvl_kunci_pertama_baru_fv`, plus `SortBestRowsTest` dirombak supaya
dua kunci saling berlawanan arah) semuanya hijau. Detail: `AGENTS.md` (blok
paling atas) + `README.md` bagian 🏆 Scan Best Pool Meteora.

# Kegiatan — 15 September 2026 (hapus total halaman 🦅 Robinhood + 📦 temp)

Permintaan user: *"hapus semua yang ada di page temp dan Robinhood, Total
hapus — langsung create pr dan merge jika sudah selesai"*, dan ketika diminta
ketegasan: *"nonaktifkan semua fungsinya, dan juga pagenya, sampai tidak ada
yang jalan"*. Dua halaman beserta semua yang menyangganya (UI, backend, cron,
dokumen) dihapus; app tinggal Solana.

## Yang dihapus

**Halaman** — `pages/8_temp.py`, `pages/6_🦅_Robinhood.py`. `pages/` kini hanya
berisi `5_🧮_Holder.py` (Holder Analytic).

**Card / section** — 🦅 Watchlist Robinhood LP & biasa, 🦅 Scan Best Pool
Krystal, 🦅 Scan Best Robinhood Coin, 🌊 Scan Meteora Pool, 📋 Watchlist
Holder, 📋 Watchlist Meteora, 🚀 Trending/Degen, plus deep-link `?page=temp`
dan `?page=robinhood` (dipantulkan ke dashboard) dan tautan nav di header.
Sesuai jawaban user, **tidak ada yang dipindah** ke dashboard.

**Modul** — `robinhood_watchlist.py`, `robinhood_holders.py`,
`robinhood_best_scan.py`, `krystal_screener.py`, `krystal_pool_ui.py`,
`trending_ui.py`, `temp_ui.py`, `docs/krystal_api.md`, dan 7 file tes
(`test_temp_page`, `test_rh_card_ui`, `test_robinhood_holders`,
`test_robinhood_watchlist`, `test_robinhood_best_scan`, `test_krystal_pool_scan`,
`test_trending_ui`, `test_watchlist_row_ui`).

**Cron** — `scripts/scan_holders.py` tinggal satu lane (Chart LP Meteora):
`RH_FAST_SCAN_INTERVAL_SEC`, `lp_slot_due`, dan pemanggilan
`process_holder_alerts` (alert holder lama) dibuang. `RUN_SCAN_INTERVAL_SEC`
dan `METEORA_LP_SCAN_INTERVAL_SEC` tetap 300 detik; gate run ganda 240 detik
tidak berubah.

**Transport** — Blockscout (holder + link explorer chain 4663) hilang dari
`links.py`, `activity_log.py`, `README.md`, `DEPLOY.md`, `docs/gmgn_api.md`,
dan env `BLOCKSCOUT_API_KEY(S)` di `.github/workflows/daily-effort.yml` +
`daily-effort-5menit.yml`. `robinhood_pool_links_html` (pool Meteora + HawkFi)
dipertahankan sebagai `meteora_pool_links_html` karena masih dipakai
`app.py`.

## Yang dipertahankan (generik / masih dipakai)

`holder_status.MANUAL_SCAN_KEY` (overlay scan manual), `alert_settings.mint_key`
+ `forget_mint_alert` (casefold alamat generik), `watchlist.add_many_to_watchlist`
/ `remove_many_from_watchlist` (public API, tes tetap), `core.get_daily_candles`
(`pre_pump_screener`), dan fixture store-isolation di `test_holder_status`,
`test_store_backup`, `test_watchlist_background_push` yang hanya meminjam nama
berkas `*_robinhood*` untuk membuktikan pemisahan store.

## Verifikasi

`python -m pytest tests -q` → **953 passed / 19 failed**. Baseline `main`
(worktree HEAD `c2b97ce`) → **27 failed / 1234 passed**; ke-19 kegagalan
tersebut persis subset baseline, dan 8 sisanya hilang bersama file tes yang
dihapus — tidak ada kegagalan baru. `test_pre_pump_screener.DashboardSectionRemovedTest`
(daftar `pages/*.py`) dan `test_scan_holders.KonstantaTest` ikut disesuaikan.

Detail: `AGENTS.md` (blok paling atas) + `README.md` bagian *Halaman*.

# Kegiatan — 14 September 2026 malam lanjutan 2 (kolom Active Range)

Permintaan user: *"ok tambahkan Active Range, tapi % saja, misal -30% +40 atau
bagaimana terserah kamu agar gampang saya baca"* — lanjutan dari penjelasan
cara membaca active range pool DLMM Meteora.

## Apa itu Active Range (dan dari mana angkanya)

DLMM = tangga **bin**; satu bin = satu harga, jarak antar bin = `bin_step`
basis point (rumus resmi `P_i = (1 + bin_step/10000)^i`, docs.meteora.ag →
DLMM Formulas). Listing API yang sudah dipakai card ini
(`pool-discovery-api.datapi.meteora.ag/pools`) mengirim tiga harga kuncinya:
`pool_price` (**bin aktif** = harga pool sekarang) serta `min_price` /
`max_price` (bin berisi likuiditas terendah/tertinggi = tepi **active range**).

Terverifikasi 2026-09-14 pada tiga pool live dengan `bin_step` berbeda —
ketiga harga cocok dengan `P_i` sampai **0,000 ppm**, jadi `min_price` /
`max_price` memang tepi bin, **bukan** high/low 24 jam:

| Pool | bin_step | pool_price | min_price | max_price | Active Range |
| --- | --- | --- | --- | --- | --- |
| CATE-USDC | 20 (0,2%) | 0.0743180 | 0.0486561 | 0.0884272 | `-34.5% / +19.0%` (300 bin) |
| biketyson-SOL | 100 (1%) | 6.4807e-05 | 6.0447e-05 | 7.0177e-05 | `-6.7% / +8.3%` (16 bin) |
| ROUTER-SOL | 250 (2,5%) | 1.49369e-05 | 1.49369e-05 | 1.56931e-05 | `0.0% / +5.1%` (3 bin) |

## Yang diubah

- **`meteora_screener.py`** — `_row_from_pool()` menyimpan `pool_price`,
  `range_min_price`, `range_max_price`, dan `bin_step` (helper baru
  `dlmm_bin_step()`, aman untuk `dlmm_params` `None` / bukan dict). Helper
  baru: `active_range_pct()` (turun/naik **diukur dari harga sekarang**:
  harga × (1 − turun/100) = tepi bawah), `active_range_width_pct()`,
  `active_range_bins()` (jumlah bin dari `bin_step`, untuk tooltip),
  `_pct_signed()`, `active_range_text()`.
- **`best_pool_ui.py`** — kolom **Active Range** di kanan **A.TVL**
  (`_COL_SPEC` + `_lane_titles` + `_render_best_table`; Pool dan ⭐ geser ke
  indeks 12/13). Builder sel baru `_active_range_cell()` + `_range_part()`
  (turun merah, naik hijau, `0.0%` tanpa tanda/warna) + `_price_or_dash()`.
  Tooltip sel = harga bin mentah, lebar range, jumlah bin, `bin_step`, dan
  penegas "bukan saringan". Tooltip judul card ikut menjelaskan.
- **`temp_ui.py`** — card 🌊 Scan Meteora Pool (halaman temp) memakai kolom +
  builder yang **sama** (di kanan Volatility; MC/TVL/Dust/Dust %MC/Pool/⭐
  geser satu kolom) supaya satu angka tidak punya dua format di dua card.
- **README.md** — bullet kolom listing Best Pool + bagian Scan Meteora Pool.

## Kenapa persen, bukan harga

Harga bin memecoin sering 1e-05 dan tidak terbaca sekilas; yang dipakai LP
untuk mengambil keputusan adalah **berapa persen harga boleh bergerak sebelum
keluar range** — di luar itu posisi berhenti menghasilkan fee. `0.0%` =
harga persis di tepi range (kasus nyata ROUTER-SOL: `min_price` ==
`pool_price`, sedikit turun langsung keluar). Data lama di `session_state`
yang belum menyimpan field-nya menulis `—`, bukan `-0.0% / +0.0%` palsu.

## Verifikasi

- Tes baru `tests/test_meteora_active_range.py` — **19 lulus**: angka tiga
  pool live, persen bisa dikembalikan persis ke harga bin, tepi tertukar
  tetap aman, data hilang → `—`, `bin_step` hilang tidak mengubah persen,
  format sel (warna + `0.0%`), kolom/judul sinkron (`len(_lane_titles) ==
  len(_COL_SPEC)`, judul ke-8 = "Active Range"), dan dua render AppTest
  (tabel 🏆 Best Pool + tabel 🌊 Scan Meteora di /temp) yang membuktikan
  `-34.5% / +19.0%`, `0.0% / +5.1%`, dan `lebar 81.7%` benar-benar tampil
  serta tombol ⭐ tidak bergeser kolom.
- `python -m unittest tests.test_best_pool_scan tests.test_temp_page
  tests.test_best_fv_prefilter` → **83 lulus** (baseline-nya juga lulus).
- Suite penuh `python -m unittest discover -s tests -t .` → **1261 tes**
  (+19 dari tes baru). Daftar tes gagal **identik byte-per-byte** dengan
  baseline commit `6932c3a1` (md5 `9720d6c6…` sama, 23 FAIL + 7 ERROR
  keduanya; baseline dijalankan dari salinan bersih `git archive HEAD`), jadi
  30 kegagalan itu warisan lama, bukan regresi perubahan ini.

# Kegiatan — 14 September 2026 malam lanjutan (F/V · Fee/TVL · Volat: hijau tua menyala)

Permintaan user: *"F/V · Fee/TVL · Volat — yang paling tinggi nilainya kasih
warna hijau menyala, hijau tua menyala"*. Dikonfirmasi ke user dan
keputusannya: **ketiganya** — sel F/V tertinggi, Fee/TVL tertinggi, dan
volatility terbesar — memakai satu warna **hijau tua menyala** di tabel
utama tiap lane (card 🏆 Meteora 24H/30M dan card 🦅 Krystal).

## Yang diubah

- **`TOP_HIGHLIGHT_COLOR` diganti `#00c853` → `#15803d`** (hijau tua
  menyala) di `best_pool_ui.py` dan `krystal_pool_ui.py` (salinan).
- **Kolom Fee/TVL ikut dicari tertingginya**: `_table_tops()` kini
  mengembalikan 3 nilai `(volatility terbesar, F/V tertinggi, Fee/TVL
  tertinggi)`; sel Fee/TVL tertinggi dibungkus `_top_span()` + tooltip
  "— Fee/TVL tertinggi di tabel ini". Tiap kolom dicari maksimumnya
  sendiri-sendiri, jadi baris pemegang Fee/TVL tertinggi boleh berbeda dari
  pemegang F/V tertinggi. Seri di puncak ikut ditandai semua; tabel
  "dilewati" tetap tanpa sorot.
- Tooltip judul kedua card + docstring menyebut **hijau tua menyala** dan
  Fee/TVL ikut ditandai.
- Tes: `test_best_pool_scan.py` + `test_krystal_pool_scan.py` — Fee/TVL
  tertinggi tersorot & yang bukan tidak; Fee/TVL teratas boleh di baris lain
  dari F/V teratas; seri Fee/TVL semua ditandai; lane 30M sel OK + Fee/TVL
  tersorot; tabel dilewati bebas marker sorotan (asersi memakai string span
  lengkap, bukan hex mentah, karena CSS global halaman sudah memakai hex yang
  sama untuk class lain).

## Verifikasi

- `python -m pytest tests/test_best_pool_scan.py tests/test_krystal_pool_scan.py -q`
  → **114 lulus** (+17 subtest).
- Suite penuh: **1215 lulus, 27 gagal** — file yang gagal identik dengan
  baseline (dibuktikan lewat worktree commit dasar `d764232`), jadi bukan
  regresi perubahan ini.

# Kegiatan — 14 September 2026 (🦅 Scan Best Pool Krystal + cache hasil scan)

Permintaan user: *"buat card 🦅 Scan Best Pool Krystal (Robinhood Chain, chain
id 4663)"* — ditempatkan **tepat di bawah card 🏆 Scan Best Pool Meteora**,
dengan **reproduksi rule F/V persis** seperti card Meteora (F = fee 24 jam ÷
TVL × 100, V = volatility 24 candle hourly, gate 24H `F/V ≥ 5×` inklusif,
V = 0 dibuang dari listing), lane **24H saja** dulu, ⭐ ke Watchlist Robinhood
LP, dan **persistensi hasil sejak awal** supaya refresh browser tidak
menghapus tabel.

## Pekerjaan gantung sesi sebelumnya (commit f9c1ec8)

Commit `f9c1ec8` *"scan: hasil meteora tahan refresh browser (cache file
lokal)"* **tidak ada di clone ini** — branch `arena/01a09d72-wallet-depth`
sudah ada di origin tetapi isinya identik dengan `main` (beda 1 baris di
`watchlist.json`), sha itu tidak ada di reflog, di semua branch remote, di
`git fsck --lost-found`, maupun di GitHub (`gh api .../commits/f9c1ec8…` →
422 *No commit found*). Jadi commit itu ikut hilang bersama clone sesi itu.
**Dibangun ulang** dalam sesi ini sebagai modul `scan_result_cache.py`
(`save_result` / `load_result` / `restore_into_session`), dipasang ke card 🏆
Meteora **dan** card Krystal baru, lengkap dengan tes + fixture isolasi
(`_iso_scan_cache` di `tests/conftest.py`, kill-switch `SCAN_CACHE=0` di
`tests/__init__.py`) — jadi "refresh browser tidak menghilangkan hasil"
benar-benar jalan, bukan cuma janji di catatan.

## Yang dikerjakan

### 1. Probe Krystal (langkah wajib #2)

| hal | hasil |
|---|---|
| `GET cloud-api.krystal.app/v1/chains` (publik, 0 unit) | ✅ Robinhood `id 4663` ada, protokol `["ramsescl","uniswapv4","uniswapv3","uniswapv2"]` |
| `GET /v1/pools?chainId=robinhood@4663` tanpa key | ✅ `{"error":"An API Key is required. Checkout https://cloud.krystal.app"}` |
| `GET /v1/pools` **dengan key** | ⏳ belum bisa dari sandbox: egress hanya mengizinkan PyPI/GitHub, dan `KC-APIKey` wajib di **header** (`securityDefinitions.ApiKeyAuth` = `apiKey` / `in: header`) — tidak ada alat HTTP di sini yang bisa menyetel header. Perintah probe + yang perlu dicek ada di `docs/krystal_api.md`. |
| jalur cadangan publik `api.krystal.app/all/v1/lp_explorer/configs` | ✅ chain 4663 = Robinhood dengan 4 protokol yang sama |
| jalur cadangan publik `.../lp_explorer/top_pools?chainId=4663` | ❌ `{"error":"rpc error: code = Unknown desc = chain id 4663 not supported"}` — tidak bisa dipakai |

Karena itu normalisasi ditulis **defensif**: `tvl` / `stats24h.{fee,volume,apr}`
(pola dokumentasi swagger + contoh landing page) dibaca toleran terhadap
`stats24h` / `stats_24h` / `24h`, payload diterima baik sebagai list maupun
`{"data": [...]}`, dan field yang tidak terbaca jadi `None` (gugur "metrik
tidak tersedia"), bukan `0`.

### 2. Modul baru

- **`krystal_screener.py`** — transport (timeout 25 dtk, error jadi pesan
  card), katalog chain publik, normalisasi payload, `row_krystal_gaps` (gate
  24H `F/V ≥ 5×`, V=0 dibuang via `row_volatility_zero`), `volatility_from_candles`
  (range 24 candle), `enrich_volatility` (sebelum holder — murah),
  `enrich_holders` (Blockscout FULL 100.000 wallet, **tanpa budget waktu**),
  `sort_krystal_rows` (F/V → vol/TVL → dust → simbol), `scan_krystal_lane`.
- **`krystal_pool_ui.py`** — card border container, tooltip judul berisi
  seluruh rule, 4 kolom inti di depan, sorot hijau menyala `#00c853` untuk F/V
  tertinggi & volatility terbesar (seri ikut semua, tabel dilewati tidak
  ditandai), pill hitungan, tombol **▶ N pool dilewati**, ⭐ → Watchlist
  Robinhood LP (`background=True`), pesan "pasang KRYSTAL_API_KEY" bila key
  belum ada.
- **`scan_result_cache.py`** — cache berkas `.scan_cache/<key>.json`
  (git-ignored, tulis atomik `os.replace`, NaN dinormalkan, peta wallet
  `wallet_snapshot`/`chrono_snapshot` dibuang, tanpa pernah melempar).

### 3. Perubahan menyilang (umum, bukan rule lintas-fungsi)

- **`core.get_hourly_candles(..., network=…)`** — URL GeckoTerminal tidak lagi
  hardcode `solana`: `GECKOTERMINAL_OHLCV_URL_TEMPLATE` + `normalize_geckoterminal_network`
  (alias `rh`/`robinhood`/`4663` → `robinhood`; nilai asing jatuh ke `solana`,
  karakter berbahaya dibuang). `get_daily_candles` ikut meneruskan network.
  Konstanta lama `GECKOTERMINAL_OHLCV_URL` dipertahankan (template Solana).
- **`links.py`** — `blockscout_address_url()` + `robinhood_pool_links_html()`
  (tautan explorer alamat **pool** Robinhood; `pool_links_html` tetap
  Meteora/HawkFi karena alamat Krystal tidak punya halaman itu).
- **`best_pool_ui.py`** — hasil scan tiap lane disimpan/dipulihkan lewat
  `scan_result_cache` (pengganti commit yang hilang). Rule, urutan, dan
  saringan Meteora **tidak disentuh**.
- **`app.py`** — `render_krystal_pool_scan()` dipanggil setelah
  `render_best_pool_scan()` (full-width, sebelum 🛰 Scan Holder).

## Verifikasi

```
python -m pytest tests/test_krystal_pool_scan.py tests/test_core_candles.py -q
  -> 80 tes + 18 subtest lulus
python -m pytest tests/test_best_pool_scan.py tests/test_best_fv_prefilter.py \
    tests/test_krystal_pool_scan.py tests/test_core_candles.py -q
  -> 146 tes + 41 subtest lulus
python -m pytest tests/ -q
  -> 34 gagal, 1198 lulus   (baseline 34 gagal / 1140 lulus)
```

34 merah = **persis** daftar lama (alert toggle per token, lp_card_ui,
manual_scan_alerts, meteora_screener, rh_card_ui, scan_holders, temp_page,
watchlist_row_ui) — tidak ada kegagalan baru; yang hijau naik 58.

Satu tes lama ikut disesuaikan karena **halaman utama sekarang memuat card
kedua**: `test_label_vol_dan_tooltip_fee_mengikuti_lane` menyaring body ke
card Meteora saja (tooltip card Krystal memang menyebut "fee 24 jam", jadi
 tanpa pembatasan itu asersi "tabel 30M tidak boleh menulis *fee 24 jam*"
 akan kena teks card lain).

## Catatan untuk sesi berikutnya

- **Probe live `GET /v1/pools` dengan key masih perlu dilakukan user** (satu
  `curl` di mesin sendiri, perintahnya ada di `docs/krystal_api.md`). Bila
  nama field Krystal ternyata berbeda, cukup menyesuaikan `normalize_pool` +
  fixture `_pool()` di tes.
- `KRYSTAL_API_KEY` sudah ditaruh di `.streamlit/secrets.toml` (git-ignored)
  dan diminta juga untuk Streamlit Cloud → Settings → Secrets.
- Lane **30M** belum ada (menunggu Krystal menyediakan window fee lebih
  pendek dari 24 jam); `KRYSTAL_LANES` sudah disiapkan tinggal ditambah.

# Kegiatan — 14 September 2026 malam (🏆 Scan Best Pool: tata kolom + sorot tertinggi)

Permintaan user: *"kita tata kolomnya baik untuk 24jam maupun 30menit —
Dust hapus — Token F/V Volat Dust %MC, 4 kolom ini diletakkan paling awal —
lalu tandai volatility paling besar di scan tersebut menjadi warna hijau
menyala — lalu tandai f/v tertinggi tersebut menjadi warna hijau menyala"*.

## Yang diubah

- **Susunan kolom kedua tabel ditata ulang** (`best_pool_ui._COL_SPEC`):
  Token · **F/V** · **Volat** · **Dust %MC** di paling depan (4 kolom inti),
  lalu MC · A.TVL · Fee/TVL · Vol · Top10 · LPs · Pool · ⭐. Kolom **Dust**
  (jumlah wallet dust) **dihapus** — dari tabel utama maupun tabel
  "dilewati" 24H.
- **Judul kolom volume mengikuti lane** (`_lane_titles()`): 24H "Vol 24h",
  30M **"Vol 30m"** — sebelumnya tabel 30M salah memakai "Vol 24h", dan
  tooltip fee/volume menulis "24 jam" padahal angkanya window 30 menit dari
  API Meteora. Sekarang tooltip ikut lane ("fee 30 menit", "volume 30
  menit").
- **Sorot hijau menyala + bold** (`TOP_HIGHLIGHT_COLOR = #00c853`,
  `_top_span()`): sel **volatility terbesar** dan sel **F/V tertinggi** di
  tabel utama tiap lane (dicari `_table_tops()`). Lane 24H menandai sel
  angkanya (`10,1×`); lane 30M menandai sel **OK**-nya (OK lain tetap hijau
  `#16a34a`). Kalau seri di puncak, semuanya ikut ditandai — tidak ada
  pemenang acak; baris tanpa angka valid diabaikan. Tabel "dilewati" 24H
  **tidak** ditandai (`mark_tops=False`) supaya tidak berbenturan dengan
  anotasi merah gugur-ambang. Tooltip sel terseorot diberi catatan
  "— volatility terbesar / F/V tertinggi di tabel ini"; tooltip judul card
  ikut menjelaskannya.
- Sengaja **tidak diubah**: urutan baris (F/V → vol/active TVL → dust),
  saringan lane, pembuangan pool volatility 0, rule 30M-OK, toggle
  disembunyikan, dan card-card lain. *(Urutan barisnya digantikan 2026-09-15:
  Fee/TVL jadi kunci pertama, F/V kunci kedua — lihat entri paling atas.)*

## Verifikasi

`python -m pytest tests/test_best_pool_scan.py tests/test_best_fv_prefilter.py -q`
→ **64 tes + 23 subtest lulus** (sebelumnya 58 + 23; +6 tes baru: urutan 4
kolom inti + kolom Dust hilang, label/tooltip mengikuti lane, sorot neon
angka 24H, OK tertinggi 30M, seri di puncak semuanya ditandai, tabel
dilewati tanpa sorot). Suite penuh `python -m pytest tests/ -q` → **34
gagal, 1140 lulus** — 34 merah persis baseline (regular Scan Meteora / temp
page / watchlist row / scan_holders / Robinhood), tidak ada kegagalan baru.

# Kegiatan — 14 September 2026 lanjutan (🏆 Scan Best Pool: volatility 0 dihapus dari listing)

Permintaan user: *"kita lanjutkan, jika volatility 0 jangan tampilkan, karena
tidak ada pergerakan disitu"*. Perubahan paginya baru membuat pool vol-0
**gugur** saringan (tapi barisnya masih terlihat sebagai ∞ di tabel
"dilewati" 24H); sekarang pool tanpa pergerakan **hilang total dari card**.

## Yang diubah

- `meteora_screener.row_volatility_zero()` (baru): True hanya untuk
  volatility **persis 0** (finite). `None`/hilang/negatif/nonfinite BUKAN
  nol — tetap masuk listing "dilewati" dengan alasan metriknya, jadi data
  rusak tidak pernah dibuang diam-diam.
- `meteora_screener.scan_best_lane()`: kandidat gugur ber-volatility-0 tidak
  lagi masuk `hidden_rows` maupun `hidden_metric`; jumlahnya dicatat di
  field baru **`dropped_volatility`** (audit) dan disebut di activity log
  (`"… · N pool volatility 0 dibuang"`). `filter_best_rows()` mengecualikan
  vol-0 dari hitungan sehingga `hidden_metric == len(hidden_rows)` selalu
  berlaku. Gate `row_best_gaps` TIDAK berubah — pool vol-0 tetap gugur
  sebelum fetch holder dengan alasan "volatility 0 — F/V tidak terukur",
  jadi kuota Helius tetap aman.
- `best_pool_ui.render_best_pool_scan()`: baris vol-0 disaring ulang di
  render, dari `rows` **maupun** `hidden_rows`, sehingga hasil scan LAMA di
  `session_state` — era sebelum ∞ gugur (baris ∞ masih di tabel lolos) atau
  era hidden yang masih menghitung vol-0 — ikut bersih tanpa scan ulang.
  `hidden` kini dihitung `len(hidden_rows)` pasca-filter (bukan counter
  mentah `hidden_metric`), jadi pill "N disembunyikan", tombol ▶, dan
  caption "N dilewati" selalu cocok dengan isi tabel. Tooltip judul +
  docstring modul ikut diperbarui.
- Sengaja **tidak diubah**: `row_best_gaps` (gate), `row_fv_ratio` /
  `sort_best_rows` (kontrak ∞ dipertahankan walau card tidak pernah lagi
  meneruskan barisnya), rule 30M lain, Scan Meteora regular (temp page),
  kolom volatility Watchlist Meteora.

## Verifikasi

`python -m pytest tests/test_best_pool_scan.py tests/test_best_fv_prefilter.py -q`
→ **58 tes + 23 subtest lulus** (sebelumnya 51 + 20; +7 tes baru: vol-0 hanya
0 persis, dibuang tanpa `enrich_pools` di kedua lane, tidak tampil & tidak
dihitung di listing dilewati 24H (AppTest), baris vol-0 warisan sesi lama
ikut hilang). Suite penuh `python -m pytest tests/ -q` → **34 gagal, 1134
lulus** — 34 merah persis baseline, diverifikasi dengan `git stash`: daftar
file FAILED identik sebelum/sesudah perubahan, tidak ada kegagalan baru.

# Kegiatan — 14 September 2026 (🏆 Scan Best Pool: ∞ gugur + 30M tulis OK, gagal tidak tampil)

Permintaan user: *"syarat F/V > 1× … perbaiki scan meteora pool pada bagian
tersebut, kok masih ada yang seperti ini?"* dengan contoh **∞** (baris ∞
masih muncul di tabel 30M padahal syaratnya F/V > 1×), lalu *"kalau di M30,
jika syarat terpenuhi, tulis OK · jangan tampilkan yang tidak terpenuhi"*.

## Yang diubah

- `meteora_screener.row_best_gaps`: volatility 0 → **gugur di kedua lane**
  dengan alasan `"24H/30M: volatility 0 — F/V tidak terukur"`. Sebelumnya
  V=0 dengan F>0 lolos dan tampil sebagai ∞ — ∞ bukan kelolosan, pool tanpa
  volatility tidak bisa membuktikan F > V. `row_fv_ratio` / `sort_best_rows`
  tidak diubah: ∞ tetap urut teratas bila muncul di tabel disembunyikan.
- `best_pool_ui._fv_cell`: lane **30M** baris lolos = **OK** hijau
  (`#16a34a`, sub `syarat F/V > 1× terpenuhi`); angka quotient tetap di
  tooltip sel dan tetap kunci urut + saringan. 24H tetap angka `N,N×`.
- `best_pool_ui.render_best_pool_scan`: lane **30M** tidak menampilkan
  kandidat gagal sama sekali — `showing_hidden` dipaksa False, toggle
  `best-pool-toggle-hidden-30m` + pill "N disembunyikan" tidak dirender,
  caption jadi `"N pool 30M tampil · listing M pool."` (tanpa "dilewati").
  24H tidak berubah.
- Tooltip judul + docstring `meteora_screener` / `best_pool_ui` / `README.md`
  / `AGENTS.md` ikut diperbarui (angka ambang tetap dari konstanta).

## Verifikasi

`python -m pytest tests/test_best_pool_scan.py tests/test_best_fv_prefilter.py -q`
→ **51 tes + 20 subtest lulus** (streamlit + matplotlib terpasang, AppTest
jalan). Suite penuh `python -m pytest tests/ -q` → **34 gagal, 1127 lulus** —
persis baseline sebelum perubahan (34 merah lama di regular Scan Meteora /
temp page / watchlist row / scan_holders / Robinhood; tidak ada kegagalan
baru, Best Pool semua hijau).

# Kegiatan — 13 September 2026 (🏆 Scan Best Pool: tombol 24H & 30M dipisah + tabel sendiri)

Permintaan user: *"kayaknya untuk timeframe 30m harus kita pisah tombol
deteksinya dan tabel serta fungsi fee/v lebih besar … jadi di scan meteora
pool, kita akan punya 2 tombol 24H dan 30M. lalu tombol scan 24H kita
prioritaskan di 24H yang fee/v >= 5x untuk di scan detail lainnya, jika kurang
dari itu langsung skip. tombol scan 30M kita prioritaskan yang fee/v nya lebih
besar, jika lebih kecil langsung skip"*.

Sebelumnya satu tombol menarik **dua lane sekaligus** (24H + 30M) lalu
meleburnya jadi satu tabel dengan kolom **Src**; yang membuat tabel terlihat
"aneh" adalah kolom F/V yang mencampur quotient dari dua window berbeda —
angka `∞` (V=0) dan `1178769,2×` (V nyaris nol) muncul di baris yang sama
dengan baris 24H ber-F/V 6×. Sekarang tiap timeframe punya tombol, saringan,
tabel, dan session key sendiri.

## Yang diubah

- `meteora_screener.scan_best_lane(lane, ...)` — fungsi baru, **satu lane per
  panggilan**: `fetch_best_pools(timeframe=lane)` saja → `drop_quote_rows` →
  saringan lane → **hanya yang lolos** yang masuk `enrich_pools()` →
  `sort_best_rows`. `scan_best_meteora(timeframe=...)` jadi wrapper tipis yang
  meneruskan lane (dulu kwarg itu label saja, kedua lane selalu diambil);
  `timeframe="both"` = perilaku lama, tetap ada untuk compat.
- Ambang per lane dibaca lewat konstanta: `BEST_FV_24H_MIN = 5.0`
  (**inklusif**, 5× persis lolos) dan konstanta baru `BEST_FV_30M_MIN = 1.0`
  (**strict** — "fee/v nya lebih besar": F == V tepat 1× **gugur**).
  `lane_fv_min()` / `lane_fv_inclusive()` / `lane_fv_sign()` /
  `best_lane_gate_label()` membacanya **saat dipanggil**, dan
  `row_fv_ratio()` = quotient yang sama untuk saringan + urutan + kolom F/V
  card (satu sumber angka, tidak ada lagi "angka filter beda dengan angka card").
- Urutan tiap tabel: **F/V terbesar** → volume/active TVL → dust %MC terkecil
  → simbol. `∞` (volatility 0, fee positif) paling atas; baris tanpa metrik
  F/V paling bawah walau dust-nya nol. *(Digantikan 2026-09-15: Fee/TVL
  terbesar jadi kunci pertama, F/V kunci kedua — lihat entri paling atas.)*
- `best_pool_ui`: dua tombol `best-pool-scan-24h` / `best-pool-scan-30m`
  (label **🏆 Scan Best Pool 24H + Holder** / **30M**, ambang di tooltip
  `help`), hasil di `best_pool_scan_24h` / `best_pool_scan_30m`, toggle
  disembunyikan per lane (`best-pool-toggle-hidden-24h` / `-30m`,
  prefix ⭐ `best-pool-24h-star-…`), lane aktif di `best_pool_lane` dengan
  tombol **◼/◻** untuk berpindah lihat tanpa scan ulang. Kolom **Src**
  dihapus; **F/V** jadi kolom metrik pertama dengan baris kecil
  `syarat F/V ≥ 5×` (atau `gugur: F/V < 5×` merah di tabel disembunyikan);
  pill kepala card = lane aktif + ambangnya.
- `_split_legacy_result()`: sesi yang masih menyimpan hasil lama
  (`best_pool_scan`, dua lane campur) dipecah sekali saat render, jadi
  listing tidak hilang saat update diturunkan.

## Verifikasi

`python -m pytest tests/ -q` → **34 gagal, 1125 lulus, 36 subtest**
(baseline sebelum perubahan ini: **62 gagal, 1097 lulus** — 28 tes kadaluarsa
dari kriteria 2026-09-13 pagi diperbaiki, dan **tidak ada satu pun kegagalan
baru**: `comm -13 sebelum sesudah` pada daftar `FAILED` kosong). 34 yang
tersisa semuanya sudah merah sebelum perubahan ini dan bukan card Best Pool
(regular Scan Meteora / temp page / watchlist row / scan_holders / Robinhood). Tes fokus Best Pool semuanya hijau:
`tests/test_best_pool_scan.py` + `tests/test_best_fv_prefilter.py` =
**49 tes + 18 subtest lulus**.

`tests/test_best_fv_prefilter.py` ditulis ulang jadi tes batas + lane:
`LaneGateBoundaryTest` (tabel 14 kasus batas 5×/1×, `lane=` meng-override
`timeframe` baris, teks gap ikut konstanta), `LaneEnrichmentTest` (tombol 24H
hanya memperkaya `PASS`; 30M memakai strict `>`; satu tombol = satu
`timeframe` di API; semua gugur → `enrich_pools` tidak dipanggil sama sekali;
urutan ∞ → 20× → 5×), `LegacyBothLaneTest` (compat `both` tetap dua record).
`tests/test_best_pool_scan.py` direstruktur: `LaneRuleTest` (konstanta +
alias + label), `BestGatesTest` termasuk **`test_saringan_lama_tetap_mati`**
(dust/volume/volatility/tier fee/Top10/LPs tidak boleh balik),
`SortBestRowsTest` (F/V kunci pertama, ∞ di atas, tanpa metrik di bawah),
`ScanLaneTest` (fetch per lane, skip sebelum Helius, error API, pool quote
dibuang, baris tanpa bukti holder tetap tampil), dan `BestPoolCardTest`
(AppTest halaman utama: dua tombol + tidak ada `best-pool-scan-now`, tombol
30M hanya memanggil lane 30m, tabel 24H tidak memuat baris 30M, kolom Src
hilang, F/V di depan, toggle disembunyikan per lane, migrasi hasil lama,
rule di tooltip bukan caption, ambang tooltip ikut konstanta).

# Kegiatan — 13 September 2026 (kolom tabel "Awal Masuk" = dust %MC saat token masuk watchlist)

Permintaan user: *"Saat masuk watchlist (13 Sep 07:00 WIB): dust 0.103% MC —
ini tambakan ke kolom table saja dengan caption Awal Masuk"*.

Angka yang sehari sebelumnya baru muncul di baris pertama expander 📈
(`baseline_note()`, entri di bawah) naik ke tabel — terlihat tanpa klik,
berdiri di sebelah kolom **Hold %MC**. Prinsip yang dijaga: TIDAK ada
definisi baseline kedua; sel membaca hasil `added_baseline()` yang sama
persis dengan kolom "Sejak masuk", caption expander, dan patokan notifikasi
⚡ EARLY DUMP 0,02%.

## Bentuk baru

- `watchlist_detail.baseline_cell(baseline, current_pct=…)` →
  `{value, sub, note}`: `value` dust % MC **3 desimal** (`"0.103%"`), `sub`
  waktu titik pembandingnya (`"13 Sep 07:00 WIB"`) + penanda varian fallback
  (` · titik pertama` bila tanggal `added` tak terbaca, ` · belum ada scan
  sejak masuk` bila terpaksa memakai titik sebelum tanggal masuk), `note`
  kalimat lengkap `baseline_note()` untuk atribut `title` sel (hover). Tanpa
  titik layak → `—` + `belum ada scan layak`.
- Kolom ke-4 dari **8** di ketiga tabel watchlist —
  `app._render_lp_row` (🌊 Watchlist Meteora, header `_render_lp_card`),
  `dashboard_components._render_rh_row` (🦅 Robinhood LP/biasa, varian
  reguler ikut karena satu renderer), `temp_ui.render_temp` (📋 watchlist
  Holder; di sana kolomnya di kiri "Sejak masuk"). Aksi 🧮/🔔/📋/✕ (dan
  🌊/✕ di temp) bergeser satu kolom; lebar grid LP/RH/temp disesuaikan
  (`[1.62, 0.72, 0.9, 0.8, …]` LP, `[1.62, 0.75, 0.9, 0.8, …]` RH,
  `[1.5, 0.8, 0.85, 0.8, 0.95, …]` temp).
- `LP_CARD_TOOLTIP` + `RH_CARD_TOOLTIP`/`RH_REGULAR_CARD_TOOLTIP` menyebut
  kolom baru ini = angka patokan rule ⚡ (hover sel untuk kalimat lengkap).

## Verifikasi

`python -m unittest discover -s tests -t .` → **Ran 1156 tests, OK**
(baseline sebelumnya 1150). Tes baru: `BaselineCellTest` (5) di
`tests/test_watchlist_detail.py` — nilai 3 desimal + waktu, tooltip
"sekarang …% MC"/"patokan notif ⚡ EARLY DUMP", dua varian fallback, tanpa
titik layak, input kosong tidak meledak. Assert kolom di AppTest:
`tests/test_lp_card_ui.py` (`test_detail_menampilkan_dust_saat_masuk_watchlist`
+ `>Awal Masuk</div>`, nilai sel 0,620%/0,300%, `title="📌 Saat masuk
watchlist…" + "· sekarang 0.610% MC (+0.310 pp)"), `tests/test_rh_card_ui.py`
(`>Awal Masuk</div>` + `title="📌 Titik pertama yang tercatat` — varian tanpa
tanggal `added`), tes per token baru di `tests/test_watchlist_row_ui.py`
(`test_kolom_awal_masuk_menampilkan_dust_saat_ditambahkan`: DRP 0,400% /
RSE 0,200% / SYN 0,300%, angka baris SYN tetap 0,71%), dan hitungan kolom di
`tests/test_temp_page.py` (dua tabel temp berkolom "Awal Masuk").

Teks yang ikut disinkronkan: `README.md` (🌊 Watchlist Meteora + Kolom
"Sejak masuk"), `AGENTS.md` (bulket `watchlist_detail.py` + spec blok baris
watchlist), entri `docs/PROGRESS.md`.

# Kegiatan — 13 September 2026 (detail watchlist: dust % MC saat token pertama masuk watchlist)

Permintaan user: *"pada detail watchlist, juga tunjukkan pertama kali saya
menambahkan ke watchlist, posisi % dust di berapa %"*.

## Angka yang sudah dihitung, tinggal ditampilkan

`watchlist_detail.py` sudah punya pembanding "sejak masuk" — `anchor_point()`
memilih titik **pertama pada/setelah** tanggal `added` yang datanya layak.
Titik yang sama juga dipakai notifikasi ⚡ EARLY DUMP sebagai patokan
(`telegram_alerts.add_baseline_for_mint`), jadi yang dikerjakan tinggal
menampilkannya:

- `added_baseline(meta, points)` → `{pct, count, ts, added_ts, fallback}`;
  titik tidak layak (sampel < 40 wallet / `truncated`) tidak pernah jadi
  patokan.
- `baseline_note(baseline, current_pct=…)` → satu baris caption:

  ```text
  📌 Saat masuk watchlist (10 Sep 12:05 WIB): dust 0.012% MC · sekarang
  0.036% MC (+0.024 pp) — patokan notif ⚡ EARLY DUMP (tiap +0.02% dihitung
  dari angka ini).
  ```

  Varian fallback tetap jujur, tidak menyamar sebagai "sejak masuk":
  `Titik pertama yang tercatat` (tanggal `added` tidak terbaca),
  `Titik pertama yang tersedia` (belum ada scan sejak tanggal masuk), atau
  "belum bisa dihitung" (tanpa titik layak sama sekali).

## Di mana muncul

Baris **pertama** expander 📈 Grafik perubahan dust holder tiap baris —
`dashboard_components._render_dust_change(..., meta=, current_pct=)` — jadi
keempat lane ikut: 🌊 Watchlist Meteora (`app.py`), 🦅 Watchlist Robinhood
LP/biasa (`dashboard_components._render_rh_row`; baris RH kini membawa
`added`), dan 📋 watchlist Holder di halaman temp (`temp_ui`).

## Verifikasi

`python -m unittest discover -s tests -t .` → **Ran 1150 tests, OK**.
Tes baru 9: 8 di `tests/test_watchlist_detail.py` (`AddedBaselineTest`:
titik pertama setelah tanggal masuk, titik tidak layak dilewati, tanpa
tanggal masuk, belum ada titik setelah add, tanpa titik sama sekali, teks
caption + varian fallback) dan 1 AppTest di `tests/test_lp_card_ui.py`
(`test_detail_menampilkan_dust_saat_masuk_watchlist`); assert tambahan di
`tests/test_rh_card_ui.py` memastikan caption ikut ter-render di lane
Robinhood.

Teks yang ikut disinkronkan: `README.md` (bagian 🌊 Watchlist Meteora +
Kolom "Sejak masuk"), `AGENTS.md` (bulket `watchlist_detail.py` + spec blok),
dan entri `docs/PROGRESS.md`.

# Kegiatan — 13 September 2026 (🌊 Scan Meteora: urut volume/active TVL · notif delta ⚡ EARLY DUMP tiap 0,02%)

Permintaan user: *"kita benahi lagi scan meteora kita — sort pertama adalah
dari volume / active tvl yang paling besar dulu — lalu dari %dust yang paling
kecil — lalu notifikasi telegram akan muncul ketika %dust naik 0.02%, jadi
sekarang bukan ambang batas, tapi notif berulang ketika dust bertambah 0.02%
dari pertama add watchlist — notifnya jadi gini: EARLY DUMP TERJADI - GANTI
WIDE RANGE"*.

## 1. Urutan listing: volume 24 jam / active TVL → dust

Kunci urut pertama pindah dari "kenaikan volume 24 jam" ke **rasio volume /
active TVL** — angka yang memang sudah dikirim API Meteora
(`volume_active_tvl_ratio`; user menempel payload pool-discovery dan
menunjukkan TACZ = 1646,63%). Kunci kedua tetap dust %MC terkecil.

- `meteora_screener.row_vol_tvl_ratio()` — satu sumber angka untuk urutan,
  UI, dan tooltip: pakai field API bila ada; baris lama di `session_state`
  (hasil scan versi sebelumnya) dihitung ulang `volume / active_tvl × 100`
  supaya kriteria urut tidak berubah hanya karena hasil lama masih tersimpan;
  `None` = tidak ada bahan hitung → barisnya paling bawah.
- `sort_best_rows()` (card 🏆 Scan Best Pool Meteora) = dust-ada → **rasio
  terbesar** → dust %MC terkecil (3 desimal tampilan) → simbol. Urutan lama
  (dust → fee/active TVL → `volume_change_pct`) tidak dipakai lagi.
- `sort_rows()` (listing 🌊 Scan Meteora Pool) tetap BEST POOL dulu → dust:
  tie-break #3 kini **rasio** (sebelumnya TVL terbesar).
- `_row_from_pool()` membawa field `volume_active_tvl_ratio`; absen = `None`
  (bukan 0,0 — kalau 0,0, fallback hitung ulang tidak pernah jalan dan semua
  baris seri).
- UI: baris kecil kolom **Vol 24h** = `Δ x% · 1,647× A.TVL` (bukti urutannya,
  sekali lihat); tooltip sel Fee/TVL menulis "informasi, bukan kunci urut lagi
  sejak 2026-09-13"; tooltip judul card dibangun dari konstanta yang sama.

## 2. Notifikasi: delta 0,02% dari patokan add-watchlist

Satu rule Telegram yang ada (level-based `dust >= STRATEGY_SHIFT_PCT` 0,06)
diganti **delta**: patokan = angka dust **saat token masuk watchlist**
(`baseline_pct`), dan pesan dikirim tiap kali dust naik melewati langkah 0,02%
MC yang belum pernah dikabarkan (`EARLY_DUMP_STEP_PCT` 0,02; kind + marker
`early_dump`).

- `_steps_from_baseline(pct, baseline) = floor((pct − baseline) / 0,02)`
  (toleransi `1e-9` untuk galat float). Langkah bersifat **high water mark**:
  dust turun tidak mengurangi langkah, jadi naik lagi ke level yang sudah
  dikabarkan tidak mengirim ulang; tidak ada pesan penutup "sudah aman".
- Marker `alert_state["early_dump"] = {ts, dust_pct_mc, baseline_pct,
  baseline_ts, step, baseline_src}`; `baseline_*` tidak pernah bergeser selama
  token dipantau dan di-reset hanya oleh `_reset_markers_on_readd` (token
  dihapus lalu di-add ulang = episode baru).
- Patokan diambil dari titik `holder_history` **pertama setelah tanggal
  `added`** (`add_baseline_for_mint` + `watchlist_detail.parse_added_ts`,
  `baseline_src="history"`) supaya kenaikan yang sudah terjadi sejak add tidak
  hilang; kalau tidak ada titik layak, patokan dipasang dari scan pertama
  (`"first-scan"`) dan token itu tidak bunyi di evaluasi pemasangan (tidak
  membanjiri Telegram saat rule baru dipasang).
- Dedup: event id per bucket `FAST_BUCKET_SEC` + jeda `EARLY_DUMP_RESEND_SEC`
  (300 dtk/token) — run ganda / scan manual di atas hasil cron tidak mengirim
  pesan kembar. Lapisan kedua: langkah 0,02% **tidak dimakan** kalau semua
  pengiriman gagal (`_restore_step`) supaya scan berikutnya mengirim ulang
  kabar yang sama.
- Judul baru: **"⚡ EARLY DUMP TERJADI - GANTI WIDE RANGE"**; baris dust
  `📊 Dust: 0.012% → 0.036% MC (+0.024 pp · langkah 1× 0.02%)` +
  `⏱️ N menit sejak masuk watchlist` (baris ini hilang bila patokan tidak
  punya timestamp).
- Jalur kirim tidak berubah: cron LP + scan manual (Chart LP, watchlist biasa,
  Robinhood LP) memakai `process_holder_alerts` yang sama; toggle 🔔/🔕 per
  token tetap dihormati (evaluasi + marker tetap jalan, hanya kirim yang
  dilewati).

## Verifikasi

`python -m unittest discover -s tests -t .` → **Ran 1140 tests, OK** (semua
hijau). `tests/test_strategy_shift.py` di-`git mv` + ditulis ulang sebagai
`tests/test_early_dump.py` (35 tes: langkah/patokan, `baseline_hint`, pesan,
pipeline, bentuk state, `NoLegacyRulesTest`). `tests/test_best_pool_scan.py`
menambah `test_sort_volume_active_tvl_then_dust`,
`test_volume_active_tvl_ratio_is_primary_key`, dan
`test_rasio_dihitung_ulang_untuk_baris_lama`;
`tests/test_meteora_screener.py` memakai `_sort_row(..., ratio, tvl=)`.

Teks yang ikut disinkronkan: `README.md` (Konsep 1 + 7, 🏆 Scan Best Pool,
🌊 Scan Meteora Pool, format alert Contoh, tabel env), `AGENTS.md` (bulket
`telegram_alerts.py` + `meteora_screener.py` + spec blok), `DEPLOY.md`
(ringkasan cron), dan `docs/PROGRESS.md` (entri 2026-09-13 kedua).

# Kegiatan — 13 September 2026 (🌊 Scan Meteora: 0,000% palsu dibersihkan — satu pembagi MC + tanpa angka tanpa bukti holder)

Permintaan user: *\\\"di scan meteora menunjukkan **0.000% baru saya scan** padahal
di scan holder hasilnya beda, coba kamu perbaiki\\\"*.

Angka **0,000%** di kolom Dust %MC kartu 🏆 Scan Best Pool Meteora / 🌊 Scan
Meteora Pool punya tiga akar, dan ketiganya bikin kartu itu **tidak** lagi
membaca hal yang sama dengan 🛰 Scan Holder:

## 1. Dua denominator untuk satu token

`holder_analysis.analyze_token` dulu mendahulukan angka dari pemanggil:

```python
mc = float(market_cap or market.get("marketcap") or 0)
price = float(price_usd or market.get("price_usd") or 0)
```

Semua pemanggil lain (`app.py` Watchlist Meteora, `temp_ui`, `pages/5_🧮_Holder.py`,
`scripts/scan_holders.py` = cron) memanggil tanpa `market_cap` → pembaginya
market cap **DexScreener**. Hanya `meteora_screener.enrich_pools` mengirim MC
listing pool Meteora (`token.market_cap or token.fdv`) — dan angka itulah yang
menang, sekaligus harganya (pemilah wallet ≤ $10 = dust). Efeknya: dua kartu
membagi dust dengan MC berbeda (MC listing bisa FDV, 10-an kali lebih besar
dari MC beredar → dust 0,015% terbaca 0,000%), harga pemilah bucketnya berbeda
(jumlah wallet dustnya ikut beda), dan titik `holder_history` yang ditulis scan
pool tidak sebanding dengan titik cron untuk token yang sama.

**Perbaikan:** precedence dibalik — data market yang baru di-fetch adalah
rujukan, angka pemanggil hanya **cadangan** saat DexScreener tidak membalas
(`market.get("marketcap") or market_cap`). Tidak ada kartu lain yang berubah
(mereka tidak pernah mengirim angka), dan `cron/historical_dust_tracker.py`
(yang memanggil `classify_holders` langsung dengan MC DexScreener) tetap sama.
`enrich_pools` **menulis balik MC yang dipakai** ke `row["mc"]` supaya kolom MC
di tabel dan Dust %MC di sebelahnya tidak pernah dari dua sumber berbeda;
tooltip sel MC + Dust %MC menuliskan sumbernya.

## 2. Scan holder tanpa bukti terbaca seperti \\\"pool paling bersih\\\"

`classify_holders` atas daftar kosong mengembalikan `dust_count: 0` /
`dust_pct_mc: 0.0` — nol aritmatik, bukan bukti. Di jalur watchlist kasus ini
sudah disaring `holder_history.holders_usable` sejak 2026-09-06 (\\\"dust turun
−100%\\\") dan di jalur Robinhood sejak 2026-09-12 (\\\"jangan tampil sebagai
dust 0,00%\\\"), **jalur Meteora belum pernah dapat guard itu** — padahal
0,0 persis nilai terbaik untuk saringan `dust < 0,05% MC`, kunci urut kedua,
dan chip 🏆 BEST POOL (`row_best_pool` hanya membaca angka, bukan buktinya).

- `meteora_screener.row_dust_pct()` sekarang mengembalikan `None` bila
  `holders_usable(analysis.holders)` False: fetch gagal, 0 wallet, hasil
  `truncated` (ekor dust tidak ikut terambil), atau sampel <
  `MIN_USABLE_WALLETS` (40). Satu fungsi itu dipakai saringan, urutan, badge,
  dan UI, jadi angka yang menyaring = angka yang tampil.
- `enrich_pools()` men-null-kan `dust_count`/`dust_pct_mc`/`real_count` untuk
  baris tanpa bukti, menandai `holders_proof: False`, dan menulis alasan
  pendek di `holders_note` (\\\"⚠️ 0 holder (provider mati)\\\", \\\"⚠️ holder
  terpotong\\\", \\\"⚠️ sampel 18 wallet — butuh ≥ 40 untuk dust %MC\\\").
- `ingest_many(ok)` di `enrich_pools` kini hanya menerima analisis yang
  **layak**: sebelumnya titik 0,0 dari provider mati bisa **menimpa** titik
  cron yang benar di dalam `MIN_POINT_GAP_SEC` (scan dobel = timpa titik
  terakhir) dan grafik dust token watchlist terlihat jatuh ke nol.
- Guardnya **bukti, bukan nilainya**: dust 0,000% dari scan FULL yang lengkap
  tetap lolos dan tetap dapat 🏆 BEST POOL. Yang gugur hanya baris tanpa bukti
  (tidak ada angka untuk dibuktikan) — persis rule yang sudah ditulis di
  docstring Best Pool \\\"`None` selalu menggugurkan baris: card ini menjual
  bukti\\\". **Konsekuensi yang disengaja:** token yang total walletnya di bawah
  `MIN_USABLE_WALLETS` (40) — pool baru, holder sedikit — juga tanpa bukti
  distribusi, jadi angkanya tidak ditampilkan dan poolnya tidak masuk Best
  Pool. Ini lantai yang sama dengan badge 🏆 BEST POOL
  (`DUST_BEST_MIN_HOLDERS`) dan dengan lane watchlist/cron sejak
  2026-09-06; dulu listing ini mengiklankan \\\"dust 0,00%\\\" dari 12 wallet
  sebagai pool terbersih, dan itu justru angka yang paling sering tidak cocok
  dengan Scan Holder.
- UI: listing Scan Meteora menampilkan `—` + catatan kecil alasan di bawah
  Dust %MC; kartu Best Pool tidak lagi menaruh baris itu di listing utama
  maupun listing \\\"disembunyikan\\\" (`row_dust_ok` = `False`).

## 3. Pool quote-only \\\"bersih\\\" selamanya

`base_token()` mengambil sisi non-quote dan **jatuh ke `token_x`** bila kedua
sisi adalah token quote. Untuk pool USDC-USDT / SOL-USDC / SOL-USDT (senantiasa
ada di listing top DLMM 24 jam, TVL besar, volume puluhan juta) yang diambil
adalah **SOL**: yang di-scan = holder SOL, pembaginya = MC SOL. Dust %MC-nya
tidak pernah bukan nol nyata → **0,000%** + 🏆 BEST POOL, dan kuota Helius
terbakar untuk scan 100k akun yang hasilnya pasti sampah.

`meteora_screener.unanalysable_row()` + `drop_quote_rows()` membuangnya
**sebelum** fetch holder (juga `mints` di `enrich_pools` — dua lapis, karena
modul ini dipakai ulang); rekapnya jadi data, bukan rule: caption
`· N pool quote dilewati` dari `result[\"skipped_quote\"]` di kedua kartu dan
satu baris di 🧾 Log Aktivitas.

## Verifikasi

`python -m unittest discover -s tests -t .` (suite offline di sandbox: tanpa
streamlit, 199 tes UI di-skip) → **1086 tes, 0 regresi** dibanding baseline
(commit sama: 1065 tes, failure/error yang tersisa semua karena `streamlit`
tidak terpasang di sandbox). Tes baru:

- `tests/test_meteora_screener.py` — `DropQuoteRowsTest` (6: pool dua sisi
  quote dibuang, mint kosong dibuang, `skipped_quote` di `scan_meteora` dan
  `scan_best_meteora`, holder quote tidak di-fetch) dan `EnrichPoolsProofTest`
  (7: fetch gagal / terpotong / sampel pendek → `None` + alasan, scan lengkap
  tetap utuh, `mc` baris ditulis balik, ingest hanya yang layak, mint quote
  tidak di-analisa); `test_baris_tanpa_data_dust_paling_bawah` disesuaikan
  karena baris \\\"0 wallet\\\" kini sekelompok dengan \\\"tanpa angka\\\";
- `tests/test_best_pool_scan.py` — `BuktiHolderTest` (5): gugur saringan,
  gugur `hidden_rows`, `hidden_dust` terhitung, scan valid 0,0 tetap lolos;
- `tests/test_holder_analysis.py` — `MarketPrecedenceTest` (3): data market
  menang atas angka pemanggil, angka pemanggil jadi cadangan, pemanggil tanpa
  angka tidak berubah.

Teks yang ikut disinkronkan: rule + ambang dibaca dari konstanta di tooltip
judul (tidak ada caption rule baru — `TooltipBukanCaptionTest`) —
`best_pool_ui.best_pool_tooltip()`, `temp_ui.meteora_scan_tooltip()`, tooltip
sel MC/Dust %MC, docstring modul `meteora_screener`, `README.md` (Konsep +
bagian 🌊 Scan Meteora Pool), dan `AGENTS.md` (bulket `meteora_screener.py` +
`holder_analysis.py`).

Satu perubahan tampilan kecil sekalian: kolom **Dust %MC** listing 🌊 Scan
Meteora Pool ikut **3 desimal** (2026-09-12 kolom Hold %MC Watchlist Meteora
sudah; listing ini justru hanya memuat dust ≤ 0,1% MC sehingga dua desimal
membuat hampir semua baris \\\"0,00%\\\").

# Kegiatan — 12 September 2026 (klik pill N disembunyikan → listing pool tersembunyi)

Permintaan user: *\"ketika saya klik disitu, app akan menampilkan pool yang
disembunyikan sorted by kenaikan volume 24 jam, tapi tetap dengan kriteria
minimal volume 24 jam 1M, dan minimum % dust dibawah 0.05%\"* (konteks:
pill **N disembunyikan** di card 🏆 Scan Best Pool Meteora).

- `scan_best_meteora()` kini meng-enrich semua pool **volume 24 jam ≥ $1M**
  (bukan hanya yang lolos volatility) supaya dust < 0,05% MC bisa dicek di
  listing tersembunyi. Pool sepi (< $1M) tetap tidak di-fetch holder.
  Hasil baru `hidden_rows`: volume ≥ $1M + dust < 0,05% MC, **bukan** di
  listing utama (gagal volatility), urut `sort_best_rows` (Δ volume 24 jam
  terbesar dulu).
- UI `best_pool_ui`: tombol **▶ N disembunyikan** (HTML pill tidak bisa
  diklik di Streamlit) membuka listing itu; **◀ kembali ke N pool lolos**
  mengembalikan listing utama. ⭐ listing tersembunyi memakai key
  `best-pool-hidden-star-…`.
- Coverage: `tests/test_best_pool_scan.py` — `hidden_rows` menolak volume
  < $1M dan dust ≥ 0,05%, urut Δ volume; AppTest klik tombol menampilkan
  token tersembunyi dan menyembunyikan yang lolos.

# Kegiatan — 12 September 2026 (🛰 Scan Holder: tulisan BEST emas kelap-kelip · 🏆 Best Pool: volume 24 jam ≥ $1M)

Permintaan user (dua bagian, menyusul entri tiga bagian sebelumnya di hari
yang sama):
*\"lalu kita tambahkan juga disini, jika kondisi %dust <= 0.035 kasih tulisan
BEST yang agak besar, dengan efek kelap kelip, warnanya GOLD\"* (konteks:
section 🛰 Scan Holder Solana / Robinhood yang baru mendapat metrik Dust %MC)
dan *\"🏆 Scan Best Pool Meteora — tambahkan juga kriteria disini, minimal
volume 24 jam adalah 1M, dibawah itu jangan di show\"*.

## 1 · 🛰 Scan Holder: tulisan **BEST** emas kelap-kelip bila dust ≤ 0,035% MC

- Syarat: `depth["dust_pct_mc"] <= meteora_screener.BEST_DUST_MARK_PCT`
  (0,035%, **inklusif** — angka yang sama dengan tanda 🏆 BEST POOL di card
  🏆 Scan Best Pool Meteora, jadi satu sumber konstanta dan tidak bisa
  menyimpang). Dust `None`/tidak terbaca = tidak pernah ditandai.
- Helper baru `dashboard_components._scan_best_mark_ok()` (syaratnya, impor
  `meteora_screener` di dalam fungsi — pola `best_pool_tooltip()`) +
  `_scan_best_badge_html()` (HTML-nya, return `""` bila tidak lolos supaya
  tidak ada elemen kosong). Dirender `app.py::_render_helius_holder_result`
  dengan `c0.markdown(...)` = **kolom metrik Dust %MC**, tepat di bawah
  angkanya, untuk **kedua jalur** (Helius *dan* Blockscout — satu renderer).
- Tampilan: **agak besar** (1,45rem, weight 900, letter-spacing), warna
  **GOLD** (gradien `#8a5a00 → #ffd700 → #fff6b0` di-clip ke teks + glow
  emas), **kelap-kelip** (`@keyframes scan-best-blink`, opacity 1 → 0,32,
  1,05s infinite) plus kilau menyapu (`scan-best-shine`, 2,8s) dan 🏆 kecil
  di ujungnya. Semua gaya hidup di CSS `render_styles()` karena
  `st.markdown` **men-sanitasi atribut `style` inline**;
  `@media (prefers-reduced-motion: reduce)` mematikan animasinya.
- Nama class-nya `.scan-best-gold`, **sengaja bukan** varian `dust-best`:
  pin regression card Scan Meteora menghitung kemunculan string class chip
  emas itu di seluruh body halaman (`tests/test_lp_card_ui.py`,
  `tests/test_best_pool_scan.py`) dan CSS ikut ter-render di body — memakai
  nama yang mengandung substring itu langsung memecahkan dua tes tersebut
  (terjadi saat implementasi, sudah diperbaiki + diberi komentar di CSS).
- Penanda **visual** saja: tidak ada metrik, saringan, atau angka yang
  berubah. Rule + ambangnya dijelaskan di **tooltip judul section**
  (`app.scan_holder_tooltip()` — konstanta `SCAN_HOLDER_TOOLTIP` dijadikan
  fungsi supaya angkanya dibaca dari `BEST_DUST_MARK_PCT` saat dipanggil),
  bukan caption baru di badan section.
- Coverage: `tests/test_rh_card_ui.py` (AppTest: badge tepat satu di 0,035%
  dan di jalur Helius; tidak muncul di 0,036/0,041/0,55/9,0 maupun saat dust
  `None`; CSS `.scan-best-gold` + `@keyframes scan-best-blink` + warna emas
  ikut ter-render; tooltip section menyebut rule-nya dan caption tidak) +
  `tests/test_best_pool_scan.py::ScanHolderBestBadgeTest` (unit helper:
  batas inklusif, data hilang, teks tanpa `style=` inline, isi CSS
  `render_styles`, ambang mengikuti konstanta).

## 2 · 🏆 Scan Best Pool Meteora: saringan **volume 24 jam ≥ $1.000.000**

- Konstanta baru `meteora_screener.BEST_VOLUME_24H_MIN = 1_000_000.0`
  (USD, **inklusif** — tepat $1M lolos) dan syaratnya masuk
  `row_best_gaps()`: label gap `volume 24 jam < $1,000,000`, volume `None`
  = gugur (sama seperti volatility — pool tanpa data volume tidak terbukti
  ramai). Saringan layar card jadi **tiga**: volume ≥ $1M + volatility ≥ 2%
  (`row_best_gaps`) dan dust < 0,05% MC (`row_dust_ok`).
- Karena `row_best_gaps()` jalan **sebelum** `enrich_pools()`, pool sepi
  gugur tanpa membakar kuota Helius; hitungannya masuk `hidden_metric`
  (bukan `hidden_dust`) sehingga rekap \"N pool lolos · M disembunyikan\" dan
  log aktivitas tetap benar tanpa perubahan UI.
- Bukan query API: `best_filter_by()` tetap `pool_type=dlmm&&fee_pct>=2&&
  active_tvl>=50000` (kunci `filter_by` yang dipakai UI Meteora — kunci
  volume tidak terverifikasi di endpoint itu, jadi disaring di layar supaya
  tidak diam-diam kehilangan seluruh listing).
- UI `best_pool_ui`: tooltip card menyebut ambangnya dari konstanta
  (`volume 24 jam >= $1,000,000 (di bawah itu tidak ditampilkan)`), dan
  tooltip sel **Vol 24h** kini menutup dengan `saringan layar: minimal
  $1,000,000` supaya angka yang jadi bukti saringan terlihat di selnya.
- Coverage: `tests/test_best_pool_scan.py` — batas inklusif ($1M lolos,
  $999.999,99 / $0 gugur), volume `None` gugur, label gap mengikuti
  konstanta, `filter_best_rows` memasukkan pool sepi ke `hidden_metric`,
  `scan_best_meteora` tidak mem-fetch holder pool $400K (fixture default
  dinaikkan ke $1,2M supaya tetap menguji satu syarat per tes), tooltip card
  + tooltip sel, dan AppTest sel Vol 24h menampilkan `$1.20M` /
  `volume 24 jam $1,200,000`.

## Verifikasi

- Suite penuh: **1102 tes lulus** (sebelumnya 1092 — 10 tes baru), tanpa
  network (`tests/conftest.py` + `tests/__init__.py`).
- Dokumentasi ikut diperbarui: `AGENTS.md` (bullet baru tanda BEST di Scan
  Holder, `scan_holder_tooltip()` menggantikan konstanta `SCAN_HOLDER_TOOLTIP`,
  saringan layar Best Pool jadi tiga + urutan baris yang sempat basi
  dikoreksi ke volume → dust → fee/TVL) dan `README.md` (tabel saringan
  layar Best Pool + paragraf metrik/BEST di section Scan Holder).

# Kegiatan — 12 September 2026 (🏆 tanda Best Pool ≤ 0,035% · Hold %MC 3 desimal · Dust %MC di Scan Holder)

Permintaan user (tiga bagian):
*\"pada 🏆 Scan Best Pool Meteora tandai jika %dust <= 0.035 menjadi Best
Pool; pada 🌊 Watchlist Meteora dan 🦅 Watchlist Robinhood pada kolom Hold
%MC buat menjadi 3 angka dibelakang koma persenannya; lalu pada 🛰 Scan
Holder Solana / Robinhood tambahkan detail % dust di sebelah kiri Akun
holder (Blockscout) — pada scan holder ini, kita buat menjadi 3 angka
dibelakang koma juga, termasuk di grafik\"*.

## 1 · 🏆 Scan Best Pool Meteora: tanda Best Pool untuk dust ≤ 0,035%

- Konstanta baru `meteora_screener.BEST_DUST_MARK_PCT = 0.035` + helper
  `row_best_pool()` (batas **inklusif** — 0,035 persis ikut ditandai; dust
  `None` tidak pernah). Penanda **visual, bukan saringan**: saringan
  listing tetap `BEST_DUST_MAX_PCT` 0,05% (lebih longgar), jadi listing
  tidak menyempit dan pool 0,04% tetap tampil hanya tanpa tanda.
- UI `best_pool_ui`: kolom **Dust %MC** baris yang lolos tanda menampilkan
  angka warna emas + chip `dust-badge dust-best` 🏆 BEST POOL (chip mengganti
  sub "dust" di selnya); kepala card mendapat pill emas **🏆 BEST POOL N**
  di antara pill jumlah pool dan "disembunyikan". Tooltip sel dan tooltip
  judul card menjelaskan ambangnya dengan angka dari konstanta (konvensi
  2026-09-10: tooltip mengikuti konstanta, tidak hard-code).
- Coverage: `tests/test_best_pool_scan.py::BestPoolMarkTest` (batas
  inklusif 0,035 / bukan saringan — 0,04% tetap lolos / `None` tak pernah /
  fallback field baris / tooltip) + 2 AppTest (chip hanya di baris ≤0,035
  dengan pill rekap; tanpa baris bertanda = tanpa chip/pill).

## 2 · Kolom Hold %MC di watchlist → 3 desimal

- `app.py::_render_lp_row` (🌊 Watchlist Meteora) dan
  `dashboard_components._render_rh_row` (🦅 Watchlist Robinhood — varian LP
  halaman utama *dan* varian biasa halaman temp ikut karena satu renderer):
  `pct_txt` `.2f` → `.3f` ("0.450%" bukan "0.45%"). Dust watchlist LP sering
  di kisaran 0,01–0,09% MC; dua desimal menyembunyikan beda 0,044% vs
  0,037% yang justru penting untuk memutuskan masuk pool.
- Yang **tidak** ikut berubah: Watchlist Holder biasa di `temp_ui.py`
  (scope permintaan hanya kedua card watchlist chain) dan pembanding
  `watchlist_detail` (Δ→% MC format lain).

## 3 · 🛰 Scan Holder: metrik Dust %MC + semua persen 3 desimal

- **Metrik baru `Dust %MC` tepat di kiri "Akun holder (…)"**
  (`app.py::_render_helius_holder_result`, kolom metrik jadi 5): nilai
  `dust_pct_mc` yang dihitung `classify_holders` **di dalam**
  `scan_token_holders` — Helius *dan* Robinhood — lalu ditempel ke
  `depth` (`dust_pct_mc`, `dust_count`, `dust_value_usd`,
  `dust_limit_usd`). Kenapa bukan bucket `$0-$10` depth: definisi
  `classify_holders` adalah sumber kebenaran kolom **Hold %MC** watchlist
  (wallet 0 < nilai ≤ $10, LP/pool disingkirkan lewat pair_addresses +
  `is_wallet`), jadi angka Scan Holder identik dengan watchlist token yang
  sama untuk kedua sumber (Helius/Blockscout). Help metrik membawa jumlah
  wallet (≥ bila scan terpotong) + total nilai USD dust.
- **3 desimal**: metrik baru (`.3f`), label batang grafik
  `helius_holders.depth_bar_chart` (`.1f` → `.3f` — bucket dust 0,008% MC
  dulu memayat jadi "0.0%"), dan kolom **% Market Cap**
  `dashboard_components._depth_tables_html` (`.2f` → `.3f`; tabel ini juga
  dipakai Wallet Depth nested di expander watchlist — seragam). Tooltip
  judul section (`SCAN_HOLDER_TOOLTIP`) ikut menyebut definisi + presisi.
- Coverage: `tests/test_helius_holders.py` (depth membawa dust stats; LP
  dust tidak ikut; marketcap 0 → `dust_pct_mc` `None` → metrik "—"; label
  grafik 3 desimal), `tests/test_robinhood_transport.py::ScanHoldersDustStatsTest`
  (jalur Blockscout identik), `tests/test_rh_card_ui.py` (AppTest: metrik
  "Dust %MC" = "0.035%" tepat sebelum "Akun holder (Blockscout)"), dan
  pin 3 desimal di `tests/test_lp_card_ui.py` (🌊, "0.610%"/"1.350%"),
  `tests/test_rh_card_ui.py` (🦅, "0.550%"), `tests/test_alert_toggle_per_token.py`
  (assert "0.55%" → "0.550%").

# Kegiatan — 11 September 2026 (🔔/🔕 toggle alert Telegram per token: Meteora + Robinhood)

Permintaan user: *"kasih toggle alert on/off per token yang ada di watchlist
meteora dan robinhood. jadi misal saya sudah tau ada notif, saya bisa
nonaktifkan. tapi pas awal memasukkan ke watchlist, otomatis on"*.

## 1 · Penyimpanan pilihan: `alert_settings.muted_mints` (blocklist)

- `alert_settings.py` menampung setelan kedua di file yang sama
  (`alert_settings.json`, ref `holder-live`): `muted_mints` = daftar token
  yang notifnya **dimatikan**. Karena bentuknya *blocklist*, token baru
  otomatis ON — tidak ada tulis/commit saat menambah token.
- API baru: `mint_key()` (EVM `0x…` di-lowercase, mint Solana
  case-sensitive), `muted_mints()`, `is_mint_muted()`,
  `mutes_for(mints)` (irisan siap pakai sebagai `mute_mints`),
  `set_mint_alert_enabled(mint, enabled)`, `forget_mint_alert(mint)`.
  `save_settings()` dapat `message=` (commit per token, e.g.
  `alert-settings: notif off 0xe2324ff2a59 [skip ci]`) dan transport
  dipindah ke `_write_remote()` supaya suite bisa mematikannya.
- **Token yang di-add ulang selalu ON**: `watchlist.add_to_watchlist` dan
  `add_many_to_watchlist` memanggil `forget_mint_alert(ca)`
  (`_reset_alert_toggle_on_add`). Tanpa ini token yang pernah dimatikan,
  dihapus, lalu di-add lagi akan mewarisi pilihan OFF periode sebelumnya.
  Mint yang memang tidak pernah dimatikan tidak menulis/meng-commit apa pun.

## 2 · Yang menghormatinya (cron + semua scan manual)

- Cron `scripts/scan_holders.py`: membaca `muted_mints(force_refresh=True)`
  **sekali per run** (1 request GitHub, tercetak di log
  `Toggle alert per token: N dimatikan`) dan meneruskan
  `mute_mints=alert_settings.mutes_for(...)` ke **kedua** lane LP.
- Scan manual: 🔍 Scan LP Meteora (`app.py`), scan ulang card Robinhood
  (`dashboard_components._render_rh_card`), dan scan watchlist biasa
  (`temp_ui.py`) memakai `mutes_for(fresh)` — sehingga token yang dipindah
  card (Meteora → Holder, LP → biasa) tetap senyap.
- Semantiknya tetap **"kirim dilewati, evaluasi jalan"**: rule 🚨 tetap
  dievaluasi dan marker `strategy_shift` tetap dimajukan, jadi menyalakan
  notif lagi tidak membanjiri pengingat episode lama. Catatan hasil scan
  manual ikut menyebut jumlah yang dilewati.

## 3 · Tombolnya di UI

- Baris Watchlist Meteora (`app.py`) dan kedua card Robinhood
  (`dashboard_components._render_rh_row`) dapat kolom baru: **🔔** (ON, klik
  = matikan) / **🔕** (OFF, klik = nyalakan) dengan key `lp-alert-<mint>`,
  `rh-alert-<0x…>`, `rhreg-alert-<0x…>`. Grid baris jadi 7 kolom; 📋/⚡ dan ✕
  bergeser satu kolom.
- Kepala card menampilkan pill **🔕 N** (`_muted_pill_html`) dan baris yang
  dimatikan menambah **· 🔕 notif off** di caption, jadi statusnya kelihatan
  tanpa menebak dari emoji tombol.
- Gagal sinkron GitHub tidak ditelan: `_store_toggle_note` /
  `_render_toggle_note(scope)` menampilkan peringatan **di card pemiliknya**
  (karena klik langsung `st.rerun()`), plus entri di 🧾 Log Aktivitas.
- `LP_CARD_TOOLTIP`, `RH_CARD_TOOLTIP`, `RH_REGULAR_CARD_TOOLTIP`, dan help
  toggle global watchlist biasa (halaman temp) menyebut tombol per token ini.
- Catatan hasil scan manual (`telegram_alerts.delivery_note`) tidak lagi
  berbunyi "notif watchlist biasa OFF" — jadi
  "(notif token itu sedang dimatikan)" supaya benar untuk kedua sumber mute.
- Watchlist Holder biasa di halaman temp **tidak** diberi tombol (scope
  permintaan user = Meteora + Robinhood); `mute_mints`-nya tetap dihormati.

## 4 · Tes

- Baru: `tests/test_alert_toggle_per_token.py` (27 tes) — store (default ON,
  mute → nyala lagi, EVM case-insensitive, `forget_mint_alert` tanpa tulis
  bila tidak dimatikan, payload rusak/toleran, push gagal tetap lokal),
  add-ulang = ON (satu + massal), UI AppTest (bell 🔔/🔕 di tiga card, pill
  🔕, caption "🔕 notif off", klik menyimpan pilihan, peringatan gagal
  sinkron), jalur scan (LP Meteora, Robinhood LP, Robinhood biasa saat toggle
  global ON, watchlist Holder Solana) memastikan **tidak ada** pesan terkirim
  tapi marker `strategy_shift` tetap tersimpan, dan wiring cron (mute
  diteruskan ke kedua lane).
- Dua tes khusus menegaskan **per token, bukan global**: dari dua token LP di
  card yang sama, hanya baris yang di-🔕 berlabel 🔕 (yang lain tetap 🔔, pill
  cukup "🔕 1"), dan scan-nya mengirim Telegram untuk token 🔔 sambil melewati
  token 🔕 (dihitung di laporan scan manual).
- Suite offline: `tests/__init__.py` + `conftest.py` men-stub
  `alert_settings._read_remote`/`_write_remote`; dua assertion lama
  (`tests/test_manual_scan_alerts.py`) menyesuaikan kalimat `delivery_note`.
- Suite penuh: **1076 lulus** (sebelumnya 1049), 21 subtests.

# Kegiatan — 11 September 2026 (🦅 Scan Best Robinhood Coin → temp · 🏆 Scan Best Pool Meteora keluar dari grid)

Dua permintaan user sekaligus:

1. **🦅 Scan Best Robinhood Coin** → *"pindah ke page temp karena belum
   berfungsi"*,
2. **🏆 Scan Best Pool Meteora** → *"jangan dibuat grid lagi"*.

- `app.py`: card **🦅 Scan Best Robinhood Coin**
  (`robinhood_best_scan.render_robinhood_best_scan()`) dihapus dari kolom
  kanan grid 2 kolom — **hanya penempatan** yang berubah: logika scan,
  filter, urutan, tombol 📋/⭐, dan session key tidak disentuh. Card **🏆
  Scan Best Pool Meteora** keluar dari grid 2 kolom (dulu menempel di bawah
  🌊 Watchlist Meteora, kolom kiri) dan dirender **full-width** di bawah
  grid, sebelum 🛰 Scan Holder — posisi seperti sebelum grid 2 kolom
  2026-09-10 (dipisah `st.divider()`). Grid 2 kolom tetap untuk dua card
  watchlist: kiri 🌊 Watchlist Meteora, kanan 🦅 Watchlist Robinhood (LP).
- `temp_ui.py`: `render_temp()` memanggil
  `robinhood_best_scan.render_robinhood_best_scan()` setelah card 🌊 Scan
  Meteora Pool, sebelum section 🔍 Temukan Token. ⭐ card tetap memasukkan
  token ke **Watchlist Robinhood LP** di halaman utama (source/target tidak
  berubah); data, cron, dan alert tidak disentuh.
- Docstring `robinhood_best_scan.py` (modul + `render_robinhood_best_scan`)
  dan `best_pool_ui.py` mengikuti (penempatan + alasan diparkir).
- Tidak ada perubahan logika sama sekali — murni pemindahan card + layout.
- Tes: `tests/test_robinhood_best_scan.py::RenderTest` (4 AppTest) kini
  membuka halaman **temp** via `switch_page("pages/8_temp.py")` (pola
  `tests/test_temp_page.py`), `test_card_tampil_di_halaman_utama` diganti
  `test_card_tampil_di_halaman_temp`; `tests/test_temp_page.py` menambah pin:
  halaman utama TIDAK lagi merender kepala/tombol Scan Best Robinhood, dan
  halaman temp MEMENUangnya. Suite penuh: **1049 passed, 21 subtests**
  (sama dengan baseline).

# Kegiatan — 11 September 2026 (🏆 Scan Best Pool Meteora: kriteria diganti total)

Permintaan user: *"untuk Scan Meteora pool kita ganti seperti ini … kriteria
yang sebelumnya, ganti total dengan ini"* — disertai curl
`pool-discovery-api.datapi.meteora.ag/pools?page_size=50&timeframe=24h&category=top&filter_by=pool_type=dlmm&&fee_pct>=2&&active_tvl>=50000`
+ respons JSON-nya, dan daftar "kondisi": hanya tampilkan dust < 0,05% MC,
kasih detail fee / active TVL di tabel, urut dust terkecil lalu fee/active
TVL terbesar, volatility minimal 2%, lalu urutkan dari kenaikan volume
terbesar. Ditanya balik, user memilih: card = **🏆 Scan Best Pool Meteora**
saja (card 🌊 /temp + 🦅 tidak disentuh), saringan lama = **dihapus** (bukan
ditumpuk), "kenaikan volume" = **`volume_change_pct`** (bukan volume
absolut).

## 1 · Rule baru (`meteora_screener.py`)

- Konstanta: `BEST_FEE_PCT_MIN` 5,0 → **2,0**, `BEST_ACTIVE_TVL_MIN` 10.000
  → **50.000** (keduanya hanya dikirim ke API sebagai `filter_by`, TIDAK
  diulang di layar), `BEST_VOLATILITY_MIN` 5,0 → **2,0** dengan operator
  **`>=`** ("minimal 2%" — 2,0% lolos; beda dari rule lama yang ketat `>`).
  `BEST_DUST_MAX_PCT` tetap **0,05** dan tetap ketat `<` (data dust hilang =
  gugur). `BEST_FEE_RATIO_MIN`, `BEST_TOP10_MAX_PCT`, `BEST_TOTAL_LPS_MIN`
  **dihapus** bersama layarnya.
- `row_best_gaps()` menyusut dari 5 cek metrik jadi **1 cek** (volatility).
  Fungsi + label gapnya tetap satu-satunya sumber angka "gugur metrik"
  (`hidden_metric`) supaya pill "N disembunyikan" jujur.
- `_row_from_pool()` menambah **`fee`** (fee 24 jam, USD) dan
  **`volume_change_pct`** — dipakai tabel + kunci urut. Card 🌊 Scan Meteora
  Pool memakai fungsi yang sama tapi tidak menampilkan field baru, jadi
  listingnya tidak berubah.
- `sort_best_rows()`: `(bawa dust? , dust % MC asc (3 desimal tampilan),
  -fee/active TVL, -volume_change_pct, simbol)`. Baris tanpa angka dust tetap
  paling bawah.

## 2 · Tabel + tooltip card (`best_pool_ui.py`)

- Kepala tabel sekarang: `Token · MC · A.TVL · Fee/TVL · Vol 24h · Volat ·
  Top10 · LPs · Dust · Dust %MC · Pool · ⭐` — tetap 12 kolom: kolom "Fee"
  (tier fee saja) dihapus dan posisinya dipakai untuk **Vol 24h** (Δ volume
  hijau/merah jadi baris kecilnya), tier fee pindah ke baris kecil
  **Fee/TVL** (`fee $97.7K·2%`), dan kolom volatilitas lama `Vol` berganti
  nama jadi `Volat` supaya tidak tabrakan. Jadi "detail fee / active TVL"
  bisa dibaca langsung: A.TVL = penyebut, fee = pembilang, rasio = kunci urut
  kedua.
- Tiap sel metrik dapat atribut `title` berisi **angka penuh** + statusnya
  ("kunci urut kedua (terbesar dulu)", "hanya informasi, bukan saringan lagi
  sejak 2026-09-11"). Konvensi 2026-09-10 tetap: prose rule hanya di tooltip
  judul, badan card hanya angka rekap.
- `best_pool_tooltip()` ditulis ulang — query API, dua saringan, tiga kunci
  urut — dan **semua angkanya dibaca dari konstanta** `meteora_screener.BEST_*`
  (konvensi AGENTS.md). Enam konstanta lama yang dihapus tidak lagi diimpor
  (kalau dibiarkan, card langsung melempar ImportError jadi baris peringatan).

## 3 · Tes & docs

- `tests/test_best_pool_scan.py` ditulis ulang (22 tes): query = persis curl
  user; `fee_pct>=2`/`active_tvl>=50000`; volatility 2,0% **lolos** dan
  1,99% gugur; deretan saringan lama diuji **tidak** menggugurkan lagi +
  konstantanya benar-benar hilang (`hasattr`); rantai urut dust → rasio → Δ
  volume; tabel harus memuat `fee $…`, rasio, dan `+12,5%`; tooltip berubah
  kalau konstantanya di-patch.
- `tests/test_strategy_shift.py` tetap hijau — `STRATEGY_SHIFT_PCT` (0,06)
  masih di atas `BEST_DUST_MAX_PCT` (0,05), ambang notifikasi tidak ikut
  berubah.
- README (§🏆 Scan Best Pool Meteora + tabel kolom), AGENTS.md (blok modul
  `meteora_screener.py` + tabel angka kunci), `docs/PROGRESS.md` mengikuti.
- **Batas verifikasi:** sandbox tidak punya jaringan, jadi payload API
  sungguhan tidak pernah dipanggil — bentuk respons diambil dari JSON yang
  user tempel (field `fee`, `volume_change_pct`, `fee_active_tvl_ratio`,
  `volatility`; satuan persen sudah final, tidak dikali 100 lagi).
  Suite: **1049 passed** (+4 tes), 21 subtests, 0 gagal.

# Kegiatan — 11 September 2026 (satu notifikasi: 🚨 GANTI STRATEGI · caption dobel tooltip dihapus)

Dua permintaan user:

1. *"tulisan ini hapus donk, sudah ada di tooltip"* → ditanya balik, user
   memilih **semuanya**: semua caption yang mengulang isi tooltip judul
   dihapus (3 tempat).
2. *"buat 1 notifikasi lagi — jika %dust diatas >= 0,06 kasih notif, WAKTUNYA
   GANTI STRATEGI"* + *"hapus notif lainnya"* → rule notifikasi diganti satu
   saja; ditanya balik soal kadens, user memilih **tiap scan selama masih di
   atas ambang** (`every_scan`).

## 1 · Caption rule → tooltip saja

- **🌊 Scan Meteora Pool** (halaman temp) sebelumnya **tidak punya tooltip
  sama sekali** — captionnya panjang dan mengarang ulang isi yang sama, jadi
  teksnya tidak dibuang tapi **dipindah**: fungsi baru
  `temp_ui.meteora_scan_tooltip()` menyusun rule + ambang dari konstanta
  (`meteora_screener.TVL_MIN`/`FEE_RATIO_24H`/`FEE_RATIO_1H`,
  `holder_history.DUST_SCAN_HIDE_PCT`/`DUST_BEST_PCT`/`DUST_BEST_MIN_*`) dan
  dipasang sebagai `tooltip=` pada `card_head_html()` di
  `temp_ui._meteora_head_html()` (impor dilakukan di dalam fungsi, sama seperti
  `best_pool_ui.best_pool_tooltip()`). Caption rekap di bawahnya kehilangan
  angka yang dobel — dulu `… {hidden} disembunyikan (dust > 0,1% MC) · listing
  K · 🏆 X BEST POOL di urutan teratas`, sekarang
  `{N} pool ditampilkan · {M} disembunyikan · listing {K}[ · 🏆 X BEST POOL]`.
  Kepala card scan best memang bukan `<details>`/accordion, hanya
  `<div class="lp-head">` dengan pill — tidak ada yang diubah di struktur itu.
  Card Robinhood (`_head_html`/`_rh_head_html`) sudah memakai helper tooltip
  yang sama, tidak disentuh.
- **🦅 Scan Best Robinhood Coin** (`robinhood_best_scan`): caption rekap masih
  menulis ulang **angka** ambangnya
  ("…= 2, top 10 holder ≥ 30% = 1, honeypot = …") — sekarang hanya
  `Listing N coin · M dilewati · dust X · top 10 Y · honeypot Z · holder gagal W.`;
  seluruh prose sudah ada di `RH_SCAN_TOOLTIP`.
- **Toggle Auto-refresh** di header halaman utama: teks abu-abu
  `st.caption("Data baris = snapshot cron (±5 menit); halaman ini re-check tiap
  ±60 detik.")` dihapus — `help` toggle sudah berkata persis begitu.
- Pin regression baru: `tests/test_temp_page.py::TooltipBukanCaptionTest`
  (teks toggle hilang dari badan halaman **tapi tetap ada di `proto.help`**;
  kepala card /temp memuat `title="Top DLMM 24 jam…"` dan captionnya bebas
  angka rule) + perluasan
  `tests/test_robinhood_best_scan.py::RenderTest.test_detail_karakteristik_di_tooltip_bukan_caption`.

## 2 · Satu rule: 🚨 WAKTUNYA GANTI STRATEGI (dust ≥ 0,06% MC)

- `telegram_alerts.py` ditulis ulang (1078 baris):
  `STRATEGY_SHIFT_PCT = 0.06`, kind/marker `strategy_shift`,
  `STRATEGY_SHIFT_TITLE = "🚨 WAKTUNYA GANTI STRATEGI"`,
  `evaluate_strategy_shift_rule(marker, current, *, mint, symbol, sent_event_ids,
  last_sent, market_context)`. Sifatnya **level-based**: selama
  `dust_pct_mc >= 0.06` tiap evaluasi menghasilkan event; `< 0.06` = marker
  `{}` dan **tidak ada** pesan "sudah aman". Ulang dibatasi bucket event
  `FAST_BUCKET_SEC` 300 dtk + `STRATEGY_SHIFT_RESEND_SEC` 300 dtk per token,
  jadi cron 5 menit + scan manual + run ganda tidak mengirim pesan kembar.
  Ambangnya sengaja **di atas** filter listing 0,05%
  (`meteora_screener.BEST_DUST_MAX_PCT`, `robinhood_best_scan.RH_SCAN_*`)
  supaya token yang baru masuk daftar tidak langsung bunyi — dipin
  `ThresholdTest`.
- **Dihapus**: ⚡ EARLY DUMP (crossing > 0,1%), 🔔 HIGH DROP (≥50% dari titik
  high), 🚨 EXIT/CUTLOSS + ✅ KEMBALI KE TITIK AMAN, rule dust 4 jam
  (dump +0,25 pp / akumulasi −0,50 pp), baseline shift ±1 pp, **gerbang
  konfirmasi volume/harga/volatilitas** (`validate_alert_with_volume`,
  `volume_verdict`, `is_high_volatility`, skor 0,70/0,80), `escalation_due`,
  `safe_return_due`, dan **jejak audit `rejected_signals`**. `NoLegacyRulesTest`
  menuntut simbol-simbol itu tidak ada lagi dan `lp_mints=` menolak TypeError.
  Yang **tidak** ikut dihapus: anchor `baseline`/`rolling` +
  `tracked_wallet_addresses()` (dipakai `holder_analysis`, `robinhood_holders`,
  `robinhood_watchlist` untuk kronologi/peta wallet) dan `alert_context.py`
  — konteks pasar sekarang murni baris info `📈 Pasar`, diambil **lazy** hanya
  saat pesan jadi dikirim, disimpan di `event["market"]` (key hanya diisi bila
  ada nilai non-None).
- **Baru di API**: `advance_anchors` (default True) memisahkan "kirim notif"
  dari "geser anchor". Cron `scripts/scan_holders.py` → `advance_anchors=args.full`;
  **semua** tombol scan manual (`app.py`, `dashboard_components._render_rh_card`,
  `temp_ui.py`) sekarang ikut mengirim notif dengan `advance_anchors=False`
  + tanpa flag scope. `holder_history` hanya menyimpan/menggabung marker
  `("strategy_shift",)` (2 tempat: restore snapshot ringkas + `_merge_alert_state`);
  `holder_status._alert_state_for_status` membuang `rejected_signals` + marker
  legacy. Tooltip card (`app.LP_CARD_TOOLTIP`, `RH_CARD_TOOLTIP`,
  `RH_REGULAR_CARD_TOOLTIP`) menyebut rule baru dari konstanta impor, bukan angka
  diketik manual, dan `st.info(..., icon="🚨")` di panel hasil scan.

## Hasil tes

`/home/user/.venv/bin/python -m pytest -q tests` → **1043 passed, 21 subtests
passed, 0 gagal** (~63 s). Berkas tes yang ikut dipensiunkan
(`git rm`): `test_early_dump.py`, `test_high_drop.py`, `test_exit_cutloss.py`,
`test_alert_gating.py`, `test_volume_validation.py`. Baru:
`tests/test_strategy_shift.py` (26 tes + 13 subtests). Ditulis ulang:
`tests/test_telegram_alerts.py` (32). Diperbaiki ikut menyesuaikan:
`test_alert_pipeline.py`, `test_manual_scan_alerts.py` (19), `test_scan_holders.py`,
`test_robinhood_dust_coverage.py`, `test_holder_status.py`, `test_store_backup.py`,
`test_alert_settings.py`, `test_lp_card_ui.py`.

Bug produk yang ketemu **berkat tes**, bukan tesnya yang diubah:
`evaluate_strategy_shift_rule` dulu mensyaratkan `since_ts` untuk
"in-episode", padahal `compact_alert_state` bisa membuangnya → marker hasil
state terkompaksi diperlakukan sebagai episode baru dan teks
"baru melewati ambang" muncul terus. Sekarang `since_ts = marker["since_ts"]
or marker["ts"]` (fallback sama di `strategy_shift_marker_next`).

Dokumen yang disamakan: `README.md` (seksi alert, "Konteks pasar di pesan",
format contoh pesan, tabel konstanta), `AGENTS.md` (bullet scan-manual,
`alert_settings`, cron, `telegram_alerts`, tabel angka kunci, konvensi
tooltip), `DEPLOY.md`.

# Kegiatan — 10 September 2026 (scan best jadi tooltip, kredit Helius di 🧾, budget waktu Scan Best Robinhood dihapus)

Tiga permintaan user sekaligus (sesi sebelum tidur — "nanti kalau sudah
selesai langsung create pr dan merge saja"):

1. *caption rule* **🏆 Scan Best Pool Meteora** dan **🦅 Scan Best Robinhood
   Coin** → *"ini juga bikin tooltip saja"*,
2. **🧾 Log Aktivitas** → *"tampilkan juga berapa kredit tersisa dari helius
   key kita"*,
3. **🦅 Scan Best Robinhood Coin** → *"hapus timeoutnya, gak papa ternyata
   tadi masalahnya holdernya sangat banyak, jadi agak lama memang
   fetchingnya"*.

## 1 · Detail card scan best = tooltip judul (bukan caption)

- `best_pool_ui.py`: `st.caption(...)` berisi seluruh ambang **dihapus**;
  gantinya `best_pool_tooltip()` yang **menyusun teks dari konstanta**
  `meteora_screener.BEST_*` saat dipanggil. Sebelumnya tooltip ini teks
  hardcoded, jadi angka bisa basi; sekarang ubah ambang = tooltip ikut
  berubah. Yang tersisa di badan card hanya rekap hasil scan
  (`N pool lolos · M disembunyikan · listing K pool`) — itu data.
- `robinhood_best_scan.py`: konstanta `CAPTION` + `st.caption(CAPTION)`
  dihapus, isinya (endpoint rank GMGN, filter, urutan, Dexboost, honeypot,
  tombol 📋/⭐, cron ±5 menit) digabung ke `RH_SCAN_TOOLTIP` yang sudah
  membaca `RH_SCAN_MAX_*`.
- Tes: `test_best_pool_scan.py` **16 → 18** (teks rule ada di
  `title="…"` pada judul dan TIDAK lagi di caption; tooltip dibangun dari
  konstanta sehingga ikut berubah kalau `BEST_DUST_MAX_PCT` diubah) dan
  `test_robinhood_best_scan.py` **27 → 29** (`title="Listing GMGN Robinhood
  Chain…"`, caption rule hilang, caption rekap hasil tetap ada).
- `tests/test_temp_page.py`: cek "card temp tidak muncul di halaman utama"
  dipindah dari *string nama card di body* ke *kepala card* `…</span>` +
  label tombol scan, karena tooltip card Best Pool memang menyebut nama
  listing yang direplikanya (dan teks tooltip sengaja tidak memakai emoji +
  nama persis itu).

## 2 · 🧾 Log Aktivitas: sisa kredit key Helius

Baris baru di bawah status pool Blockscout, contoh:

```
Helius API: 2 key · key#1 (wallet-depth) kredit tersisa 812,345 dari
1,000,000 (pakai 18.8%) · ±1,204 request sesi ini · dicek 3 mnt lalu
```

- `core.py` (modul pemilik pool key — bukan UI): `helius_key_status()`
  memprobe metadata key `GET https://api.helius.xyz/v0/keys` per key di pool
  (fallback `mainnet.helius-rpc.com/v0/keys`), `parse_helius_credits()`
  menerima **semua** bentuk respons plan (objek `{total, used, available}`,
  angka tunggal, field datar `creditsRemaining`, string berpemisah ribu) dan
  mengembalikan `None` bila Helius tidak lapor; `total` & `used` → sisa
  dihitung, bukan ditebak. Persentase memakai `used` bila ada, jika tidak
  `(total - remaining) / total`.
- **Key tidak pernah bocor**: pesan error di-*scrub* (`api-key=…` →
  `api-key=***`), baris hanya berisi `key#N` + nama key dari Helius.
- **Kredit per project, bukan per key** — beberapa key satu project melaporkan
  plafon yang sama, jadi nilainya **tidak dijumlah** (didedup;
  `helius_credit_remaining()` menjumlah nilai unikat).
- Render non-blokir: `helius_usage_summary()` dipakai panel log lewat
  `helius_usage_status(background=True)` → **tidak pernah memblokir render**: cache
  ±5 menit (`HELIUS_USAGE_TTL_SEC`, env) dibaca, dan bila basi satu thread
  daemon (`refresh_helius_usage_async`, guard `_helius_usage_inflight`)
  mengisinya; angka muncul pada auto-refresh ±60 dtk berikutnya. Cron/tes bisa
  minta probe inline (`background=False`).
- Level log: kredit `0` atau key ditolak 401/403 → **❗ `action`** (merah bold,
  sesuai konvensi "perlu perubahan manual"); tidak bisa dihubungi / kredit
  menipis ≥ 90% → ⚠️ `warn` (dedup 30 mnt supaya rerun tidak banjir).
  Plan yang tidak mengirim angka kredit → tidak ada entri log, hanya caption
  "Helius tidak mengirim angka kredit untuk plan ini (sisa hanya terlihat di
  dashboard.helius.dev)" + hitungan request lokal.
- Pelengkap baru lain: `helius_request_count()` — dihitung di
  `helius_rpc_request()`/`helius_api_get()` saat request sukses, jadi "±N
  request sesi ini" selalu benar walau Helius tidak mengirim angka.
- Suite offline: `tests/__init__.py` menyetel `HELIUS_USAGE_PROBE=0`
  (kill-switch `core._helius_probe_enabled()`); tes yang menguji transport
  menyalakannya sendiri lewat `mock.patch.dict`.
- **Perbaikan berbarengan (bug nyata yang membuat angka "sisa kredit" tak akan
  pernah terbaca)**: urutan pool key jadi *eksplisit → config passed →
  Streamlit secrets → env → config.json* dan placeholder
  `PASTE-API-KEY-KAMU-DISINI` disaring `_KEY_PLACEHOLDER_RE`. Sebelumnya
  `config.json` (berisi placeholder, ikut ter-bundle di Streamlit Cloud)
  menang atas secrets, `merge_helius_keys` first-wins, dan
  `helius_rpc_request` **tidak** rotation-fallback pada HTTP 401 — tiap scan
  holder mati walaupun key valid terpasang.
- Tes baru `tests/test_helius_usage.py` (**32**) — parser bentuk kredit,
  scrub key,
  cache/TTL + invalidasi saat daftar key berubah, kill-switch offline,
  fallback host kedua, level log per kejadian, teks summary (termasuk plafon
  dibagi beberapa key), urutan sumber key, counter request, dan AppTest
  halaman utama yang memastikan caption Helius benar-benar dirender.

## 3 · Budget waktu Scan Best Robinhood dihapus

- `scan_candidates()`: `CANDIDATE_TIMEOUT_SEC = 300`, `deadline =
  time.monotonic() + …`, `wait(FIRST_COMPLETED)`, `shutdown(wait=False,
  cancel_futures=True)` dan param `timeout_sec` **dihapus** →
  `with ThreadPoolExecutor` + `as_completed(futures)` tanpa timeout. Kandidat
  ber-holder puluhan ribu tidak lagi ditandai "gagal/lewat budget"; hasil
  scan tidak kehilangan baris, hanya butuh lebih lama (sesuai keputusan user).
  Entri log `kandidat lewat budget … dan dilewati` ikut hilang.
- Yang **tidak** ikut dihapus: timeout HTTP per request GMGN
  (`_get_json(timeout=25)`), `CSV_TIMEOUT` Blockscout 90 dtk, `PAGE_SLEEP_SEC`,
  dan masa parkir key PRO (401/402/403/429) — itu proteksi koneksi/kuota,
  bukan batas umur scan. `timeout-minutes: 15` di workflow cron juga tetap
  (watchdog Actions; scan best hanya jalan dari tombol UI).
- Tooltip card sekarang jujur soal durasi ("semua kandidat ditunggu sampai
  selesai … bisa makan waktu puluhan menit"); label progress `sedang: SYMBOL
  (+N lagi)` tetap supaya scan panjang tidak kelihatan hang.
- Tes: `ScanCandidatesTest` dibalik — `test_kandidat_lambat_dilewati_setelah_budget`
  (dulu menuntut kandidat lambat dibuang) jadi
  `test_kandidat_lambat_tetap_ditunggu_sampai_selesai`, plus
  `test_scan_candidates_tidak_menerima_budget_waktu` yang membaca sumber
  modul: `timeout_sec` / `deadline` / `CANDIDATE_TIMEOUT_SEC` tidak boleh
  muncul lagi.

Catatan hasil: `python -m unittest discover tests` → **1138 tes** (sebelumnya
1102: +2 Best Pool, +2 Best Robinhood, +32 Helius) — lulus kecuali 2 tes
`test_scan_holders` (DurableStoreBackup + EarlyDumpScope) yang **sudah gagal
di HEAD sebelum perubahan ini juga** (polusi state antar tes saat whole-suite
discover — store/watchlist betulan; lolos kalau modulnya dijalankan sendiri),
jadi bukan efek perubahan ini.

# Kegiatan — 10 September 2026 (grid 2 kolom: scan best di bawah watchlist chain-nya)

Permintaan user: *"🏆 Scan Best Pool Meteora dibawah 🌊 Watchlist
Meteora; 🦅 Scan Best Robinhood Coin dibawah 🦅 Watchlist Robinhood —
kita edit tampilannya, menjadi 2 grid."*

- `app.py`: kedua card scan best pindah **masuk ke grid 2 kolom** —
  kolom kiri = 🌊 Watchlist Meteora + 🏆 Scan Best Pool Meteora, kolom
  kanan = 🦅 Watchlist Robinhood + 🦅 Scan Best Robinhood Coin. Dulu
  keduanya full-width di bawah grid (Best Pool sebelum Scan Holder,
  Best Robinhood setelahnya). 🛰 Scan Holder dan 🧾 Log Aktivitas tetap
  full-width di bawah grid. Tidak ada perubahan logika scan/render card
  — hanya penempatan (listing di dalam card memakai kolom relatif, jadi
  aman menyempit setengah lebar).

# Kegiatan — 10 September 2026 (🧾 Log Aktivitas + scan "macet 6/7")

User melaporkan **Scan Best Robinhood macet di 6/7** dan **Scan Holder
biasa Robinhood ikut lambat** ("apakah kena limit? di 4 API semuanya?").
Diagnosa: bukan hang — kandidat terakhir jatuh ke paginasi RPC Blockscout
(400 wallet/halaman + jeda 0,6 dtk; token 80-100rb holder ≈ 10-15 menit),
sementara progress bar hanya di-update saat kandidat **selesai**
(`as_completed`) jadi terlihat diam. Scan Holder biasa melambat karena
**pool key PRO Blockscout dipakai bersama** oleh semua card dalam satu
proses; 6 worker Scan Best menabrak 5 RPS/key → key diparkir berantai →
request jatuh ke instance publik yang lambat.

Perbaikan (permintaan user: progress jujur + budget waktu + **log**):

- **`activity_log.py` (modul baru)** — ring buffer in-memory thread-safe
  (400 entri, dedup 60 dtk → `×N`), 4 level: `info` / `warn` / `error` /
  **`action` = perlu perubahan manual user → merah bold** (permintaan
  user eksplisit). Panel **🧾 Log Aktivitas** dirender di **paling bawah
  `app.py`**; kepala panel menampilkan pill jumlah per level +
  `pro_key_summary()` (status per key PRO: sisa kredit / parkir) —
  jawaban langsung "kena limit di key mana".
- **Instrumentasi**: `robinhood_holders` (key diparkir 401/402/403 =
  action, 429 = warn; semua key parkir → fallback publik = warn; 403
  bot-protection = action dengan petunjuk key; hasil fetch holder per
  token: sukses/terpotong/gagal), `robinhood_best_scan` +
  `meteora_screener` (scan mulai/selesai/listing gagal),
  `helius_holders` (key hilang = action, scan gagal = error),
  `watchlist._github_push` (token hilang = action, push gagal = error).
  Semua `import activity_log` dibungkus try/except — cron/tes tanpa
  modul/Streamlit tetap jalan.
- **`scan_candidates` (Scan Best Robinhood)**: progress dipanggil juga
  saat kandidat **mulai** dengan label `sedang: SYMBOL (+N lagi)` — 6/7
  tidak lagi terlihat seperti hang; **budget waktu per scan**
  (`CANDIDATE_TIMEOUT_SEC = 300` dtk): kandidat yang lewat budget
  dilewati (dicatat di log), thread telatnya dibiarkan selesai di latar
  (`shutdown(wait=False)` — sengaja bukan `with ThreadPoolExecutor` yang
  `shutdown(wait=True)`).

Tes: `tests/test_activity_log.py` (16) + 3 tes `scan_candidates`
(timeout/progress) → **1102 lulus** (71 dtk).

# Kegiatan — 10 September 2026 (Scan Best Robinhood Coin di halaman utama)

Permintaan user: *"buatkan saya Scan Best Coin Robinhood — datanya dari
gmgn … ini pakai volume 6 jam terakhir; sortnya: %dust paling kecil,
volume paling besar; hanya tampilkan yang top holder dibawah 30%; jika
pernah ada dexboost, menjadi poin tambah; hanya tampilkan yang %dust
<= 0,05%; buat di main app, seperti scan meteora pool; kasih nama Scan
Best Robinhood Coin; kasih tombol copy CA, add watchlist ke watchlist
robinhood."*

- Modul baru `robinhood_best_scan.py` + card **🦅 Scan Best Robinhood
  Coin** di halaman utama (`app.py`, full-width di bawah Scan Holder);
  bentuk meniru **Scan Meteora Pool** (tombol scan + progress, hasil di
  `session_state`, ⭐ per baris) + input "Jumlah kandidat" (default 50,
  sesuai `limit=50` di curl user).
- Sumber data: **endpoint rank publik GMGN** (diverifikasi live
  2026-09-10, tanpa auth): `GET
  /defi/quotation/v1/rank/robinhood/swaps/6h?orderby=volume&direction=
  desc&limit=N` → `data.rank[]` sudah berisi `top_10_holder_rate` +
  penanda Dexboost (`dexscr_boost_ts` / `dexscr_boost_fee`). Endpoint
  `follow_token/following_group_tokens` dari curl user **tidak dipakai**
  — butuh Bearer token user (hidup ±30 menit) dan hanya mengembalikan
  token yang di-follow; dicatat di `docs/gmgn_api.md`.
- Dust % MC dari **Blockscout** via `robinhood_holders.analyze_token`
  (FULL 100.000, LP/pool disingkirkan; harga + MC dari baris GMGN agar
  rasio konsisten dengan listing, `fetch_market` hanya untuk metadata
  pool). Rule: **top 10 holder < 30%** + **dust ≤ 0,05% MC** (nilai
  0,05% tepat ikut tampil), honeypot dikeluarkan; urut **dust % MC
  terkecil → volume 6 jam terbesar** (deterministik, tie simbol A-Z).
  Pernah Dexboost = **poin tambah**: badge 🚀 DEXBOOST + rekap di kepala
  card (bukan kunci sort).
- Baris: kolom Token/MC/Vol 6J/Liq/Holders/Top10/Dust %MC + tombol **📋
  copy CA** (JS clipboard + fallback; dirender `st.iframe` karena
  markdown Streamlit men-trip `<script>`; `st.components.v1.html` sudah
  deprecated di 1.61) dan **⭐ tambah ke Watchlist Robinhood LP**
  (halaman utama, scan cron ±5 menit; tanpa `st.rerun()` — pola ⭐
  Scan Meteora).
- Validasi: 24 test baru `tests/test_robinhood_best_scan.py`
  (normalisasi, filter/ambang, urutan, dexboost, AppTest card + tombol
  scan + ⭐); suite penuh **1067 tests** hijau.
- Catatan utk test: request GMGN/Blockscout **live tidak lulus jaringan
  sandbox** (TLS diputus — batasan yang sudah lama terdokumentasi);
  preview live hanya menampilkan warning "GMGN API: koneksi TLS …".
  Endpoint sudah diverifikasi publik & normal via klien lain; dari
  browser/Streamlit Cloud seharusnya langsung jalan.
  (Permintaan user: selesai dulu, nanti test & rapikan ulang bersama PR
  lain.)
# Kegiatan — 10 September 2026 (🏆 Scan Best Pool Meteora di halaman utama)

Permintaan user: *"replika scan meteora pool, masukkan ke main app page …
ganti filter baru seperti ini"* (curl `filter_by=pool_type=dlmm&&fee_pct>=5
&&active_tvl>=10000`, timeframe 24 jam, category top) — yang ditampilkan
hanya pool dengan dust holder < 0,05% MC, active TVL > 10K, fee/active TVL
> 20%, volatility > 5%, top 10 holder < 30%, total LPs > 20, **diurutkan
dari % dust terkecil lalu volume terbesar** ("ambil yang terbesar dan
terbaik"). Judul card: **Scan Best Pool Meteora**.

- `meteora_screener.py`: blok konstanta `BEST_*` + fungsi baru —
  `best_filter_by()` (menghasilkan `pool_type=dlmm&&fee_pct>=5&&
  active_tvl>=10000` persis filter UI Meteora), `fetch_best_pools()`,
  `rows_from_pools()` (dedup `pool_address`), `row_best_gaps()` (5 metrik
  pool: active TVL, fee/active TVL, volatility, top 10 holder, total LPs),
  `row_dust_ok()` (dust < 0,05% MC), `filter_best_rows()`,
  `sort_best_rows()`, dan `scan_best_meteora()`. Semua syarat **ketat**
  (`>`/`<`): angka pas di ambang tidak lolos, dan data hilang (`None`) juga
  gugur — helper `_maybe_float()` membedakan "nol" dari "tidak ada data"
  (beda dari `_float()` yang menelan `None` jadi 0).
- `_row_from_pool()` kini ikut membawa `volatility`, `total_lps`, dan
  `top_holders_pct` (diambil dari **token base**, bukan sisi quote SOL/USDC)
  supaya saringan baru punya datanya; field lama tidak berubah sehingga
  card **🌊 Scan Meteora Pool** di halaman temp tetap seperti semula.
- Hemat kuota Helius: 5 syarat metrik pool disaring **sebelum**
  `enrich_pools()`, jadi holder hanya di-fetch untuk pool yang masih bisa
  lolos; dust < 0,05% MC baru dicek setelahnya.
- Urutan baris `sort_best_rows()`: **dust % MC terkecil → volume terbesar**.
  Kunci dust dibulatkan ke `BEST_DUST_SORT_DECIMALS` (3 desimal = angka yang
  tampil di card) supaya dua pool yang di layar sama-sama "0,030%" diurutkan
  menurut volumenya; baris tanpa angka dust paling bawah, simbol alfabetis
  sebagai tie-break terakhir (deterministik antar scan).
- Card baru `best_pool_ui.render_best_pool_scan()` dirender full-width di
  **halaman utama** (`app.py`, antara grid watchlist dan 🛰 Scan Holder,
  dipisah `st.divider()`): 12 kolom listing (Token · MC · A.TVL · Fee/TVL ·
  Vol · Top10 · LPs · Fee · Dust · Dust %MC 3 desimal · Pool · ⭐), kepala
  card `card_head_html()` dengan pill jumlah pool + yang disembunyikan, dan
  detail karakteristik di **tooltip judul** (`best_pool_tooltip()`) mengikuti
  konvensi 2026-09-10. Tombol scan: **🏆 Scan Best Pool Meteora + Holder**
  (progress bar holder, hasil di `session_state["best_pool_scan"]`).
- ⭐ memakai `source=meteora` (`lp_watchlist.LP_SOURCE`) → token masuk card
  **🌊 Watchlist Meteora** di halaman utama dan ikut cron ±5 menit; key
  tombol diikat ke pool address, bukan nomor baris (urutan listing berubah
  setelah scan ulang).
- Tidak ada perubahan data/cron/alert: `watchlist*.json`, history, source
  token, jadwal scan, dan rule Telegram tidak disentuh. Card **🌊 Scan
  Meteora Pool** di halaman temp tetap ada dengan filter lamanya (24 jam
  `fee_active_tvl_ratio≥250` + 1 jam `≥1`).
- Validasi: suite penuh **1059 tests** hijau lewat `pytest` (16 test baru di
  `tests/test_best_pool_scan.py`: string `filter_by`, parameter
  `fetch_best_pools`, ekstraksi metrik baru, tiap syarat ketat + boundary
  0,05%/10K/20%/5%/30%/20, `filter_best_rows`, urutan dust→volume termasuk
  tie presisi tampilan, `scan_best_meteora` end-to-end dengan `enrich_pools`
  di-mock — memastikan pool yang gugur di metrik tidak di-fetch holder-nya —
  serta AppTest `app.py` yang memastikan card + tombol + listing terender di
  halaman utama); `python -m py_compile` semua modul daftar AGENTS.md bersih;
  live preview Streamlit port 8501. **Catatan:** API Meteora/DexScreener
  tidak terjangkau dari sandbox ini (TLS ditutup), jadi listing live
  diverifikasi lewat endpoint `pool-discovery-api.datapi.meteora.ag/pools`
  dengan `filter_by` yang sama (32 pool, field `volatility`/`total_lps`/
  `top_holders_pct` ada di response); angka dust tetap butuh `HELIUS_API_KEY`
  saat dijalankan di dashboard.

# Kegiatan — 10 September 2026 (Wallet Depth by Threshold → grafik perubahan dust holder ala Watchlist Meteora)

Permintaan user: *"📊 Wallet Depth by Threshold - ganti seperti pada
**Watchlist Meteor** / Grafik perubahan dust holder"* — expander mandiri
**📊 Wallet Depth by Threshold** (hanya tabel bucket + tier) di baris
watchlist diganti expander grafik seperti card **Watchlist Meteora**; tabel
Wallet Depth tidak dihapus melainkan ikut ter-nested di dalam expander
grafik (persis susunan di Watchlist Meteora).

- Pembuat bersama baru `dashboard_components._render_dust_change(points,
  holders, symbol, interval=…)`: expander **📈 Grafik perubahan dust
  holder — $SYM** berisi grafik `lp_watchlist.lp_chart_figure(...,
  interval=…)` (garis dust % MC + garis ambang HATI-HATI/BAHAYA + batang
  jumlah wallet dust), caption ringkas, lalu `_render_depth` ter-nested
  bila scan menghasilkan `depth`. Pesan "belum cukup titik" mengikuti
  kadens (`_dust_change_empty_note`).
- `lp_watchlist.lp_chart_figure` kini menerima `interval` (default tetap
  `LP_INTERVAL_SEC` = bucket 5 menit, jadi output Watchlist Meteora tidak
  berubah); helper `interval_label()` memberi judul "(5 menit)" /
  "(4 jam)". `resample_5m` di figure diganti `resample_4h(...,
  interval=…)` yang identik untuk default lama.
- Dipakai di tiga card: **🦅 Watchlist Robinhood** LP (bucket 5 menit) +
  Robinhood biasa (bucket 4 jam) di `dashboard_components._render_rh_row`,
  dan **📋 Watchlist Holder** biasa di `temp_ui.py` (bucket 4 jam).
  `_render_lp_row` di `app.py` dipindah ke pembuat yang sama supaya bentuk
  rujukan tidak bercabang (caption/jumlah bucket tetap sama).
- Tidak ada perubahan data/cron/alert: `watchlist*.json`, history, source
  token, jadwal scan, dan rule Telegram tidak disentuh — hanya presentasi
  baris watchlist.
- Validasi: suite penuh **1043 tests** hijau (5 test baru: figure bucket 4
  jam + `interval_label`, AppTest baris Robinhood LP & watchlist biasa
  merender expander grafik + caption); AppTest data asli repo tanpa
  exception (expander grafik tampil di baris $STONK dan $ORBIO); live
  preview Streamlit port 8501.

# Kegiatan — 10 September 2026 (rename card + detail jadi tooltip judul)

Permintaan user: ganti judul card — **🌊 Chart LP — Watchlist Meteora** →
**🌊 Watchlist Meteora**, **🦅 Watchlist Robinhood LP — Holder Dust** →
**🦅 Watchlist Robinhood**, **🛰 Scan Holder Khusus — Helius / Robinhood** →
**🛰 Scan Holder Solana / Robinhood** — dan teks detail karakteristiknya
bukan caption lagi melainkan **tooltip** yang hanya muncul saat kursor
digeser ke tulisan judulnya. Selain itu **🌊 Scan Meteora Pool** dipindah ke
halaman temp dan **Watchlist Robinhood** (LP) pindah ke samping **Watchlist
Meteora**.

- Tooltip = atribut `title="…"` native browser di teks judul, bukan elemen
  tambahan: card memakai `dashboard_components.card_head_html(title, pills,
  tooltip=…)` (atribut menempel di `<span class="lp-title">`), section Scan
  Holder memakai `hover_title_html()` — heading markdown `###` dengan
  `<span title>` supaya styling persis `st.subheader` dan tooltip hanya
  aktif di atas teks (bukan seluruh lebar baris). CSS `cursor:help`
  ditambahkan sebagai hint halus.
- Teks detail hidup di konstanta — `LP_CARD_TOOLTIP` + `SCAN_HOLDER_TOOLTIP`
  (`app.py`), `RH_CARD_TOOLTIP` (`dashboard_components.py`) — dengan ambang
  diambil dari konstanta `holder_history` (`DUST_BEST_PCT`,
  `DUST_CAUTION_PCT`, `DUST_DANGER_PCT`), jadi kalau karakteristik/rule
  berubah tinggal edit konstanta dan angkanya tetap sinkron. Atribut
  `title` tidak mengenal markdown → teks plain (tanpa `**`).
- `app.py`: grid 2 kolom kini **kiri** Watchlist Meteora, **kanan** Watchlist
  Robinhood LP (`_render_rh_card(variant="lp")` dipindah dari full-width ke
  kolom kanan; `split_robinhood_watchlist` naik ke atas grid). Scan Holder
  tetap full-width di bawah `st.divider()`. Label di dalam card LP ikut
  diganti ("Tambah CA manual ke Watchlist Meteora", "Scan sekarang Watchlist
  Meteora", ✕ "Hapus dari Watchlist Meteora", info kosong menunjuk
  **⭐ Scan Meteora Pool di halaman temp (📦)**).
- `temp_ui.py`: `render_meteora_scan()` (pindahan `app.py`, termasuk
  `_meteora_head_html` + `METEORA_CARD_TITLE`) dipanggil sebelum section
  **🔍 Temukan Token**; `card_head_html` kini pembuat kepala bersama.
  ⭐ tetap `add_to_watchlist(..., source=meteora)` — targetnya card
  **Watchlist Meteora** di halaman utama; caption/help di halaman temp
  disinkronkan ("Chart LP" → "Watchlist Meteora").
- `dashboard_components.py`: judul card LP Robinhood menjadi
  `RH_CARD_TITLE = "🦅 Watchlist Robinhood"` (card biasa/temp tetap
  "🦅 Watchlist Robinhood — Holder Dust"); caption LP dihapus dan digantikan
  tooltip, caption card biasa (temp) tidak diubah.
- Tidak ada perubahan data/cron: `watchlist.json`,
  `watchlist_robinhood.json`, source token, jadwal scan ±5 menit, dan rule
  alert Telegram sama persis — hanya judul, teks, dan posisi card.
- Validasi: `py_compile` app/temp_ui/dashboard_components lolos; suite
  penuh **1038 tests** = sama dengan baseline (2 FAIL `test_scan_holders`
  itu pre-existing saat dijalankan `discover`, terbukti ikut muncul di
  `git stash` baseline); AppTest ad-hoc memastikan tiga tooltip ter-render
  di markup (atribut `title` lengkap) tanpa exception; live preview
  Streamlit port 8501. Frontend Streamlit memakai `rehype-raw`, jadi HTML
  inline (termasuk `title`) di dalam heading markdown ikut ter-render.

# Kegiatan — 9 September 2026 (cron 5 menit mati lagi: rantai dipindah ke skrip)

User: *"coba cek kenapa cron tidak berjalan per 5 menit"* (run #1182 selesai
16:40:24 UTC; tidak ada run baru sampai 17:29 UTC ke atas).

## 1. Diagnosa (angka dari `GET /actions/workflows/daily-effort.yml/runs`)

- Repo **publik** (`isPrivate: false`) dan workflow berstatus `active` → bukan
  kuota billing, bukan workflow dinonaktifkan.
- Hari itu `schedule: */5` hanya menghasilkan **4 run** (01:35, 06:41, 11:56,
  16:30 UTC) dari 288 yang dijadwalkan — scheduler GitHub di-throttle, jarak
  antar-kejadian 4,5–5,2 JAM. Bukan anomali baru: `*/15` pernah terukur ±2 jam
  (DEPLOY.md).
- Pola tiap kejadian schedule identik: schedule → **tepat satu** chain dispatch
  → hening (01:35→01:35, 06:41→06:45, 11:56→12:00, 16:30→16:35). Empat stall
  hari itu (01:40, 06:50, 12:05, 16:40 UTC) = empat kejadian schedule.
- Akar masalah: **Guard 2 di `.github/workflows/daily-effort.yml`** — dispatch
  dilewati bila run `event=schedule` terakhir selesai < 900 detik lalu. Chain
  dispatch berjalan ±5 menit setelah schedule, jadi umurnya selalu ~300 detik →
  "schedule */5 sehat" → dispatch dibuang → tidak ada yang membangunkan
  pipeline sampai schedule (telat berjam-jam) berikutnya. Guard lama juga tidak
  mengecualikan run sendiri (query `event=schedule&status=completed&per_page=1`),
  akibatnya run schedule SELALU dispatch dan run dispatch SELALU skip —
  persis rasio 1:1 yang terukur.
- Perbaikan Guard 2 sudah ditulis pagi harinya di `daily-effort-5menit.yml`
  (root repo) tapi **tidak pernah terpasang**: `git push` yang menyentuh
  `.github/workflows/*` ditolak remote (`refusing to allow a GitHub App to
  create or update workflow ... without 'workflows' permission`) — diverifikasi
  ulang hari ini dengan pesan yang sama.
- Temuan tambahan: langkah rantai versi inline bash **fail-closed** — di bawah
  `bash -e`, satu hiccup `curl -sSf` di `ACTIVE=$(…)` membatalkan seluruh
  langkah tanpa dispatch (stall yang sama, penyebab lain), dan daftar run
  queried 2× per run (Guard 1 + Guard 2) padahal cukup sekali.

## 2. Perbaikan

- **`scripts/chain_next_run.py`** (baru, stdlib saja): tidur ke batas kadens →
  SATU `GET …/runs` dipakai Guard 1 (antrean `holder-scanner`) + Guard 2 (umur
  run `completed` terbaru, event apa pun, cabang sama, run sendiri dikecualikan)
  → `POST dispatches`. `CHAIN_QUIET_SEC=240` < kadens 300 supaya rantai tidak
  bisa mematikan dirinya sendiri; API error = **fail-open** (tetap dispatch —
  run ganda sudah disaring `MIN_RUN_GAP_SEC` di scanner); retry 3× GET / 4×
  POST dengan backoff, 400/401/404/422 tidak diulang; dispatch buntu → `exit 1`
  + pesan "rantai TERPUTUS" supaya run merah, bukan hijau tanpa penerus; tanpa
  `GITHUB_TOKEN`/`GITHUB_REPOSITORY` (jalankan lokal) → `exit 0` diam.
- **`daily-effort-5menit.yml`**: langkah "Chain run berikutnya" jadi satu baris
  `python scripts/chain_next_run.py` + env `CHAIN_CADENCE_SEC`/`CHAIN_WORKFLOW`.
  Karena logika pindah ke skrip, yang butuh UI tinggal satu baris YAML;
  alternatif permanen: **Settings → Third-party Access → app bot → Repository
  permissions → Actions Workflows: Read & write**.
- **`tests/test_chain_next_run.py`** (28 test, offline): tabel keputusan guard
  termasuk **regresi stall 2026-09-09** (`active=0`, umur run schedule 299 s →
  wajib dispatch), filter cabang/dirinya, `--quiet-sec ≥ --cadence` dipotong
  otomatis, retry 5xx vs 4xx permanen, fail-open saat API mati, exit 1 saat
  dispatch buntu, dan `next_boundary_wait`.

## 3. Yang harus dilakukan user

1. **Pasang `daily-effort-5menit.yml` ke `.github/workflows/daily-effort.yml`**
   (GitHub UI → Actions → Holder Dust Scanner → edit → timpa dari baris `name:`
   → commit). Tanpa ini Guard 2 lama tetap membuang dispatch.
2. Sembari menunggu, **jalankan "Run workflow" manual** (tanpa centang): rantai
   langsung tersambung lagi — guard lama hanya membuang dispatch bila ada run
   `schedule` selesai < 15 menit lalu, jadi mulai sekarang chain jalan terus
   sampai kejadian schedule berikutnya.

## 4. Batas verifikasi

Sandbox tidak bisa mengunduh log run (`results-receiver`/blob storage diblokir),
jadi pesan guard disimpulkan dari **pola waktu run** (create/update + event),
bukan dari stdout langkah "Chain run berikutnya". Skrip diverifikasi terhadap
API asli read-only (50 run terbaca; `head_branch`, `updated_at`, status
`completed`+conclusion `cancelled` diperlakukan benar) dan jalur fail-open
dengan token palsu (404 → dispatch tetap dicoba, retry tidak dibakar).
Kadens nyata setelah fix terpasang baru terbukti ±1–2 jam di tab Actions.

# Kegiatan — 9 September 2026 (secret GitHub ≠ secret Streamlit)

User: *\"1 alert GAGAL dikirim (Telegram credentials are not configured).
sebentar, saya sudah setting token di secret loh, apa butuh di setting di
streamlit juga?\"*

Ya. Secret **GitHub Actions** (`Settings → Secrets → Actions`) hanya
terlihat cron; scan manual jalan di proses Streamlit Cloud yang tidak
menerima env itu. Perlu **dua** secret di **kedua** tempat:
`TELEGRAM_BOT_TOKEN` **dan** `TELEGRAM_CHAT_ID`. Token bot saja tetap
gagal dengan pesan yang sama.

- `_telegram_credentials()` kini menerima nama key huruf besar
  (`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`, konvensi GitHub/DEPLOY)
  **dan** huruf kecil (`telegram_bot_token` / `telegram_chat_id`) dari
  env, `config.json`, dan `st.secrets` — sebelumnya Streamlit hanya
  membaca huruf kecil, jadi secret yang disalin persis dari GitHub ke
  Streamlit Cloud tidak ketemu.
- DEPLOY.md bagian **Setup Telegram** memisahkan langkah GitHub (cron)
  vs Streamlit Cloud (scan manual) + contoh TOML. AGENTS.md + README
  menyebut pemisahan yang sama.
- Tes baru: secrets Streamlit huruf besar, huruf kecil, dan token tanpa
  chat ID tetap dilaporkan belum terpasang.

# Kegiatan — 9 September 2026 (MOO 0,11% tanpa alert: cron mati + scan manual bisu)

Laporan user: `0xc103ac00a25173870c909223c5676d50bf5728b2` (MOO) menampilkan
**0,11% MC** di card Robinhood tetapi tidak ada pesan Telegram.

## 1. Diagnosa (semua angka dari API GitHub, bukan asumsi)

- Token **benar** ada di lane LP: `watchlist_robinhood.json` di `main`
  (commit `3c537ff`, 2026-09-09T21:53:20+07:00 = **14:53:20 UTC**) memuat MOO
  dengan `source: "lp"` — jadi scope rule ⚡ EARLY DUMP mencakupnya.
- **Cron berhenti**: run workflow `Holder Dust Scanner` terakhir selesai
  **2026-09-09T12:05:24Z**; tidak ada run lagi sampai 15:16 UTC (±3 jam)
  meski jadwalnya `*/5 * * * *`. Hari itu schedule GitHub hanya menyala 3×
  (01:35, 06:41, 11:56 UTC), masing-masing diikuti **tepat satu** chain
  dispatch lalu hening. MOO baru masuk watchlist **14:53 UTC**, jadi cron
  belum pernah memindainya sama sekali → tidak mungkin ada alert.
- Snapshot Robinhood di ref `holder-live` terakhir
  **2026-09-08T03:56:11Z** dan hanya berisi CME. Ini **bukan** lane rusak:
  pada run 11:56 UTC watchlist Robinhood di `main` masih `{}` (PARE baru
  ditambah 13:24 UTC, NUDES 14:01 UTC), jadi scanner memang mencetak
  "watchlist LP kosong".
- **Akar masalah ritme**: langkah "Chain run berikutnya" punya Guard 2 yang
  menyimpulkan "schedule */5 sehat" bila ada run `event=schedule` yang
  selesai < 900 detik lalu, lalu **melewati dispatch**. Scheduler GitHub bisa
  di-throttle berjam-jam, jadi begitu satu dispatch dilewati tidak ada lagi
  yang membangunkan pipeline. Dibuktikan dengan data run asli: pada
  12:05:24Z umur run schedule terakhir 299 detik → guard lama
  `299 < 900` = lewati (stall), guard baru `299 ≥ 240` = dispatch.
- **Scan manual tidak pernah mengirim alert**: `process_holder_alerts`
  hanya dipanggil `scripts/scan_holders.py`; tombol scan di dashboard cuma
  `publish_scan(..., push=False)`. Angka 0,11% yang dilihat user berasal
  dari scan manual itu — tampil di dashboard, tidak pernah jadi pesan.
- Rule-nya sendiri sehat: simulasi `process_holder_alerts(lp_mints={MOO},
  volume_rules=False)` dengan dust 0,11% MC menghasilkan 1 event
  ⚡ EARLY DUMP (tanpa `lp_mints` → 0 event).

## 2. Perbaikan

- **Scan manual ikut mengirim alert** (permintaan user). Tiga tombol —
  Chart LP Meteora (`app.py`), Robinhood LP/biasa
  (`dashboard_components._render_rh_card`), watchlist biasa Solana
  (`temp_ui.py`) — memanggil `process_holder_alerts` **sebelum**
  `ingest_many`/`publish_scan`, jadi rule membaca anchor lama dan state
  (`sent_event_ids`/`last_sent`/marker episode) ikut tersimpan bersama titik
  baru. `volume_rules=False`: hanya rule lane (⚡ EARLY DUMP + eskalasi EXIT
  di LP, 🔔 HIGH DROP di lane biasa), anchor 4 jam cron tidak digeser.
  `mute_mints` mengikuti tombol on/off notif watchlist biasa.
- **Hasil kirim dilaporkan ke UI** (`_store_alert_note` /
  `_render_alert_note`, lewat `session_state` karena tiap tombol langsung
  `st.rerun()`): "⚡ 1 alert Telegram dikirim", "dilewati (notif watchlist
  biasa OFF)", atau "**GAGAL dikirim** (alasan)" — kegagalan tidak lagi
  terbaca seperti "tidak ada sinyal".
- **Kredensial Telegram** dibaca `env → config.json → st.secrets`
  (`telegram_alerts._telegram_credentials()`, lazy + guarded karena runner
  Actions hanya memasang requests + curl_cffi). Dashboard tidak punya env
  Actions, jadi tanpa ini scan manual selalu gagal kirim.
- **Guard 2 chain dispatch** di `daily-effort-5menit.yml`: pembandingnya run
  terakhir **event apa pun** dengan jendela `CHAIN_QUIET_SEC=240` (< kadens
  5 menit), bukan umur run schedule 900 detik. Aman dari stall karena
  langkah ini tidur sampai batas 5 menit berikutnya, jadi satu run minimal
  ±320 detik — run yang baru selesai pasti lebih tua dari jendela.

## 3. Yang harus dilakukan user

1. **Salin `daily-effort-5menit.yml` ke `.github/workflows/daily-effort.yml`**
   lewat GitHub UI (bot ditolak menulis folder workflow: tanpa izin
   `workflows`). Selama belum disalin, cron tetap memakai Guard 2 lama dan
   bisa mati berjam-jam lagi.
2. Pasang **`telegram_bot_token` + `telegram_chat_id`** di secrets Streamlit
   (atau `config.json`) bila ingin notif dari scan manual; tanpa itu UI kini
   menampilkan "GAGAL dikirim (Telegram credentials are not configured)".
3. Untuk memicu scan sekarang: Actions → "Holder Dust Scanner" → **Run
   workflow** (MOO sudah di lane LP, jadi ⚡ EARLY DUMP langsung terkirim
   bila dust masih > 0,1% MC).

## 4. Validasi & batas verifikasi

- **1007 passed, 37 subtests passed** (991 baseline + 16 tes baru di
  `tests/test_manual_scan_alerts.py`: ringkasan kirim, fallback kredensial
  config.json/env, scan manual Chart LP mengirim ⚡ di 0,11% dan diam di
  0,05%, 🚨 EXIT/CUTLOSS saat naik 3× berturut, ✅ KEMBALI KE TITIK AMAN saat
  turun ≤ 0,1% MC, dedup bucket 5 menit antar scan manual, state alert ikut
  tersimpan, Robinhood LP mengirim ⚡, lane biasa memakai 🔔 HIGH DROP, dan
  mute saat notif OFF).
- Tabel karakteristik → notif diverifikasi dengan menjalankan
  `process_holder_alerts` langsung (fungsi yang dipanggil tombol scan
  manual): 0,11% → ⚡; 0,05% dan tepat 0,10% → diam; naik 3× dalam 15 menit →
  ⚡ + 🚨 `exit_cutloss`; turun ke 0,08% dalam jendela episode → ✅
  `safe_return`; high 0,80% → 0,20% → 🔔; high 0,80% → 0,50% → diam; holder
  10 wallet (scan tidak layak) → diam; notif biasa OFF → mute.
  Catatan: marker episode **wajib** bersarang di
  `alert_state["early_dump"]` (dan 🔔 di `alert_state["high_drop"]`) — bentuk
  yang salah membuat rule episode tidak pernah melihat episodenya; dua tes
  baru mengunci bentuk itu.
- Log run Actions **tidak terbaca** dari sandbox (unduh log `EOF`), daftar
  secret repo **403**, dan API live Blockscout/DexScreener tidak terjangkau
  (egress sandbox hanya GitHub/PyPI) — jadi penyebab pasti kosongnya lane
  Robinhood di run-run sebelumnya disimpulkan dari isi watchlist per commit +
  timestamp snapshot, bukan dari log.

# Kegiatan — 9 September 2026 (header dihapus + grid 2 kolom)

Permintaan user: buang header penjelasan di atas halaman utama, lalu
tampilkan **Chart LP — Watchlist Meteora** di kiri dan **Scan Meteora Pool**
di kanan sebagai grid 2 kolom.

- `app.py`: blok `.hero` (judul 🧮 Wallet Depth + ringkasan ambang) dihapus;
  halaman sekarang mulai dari tautan 📦 temp + toggle auto-refresh. Card
  Chart LP dan Scan Meteora dirender berdampingan lewat
  `st.columns([1, 1], gap="medium")` — dua card ber-`border` sejajar, ⭐ di
  kanan tetap memasukkan token ke card kiri. Robinhood LP dan Scan Holder
  Khusus tetap full-width di bawah, dan `st.divider()` dipindah ke sebelum
  card Robinhood (divider milik Scan Meteora hilang bersama subheader-nya).
  Di layar sempit kolom Streamlit menumpuk sendiri.
- `_render_meteora_scan()`: `st.divider()` + `st.subheader` diganti
  `st.container(border=True)` + kepala `_card_head_html()` (helper baru,
  dipakai juga oleh `_lp_head_html`) dengan pill `N pool` / `🏆 N BEST` /
  `N disembunyikan`. Hasil scan disimpan ke `session_state` lalu
  `st.rerun()` supaya pill, caption, dan listing satu sumber data — pola
  yang sama dengan tombol Scan di card LP. Kolom tabel, badge 🏆 BEST POOL,
  filter dust ≤ 0,1% MC, urutan `sort_rows()`, dan key tombol tidak berubah.
- `dashboard_components.py`: CSS `.hero` dihapus (sudah tidak ada pemakai).
- Teks petunjuk ikut disinkronkan: "Scan Meteora Pool **di bawah**" →
  "**di kolom kanan**", "⭐ … ke card Chart LP di bagian atas dashboard" →
  "di kolom kiri"; AGENTS.md + docstring `lp_watchlist` diperbarui.
- Validasi: **991 passed, 37 subtests passed** (sama dengan baseline
  sebelum perubahan), `py_compile` daftar modul AGENTS.md lolos, dan
  AppTest ad-hoc memastikan grid benar-benar 2 kolom (kolom 0 = card Chart
  LP + form/tombol scan LP, kolom 1 = card Scan Meteora + ⭐) tanpa
  exception. Live preview Streamlit port 8501; scan live Meteora/Helius
  tidak dijalankan dari sandbox (tanpa API key), jadi preview menampilkan
  listing kosong sampai tombol scan ditekan.

# Kegiatan — 9 September 2026 (halaman temp)

Permintaan user: parkir tiga section yang sementara tidak digunakan ke
halaman baru bernama **temp**.

- `pages/8_temp.py` (`/temp`) + `temp_ui.py`: Robinhood biasa/non-LP,
  Watchlist — Analisa Holder (Dust), dan Temukan Token (Trending/Degen).
  Data dan kontrol tambah, scan, pindah lane, hapus, serta setelan Telegram
  tetap tersedia. Scan manual hanya lane yang tampil, bukan token LP di
  halaman lain; snapshot lain tetap di-merge.
- `app.py`: hanya Chart LP Meteora, Scan Meteora, Robinhood LP, dan Scan
  Holder Khusus. Tautan **📦 temp** di atas; halaman temp memiliki tautan
  kembali. Tidak mengubah source token, store, cron, atau setelan alert.
- `dashboard_components.py`: presentasi/CSS dan card Robinhood bersama;
  loader data menjaga store Solana/Robinhood dan overlay manual. Tidak
  mengimpor/menjalankan halaman utama untuk membuka temp.
- AppTest lama diarahkan ke halaman baru sesuai section; 9 tes navigasi,
  pembagian layout, persistensi, scan per lane (Robinhood tetap 100.000),
  default form, dan pindah token antarhalaman ditambahkan.
- Validasi: **991 passed, 37 subtests passed**, py_compile dan pemeriksaan
  import/nama tidak terdefinisi lolos. Live preview Streamlit port 8501.

# Kegiatan — 9 September 2026 (PARE: cakupan scan watchlist)

Laporan: PARE `0x15d36b6a28d8327abc7afabf0f106ae2c9af5c4d`
0,00% di watchlist vs 0,03% di Scan Holder Khusus.

- Akar masalah kode: cap watchlist Robinhood 2.000 / cron 3.000 berbeda
  dari scan khusus 100.000. Urutan saldo terbesar Blockscout memotong ekor
  dust. Tombol dan cron Robinhood sekarang 100.000; budget workflow
  `--max-wallets` hanya untuk Solana. Default modul Robinhood juga 100.000.
- Penanda `truncated` diperbaiki untuk CSV capped/counters tak lengkap,
  RPC gagal setelah sebagian halaman, dan batas halaman v2. Alasan hasil
  parsial diteruskan; guard bersama menolaknya dari snapshot, angka baris,
  grafik, dan alert, termasuk history lama bertanda truncated. Data lama
  tidak diubah; memakai hasil lengkap terakhir atau belum ada data.
- Tes baru mereproduksi cap 2.000/3.000 → 0,00% dan lengkap → 0,03%
  memakai fixture sintetis 3.300 holder. Wiring tombol UI dan cron lama,
  fallback provider, publish/history, dan guard alert ikut diuji.
- Validasi: **982 passed, 36 subtests passed**, py_compile sukses.
  API live tidak terverifikasi dari sandbox karena kegagalan TLS; angka
  0,03% produksi berasal dari laporan user, bukan hasil scan live sesi ini.
  Tidak mengubah workflow atau file status/history produksi.

# Kegiatan — 9 September 2026 (sesi 12 · 📨 Telegram: judul 50 bin + hyperlink)

Permintaan user: judul eskalasi diganti menjadi **"🚨 WAKTUNYA EXIT /
CUTLOSS / Reshape bid-ask 50 bin"** (dulu 25 bin), dan baris link
`🔗 GMGN: https://gmgn.ai/sol/token/<mint>` / `🦆 DexScreener: https://…`
diganti **hyperlink** saja, bukan URL polos.

- `telegram_alerts.ESCALATION_TITLE` → "… 50 bin".
- `build_alert_message(event)` baru → `(teks, entities)`: baris link hanya
  `"<emoji> <label>"` dan label diberi entity `text_link` Bot API (offset /
  length UTF-16, sama seperti entity `bold` judul EXIT yang sudah ada).
  Berlaku untuk semua jenis alert dan semua link: GMGN, DexScreener,
  Meteora, HawkFi (LP), rh-scan, Blockscout (Robinhood). `send_telegram_alert`
  memakai builder ini; `format_alert_message()` sekarang hanya teksnya
  (dipakai log/tes). Tanpa mint → tanpa baris link & tanpa entity.
- `links.token_links(ca)` → `[(emoji, label, url)]` sebagai satu sumber;
  `token_link_lines()` (teks polos) tetap ada untuk log/CLI, tidak lagi
  dipakai Telegram. `telegram_alerts._pool_links()` padanannya untuk pool.
- Tes diperbarui: `test_telegram_alerts.py` (helper `_utf16_slice`/`_links`
  memverifikasi label & URL tiap entity, offset tepat walau symbol/mint
  beremoji, alert lain tanpa bold, test alert tanpa entities),
  `test_exit_cutloss.py`, `test_early_dump.py`. **Suite penuh 969 passed.**
- README (contoh pesan + catatan hyperlink), AGENTS.md.

# Kegiatan — 9 September 2026 (sesi 11 · 🦅 Blockscout PRO API: beberapa key sekaligus)

Pertanyaan user: *"1 api cukup atau tidak? atau beberapa api sekaligus?"* →
hitungan: ±3 request Blockscout per token per scan (getToken + counters +
CSV ≈ 60–80 kredit), cron 288 run/hari, free tier 100K kredit/hari & 5 RPS
**per akun** → 1 key cukup untuk ≤ 3–4 token LP; token > 10.000 holder
(paginasi RPC) atau watchlist lebih besar butuh lebih. Key tambahan dari
akun yang **sama** tidak menambah kuota. User: *"saya sudah punya 4 key,
kita menggunakan lebih dari 1 key, tolong bikinkan"*.

## 1. `robinhood_holders.py`: pool key PRO (`_ProKeyPool`)

- `get_pro_api_keys()` menggabungkan semua sumber (pola
  `core.get_helius_keys`, memakai `merge_helius_keys`): env
  `BLOCKSCOUT_API_KEY` / `BLOCKSCOUT_API_KEYS` (koma/baris baru) /
  `BLOCKSCOUT_PRO_API_KEY` → `blockscout_api_key` / `blockscout_api_keys`
  di `config.json` → Streamlit secrets nama sama; dedup, urutan = label
  `key#1..N`. `get_pro_api_key()` tetap ada (key pertama).
- `_pro_round()`: round-robin di antara key **aktif**; `ProApiError`
  401/403 → parkir 60/5 mnt, 402 kredit habis → parkir 30 mnt (probe ulang
  murah karena reset harian Blockscout tidak berjam tetap), 429 → parkir
  sesuai `x-ratelimit-reset` (≤ 60 dtk); request langsung pindah ke key
  berikutnya di putaran yang sama tanpa backoff. 404 rute → publik.
  Semua key diparkir → `ProKeysParked` → publik. Sisa kredit dibaca dari
  `x-credits-remaining`. Thread-safe (ThreadPool `scan_watchlist`);
  `clear_holder_cache()` juga me-reset pool.
- Pelaporan tanpa bocor key: `pro_key_status()`, `pro_key_summary()`
  (*"Blockscout PRO API: 4 key · key#1 sisa 90,850 kredit, 5 req · key#2
  parkir 402 kredit habis (30 mnt) · …"*), `WARN` sekali per key di stderr.
  Hasil `fetch_holders` bertambah `pro_key` (label yang dipakai) &
  `pro_keys` (jumlah key); `analyze_token` meneruskannya ke `holders`.
- `BlockscoutBlocked` punya `hint` terpisah: tanpa key → "pasang
  BLOCKSCOUT_API_KEY"; key ada tapi PRO ikut gagal →
  `HINT_KEYS_FAILED` ("key PRO API ada tetapi semuanya ditolak / kreditnya
  habis — periksa dashboard") + detail `PRO: PRO API 402 … (key#4)`.

## 2. UI, cron, konfigurasi

- `app.py`: caption *Blockscout (Robinhood Chain) · PRO API key#3*; pesan
  `scan_failed`+`blocked` dibedakan: 0 key → "Pasang `BLOCKSCOUT_API_KEY`
  …", N key → "N key PRO API terpasang tetapi semuanya ditolak / kredit
  hariannya habis — cek dashboard … atau tambah key akun lain ke
  `BLOCKSCOUT_API_KEYS`"; baris watchlist ikut. `pages/5_🧮_Holder.py`
  sama.
- `scripts/scan_holders.py`: `blockscout_pro_keys=N` di baris rencana,
  `WARN` bila 0 key, ringkasan pool setelah scan, `route=` dari label.
- Workflow (`daily-effort-5menit.yml` + `.github/workflows/daily-effort.yml`)
  meneruskan `BLOCKSCOUT_API_KEYS`; `config.example.json` +
  `blockscout_api_keys`.

## 3. Tes & dokumen

- `tests/test_robinhood_transport.py` +12 (31 total): sumber key
  (env daftar, config dua nama, secrets list/string), round-robin, 402 →
  parkir & pindah key, 429 sesuai header, probe ulang setelah parkir,
  semua key gagal → publik + pesan "key habis" tanpa bocor key, label key
  di hasil/analyze_token, pool dibangun ulang saat daftar key berubah.
  `tests/test_rh_card_ui.py` +2 AppTest. **Suite penuh 965 passed** (1
  flaky lama `test_watchlist_clear` lulus saat diisolasi).
- Dok: DEPLOY.md bagian baru **Setup key Blockscout PRO API** (langkah
  Streamlit Cloud + GitHub), README (paragraf + tabel env), AGENTS.md,
  `docs/robinhood_holders_api.md` (diagram pool).

# Kegiatan — 8 September 2026 (sesi 10 · 🦅 Blockscout 403 → PRO API + fallback publik)

Laporan user: Scan Holder Khusus untuk CA Robinhood
`0x1209ec401498a1b781412576c978eee0daa0bb6e` pulang *"Scan tidak
menghasilkan holder. Pastikan CA valid dan harga token tersedia
(DexScreener). Detail: getToken: 403 Client Error: Forbidden …; csv: 403 …;
v2: 403 …"*. Analisis user (WAF/Cloudflare atau migrasi ke PRO API, bukan CA
salah) **divalidasi benar**: dari klien browser endpoint yang sama masih 200
(Pusheen, 409 holder, 18 desimal), dan dokumen resmi Blockscout menyatakan
instance publik dilindungi bot-protection (403 + halaman "Just a moment…")
sementara akses API per-instance **deprecated** → akses program lewat
**PRO API** `https://api.blockscout.com/4663/…` dengan key gratis
(`proapi_…`, <https://dev.blockscout.com>, tanpa kartu; free tier 5 RPS /
100K kredit per hari ≈ 3.000–5.000 request). Opsi #2 user (User-Agent
browser) sudah dipakai sejak awal dan terbukti tidak cukup — yang difilter
TLS fingerprint/IP server.

## 1. `robinhood_holders.py`: transport PRO API → instance publik

- Semua request lewat `_blockscout_get(url)`: bila `BLOCKSCOUT_API_KEY`
  ada (env `BLOCKSCOUT_API_KEY`/`BLOCKSCOUT_PRO_API_KEY` →
  `blockscout_api_key` di `config.json` → `st.secrets`) → **PRO API**
  dengan path identik (`_pro_url`) dan header `Authorization: Bearer`
  (key tidak pernah di URL/log/pesan error); PRO 401/402/403/404 → jatuh
  ke instance publik. Tanpa key → publik: `curl_cffi` impersonate
  (`chrome → chrome136 → chrome131 → safari184 → safari17_0 → firefox133`,
  dirotasi saat 403, `_curl_requests()` bisa di-mock) lalu `requests`
  biasa + header browser.
- `BlockscoutBlocked` (403, atau 503 berbadan halaman challenge Cloudflare;
  detail `cf-mitigated`/`server`) **bukan transient**: tidak di-retry,
  `is_transient_error` → False, `is_blocked_error` baru. Response tanpa
  `status_code` numerik (stub test lama) diserahkan ke `raise_for_status`
  bawaan (`_status_of`).
- `fetch_holders()` merangkum 403 dari getToken/CSV/RPC/v2 menjadi **satu**
  kalimat (*"Blockscout publik menolak request (HTTP 403 bot-protection) di
  /api [cf-mitigated=challenge Cloudflare] — pasang BLOCKSCOUT_API_KEY (key
  gratis: https://dev.blockscout.com) agar scan lewat PRO API"*) + key baru
  `blocked: bool` (juga di early-return); bila PRO ikut gagal alasannya
  disambung (`…; PRO: PRO API 401 Invalid API key`). `fetch_holders_rpc`
  mengembalikan instance `BlockscoutBlocked` sebagai error ke-4.
- `source` sukses diberi akhiran rute: `blockscout-csv@pro` /
  `@public` (thread-local `_ROUTE_STATE`, aman untuk ThreadPool
  `scan_watchlist`); helper `source_with_route`, `source_base`,
  `route_label`, `last_route`. `analyze_token` meneruskan
  `holders["blocked"]` di samping `holders["fetch_error"]`.
- Shape dict hasil (`mint/symbol/market/snapshot/depth/source/…`) dan gate
  `holders_usable`/`fetch_error` tidak berubah; snapshot lama tetap tidak
  ditimpa saat 403.

## 2. UI & cron

- `app.py` `_scan_source_meta`: cocokkan jalur lewat `source_base()` dan
  tambahkan " · PRO API" / " · instance publik" ke help + caption.
  `scan_failed` dengan `snapshot["blocked"]` → pesan baru *"Blockscout
  publik menolak request scan (HTTP 403 bot-protection) — bukan karena CA
  salah. Pasang `BLOCKSCOUT_API_KEY` …"* (pesan lama "Pastikan CA valid"
  tetap untuk kegagalan non-403). Baris watchlist Robinhood: `blocked` →
  catatan ringkas "Blockscout 403 bot-protection — pasang
  BLOCKSCOUT_API_KEY (PRO API)".
- `pages/5_🧮_Holder.py`: peringatan "scan tidak lengkap" menyebut 403 +
  key bila `holders["blocked"]`.
- `scripts/scan_holders.py`: log lane Robinhood menambah `route=pro|public`
  dan `WARN: Blockscout publik menolak scan N/M token …` ke stderr.
- Workflow (`daily-effort-5menit.yml` + `.github/workflows/daily-effort.yml`)
  meneruskan `BLOCKSCOUT_API_KEY: ${{ secrets.BLOCKSCOUT_API_KEY }}`
  (secret perlu dibuat di GitHub; push ke `.github/workflows` mungkin ditolak
  untuk bot — salin manual seperti biasa). `config.example.json` +
  `blockscout_api_key`.

## 3. Tes & dokumen

- Baru `tests/test_robinhood_transport.py` (19 tes): key env/config/secrets,
  `_pro_url`, PRO Bearer tanpa key di URL, PRO 401/402 → publik, PRO+publik
  gagal → pesan gabungan tanpa bocor key, 403 → `BlockscoutBlocked` tanpa
  retry, rotasi profil TLS, header UA tidak menimpa impersonate, curl_cffi
  rusak → requests, 503 challenge, 429 masih di-retry, `fetch_holders`
  semua jalur 403 (dengan/tanpa decimals) → satu pesan + `blocked`,
  `analyze_token`/`scan_token_holders` meneruskan penanda, label rute.
  `tests/test_rh_card_ui.py` +3 AppTest (caption `@pro`, pesan 403 di Scan
  Holder Khusus, pesan lama untuk kegagalan biasa). **Suite penuh 952
  passed.**
- Dok: `docs/robinhood_holders_api.md` (bagian *Transport* + rate limit PRO;
  koreksi klaim lama "mirror PRO jangan dipakai"), README (paragraf Scan
  Holder Khusus + tabel env), DEPLOY (secrets + env Actions), AGENTS.md.

## Yang harus dilakukan user

1. Buat key gratis di <https://dev.blockscout.com> (Sign in → *Create API
   key*; key `proapi_…` hanya ditampilkan sekali).
2. Streamlit Cloud → *Settings → Secrets*: `BLOCKSCOUT_API_KEY = "proapi_…"`
   (atau `blockscout_api_key` di `config.json` lokal).
3. GitHub → *Settings → Secrets and variables → Actions*: secret
   `BLOCKSCOUT_API_KEY`, lalu pastikan `.github/workflows/daily-effort.yml`
   memuat baris env baru (lihat `daily-effort-5menit.yml`).
4. Ulangi scan `0x1209ec…bb6e`: caption harus berbunyi *Blockscout
   (Robinhood Chain) · PRO API*.

Belum dikerjakan (opsional, bila PRO API pun tidak memadai): fallback
on-chain lewat RPC publik `https://rpc.mainnet.chain.robinhood.com`
(`eth_getLogs` Transfer + `balanceOf`; rate-limited, "bukan untuk indexer")
dan Bitquery (berbayar).

# Kegiatan — 8 September 2026 (sesi 9 · 🛰 Scan Holder Khusus: + Robinhood Chain)

Permintaan user: **"tambahkan fungsi kita bisa scan robinhood disini juga"**
(section **🛰 Scan Holder Khusus — Helius** di halaman utama).

## 1. Backend: `robinhood_holders.scan_token_holders()`

Padanan EVM dari `helius_holders.scan_token_holders` — alurnya sama:
market (harga & marketcap) dari DexScreener (`chain_id=robinhood`), token
info (decimals & supply) dari Blockscout, seluruh holder dari
`fetch_holders` (GMGN primary, Blockscout fallback), lalu
`solscan_holders.wallet_depth`. **Shape dict hasilnya sama persis**
(`mint/symbol/market/snapshot/depth/source/no_helius_keys/scan_failed`)
supaya UI dipakai ulang tanpa cabang. Pool AMM (`pair_addresses`
DexScreener + penanda non-wallet GMGN) ditandai `_mark_pools` lalu
default **disingkirkan dari bucket** (`include_pools=False`) — sama
dengan perilaku jalur Helius. `no_helius_keys` selalu `False` (jalur ini
tidak butuh key Helius).

## 2. UI `app.py` (`_render_helius_holder_scan` / `_render_helius_holder_result`)

- Judul section: **🛰 Scan Holder Khusus — Helius / Robinhood**; caption +
  placeholder form menjelaskan kedua chain (base58 Solana / `0x…`
  Robinhood).
- Validasi CA menerima **dua format**: base58 (Solana) ATAU `0x` + 40 hex
  (Robinhood) — pesan error menyebut keduanya. CA EVM di-normalize
  (lowercase) sebelum scan.
- Dispatch per chain: `0x…` → `robinhood_holders.scan_token_holders`
  (status "Mengambil holder dari GMGN/Blockscout (Robinhood Chain)…"),
  base58 → `scan_token_holders` Helius (perilaku lama).
- Helper baru `app._scan_source_meta(result)`: label metrik "Akun holder
  (…)", help, dan caption "Sumber holder: …" dihitung dari
  `result["source"]` — `gmgn+robinhood*` → **GMGN (Robinhood Chain)**;
  ada `blockscout` (GMGN gagal, Blockscout yang pulang) →
  **Blockscout (Robinhood Chain)**; selain itu → **Helius DAS**
  (perilaku lama). Pesan error `scan_failed` hanya menyebut "Helius API
  key aktif" untuk jalur Helius.
- Input CA diberi key `helius-ca-input` (konvensi `lp-ca-input`/
  `add-token-input`) supaya bisa ditarget test.

## Verifikasi

- `tests/test_robinhood_watchlist.py::ScanTokenHoldersTest`: shape hasil
  identik jalur Helius; pool keluar dari bucket default / masuk saat
  `include_pools=True`; `max_wallets/price_usd/decimals/total_supply`
  diteruskan; tanpa harga → `scan_failed` + `fetch_token_info` tidak
  dipanggil; GMGN+Blockscout gagal → `scan_failed` + alasan provider
  tersimpan.
- `tests/test_rh_card_ui.py::HolderKhususRobinhoodScanTest` (AppTest):
  CA `0x…` (mixed case) → `robinhood_holders.scan_token_holders` dengan
  CA lowercase + `max_wallets=100_000`, hasil dirender "Akun holder
  (GMGN)" + caption "GMGN (Robinhood Chain)" + tautan rh-scan/Blockscout;
  source fallback → label "Akun holder (Blockscout)"; CA base58 tetap →
  `helius_holders.scan_token_holders` + label "Akun holder (Helius)";
  `0x123` → ditolak tanpa scan.
- Suite penuh: 916 passed (termasuk test Helius lama — jalur Solana
  tidak berubah).

---

# Kegiatan — 7 September 2026 (sesi 8 · 🌊 Scan Meteora: hanya dust ≤ 0,1% + BEST POOL TVL ≥ 10K)

Permintaan user: **"jangan tampilkan yang dust sudah > 0,1%, jadi sesi
deteksi dan notifikasi aman, hati-hati, bahaya sudah tidak diperlukan lagi,
bisa dinonaktifkan. Lalu best pool kriterianya dari kriteria kita tambah
minimum TVL adalah 10K."**

## 1. Filter listing: `hide` = dust > 0,1% MC (`holder_history.py`)

- Konstanta baru `DUST_SCAN_HIDE_PCT = DUST_BEST_PCT` (0,1). `dust_flag()`
  kini mengisi `hide = pct > DUST_SCAN_HIDE_PCT` untuk semua level — dulu
  hanya BAHAYA (≥ 1%) yang `hide`. `should_hide_dust()` (dipakai
  `meteora_screener.hide_dust_limit`) otomatis ikut. Boundary strict `>`:
  tepat 0,1% masih tampil (tapi bukan BEST POOL karena butuh `<`), dust
  `None` (holder gagal) tetap tampil tanpa angka.
- **Level/label AMAN/HATI-HATI/BAHAYA tidak dihapus** dari `dust_flag` —
  Chart LP Meteora, Robinhood LP, cron dan alert masih memakainya. Yang
  dinonaktifkan hanya *tampilannya* di listing Scan Meteora.
- `DUST_LIMIT_PCT` (alias lama) sekarang menunjuk `DUST_SCAN_HIDE_PCT`.

## 2. BEST POOL + minimum TVL 10K

- `DUST_BEST_MIN_TVL_USD = 10_000.0` + guard `_tvl_valid_for_best()`.
  `dust_flag(..., holders=..., tvl=...)` → `best` True hanya bila dust
  < 0,1% **dan** holder valid (≥ 40 wallet) **dan** TVL ≥ 10K. `tvl=None`
  → bukan best (sama seperti `holders=None`), jadi Chart LP / watchlist yang
  tidak mengirim TVL tidak berubah perilaku.
- Sumber TVL = field `tvl` pool dari API Meteora (sudah ada di baris hasil
  `_row_from_pool`).

## 3. UI `app.py` (`_render_meteora_scan`)

- Baris listing **tidak lagi** merender `_dust_badge_html` (chip
  AMAN/HATI-HATI/BAHAYA); hanya angka dust % MC + chip 🏆 BEST POOL.
- Kolom baru **TVL** di antara MC dan Dust (`col_spec` 8 kolom).
- Caption + ringkasan "N disembunyikan (dust > 0,1% MC)" + hero text
  disesuaikan; `scan_meteora()` menambah `hide_pct` di hasil.

## Verifikasi

- `tests/test_holder_history.py`: boundary hide 0,1 (strict), guard TVL
  (None / "abc" / 9 999,99 → bukan best; 10 000 / "12000" → best).
- `tests/test_meteora_screener.py`: 2,4% / 0,5% / 0,2% disembunyikan,
  `None` / 0,1 / 0,03 tetap; `analysis.holders.dust_pct_mc` menang atas
  `row.dust_pct_mc`; `hide_pct` di hasil scan.
- `tests/test_lp_card_ui.py::MeteoraBestBadgeTest`: 3 baris (CLN TVL 25K →
  BEST; BGS holder 0 → bukan; THN TVL 4K → bukan), kolom TVL dirender,
  tidak ada chip level di listing.
- Suite penuh: 867 passed (1 test `StandalonePageTest` pre-pump gagal
  karena sandbox tanpa akses jaringan — sudah gagal di `main`, tidak
  terkait).

---

# Kegiatan — 6 September 2026 (sesi 7 · 🗑️ Hapus semua watchlist biasa)

Permintaan user: **"tambahkan tombol delete all watchlist di watchlist biasa
selain meteora dan robinhood."**

## 1. Backend: `watchlist.remove_many_from_watchlist()`

Hapus satu token (`remove_from_watchlist`) memakai satu journal write + satu
commit per klik ✕; mengosongkan 79 token biasa dengan cara itu berarti 79
commit (worker sudah men-*coalesce*, tetapi journal tetap ditulis 79×). Fungsi
baru menerima **daftar CA** dan memakai kontrak durabilitas yang sama, hanya
di-batch:

- `_load_and_merge(local_first=background)` → hitung yang benar-benar ada;
- **journal dulu** lewat `_journal_many` (satu tulis atomik; last-op-wins per
  CA membatalkan `add` yang masih tertunda);
- `save_watchlist(..., background=True)` = tulis lokal + seed cache + **satu**
  commit di thread latar (`remove N token (watchlist biasa)`).

Fungsi **tidak menyaring `source`** — pemanggil yang menentukan scope, sama
seperti `remove_from_watchlist`. Op `remove` untuk CA yang tidak ada di state
lokal tetap di-journal supaya remote yang lebih baru ikut bersih
(`_op_is_applied` mem-prune bila memang sudah tidak ada). Return
`{removed, missing, saved, addresses}`.

## 2. UI (`app.py`): tombol popover di kepala card watchlist biasa

Di sebelah selectbox "Urutkan baris watchlist" (kolom ketiga,
`vertical_alignment="bottom"`): **🗑️ Hapus semua** → popover berisi teks
"Hapus **N token** dari watchlist biasa?" + tombol primary **Ya, hapus N
token** (`key="clear-regular-watchlist"`). Klik → `remove_many_from_watchlist(
list(holder_watch), note="watchlist biasa", background=True)` → laporan
`st.success` setelah rerun (lewat `st.session_state["watchlist_clear_report"]`).

Scope = `holder_watch` hasil `split_watchlist` (token Solana non-LP). Card
**Chart LP Meteora** dan kedua card **Robinhood** SENGAJA tidak ikut — mereka
punya file/watchlist sendiri dan tidak diberi tombol serupa. Teks konfirmasi
menyebut bahwa token `degen` (Pre-Pump Screener) ikut terhapus, dan bahwa
history holder tidak dihapus (`snapshot_status` membuang kunci di luar
watchlist pada publish berikutnya). Tombol tidak dirender bila card kosong.

## Verifikasi

- `python -m pytest -q` → **850 hijau** (sebelumnya 836; +14 test baru di
  `tests/test_watchlist_clear.py`).
- Backend: hanya CA yang diminta yang dihapus (token `meteora` di file
  tetap), satu `_save_pending` untuk seluruh batch, nol pull di jalur klik,
  tepat satu `_github_push`, jurnal dibersihkan setelah commit sukses dan
  dipertahankan saat gagal (token tidak muncul lagi di `load_watchlist`),
  duplikat/kosong diabaikan, daftar kosong tidak menulis apa pun, `remove`
  membatalkan `add` tertunda, jalur sinkron (`background=False`) tetap ada.
- AppTest: tombol menyebut "2 token" (LP tidak dihitung), klik konfirmasi
  memanggil `remove_many_from_watchlist` dengan CA non-LP saja +
  `background=True`, laporan sukses tampil, tombol tidak ada bila watchlist
  hanya berisi token LP, tombol ✕ per baris tetap ada.

# Kegiatan — 6 September 2026 (sesi 6 · ✕ watchlist bolak balik + flush latar)

Permintaan user: **"fungsi hapus dari watchlist masih bolak balik dan tidak
optimal."**

## 1. Akar "bolak balik": jurnal remove di-prune prematur terhadap cache optimis

Reproduksi: token dihapus (✕) tapi **muncul lagi** di render berikutnya setelah
push GitHub gagal. Penyebab ada di `watchlist._load_and_merge`: ia mem-prune
jurnal pending terhadap `raw` yang (dalam TTL 60 dtk) berasal dari **cache
seed** hasil perubahan lokal — state **optimis**, belum tentu sudah sampai ke
GitHub. Kalau push latar belakang gagal, jurnal `remove` sudah di-prune,
sehingga begitu cache kedaluwarsa dan `load_watchlist()` menarik ulang remote
yang *masih memuat* token itu, tidak ada lagi op `remove` yang mengoreksi →
token muncul lagi (dan setiap render ulang mem-flush sinkron yang membekukan UI
selama push gagal). Ini juga berlaku untuk `add`/`source` (sekali saja push
gagal, perubahan "hilang" lalu timbul kembali).

**Perbaikan (`watchlist.py`):**

- Cache `_REMOTE_CACHE` kini menyimpan penanda **`settled`**: `True` bila isi
  **mencerminkan repo** (hasil `_github_pull` atau `_github_push` yang sukses),
  `False` bila isi **optimis** (seed `_seed_remote_cache` setelah perubahan
  lokal). Helper baru `_set_remote_cache(repo_path, data, settled)`.
- `_load_and_merge` (dan `_push_worker`) **hanya mem-prune jurnal terhadap
  state `settled=True`**; terhadap seed optimis atau file lokal, jurnal
  dipertahankan. Jadi `remove` yang belum ter-commit aman dikoreksi ulang saat
  remote ditarik.
- `_push_worker` mem-prune terhadap `wl` yang **benar-benar di-commit** (bukan
  cache yang bisa saja di-seed ulang mutation lain saat push jalan).

## 2. "Tidak optimal": flush `load_watchlist` jadi latar belakang

Dulu `load_watchlist()` yang menemukan sisa jurnal (mis. push gagal) langsung
`_github_push` **sinkron** — setiap render ulang memblokir sampai ±2 menit saat
API lambat. Sekarang diserahkan ke `_queue_github_push` (fire-and-forget):
UI tidak menunggu, jurnal dibersihkan worker setelah commit sukses, dan
`push_inflight` tetap menahan flush dobel saat worker masih jalan.

## Verifikasi

- `python -m pytest -q` → **830 hijau** dan `python -m unittest discover -s
  tests -t .` → **830 OK** (sebelumnya 829).
- Test baru `RemoveBackgroundTest::test_remove_tidak_muncul_lagi_saat_push_belum_berhasil`:
  push selalu gagal (remote masih memuat CA), lalu `load_watchlist` memakai seed
  cache dan `force_refresh` menarik remote lama → CA tetap hilang karena jurnal
  remove dipertahankan.

# Kegiatan — 6 September 2026 (sesi 5 · Chart LP Meteora ikut 5 menit)

Permintaan user: **"iya untuk watchlist meteora juga, per 5 menit, biar
perubahan holder bisa langsung ketahuan."** Ini **membatalkan** keputusan sesi 4
yang sengaja menahan lane Solana di slot ±15 menit demi anggaran Helius —
readernya: laju 5 menit sekarang berlaku untuk KEDUA card LP, dan penghematan
Helius menjadi knob opsional, bukan default kode.

## 1. Lane Meteora = tiap run (satu knob, bukan dua jam dinding)

Sebelum sesi ini ada dua gerbang di `scripts/scan_holders.py`
(`RH_FAST_SCAN_INTERVAL_SEC` 5 menit untuk Robinhood, `METEORA_LP_SCAN_INTERVAL_SEC`
15 menit untuk Solana). Sekarang keduanya menempel satu jam dinding run:

```
RUN_SCAN_INTERVAL_SEC = RH_FAST_SCAN_INTERVAL_SEC = FAST_SCAN_INTERVAL_SEC = 300
LP_SCAN_RUN_MULTIPLIER = int(env, default 1)          # katup hemat, opsional
lp_slot_sec() = RUN_SCAN_INTERVAL_SEC * MULTIPLIER    # slot LP = slot run
```

`lp_slot_due(now, snapshot.updated_at)` tetap ada dan tetap berbasis **nomor
slot** (bukan umur titik): dengan multiplier 1 setiap cron run = slot LP baru,
jadi Helius ditarik tiap 5 menit; yang tidak due hanyalah run KEDUA dalam satu
slot (chain dispatch menabrak schedule) — persis yang diinginkan. Gate lama
berbasis umur titik tidak dipakai lagi sejak sesi 2 karena publish yang gagal
membuat token tidak pernah terkejar.

Bila kuota Helius mulai menipis, tidak perlu sentuh kode: env
`LP_SCAN_RUN_MULTIPLIER: "3"` di langkah "Holder scan" pada workflow → lane
Solana kembali ±15 menit, Robinhood LP tetap tiap run. Log run selalu
menyebutkan kadens aktif: `Rencana scan: LP=… biasa=… due=… slot_lp=… (LP ±5
menit · tiap run · biasa ±4 jam)`.

## 2. Konsekuensi yang harus ikut digerakkan: `MAX_POINTS`

Densitas titik riwayat = kadens run. `ingest_point` **menimpa** titik yang lebih
muda dari `MIN_POINT_GAP_SEC`, jadi tidak ada cara "scan 5 menit tapi simpan
tiap 15 menit" dengan mekanisme itu (titik terakhir selalu berjarak 5 menit →
satu-satunya titik yang pernah ada). Satu-satunya knob panjang grafik =
`holder_history.MAX_POINTS`:

| | densitas | batas | jendela | bucket 4 jam |
| --- | --- | --- | --- | --- |
| lama (sesi 2–4) | 15 menit | 336 | 3,5 hari | 21 |
| 5 menit, batas lama | 5 menit | 336 | **28 jam** | **7** |
| sekarang | 5 menit | **1008** | 3,5 hari | 21 |

Tanpa kenaikan itu "Grafik 4 jam" di card LP menyusut 3× persis saat datanya
paling rapat. Ukuran tetap aman: snapshot dashboard selalu
`compact_history_for_status` (≤ 84 bucket `resample_4h`) dan sparkline
meresample internal, jadi payload HTML tidak berubah; simulasi store sintetis
(10 token LP @ 1008 titik 5 menit + 45 token biasa @ 336 titik/hari) =
**0,33 MB gz** vs 0,25 MB sebelum perubahan, di bawah `MAX_BACKUP_BYTES`
3,5 MB. `MIN_POINT_GAP_SEC` (4 menit) dan `MIN_RUN_GAP_SEC` (4 menit) tetap
**— harus di bawah 5 menit**, itu yang dikunci
`ScanCadenceTest::test_konstanta_kadens`.

## 3. Teks yang ikut disinkronkan

Caption/penjelasan kadens di `app.py` (kepala card Chart LP & Robinhood,
helper tab, komentar router), `pages/5_🧮_Holder.py`, komentar
`watchlist_detail.py` (ambang basi tetap 20 menit — sengaja jauh di atas
kadens supaya hanya cron mati yang kena), `robinhood_watchlist.py`,
`holder_status.py`, dan `telegram_alerts.py`. Yang SENGAJA tidak berubah:
bucket pengingat ⚡ (`FAST_BUCKET_SEC` 15 menit/token) — kalau ikut dipercepat,
satu token menerima 3 pesan identik per 15 menit; data dashboard sendiri tetap
diperbarui tiap run.

## 4. Workflow (satu-satunya langkah manual)

Berkas workflow tidak bisa ditulis bot (GitHub menolak push/PUT ke
`.github/workflows/*`, 403). Kadens cron **tidak perlu diubah lagi** untuk sesi
ini — `*/5` + chain `WAIT=$((300 - NOW % 300 + 20))` sudah ada di
`daily-effort-5menit.yml`; yang berubah hanya nama langkah + catatan env
opsional. Terukur dari `holder-live`: commit masih berjarak 15 menit (01:00,
01:15, 01:30, … UTC) → berkas itu belum ditempel. Setelah ditempel, bukti
kadens nyata = baris `Rencana scan: … (LP ±5 menit · tiap run …)` dan commit
`holder-status: snapshot …` tiap 5 menit. Konsekuensi: ±576 commit/hari di
branch `holder-live` (repo terukur ±56 MB pada kadens 15 menit).

## Verifikasi

- `python -m pytest -q` dan `python -m unittest discover -s tests -t .` — lihat
  angka di PR; yang relevan: `ScanCadenceTest` (kadens + `main()` integration
  dengan jam tersumbat), `ScanDensityCalibrationTest` (kalibrasi `MAX_POINTS`,
  21 bucket 4 jam, lane biasa), `FiveMinuteCadenceTest`,
  `test_watchlist_background_push`, `test_rh_card_ui`.
- Uji baru yang spesifik menahan permintaan sesi ini:
  `test_run_biasa_scan_kedua_lane_lp` (tiap run = Meteora **dan** Robinhood),
  `test_multiplier_menahan_solana_tetapi_tidak_robinhood` (katup hemat bekerja),
  `test_lp_slot_due_default_setiap_run`.

# Kegiatan — 6 September 2026 (sesi 4 · ✕ watchlist responsif + fetch Robinhood 5 menit)

Permintaan user: **"perbaiki juga hapus dari watchlist robinhood, kurang
responsif, lalu percepat fetch untuk watchlist robinhood menjadi 5 menit
sekali."**

## 1. Hapus dari watchlist: tidak lagi menunggu GitHub di dalam rerun

Diukur dengan stub RTT 0,8 dtk (skrip sementara; angka di log Actions nyata
lebih besar): satu klik ✕ = **2,40 s** tertahan dan **3 panggilan HTTP** di
jalur klik — `remove_from_watchlist()` → `_load_and_merge()` menarik remote
(sampai 3 GET × timeout 10 dtk) lalu `save_watchlist()` → `_github_push()`
(GET sha + PUT, 3 percobaan × timeout 15 dtk + backoff). Saat API melambat
klik bisa mendekati ±2 menit, dan setiap render ulang ikut mem-flush journal
yang gagal → terasa "kurang responsif".

**Perbaikan (`watchlist.py`)** — kontrak baru untuk jalur UI, flag
`background=True` (default `False` untuk cron/skrip):

1. state dibaca **lokal** (`_load_and_merge(local_first=True)`: cache
   `_REMOTE_CACHE` → file watchlist) — nol HTTP;
2. journal + tulis file lokal seperti semula;
3. `_seed_remote_cache()` memasang state baru sebagai "remote terbaru" →
   render ulang berikutnya **tidak** pull (TTL load watchlist 15 → **60 dtk**);
4. commit ke GitHub di **thread daemon** `_queue_github_push` (satu worker per
   file; job terbaru menimpa job lama, jadi klik cepat beruntun = satu commit
   final); journal dibersihkan hanya setelah commit sukses;
5. `load_watchlist()` melewati flush inline selama `push_inflight()` benar
   (mencegah balap 409 dengan worker); dispatch "scan sekarang"
   (`request_immediate_scan`) pindah ke `dispatch_scan_async()` dengan rem 10s.

Terukur setelahnya: **1,4 ms** untuk klik + 0,9 ms render ulang, **0 HTTP** di
jalur klik. Badge status di kepala card Robinhood: `🔄 sinkron…` /
`⚠️ belum sinkron` (`push_status()`). Dipakai di semua jalur UI: ✕/📋/⚡ di
card Robinhood (lp & biasa), ✕/📋 Chart LP, ✕/🌊 watchlist holder, form tambah
(Solana + Robinhood), tombol ➕ di `pages/4_📊_CVD.py` dan
`pages/5_🧮_Holder.py`.

## 2. Fetch watchlist Robinhood jadi tiap 5 menit

Kadens lama = **satu angka** (`FAST_SCAN_INTERVAL_SEC` 15 menit) untuk Chart
LP Meteora **dan** Robinhood LP, dijaga chain dispatch `WAIT=900-NOW%900+20`.
Yang diminta hanya Robinhood, jadi lane dipecah (`scripts/scan_holders.py`):

| Lane | Kadens | Konstanta |
| --- | --- | --- |
| 🦅 Robinhood LP | tiap run = ±5 menit | `RH_FAST_SCAN_INTERVAL_SEC` = `RUN_SCAN_INTERVAL_SEC` = 300 |
| 🌊 Chart LP Meteora | slot ±15 menit | `METEORA_LP_SCAN_INTERVAL_SEC` + gate baru `lp_slot_due(now, snapshot.updated_at)` |

> Baris Chart LP pada tabel ini **sudah digantikan sesi 5** (lihat di atas):
> sejak itu lane Meteora ikut tiap run, dan `lp_slot_due` hanya mengikat kalau
> `LP_SCAN_RUN_MULTIPLIER` > 1.
| 📋 biasa (Solana + Robinhood) | slot 4 jam | `REGULAR_SLOTS` 16 → **48** |

- Cron `*/15` → **`*/5`** dan chain `900` → **`300`**. Berkas
  `.github/workflows/daily-effort.yml` **ditolak GitHub** saat di-push/PUT
  (GitHub App tanpa izin `workflows`, 403), jadi workflow lengkapnya disiapkan
  di root repo sebagai **`daily-effort-5menit.yml`** untuk disalin lewat UI
  GitHub; selama belum disalin cron tetap 15 menit dan lane Robinhood ikut 15
  menit (tidak ada yang rusak — scanner sudah mendukung keduanya).
- **`MIN_RUN_GAP_SEC` 840 → 240 dtk.** Ini wajib: gate run ganda dibaca dari
  umur snapshot, dan kalau ambangnya ≥ kadens run (5 menit), lane Robinhood
  justru dibungkam gate-nya sendiri. Invarian ini dites.
- **`holder_history.MIN_POINT_GAP_SEC` 8 → 4 menit.** Bug yang dicegah:
  titik yang lebih muda dari ambang **ditimpa**, jadi dengan run tiap 5 menit
  dan ambang 8 menit store Robinhood tidak pernah punya lebih dari satu titik
  (grafik/Δ membeku). `FiveMinuteCadenceTest` mengunci
  `MIN_RUN_GAP_SEC ≤ MIN_POINT_GAP_SEC < kadens run`.
- Solana **tidak** ikut 3× lebih sering: run di luar slot LP tidak memanggil
  Helius sama sekali (log `Rencana scan: … slot_lp=bukan`), jadi kuota
  Helius tetap. Repo publik → menit Actions gratis (±288 run/hari,
  sebagian besar tidur di langkah chain).
- Alert **tidak** ikut spam: bucket pengingat ⚡ `FAST_BUCKET_SEC` sengaja
  tetap 15 menit per token (`telegram_alerts`), hanya caption UI yang berubah.
- Teks UI mengikuti: label radio, caption card, `chain_note` baris
  ("LP · scan ±5 menit"), help tombol ⚡, caption "Cadens cron" — Chart LP
  Meteora tetap tertulis ±15 menit *(kalimat ini berlaku sampai sesi 5; kini
  kedua lane LP tertulis ±5 menit di semua caption)*.

## 3. Bug silang jaringan di `watchlist._github_push` (ikut diperbaiki)

Sebelum merge journal di-push, fungsi itu selalu membaca
`watchlist_pending.json` (**journal Solana**) — padahal ia dipakai untuk tiga
file: `watchlist.json`, `watchlist_robinhood.json`, **dan**
`holder_status*.json` (publish snapshot). Artinya op `add` yang masih tertunda
di satu jaringan disuntikkan ke payload file jaringan lain
(`_apply_ops(latest_remote, pending_solana)`), bahkan ke snapshot dashboard.
Sekarang `_github_push(..., pending_path=…)` membaca jurnal **milik file yang
sedang ditulis** (diteruskan oleh `save_watchlist`, `load_watchlist`, dan
worker latar belakang), dan `holder_status.publish_holder_status` mengirim
`merge_journal=False` karena file snapshot tidak punya jurnal operasi.
Dua uji `GithubPushJournalIsolationTest` menguncinya.

Selain itu tulis-baca journal kini dilindungi `_JOURNAL_LOCK` (RLock): worker
latar belakang mem-prune jurnal tepat setelah commit sukses, dan tanpa lock
op yang baru ditulis thread UI pada detik yang sama bisa ikut terhapus
(token muncul lagi di render berikutnya).

## Verifikasi

`python -m pytest -q` → **824 hijau** (sebelumnya 794; +30) dan
`python -m unittest discover -s tests -t .` lolos. Test baru:
`tests/test_watchlist_background_push.py` (12: nol HTTP di
jalur klik, commit di thread lalu journal dibersihkan, push gagal = journal
dipertahankan + status `error`, coalescing, flag sinkron tidak berubah,
badge/`push_status`, rem dispatch), `ScanCadenceTest` di
`tests/test_scan_holders.py` (konstanta + `lp_slot_due` + `build_scan_plan`
+ dua integrasi `main()` dengan jam tersumbat: tengah slot hanya Robinhood,
di slot LP Solana ikut, gate run ganda membungkam semuanya),
`FiveMinuteCadenceTest` di `tests/test_holder_history.py` (3), dan 5 test UI
di `tests/test_rh_card_ui.py` (✕/📋 wajib `background=True`, caption ±5 menit,
badge sinkron). Test lama yang memassert kwargs pemanggilan diperbarui
(`tests/test_lp_card_ui.py`, `tests/test_robinhood_watchlist.py`).

# Kegiatan — 6 September 2026 (sesi 3 · tautan 🧮 Holder + scan Robinhood jujur)

Laporan user: menempel URL `…streamlit.app/…/pages/5_🧮_Holder.py?mint=0x1a3876…`
dengan keterangan **"belum berfungsi"**.

## 1. Penyebab: tautan memakai path file, bukan slug halaman

Streamlit tidak melayani file `pages/` lewat path file-nya. Registry runtime
app ini dibaca lewat websocket `/_stcore/stream` dan berisi `url_pathname`:
`CVD`, `Holder`, `Deteksi_Akumulasi`, `Pre-Pump`; frontend mencocokkan URL
dengan `pathname.endsWith('/' + urlPathname)` (case-sensitive). Jadi
`pages/5_🧮_Holder.py?mint=…` tidak cocok dengan halaman mana pun →
"Page not found" + halaman utama yang jalan → `?mint=` tak pernah dibaca
halaman Holder. (Dua uji `tests/test_rh_card_ui.py` sudah merah di HEAD karena
ganti tombol → anchor ini.)

**Perbaikan:** `links.page_url_path()` (mirror aturan Streamlit
`source_util.page_icon_and_name`, fallback lokal identik) + `page_url()` yang
root-absolute dan menghormati `server.baseUrlPath` →
`holder_analytic_url(ca)` = `/Holder?mint=…`. **Jaring:** modul baru
`page_router.py` + `page_router.apply()` di awal `app.py` memantulkan
`mint|ca|token|address` (opsional `page=<slug|nomor|file|path>`) yang mendarat
di halaman utama ke `st.switch_page` — tautan lama yang sudah tersebar ikut
pulih. CA divalidasi (base58 Solana / `0x`+40 hex), registry alias dibaca dari
folder `pages/` (tidak ada path hardcoded), penanda
`st.session_state["_deep_link_routed"]` mencegah pantulan berulang.

## 2. Scan holder Robinhood tidak boleh tampil sebagai "dust 0,00%"

Snapshot `holder_status_robinhood.json` di ref `holder-live` (dibaca langsung)
menunjukkan `total_fetched: 0, wallets_analyzed: 0, dust_count: 0,
dust_pct_mc: 0.0` untuk **0x1a38… (Onboard)** dan **0x8490… (VLAD)** padahal
VLAD punya 2.929 wallet di history — scan provider gagal, dan untuk chain ini
hasilnya tetap di-publish (jalur Solana sudah disaring `holders_usable`,
jalur Robinhood belum).

- `robinhood_holders._jsjson`: error sementara (429/5xx/timeout) diulang 1×
  dengan jeda 3 detik; `fetch_token_info` melempar bila Blockscout membalas
  `status: "0"` (sebelumnya diam-diam jadi `decimals: -1` lalu seluruh scan
  pulang dengan 0 wallet); `fetch_holders` menyalin alasan ke `error` dan
  `analyze_token` menempelnya sebagai `holders.fetch_error`.
- `robinhood_watchlist.publish_scan(..., skip_unusable=True)`: analisis yang
  `holders_usable`-nya False tidak masuk snapshot (aturan cron Solana), titiknya
  tetap di-ingest dengan penanda `degraded`, dan token mewarisi angka lama
  lewat `merge_status`.
- Baris card Robinhood di `app.py` kini menulis
  **"⚠️ scan terakhir tidak lengkap (Blockscout getToken: 429 …)"**; halaman
  Holder menambahkan "Alasan provider: …" di peringatan scan pendek.

## Verifikasi

`python -m pytest -q` → **794 passed** (sebelumnya 758 passed + 2 failed).
Uji baru: `tests/test_page_router.py` (13), `HolderDeepLinkTest` di
`tests/test_links.py` (assert slug == `page_icon_and_name` untuk **semua** file
`pages/`), `ProviderFailureTest` di `tests/test_robinhood_watchlist.py`, guard
publish + pesan baris di `tests/test_rh_card_ui.py`.

# Kegiatan — 5 September 2026 (sesi 2 · scan 15 menit + titik high)

Empat permintaan user: (1) watchlist **Meteora (Chart LP) & Robinhood LP**
di-scan cron tiap **±15 menit** (awalnya minta 30 menit, dikoreksi jadi 15
"agar exit bisa lebih early"); watchlist lain tetap ±4 jam; (2) bila hold
dust **> 0,1% MC**, pemberitahuan dikirim **berulang** sampai token
dihapus dari watchlist atau dipindah ke watchlist biasa; (3) watchlist
Robinhood lama diganti **"watchlist Robinhood LP"**, terpisah dari
watchlist Robinhood biasa; (4) titik acuan alert watchlist biasa bukan
lagi snapshot awal melainkan **hold % MC terbesar (titik high)** — turun
**≥ 50% dari titik high** mengirim alert Telegram.

## 1. Cron 15 menit untuk watchlist LP (Meteora + Robinhood LP)

`scripts/scan_holders.py` punya `build_scan_plan()`: token LP
(`source=meteora` / watchlist Robinhood LP) **due tiap run**, watchlist
biasa hanya di **slot 4 jam** (`REGULAR_SLOTS` 16/hari) atau saat token
baru belum punya titik (`token_needs_scan`), plus catch-up bila slot
terlewat (`REGULAR_CATCHUP_SEC` 3,75 jam). Flag baru `--scope
auto|fast|all` (auto = default cron; fast = hanya LP; all = dispatch
manual) + gate run ganda (`recently_published`, `MIN_RUN_GAP_SEC` 14
menit) yang bisa dilewati `--ignore-gap`. Run cepat mem-publish snapshot
dengan `merge_status` — token biasa di luar slot diwariskan agar
dashboard tidak kehilangan baris. Blok Robinhood best-effort (gagal
jaringan tidak merahkan cron) kini juga dipecah LP/biasa dengan scope
rule masing-masing.

`.github/workflows/daily-effort.yml` **tidak bisa diedit/dipush lewat
bot** (GitHub menolak tanpa izin `workflows` — push ditolak saat sesi
ini). Isi lengkap workflow baru disiapkan di **`daily-effort-15menit.yml`**
(berkas di luar repo, satu tingkat di atas folder repo): cron `*/15`,
input dispatch `scan_all` (menjalankan `--scope all --ignore-gap`) dan
`telegram_test`, langkah "Chain run berikutnya" men-dispatch run
berikutnya tepat setelah batas 15 menit, permissions
`contents: write` + `actions: write`, concurrency `holder-scanner`.
Salin isinya ke `.github/workflows/daily-effort.yml` lewat GitHub UI.
Catatan: `--max-wallets 3000` masih disematkan di workflow (menjaga
durasi run ≤ 45 menit pada slot 4 jam) — hapus manual bila mau FULL
100 ribu di cron.

## 2. Pengingat ⚡ > 0,1% MC berulang (level-based)

`telegram_alerts.evaluate_early_dump_rule()` berubah dari crossing-based
menjadi **level-based**: selama dust % MC di atas `DUST_BEST_PCT`
(0,1%), tiap evaluasi mengirim event — naik, turun sedikit, atau hover
sama. Frekuensi dibatasi bucket **15 menit** (`FAST_BUCKET_SEC`) +
cooldown `EARLY_DUMP_RESEND_SEC` (15 menit); turun ke ≤ 0,1% MC = reset
otomatis. Scope rule = watchlist Meteora (Chart LP) + **Robinhood LP**.
Penghenti hanya: hapus token (✕) atau pindah ke watchlist biasa (📋 di
baris Robinhood LP, 📋 `lp-move` di Chart LP).

## 3. Watchlist Robinhood dipecah dua card

`robinhood_watchlist` punya `RH_LP_SOURCE` / `RH_REGULAR_SOURCE` +
`split_robinhood_watchlist()` (default/manual = LP; `"regular"` =
biasa). `app.py` merender **dua card**: "🦅 Watchlist Robinhood LP —
Holder Dust" (scan ±15 menit, pengingat ⚡ berulang) dan "🦅 Watchlist
Robinhood — Holder Dust" (scan ±4 jam, rule 🔔 titik high), lengkap
tombol pindah ⚡/📋 antar card, form tambah dengan radio tujuan card, dan
caption kadens masing-masing.

## 4. Rule 🔔 HIGH DROP: titik acuan = titik high

`telegram_alerts` baru: `evaluate_high_drop_rule()` +
`high_drop_marker_next()` dengan marker `{high, high_ts, notified_high}`
(satu alert per titik high). Naik ke high baru / keluar zona drop =
re-arm. Konek ke cron: `process_holder_alerts(lp_mints=…,
high_mints=…, watchlist_meta=…)` — `high_mints` = watchlist biasa
Solana + Robinhood biasa. Turun ≥ 50% dari titik high mengirim alert
"🔔 DUST TURUN ≥ 50% DARI TITIK HIGH" tanpa gerbang volume keras
(konteks pasar info saja). Caption + selectbox urut baris watchlist
menyebut rule titik high.

## Verifikasi

`python -m unittest discover tests` — 725 test hijau (termasuk 14 test
baru `tests/test_high_drop.py`, 2 test `ScanScopeMergeTest`, revisi
test early dump ke semantik bucket 15 menit). `py_compile` semua modul
teredit lolos.

# Kegiatan — 5 September 2026

Dua permintaan user: (1) token yang sudah ada di watchlist maupun baru
ditambahkan menjadi **titik awal holder analytic** — cron mulai sekarang
scan **holder FULL** sehingga kronologi bisa langsung dilihat tanpa scan
manual; (2) baris watchlist diurut dari **minus dust holder terbesar**
(contoh: GPRO −60% sejak masuk harus di atas, Sue juga).

## 1. Watchlist = titik awal holder analytic; cron scan FULL

Sebelumnya hanya tombol manual "Scan holder FULL" di halaman Holder yang
memanggil `ingest_many(detail=True)` — baseline (snapshot FULL pertama)
dan kronologi tidak pernah terbentuk untuk token yang tidak pernah di-scan
manual. Sekarang `scripts/scan_holders.py`:

- `--max-wallets` default = **FULL** (`holder_history.FULL_SCAN_MAX_WALLETS`
  100.000, sama dengan tombol scan FULL manual; sebelumnya 3000) dan
  `ingest_many(..., detail=True)` — scan pertama setelah token masuk
  watchlist (token lama maupun baru) menulis **baseline immutable** (titik
  awal), tiap run berikutnya memperbarui `latest_detail` + interval
  **kronologi** (bounded: `MAX_CHRONOLOGY_INTERVALS` 24, snapshot 400
  wallet, 40 movement/interval) yang tampil di halaman Holder.

Biaya ekstra hanya untuk token > 3.000 holder (token ≤ 3.000 sama seperti
sebelumnya). Teks kosong di halaman Holder diperbarui: "Belum ada scan
FULL" kini menyebut cron otomatis ≤ ±1 jam. Tes baru
`tests/test_scan_holders.py::CronFullScanTest` memastikan cron memakai
`detail=True` + `FULL_SCAN_MAX_WALLETS`.

Catatan: baris `--max-wallets 3000` di `.github/workflows/daily-effort.yml`
belum bisa dihapus lewat bot (butuh izin `workflows` di repo) — sampai
dihapus manual, cron produksi masih terbatas 3.000 wallet/token; token
≤ 3.000 tidak terpengaruh, baseline + kronologi tetap jalan.

## 2. Watchlist: minus dust holder terbesar di atas

`watchlist_detail.py` mendapat `row_sort_key()` + konstanta
`SORT_DROP` (default) / `SORT_PCT` / `SORT_NAME`. Default baris watchlist
di `app.py` kini diurut dari `pct_change` "Sejak masuk" paling **negatif**
(dust % MC turun paling banyak — GPRO −60%, Sue — di baris paling atas);
token tanpa pembanding ditaruh di bawah. Ada selectbox "Urutkan baris
watchlist" untuk beralih ke dust % MC tertinggi / nama A–Z. Tes unit
`RowSortKeyTest` + AppTest urutan `DRP(−75%) → SYN(+137%) → RSE(+200%)`.

# Kegiatan — 4 September 2026

Permintaan user: halaman baru **🚀 Pre-Pump Screener** — deteksi memecoin
yang mendekati pump lewat sinyal on-chain + velocity volume. Modul baru
`pre_pump_screener.py` (scope: **hanya watchlist `source=degen`**), section
di `app.py` + halaman mandiri `pages/7_🚀_Pre-Pump.py`.

1. **Empat sinyal** → `PUMP SCORE` 0–10 (rata-rata berbobot 0,25 × 4 × 10),
   kartu per token diurut skor menurun: ✅ Liquidity Wave (add kedua ≥ 5x
   dalam 48 jam; 3x untuk likuiditas < $25k), ⚠️ Holder Consolidation
   (≥ 5 wallet keluar dari dust + avg bag real ≥ 2x), 🔥 Volume Spike
   (calm-before-storm 7 hari), 📊 TX Velocity (akselerasi ≥ 1,5 +
   buy_pressure ≥ 0,65). Shortcut kartu: 🔗 Chart (DexScreener), 👥 Holders,
   📈 CVD, plus link GMGN/Dex.
2. **Journal likuiditas** `pre_pump_liq.json` (gitignored): DexScreener tidak
   menyediakan riwayat likuiditas, jadi tiap scan mencatat `liquidity.usd`
   per pool (72 jam / 900 titik). < 2 observasi → confidence likuiditas
   dikunci **0,3**, bukan 0 dan bukan 1; pola dua gelombang baru terbaca
   setelah beberapa run.
3. **Tiga koreksi atas blueprint** (semuanya dijelaskan di docstring):
   (a) syarat "24 jam ≤ 30% rata-rata" + "6 jam ≥ 2x baseline" mustahil
   benar bersamaan bila 24 jam-nya trailing → window tenang dihitung pada
   24 jam **sebelum** window 6 jam (`vol_ratio_24h_trailing` tetap
   dilaporkan, `VOLUME_SPIKE_BASE="daily"` mengembalikan pembacaan harfiah);
   (b) auto-refresh memakai `st.fragment(run_every=300)` + `st.rerun`, bukan
   `while True: time.sleep(300)` yang membuat script Streamlit tidak pernah
   kembali (UI beku); (c) `app.py` tidak punya tab bar, jadi screener masuk
   sebagai section yang memanggil `main(configure_page=False)` —
   `st.set_page_config` hanya boleh sekali per halaman.
4. **Guard sinyal palsu**: token tanpa snapshot holder tidak pernah dihitung
   sebagai konsolidasi (`_snapshot_usable`); tanpa `HELIUS_API_KEY`, TX
   velocity jatuh ke agregat `txns` DexScreener dengan confidence dibatasi
   0,6; history < 24 jam → sinyal volume `available: False` ("tidak tahu",
   bukan "tenang"); snapshot 24 jam tidak ada → pakai titik tertua + tandai
   `stale`.
5. **Tes**: `tests/test_pre_pump_screener.py` (64 kasus: filter watchlist,
   gelombang add + journal, konsolidasi holder, profil volume, velocity
   Helius/DexScreener, skor, kartu UI lewat AppTest, integrasi `app.py`).
   Total suite 508 → **572 test, OK**.

# Kegiatan — 4 September 2026 (lanjutan)

Tiga permintaan user: (1) halaman baru **Deteksi Akumulasi** dengan 8 metrik,
(2) koreksi metrik 4 supaya **GMGN saja** (kuota Helius terlalu boros),
(3) detail baru di baris watchlist — perubahan dust sejak masuk + warna ambang
— dan perbaikan sinkronisasi data watchlist ↔ scan terakhir.

## 1. Halaman `pages/6_🔎_Deteksi_Akumulasi.py` + modul `accumulation.py`

Semua logika masuk modul **baru** `accumulation.py` (murni kalkulasi, tanpa
Streamlit, **tanpa satu pun request jaringan**); halaman hanya menarik bahan
mentah lewat fetcher yang sudah ada dan merender hasilnya. Sumber daftar token
**selalu** `watchlist.load_watchlist()` — bukan listing Meteora/trending, dan
tidak ada file watchlist baru.

| # | Metrik | Bahan mentah (fetcher lama, reuse) |
|---|---|---|
| 1 | Tier Migration Velocity | bucket wallet depth dua titik `holder_history` terakhir |
| 2 | Diamond Hands Ratio | posisi net per wallet dari swap GMGN |
| 3 | Pola DCA vs One-off Buy | jumlah buy unik + dominasi satu buy per wallet |
| 4 | Smart Money / PnL Wallet | **GMGN**: `maker_tags` + `realized_profit` |
| 5 | Silent Range Accumulation | `core.get_market` + `calculate_volatility_metrics` + CVD net swap |
| 6 | Spring / Test Pattern | candle 4 jam (agregasi dari `core.get_hourly_candles`) vs level support D1 |
| 7 | Fresh Wallet Prep | tag `fresh_wallet` GMGN + pola waktu buy |
| 8 | Sell-Side Liquidity Thinning | posisi net per wallet tanpa jual 14 hari |

Setiap fungsi mengembalikan `{key, nama, nilai, nilai_text, status,
status_label, penjelasan, cukup_data, bobot, detail, sumber}`. `cukup_data`
False **selalu** dipaksa ke status `tidak_cukup_data` dan tidak ikut pembagi
skor (pola `available` di `calculate_volatility_metrics`): "tidak tahu" tidak
pernah dihitung "netral". Skor 0–100 ≥ 60 → **Terindikasi Akumulasi**, selain
itu **Netral**, tanpa data → **Tidak Cukup Data**.

**Koreksi user (metrik 4)** — riwayat PnL lintas token lewat Helius Enhanced
API **tidak diimplementasikan**: terlalu boros kuota Helius. Yang dipakai
metadata per-wallet yang sudah diparsing `cvd._extract_gmgn_trade_meta`
(`realized_profit`, `unrealized_profit`, `maker_tags` ∩
`cvd_daily.SMART_MONEY_TAGS`). Konsekuensinya ditulis jujur di `penjelasan`
dan `detail["catatan"]`: angka PnL = realized profit wallet itu **pada token
ini** menurut GMGN, bukan rekam jejak lintas token. Seluruh halaman ini
**tidak** memanggil Helius sama sekali (dijaga tes
`tests/test_accumulation_page.py::test_helius_is_never_touched`).

**Adaptasi karena modul yang disebut spec tidak ada di repo ini** (dicek:
tidak ada `signals.py`, `breakout_guard.py`, `breakout_log.py`, `ai_prompt.py`,
`levels.json`, `history.json`, `conviction.json`, `cvd.json`, `breakouts.json`,
juga tidak ada test `test_breakout_guard.py` / `test_scoring_continuity.py` /
`test_markup_ai_prompt.py`):

- metrik 1 memakai `points[].buckets` dari `holder_history.json` (label
  `>$0-$10` … `>$500k`; repo ini tidak punya boundary $1M),
- metrik 6 menurunkan level support D1 sendiri
  (`accumulation.derive_support_level` dari candle harian
  `core.get_daily_candles`) karena `levels.json` tidak ada,
- metrik 7 memakai tag `fresh_wallet` GMGN: **identitas funder tidak tersedia**
  tanpa scan Helius, jadi yang diukur pola "wallet baru beli bertahap tanpa
  jual", dan disclaimer itu ditulis eksplisit di penjelasan metrik.

State baru disimpan di file **terpisah** `accumulation_history.json` (skema
`wallet-depth-accumulation-v1`, git-ignored) — hanya skor/status + proporsi
thinning per run, dipakai metrik 8 untuk menunjukkan arah (delta pp) dari waktu
ke waktu. Format `watchlist.json`, `holder_history.json`, `holder_status.json`
tidak diubah.

## 2. Baris watchlist: kolom "Sejak masuk" + sinkronisasi (modul `watchlist_detail.py`)

1. **Delta sejak masuk** — `dust_change_since_added()` membandingkan titik
   pertama **pada/setelah** tanggal `added` dengan **scan terakhir**: perubahan
   relatif %, poin persentase (satuan rule alert), dan perubahan jumlah wallet
   dust. Tooltip memuat semuanya + umur window; bila belum ada titik setelah
   tanggal masuk, pembandingnya titik pertama dan itu ditandai.
2. **Warna sesuai ambang user** — `tone_for_change()`: turun **≥ 50%** = hijau
   `#15803d`, naik **≥ 100%** = merah `#b91c1c`, di antaranya abu-abu; nilai
   awal 0% → "—" (perubahan relatif dari nol tidak bermakna).
3. **Sinkronisasi watchlist ↔ scan terakhir** — akar masalahnya sama dengan
   kasus "grafik 0,7% tapi kartu 1,16%" di permintaan ke-4: baris watchlist
   membaca snapshot `holder_status.json` (cron) sedangkan sparkline membaca
   `holder_history.json` yang sudah memuat titik scan manual/scan lebih baru,
   dan caption "Terakhir scan" memakai `status.updated_at` global. Perbaikan:
   `resolve_view()` memilih sumber **terbaru** per baris (menandai `drift` bila
   snapshot ≠ titik history > 0,01 pp, dan `stale` bila umur data > 2 jam),
   `previous_pct()` memilih pembanding badge yang benar (bucket sebelum nilai
   yang ditampilkan, bukan `sampled[-2]`), tiap baris kini menulis
   `scan <waktu> · titik history · ⚠️ snapshot ≠ history · basi`, dan caption
   card diganti `sync_caption_text()` — satu waktu "Scan terakhir" + rincian
   berapa token memakai snapshot cron / titik history lebih baru / belum ada
   data / basi.
4. **Perubahan `app.py` dibatasi rendering**: impor `watchlist_detail`, hitung
   `view`/`change` sekali per token, tambah kolom **Sejak masuk** (7 → 8
   kolom), dan ganti caption. Tidak ada logika kalkulasi baru di `app.py`, dan
   `lp_watchlist.py` / `holder_status.py` / `holder_history.py` tidak disentuh.

## 3. Tes

`tests/test_accumulation.py` (59), `tests/test_watchlist_detail.py` (37),
`tests/test_watchlist_row_ui.py` (5, AppTest `app.py`),
`tests/test_accumulation_page.py` (6, AppTest halaman baru + guard "Helius
tidak tersentuh" + store snapshot di temp dir). Semua tanpa jaringan dan tanpa
pytest, mengikuti pola suite yang ada.

```
Ran 615 tests ... OK   (sebelumnya 508)
```

# Kegiatan — 3 September 2026

Dua permintaan user: ambang **HATI-HATI** untuk dust holder dan watchlist
terpisah **Chart LP** untuk token hasil Scan Meteora.

1. **Ambang dust jadi dua tingkat**: `≥ 0,5% MC = HATI-HATI` (badge kuning,
   peringatan dini) dan `≥ 1% MC = BAHAYA` (tetap disembunyikan dari Scan
   Meteora). `holder_history.dust_flag` mengembalikan level
   `ok`/`caution`/`danger`, helper baru `dust_level_rank`; badge di `app.py`
   + halaman Holder, dan grafik 4 jam kini punya garis ambang 0,5% & 1%.
   (Catatan: user sempat menulis 5%, lalu dikoreksi menjadi **0,5%**.)
2. **Card 🌊 Chart LP di paling atas dashboard**: watchlist terpisah berisi
   token `source=meteora`. Modul baru `lp_watchlist.py` menyiapkan baris
   data + figure: grafik perubahan dust holder per token (dust % MC + jumlah
   wallet dust + garis ambang), overlay semua token LP, Δ 4 jam & Δ total
   dalam poin persentase, sparkline, dan urutan BAHAYA → HATI-HATI → AMAN.
   Token LP tidak muncul lagi di watchlist holder bawah.
3. **Tambah manual ke card Meteora**: form ➕ Tambah token punya radio
   *Masuk ke card* (📋 Watchlist Holder / 🌊 Chart LP), card LP punya form
   CA sendiri, ⭐ di Scan Meteora menulis `source=meteora`, tombol 🌊/📋
   memindahkan token antar card lewat `watchlist.set_watchlist_source`
   (op journal baru `"source"`, aman terhadap push gagal / entri baru).

# Kegiatan — 1 September 2026

Fokus UI ke **analisa holder dust** (bukan silent 12 jam) + Scan Meteora.

1. Watchlist: buang Status/Net/Harga 12j, Real, Dust kolom lama, Scan,
   shortcut CVD. Ganti ringkasan dust (jumlah wallet + % MC), badge
   AMAN / HATI-HATI (≥1%) / DUMP (>2%), sparkline 4 jam, tombol 🧮 ke
   halaman Holder Analytic.
2. Trending/Degen: buang kolom Real/Dust/Dust%MC/12 Jam/Net 12j dan
   scan holder. Listing GMGN saja (Token, MC, 24h).
3. Halaman baru `pages/5_🧮_Holder.py` (di bawah CVD): dust, grafik 4
   jam, sisa token kohort Crab+Fish.
4. CVD: buang 🧮 Holder Analytic + kartu silent 12 jam.
5. `holder_history.py` + `holder_history.json`: catat dust/kohort tiap
   scan, resample 4 jam. Cron watchlist holder-only.
6. Scan Meteora di halaman utama: API 24h (fee_ratio≥250) + 1h (≥1),
   DLMM active_tvl≥1000. Pool 24h yang masih di 1h tetap tampil. Dust
   >2% MC disembunyikan. Shortcut Meteora DLMM + HawkFi.

# Kegiatan — 31 Agustus 2026 (lanjutan)

**Migrasi total sumber data ke Helius** (kecuali listing Trending/Degen
yang memang hanya ada di GMGN):

1. Fix bug konversi holder Helius: `amount` DAS adalah unit RAW → dibagi
   `10^decimals` mint (decimals dari DAS `getAsset`, fallback RPC
   `getTokenSupply`; per-item bila tersedia; abort bersih bila tidak
   ketemu). Sebelumnya nilai USD holder 10^decimals× lebih besar (tier
   Shark bernilai triliunan $).
2. `_fetch_holders_snapshot`: **Helius dulu, GMGN
   fallback**. `fetch_swaps` Enhanced API diprioritaskan juga di
   `scripts/update_cvd.py` (fetch harian CVD) dengan fallback GMGN.
3. **Solscan API dilepas total**: `solscan_holders.py` hanya tersisa
   kalkulasi `wallet_depth` (bucket/tier); `get_solscan_key` +
   `solscan_api_key` dihapus; nilai `holder_source=solscan` lama otomatis
   jatuh ke `auto` (= Helius). Opsi sumber kini `auto`/`helius`/`gmgn`.
4. Tier Helius sekarang mengecualikan LP/pool via `pair_addresses`
   DexScreener; legend/ikon UI menghilangkan 📡 Solscan.
5. Workflow `daily-effort.yml` **belum** bisa diubah via push (GitHub App
   tanpa permission `workflows`) — tambahkan manual env `HELIUS_API_KEY` /
   `HELIUS_API_KEYS` di step scan (lihat snippet di README); tanpa secret
   → otomatis fallback GMGN.

# Kegiatan — 31 Agustus 2026

Holder token watchlist diambil dari **Solscan**, plus **Wallet Depth by
Threshold** ala halaman analytics Solscan.

## Yang dikerjakan

1. `solscan_holders.py`: fetch holder Solscan — Pro API `v2.0/token/holders`
   bila `SOLSCAN_API_KEY` ada (tiap baris membawa `value` USD + `percentage`
   dari Solscan), fallback Public API `token/holders` (nilai USD =
   balance × harga app), lalu fallback GMGN/Helius. Normalisasi ke bentuk
   holder GMGN; LP/pool (dari `pair_addresses` DexScreener) ditandai bukan
   wallet.
2. `wallet_depth()`: **bucket** `>$0-$10` … `>$500k` atas semua akun
   (seperti chart Solscan) dan **tier** 🦐/🦀/🐟/🐬/🦈 atas wallet murni —
   count, total value, % marketcap per bucket/tier.
3. `silent_accumulation.analyze_token` punya `holder_source`
   (`gmgn`/`solscan`/`auto`, default config `holder_source` = `auto`):
   watchlist (cron & tombol scan lokal) Solscan dulu; listing
   Trending/Degen tetap GMGN. Saat sumber Solscan, `holders["depth"]` +
   `holders["api"]` ikut tersimpan di snapshot `silent_status`.
4. UI watchlist: ikon 📡 Solscan di kolom Real, expander per token
   "📊 Wallet Depth by Threshold" berisi dua tabel (bucket & tier).
5. Workflow cron menerima env `SOLSCAN_API_KEY` (repo secret, opsional);
   `config.example.json` + docs diperbarui. Catatan: bila GitHub App
   menolak push perubahan `.github/workflows`, tambahkan env tersebut
   manual di settings repo.

Tidak diubah: logika silent 12 jam, filter holder depth (SILENT/LP/
PUMPDUMP), listing Trending/Degen.

# Kegiatan — 19 Agustus 2026 (lanjutan)

- Token baru: fetch penuh **48 jam** (bukan incremental), lalu kirim Telegram
  untuk **semua** sinyal di window itu (historis tetap dikirim, sekali per
  `event_id`).
- Payload Telegram: hari (WIB), jam bar, range harga, range MC, R/CVD/TX,
  link GMGN + DexScreener. Tag “Historis” vs “Sinyal baru”.
- `add_to_watchlist` memanggil `request_immediate_scan()` (workflow_dispatch)
  agar 48 jam ditarik segera, lalu cron 15 menit menyambung incremental.

# Kegiatan — 19 Agustus 2026

Port sinyal ekstensi [SMART_SEROK v9.1.3](https://github.com/lparmycalprut/SMART_SEROK) ke wallet-depth.

## Yang dikerjakan

1. **Watchlist dikosongkan** (`watchlist.json` = `{}`).
2. **Symbol otomatis** saat CA manual: field ticker dihapus di form Streamlit;
   `watchlist.fetch_token_symbol()` memanggil DexScreener.
3. **Sinyal diganti** dari wash-collapse / SBR menjadi:
   - 🔴 WASPADA DUMP
   - 🟢 SIAP2 PUMP
   - ⚔️ BATTLE TERJADI
   Engine: `serok_engine.py` (bar 1 jam, R ≥10× prev + |R|≥10, battle gap ≤2.5% + P65).
4. **Scan tiap 15 menit** (intended cron `*/15`). File workflow tidak bisa
   di-push oleh GitHub App (butuh permission `workflows`) — ubah manual
   `.github/workflows/daily-effort.yml` menjadi `*/15 * * * *`. Fetch 48 jam.
5. **Telegram** rapi: judul + `$SYMBOL`, syarat, R/CVD/TX/wallet, range MC (battle),
   jam WIB, tautan GMGN + DexScreener. Satu alert per `event_id`.
6. **Tes** `tests/test_serok_engine.py`; payload Telegram & UI disesuaikan.
   `python -m unittest` untuk modul baru lulus.

Tidak diubah tanpa perlu: halaman CVD, listing Trending/Degen, fetch GMGN,
persist watchlist GitHub.

# Kegiatan — 30 Agustus 2026

Refactor besar: **buang semua sinyal + Telegram**, fokus **silent
accumulation 12 jam** dan **holder depth**.

## Yang dikerjakan

1. Hapus modul sinyal (serok, reversal, effort, price_structure), scanner
   realtime, dan transport `signals.py` (Telegram) beserta secrets.
2. `silent_accumulation.py`: fetch holder GMGN paginasi `next`
   (verified limit 1000/page, `limit=1000`), klasifikasi real holder
   (>$10 value) vs dust (0 < value <= $10), dust % dari marketcap,
   net flow 12 jam (`token_trades`), deteksi silent (net >= $50,
   >= 3 akumulator, |harga| <= 5%, bot <= 35%).
3. `silent_status.py` + `scripts/scan_silent.py`: cron tiap ~15 menit
   publish snapshot ke ref `silent-live`.
4. `app.py` & `trending_ui.py`: kolom/holder-depth langsung saat scan
   Trending/Degen (real count, dust count, dust %MC, status 12 jam).
5. Halaman CVD: chart flow harian tanpa sinyal; `daily_effort.json`
   dipertahankan sebagai agregasi murni (`daily_store.py`).
6. Workflow `daily-effort.yml` target: Silent Accumulation 12H Scanner tanpa
   `TELEGRAM_*`. Catatan: file workflow tidak bisa di-push oleh GitHub App
   (butuh permission `workflows`), jadi `scripts/realtime_reversal.py`
   dipertahankan sebagai adapter ke `scan_silent.py` agar cron tetap
   berjalan; ubah workflow manual bila ingin langsung memanggil
   `scripts/scan_silent.py`.

Tidak diubah tanpa perlu: watchlist GitHub, fetch GMGN/Helius, listing
screener.
## Lanjutan hari yang sama — konfirmasi volume + volatilitas (permintaan ke-3)

User mengirim prompt baru: alert dust 0,25 pp masih sering false positive,
jadi tiap sinyal harus divalidasi volume + harga + volatilitas dulu, tetap
reaktif (< 5 menit), dan ambang dust yang ada tidak boleh diubah.

1. **Volume correlation** — `validate_alert_with_volume()` di
   `telegram_alerts.py`: dump butuh volume 4 jam ≥ 2× `avg_volume_7d`
   **dan** harga ≤ −1%; akumulasi butuh ≥ 1,5× **dan** tekanan beli >
   tekanan jual. Skor 0,70 dasar + ≤0,15 volume + ≤0,10 harga/tekanan +
   0,20 volatilitas tinggi yang mendukung arah; gagal gerbang → ≤0,40.
   `avg_volume_7d` dibaca sebagai rata-rata **per window 4 jam** selama
   7 hari agar sebanding dengan `volume_4h`. Semua kandidat yang ditolak
   di-log + dicatat ke `rejected_signals` supaya bisa diaudit.
2. **Volatility metrics** — `calculate_volatility_metrics()` di
   `holder_history.py` dari 16 candle hourly: `price_stddev_4h`,
   `price_range_4h`, `intra_hour_volatility`. Kalau `price_stddev_4h > 3%`
   ambang skor naik dari 0,70 ke **0,80** — dan karena volatilitas tinggi
   tanpa dukungan arah harga tidak memberi bonus, ambang itu benar-benar
   menyaring (terukur 0,702 < 0,80). Hasilnya disimpan berdampingan
   dust % MC di `holder_status.json` sebagai `tokens[mint].market_signal`.
3. **Sumber konteks** — `alert_context.py` (baru): candle hourly
   GeckoTerminal → DexScreener (data yang sudah diambil `analyze_token`,
   tanpa request tambahan) → `daily_effort.json`. Ditarik **lazy**: hanya
   token yang punya kandidat (keputusan user), memo 1× per token per run,
   jadi latensi run normal tidak bertambah. `core.get_hourly_candles()`
   baru dan `get_daily_candles()` kini agregasi dari candle yang sama.
4. **Data hilang** (keputusan user): alert tetap dikirim, diberi baris
   `⚠️ TIDAK TERVERIFIKASI` dengan skor 0,50 — jadi tidak ada sinyal yang
   hilang diam-diam saat GeckoTerminal mati.
5. **Dedup 1 jam** — selain event id bucket 4 jam, kini ada jeda minimum
   1 jam per token+jenis(+arah) lewat `alert_state.last_sent`; sebelumnya
   dua alert identik bisa terkirim berjarak ±2 menit di sekitar batas
   bucket.
6. **Review optimasi** (diminta user, tabel lengkap di
   `docs/PROGRESS.md`): heap untuk `matching_dexscreener_pairs` diukur
   **tidak** lebih cepat sehingga tidak diubah; `get_daily_candles`
   diperbaiki (sel null, `limit_days=0`, timestamp duplikat) dan batas UTC
   diverifikasi sampai kasus kabisat; `classify_holders` dibuat single-pass
   ramping (2,86 → 1,94 ms per 12k holder, keluaran identik di 500 trial);
   `wallet_movements()` tidak lagi dihitung dua kali; dua `TODO(alerts)`
   (429 `retry_after`, throttle GeckoTerminal).
7. **Tes** — 6 file baru, 141 tes tambahan: 369 lulus (sebelumnya 228),
   termasuk edge case volume 0, avg 0/None, NaN/inf, candle bolong,
   candle < 2, candle basi, payload DexScreener rusak, provider gagal,
   cooldown 1 jam, dan lazy-fetch.
## Permintaan ke-4 — AGENTHQ: grafik 0,7% tapi kartu "Dust hold % MC" 1,16%

User melaporkan angka yang tidak cocok di halaman Holder Analytic. Setelah
ditelusuri (snapshot live di ref `holder-live` + DexScreener), ada dua lapis
penyebab dan **bukan** bug grafik:

1. **Kartu metrik dan grafik membaca dua sumber berbeda umur.** Kartu metrik,
   badge, dan caption membaca snapshot `holder_status.json` (cron 21:35 WIB),
   sedangkan grafik membaca `holder_history.json` yang sudah memuat titik scan
   manual yang baru dijalankan. Tombol scan FULL hanya `ingest_many(detail=True)`;
   ia tidak mempublish snapshot — dan memang tidak boleh, karena
   `snapshot_status` membangun `tokens` hanya dari analyses yang diberikan
   (publish satu token = token lain hilang dari dashboard).
2. **Harga sedang pump +74% dan cutoff dust itu $10 dalam USD.** harga
   0,0001085 → 0,0001889, MC $108.545 → ±$188.968. dust % MC invariant
   terhadap harga, tetapi **klasifikasi**-nya tidak: wallet dengan 52.938–
   92.166 token (nilai lama $5,74–$10) "lulus" menjadi real >$10, sehingga
   ±40% nilai dust pindah bucket dan dust % MC turun 1,16% → 0,7% tanpa ada
   yang jual. Cerminannya (harga turun) menaikkan dust % MC ±0,4-0,5 pp —
   di atas ambang dump 0,25 pp — dan itu lolos gerbang volume/harga.

Perbaikan yang dikerjakan (user memilih opsi A): `holder_status` mendapat
`compact_manual_scan()`, `resolve_token_view()`, dan `apply_manual_scan()`;
halaman Holder Analytic + `app.py` mengoverlay scan manual yang lebih baru ke
snapshot sebelum render, sehingga kartu metrik, badge, watchlist, dan Chart LP
setuju dengan grafik, dan caption menandai *scan manual barusan*. Guard
re-klasifikasi harga (opsi B) belum dikerjakan — keputusannya (**annotate,
bukan reject**) dicatat sebagai `TODO(alerts)` di `telegram_alerts.py`.
Tes: 27 murni + 2 AppTest baru → **398 lulus**.

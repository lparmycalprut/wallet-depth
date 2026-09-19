# -*- coding: utf-8 -*-
"""Card **🏆 Scan Best Pool Meteora** untuk halaman utama (``app.py``).

**Satu tombol deteksi, satu tabel — 24H saja.** Dulu card ini punya dua tombol
+ pemilih lane (permintaan user 2026-09-13: "kayaknya untuk timeframe 30m harus
kita pisah tombol deteksinya dan tabel serta fungsi fee/v lebih besar … di scan
meteora pool, kita akan punya 2 tombol 24H dan 30M"); sejak 2026-09-16 lane 30M
dihapus (permintaan user: *"hapus scan 30 menit, kita sisakan yang 24 jam
saja"*) sehingga :data:`meteora_screener.BEST_LANES` hanya berisi ``("24h",)``
dan :func:`meteora_screener.normalize_best_lane` memetakan semua alias lama
(``30m``/``1h``/``both``) ke 24H:

- **🏆 Scan Best Pool 24H + Holder** — listing timeframe 24H saja; hanya pool
  ``F/V ≥ 5×`` (``BEST_FV_24H_MIN``) yang di-scan detail (holder FULL Helius).
  Yang di bawah itu **langsung di-skip** dan masuk listing "disembunyikan"
  (toggle "▶ N pool dilewati" tetap ada — di 24H kandidat gagal justru
  berguna untuk dibandingkan; aturan 30M "jangan tampilkan yang tidak
  terpenuhi" + label "OK" hijau di sel F/V dicabut bersama lane-nya);
- Volatility 0 **gugur dan dibuang total** (2026-09-14): ∞ bukan kelolosan,
  pool tanpa pergerakan tidak masuk tabel lolos maupun daftar "dilewati"
  (permintaan user: "jika volatility 0 jangan tampilkan, karena tidak ada
  pergerakan disitu");
- **Volatility di luar 1%–10% juga disembunyikan** (2026-09-16, permintaan
  user: *"volatility kurang dari 1 sembunyikan juga"* + *"volatility > 10
  sembunyikan juga"*) — :data:`meteora_screener.BEST_VOL_SHOW_MIN` /
  ``BEST_VOL_SHOW_MAX``, batasnya inklusif jadi 1% dan 10% tetap tampil,
  alasannya muncul sebagai ``volatility … < 1%`` / ``> 10%`` di sub sel F/V
  tabel "dilewati";
- **Top10 holder >= 20% supply tidak ditampilkan lagi**
  (:data:`meteora_screener.BEST_TOP10_MAX_PCT`, permintaan user 2026-09-16:
  *"jika ada top 10 >= 20% jangan tampilkan"* — batas inklusif di sisi BUANG,
  tepat 20% ikut hilang);
- **Likuiditas total GMGN di bawah ambang tidak ditampilkan** (2026-09-17,
  permintaan user: *"jika grand total liquiditas kurang dari 1M, jangan
  tampilkan di hasil scan"*; ambangnya **$500K** —
  :data:`gmgn_liquidity.MIN_TOTAL_LIQ_USD`, diturunkan dari $1M sore harinya
  sesudah user melaporkan *"poolnya kok jadi kosong, padahal token PAID
  harusnya masuk"*: likuiditas GMGN PAID terukur $884.912, jadi $1M membuang
  dia dan praktis seluruh listing) — angka per token diambil dari GMGN
  (:mod:`gmgn_liquidity`, satu request batch untuk semua kandidat) dan baris
  yang terbukti di bawah ambang masuk daftar "dilewati" dengan alasannya di
  sub sel F/V;
- **Filter server Jupiter safeguard dimatikan default-nya**
  (2026-09-17, :data:`meteora_screener.JUPITER_SAFEGUARD_FILTERS` masih
  tersedia dengan kwarg ``safeguard=True``) — filter server
  ``base_token_has_critical_warnings=false&&quote_token_has_critical_warnings=false``
  yang dipasang 2026-09-16 (permintaan user *"scan baru saya tambahkan
  jupiter safeguard untuk filter yang mungkin rug"*) ternyata membuang
  token seperti PAID sebelum listing sampai ke client (tidak tampil di
  tabel lolos maupun daftar "dilewati"). Bendera token kritis
  (freeze/hook/transfer-fee/non-transferable dll.) **tetap dilaporkan** di
  kolom RugCheck sebagai informasi — kolom itu tidak pernah membuang baris;
- **Kolom RugCheck baru** (2026-09-16; angka likuiditas beralih ke **GMGN**
  2026-09-17): tiap mint base diperiksa lewat honeypot checker
  **rugchecker.cc** (modul :mod:`rugchecker`, tanpa API key) — verdict
  AMAN/WASPADA/BERISIKO/RUG + bendera keamanan, dengan **angka likuiditas
  total dari GMGN** (modul :mod:`gmgn_liquidity`; permintaan user *"ubah
  info liquidititas dari rugchecker.cc ke gmgn saja"*) — rincian per-DEX
  rugchecker.cc tidak lagi ditampilkan. Saringan "likuiditas < ambang" di
  atas adalah satu-satunya yang membuang berdasarkan angka ini;
- **LPs HIJAU bila > 100 LP** (permintaan user 2026-09-16: *"LPs jika lebih
  dari 100, kasih warna hijau jika tidak, tidak ada perubahan"*),
  :data:`LP_GREEN_COLOR` / :data:`LP_GREEN_MIN_LP`.

F = fee_active_tvl_ratio, V = volatility. Hasil scan disimpan di session key
``best_pool_scan_24h`` (+ cache berkas dengan nama yang sama) sehingga hanya
ada satu tabel dan hasil 30M lama tidak pernah bisa muncul; key gabungan lama
``best_pool_scan`` tidak dibaca lagi.

- urutan baris tiap tabel (permintaan user 2026-09-15: *"kita urutkan
  fee/TVL paling besar dulu, baru perkalian f/v"*): **Fee/TVL terbesar**
  (``fee_active_tvl_ratio``) → **F/V terbesar** (``row_fv_ratio``) →
  **volume / active TVL** (``volume_active_tvl_ratio``, dikirim API Meteora
  dan ditulis di baris kecil kolom Vol) → **dust % MC terkecil**;
- **Kolom Token menulis pasangan pool-nya** (permintaan user 2026-09-15:
  "kolom Token sekarang akan menunjukkan pasangan pairnya, misal
  ALLINU/SOL"): ``$TOKEN`` di baris pertama, pasangan pool DLMM di bawahnya
  (``row_pair_label`` — nama pool dari API Meteora, mis. ``ALLINU/SOL``),
  alamat mint tetap di baris terakhir. Angka **F/V** diformat
  ``format_fv_ratio``: satu desimal di bawah 100× (``10,1×``), bulat +
  pemisah ribuan dari 100× ke atas (``6,328,266×``) — rasio ekstrem tidak
  lagi tampil sebagai ``6328266.1×`` (laporan user 2026-09-15: *"gold
  menunjukkan 6328266.1 F/V"*);
- **Kolom** (2026-09-19, 13 kolom + **STRATEGY** paling kanan di tabel
  utama): Token, **F/V**, **Fee/TVL** (pembilang
  F-nya — permintaan user 2026-09-14: "kolom Fee/TVL taruh sebelah kanan
  F/V"), **Volat**, **Active Range**, **LPs**, **Fee %**, **MC**, **A.TVL**,
  **Vol 24h**, **Top10**, **RugCheck**, **Pool**, **STRATEGY** — permintaan user
  2026-09-16: *"Active Range kolom ini pindah ke kanan volat"* dan
  *"kolom LPs pindah ke kanan active range setelah dipindah"*. **Active
  Range** menulis persen saja (``-34.5% / +19.0%`` = harga masih boleh turun /
  naik sebelum keluar dari bin berisi likuiditas); kolom **Dust** (jumlah
  wallet) tetap dihapus. **Penataan 2026-09-17** (permintaan user):
  kolom **Dust %MC dihapus** (*"hapus kolom dust %"*) — dust %MC masih
  dihitung sebagai tie-break urutan terakhir, hanya tidak lagi tampil
  sebagai kolom; **tombol ⭐ favorit/watchlist dihapus** (*"hapus tombol
  favorit / watchlist"*) — token watchlist kini dikelola dari halaman
  📦 TEMP; kolom **Pool** kini memuat tombol 📋 **copy link HawkFi** di
  samping tautan 🌊Meteora/🦅HawkFi (*"tambahkan copy link hawkfi dibagian
  scan"*) — clipboard murni JS, tanpa rerun; dan **tiap kolom dibatasi
  garis vertikal** (*"batasi per kolom dengan garis naik turun"*) lewat
  marker ``.bp-cols-next`` + CSS di ``dashboard_components.render_styles``
  (hanya layar > 768px);
- **Penataan 2026-09-19** (permintaan user): **kolom Bubble Map dihapus**
  (*"hapus tentang bubblemap, sisakan hyperlink ke bubblemapnya saja"*) —
  cluster/top holder/warning tidak lagi ditampilkan dan status Bubblemaps
  tidak lagi di-fetch saat scan (``scan_best_lane(bubblemap=False)``), yang
  tersisa hanya tautan 🫧 ke ``v2.bubblemaps.io`` di kolom **Pool**
  (:func:`links.bubblemap_icon_link_html`); **kolom STRATEGY baru di paling
  kanan** (*"Kasih kolom baru dipaling kanan STRATEGY"*) — saran penempatan
  likuiditas per pool dari :mod:`gmgn_liquidity`
  (:func:`gmgn_liquidity.row_strategy`): likuiditas total **> $500K** →
  ``hybird 7030, bidask 3070 - full range``, selain itu (di bawah ambang,
  tepat $500K, atau tidak terukur) → ``hybird 5050, bidask - full range``
  (teks verbatim permintaan user). Kolom STRATEGY **hanya ada di tabel
  utama** — tabel "▶ N pool dilewati" tetap 13 kolom tanpa STRATEGY
  (konfirmasi user 2026-09-19) — dan seperti kolom informasi lain tidak
  pernah membuang baris; **tulisan tabel diperbesar** (*"agak perbesar
  tulisan table semuanya ya, tapi tidak mempengaruhi tampilan"*):
  :data:`HEADER_FONT_SIZE` 0.72rem → 0.82rem + class CSS ``.bp-*`` di
  ``dashboard_components.render_styles`` (nilai sel 0.95 → 1.05rem, baris
  kecil 0.65 → 0.74rem, simbol/pair/mint/tautan ikut naik) — hanya ukuran
  huruf yang berubah, lebar kolom (``_COL_SPEC``) dan tata letak tidak;
- **sorot hijau tua menyala** (``TOP_HIGHLIGHT_COLOR``, bold) di tabel utama:
  sel volatility terbesar, sel F/V tertinggi, dan sel Fee/TVL tertinggi scan
  itu — seri di puncak ikut ditandai semua; tabel "dilewati" tidak ditandai;
- kolom konteks menampilkan detail fee dan active TVL (**A.TVL**,
  **Fee/TVL** dengan fee USD + tier fee, Vol dengan Δ volume + rasio
  volume/active TVL) sebagai informasi.

**Persistensi (2026-09-14):** hasil scan disimpan ke cache berkas lokal
(``scan_result_cache.save_result``, key = session key lane-nya) dan dipulihkan
ke ``session_state`` bila sesi kosong, jadi **refresh browser (F5) tidak
menghilangkan tabel** — sesudah scan holder FULL yang memakan menit, user tidak
perlu menekan tombol scan lagi dari nol.

**🏆 BEST POOL badge (dust <= 0,035% MC) dihapus** 2026-09-13 sore per
permintaan user: "tulisan tentang dust holder BEST POOL aman dll hapus
juga". Pill di kepala card juga dihapus. Sejak 2026-09-17 kolom Dust %MC
sendiri ikut dihapus (permintaan user: *"hapus kolom dust %"*) — angkanya
tetap dipakai backend sebagai tie-break urut tanpa tampil di layar.

Detail karakteristik = **tooltip judul** — bukan caption panjang. Tombol ⭐
watchlist dihapus 2026-09-17 (permintaan user: *"hapus tombol favorit /
watchlist"*); kolom Pool kini punya tombol 📋 copy link HawkFi
(*"tambahkan copy link hawkfi dibagian scan"*).
"""
from __future__ import annotations

# Session key lama (satu listing gabungan 24H + 30M). Masih dibaca sekali untuk
# bermigrasi: hasil scan versi sebelum lane dipisah dipecah per timeframe, jadi
# user tidak kehilangan listing setelah update ini.
BEST_SESSION_KEY = "best_pool_scan"
BEST_SHOW_HIDDEN_KEY = "best_pool_show_hidden"
# Satu key per lane — ini yang dipakai card sejak 2026-09-13.
BEST_LANE_SESSION_KEY = "best_pool_scan_{}"
BEST_LANE_HIDDEN_KEY = "best_pool_show_hidden_{}"
BEST_ACTIVE_LANE_KEY = "best_pool_lane"


def best_lane_session_key(lane) -> str:
    """Session key hasil scan satu lane (``best_pool_scan_24h`` / ``_30m``)."""
    from meteora_screener import normalize_best_lane

    return BEST_LANE_SESSION_KEY.format(normalize_best_lane(lane))


def best_lane_hidden_key(lane) -> str:
    """Session key toggle "N disembunyikan" satu lane."""
    from meteora_screener import normalize_best_lane

    return BEST_LANE_HIDDEN_KEY.format(normalize_best_lane(lane))


def best_lane_gate_text(lane) -> str:
    """Syarat kelolosan satu lane dalam teks UI, angka dari konstanta screener.

    ``meteora_screener`` diimpor di dalam fungsi (pola tooltip modul UI lain)
    supaya modul ini tetap ringan diimpor dan ambangnya tidak pernah bisa basi.
    """
    from meteora_screener import lane_fv_min, lane_fv_sign, normalize_best_lane

    normalized = normalize_best_lane(lane)
    return f"F/V {lane_fv_sign(normalized)} {lane_fv_min(normalized):g}×"


def best_lane_detail(lane) -> tuple[str, str, str]:
    """``(label, warna, teks syarat)`` satu lane — dipakai pill, tombol, tooltip."""
    from meteora_screener import BEST_LANE_LABELS, normalize_best_lane

    normalized = normalize_best_lane(lane)
    return (BEST_LANE_LABELS.get(normalized, normalized.upper()),
            "#9333ea" if normalized == "30m" else "#0284c7",
            best_lane_gate_text(normalized))


def best_pool_tooltip() -> str:
    """Rule ada di tooltip, bukan caption — satu tombol, satu lane (24H)."""
    from meteora_screener import (BEST_ACTIVE_TVL_MIN, BEST_TOP10_MAX_PCT,
                                  BEST_VOL_SHOW_MAX, BEST_VOL_SHOW_MIN,
                                  gmgn_min_label, normalize_best_lane)

    active = normalize_best_lane("24h")
    label = best_lane_detail(active)[0]
    gate = best_lane_gate_text(active)
    volat = (f"{float(BEST_VOL_SHOW_MIN):g}%"
             f"\u2013{float(BEST_VOL_SHOW_MAX):g}%")
    return (
        f"Satu tombol = satu lane: listing API Meteora timeframe {label} "
        f"(category top, page_size 50), "
        f"pool_type=dlmm&&active_tvl>={int(BEST_ACTIVE_TVL_MIN)} "
        "(filter server Jupiter safeguard dimatikan default-nya sejak "
        "2026-09-17 — membuang token seperti PAID diam-diam; tersedia "
        "dengan kwarg safeguard=True). "
        f"{label}: {gate}. F = fee_active_tvl_ratio; V = volatility. Scan 30 "
        "menit dihapus 2026-09-16 (permintaan user: \"hapus scan 30 menit, "
        "kita sisakan yang 24 jam saja\") — semua alias lane lama "
        "(30m/1h/both) dipetakan ke 24H, tidak ada lagi dua tabel. "
        "Saringan layar dieksekusi SEBELUM scan holder (kuota Helius tidak "
        "terbakar) dan kandidat yang gugur tetap bisa dilihat lewat tombol "
        "\"dilewati\": (1) F/V di bawah "
        f"{gate.split(' ', 1)[1]} gugur; (2) volatility di luar {volat} "
        "gugur — di bawah itu pool nyaris tidak bergerak, di atas itu "
        "pergerakan lebih besar daripada fee yang dibagi; (3) Top10 "
        f"{BEST_TOP10_MAX_PCT:g}% atau lebih gugur (permintaan user "
        "2026-09-16: \"jika ada top 10 >= 20% jangan tampilkan\" — batasnya "
        "sekarang di sisi BUANG, jadi tepat 20% tidak lagi tampil; tanpa "
        "angka Top10 = tidak terukur, barisnya tetap tampil). Likuiditas "
        "total GMGN TIDAK lagi menyaring (2026-09-17 malam, permintaan user "
        "\"filter likuiditas hapus coba\") — angkanya tampil di kolom "
        f"RugCheck, HIJAU bila > {gmgn_min_label()}, MERAH bila < "
        f"{gmgn_min_label()} (permintaan user 2026-09-17), tepat di ambang "
        "tetap hitam. "
        "Volatility 0 "
        "gugur DAN tidak ditampilkan di mana pun: F/V \u221e bukan kelolosan, "
        "pool tanpa pergerakan dibuang total dari listing, tidak masuk tabel "
        "dilewati dan tidak dihitung di pill \"dilewati\". Metrik "
        "hilang/tidak valid dilewati (tetap terlihat di tabel disembunyikan). "
        "Kolom F/V memakai format satu desimal di bawah 100\u00d7 (10,1\u00d7) "
        "dan bulat berpemisah ribuan dari 100\u00d7 ke atas (6,328,266\u00d7), "
        "jadi rasio ekstrem tidak pernah tampil mentah; sel F/V baris gugur "
        "merah dengan sub \"gugur: <alasan>\". Hanya pool lolos yang "
        "mengambil detail holder FULL Helius. Dust, volume, dan tier fee "
        "bukan syarat kelolosan. Urutan tiap tabel: Fee/TVL terbesar, lalu "
        "F/V terbesar, lalu volume/active TVL terbesar, lalu dust %MC "
        "terkecil. Kolom Token menulis pasangan pool-nya apa adanya dari API "
        "Meteora (mis. ALLINU/SOL) \u2014 $SIMBOL tetap baris pertama, alamat "
        "mint di baris terakhir. Kolom, kiri ke kanan: Token, F/V, Fee/TVL "
        "(tepat di kanan F/V), Volat, Active Range, LPs, Fee % "
        "(tier fee pool, mis. 0,5% / 2%), MC, A.TVL, Vol 24h, Top10, RugCheck, "
        "Pool, STRATEGY \u2014 penataan 2026-09-16: Active Range digeser ke kanan "
        "Volat (dua-duanya soal pergerakan) dan LPs tepat di kanannya, lalu "
        "kolom RugCheck baru; penataan 2026-09-17 (permintaan user): kolom "
        "Dust %MC dihapus (\u0022hapus kolom dust %\u0022 \u2014 dust tetap jadi "
        "tie-break urutan terakhir, hanya tidak tampil sebagai kolom), "
        "tombol \u2b50 favorit/watchlist dihapus (\u0022hapus tombol favorit / "
        "watchlist\u0022), kolom Pool kini memuat tombol \U0001f4cb copy link "
        "HawkFi di samping tautan \U0001f30aMeteora/\U0001f985HawkFi "
        "(\u0022tambahkan copy link hawkfi dibagian scan\u0022 \u2014 salin URL "
        "pool HawkFi ke clipboard murni lewat JS, tanpa rerun), dan tiap "
        "kolom dibatasi garis vertikal (\u0022batasi per kolom dengan garis "
        "naik turun\u0022, hanya di layar lebar). Penataan 2026-09-19 "
        "(permintaan user): kolom **Bubble Map** dihapus (\u0022hapus tentang "
        "bubblemap, sisakan hyperlink ke bubblemapnya saja\u0022) \u2014 status "
        "cluster/holder terbesar Bubblemaps tidak ditampilkan lagi dan tidak "
        "di-fetch saat scan, yang tersisa hanya tautan \U0001f9e7 ke "
        "v2.bubblemaps.io di kolom Pool; kolom **STRATEGY** baru di paling "
        "kanan (\u0022Kasih kolom baru dipaling kanan STRATEGY\u0022, hanya di "
        "tabel utama \u2014 tabel \u0022dilewati\u0022 tetap tanpa STRATEGY): "
        f"likuiditas total > {gmgn_min_label()} ditulis \u0022hybird 7030, "
        "bidask 3070 - full range\u0022, selain itu (di bawah ambang, tepat di "
        "ambang, atau tak terukur) \u0022hybird 5050, bidask - full range\u0022. "
        "Active Range menulis persen "
        "saja: -34.5% / "
        "+19.0% artinya harga pool masih boleh turun 34,5% atau naik 19,0% "
        "sebelum keluar dari bin yang berisi likuiditas (min_price \u2026 "
        "max_price API Meteora) \u2014 di luar range itu posisi LP berhenti "
        "menghasilkan fee; 0.0% berarti harga persis di tepi range. Harga bin "
        "mentah, lebar range, dan jumlah bin ada di tooltip selnya. LPs "
        f"HIJAU bila > {LP_GREEN_MIN_LP:g} liquidity provider (permintaan "
        "user 2026-09-16), selain itu tampil biasa. Kolom **RugCheck** "
        "melaporkan tiap mint base lewat honeypot checker rugchecker.cc "
        "(tanpa API key): verdict AMAN / WASPADA / BERISIKO / RUG + bendera "
        "keamanan (mintable, freezable, closable, non-transferable, "
        "transfer-fee, hook) + likuiditas per DEX dalam versi ringkas "
        "(top beberapa pool + total + share pool ini) dan pasar (MC) \u2014 "
        "verdict RUG hanya bila honeypot, bendera kritis (mint/freeze/"
        "non-transferable/hook/transfer-fee) jadi BERISIKO, sisanya minor "
        "jadi WASPADA; RUGCHECK TIDAK PERNAH MEMBUANG BARIS \u2014 ia kolom "
        "informasi, saringannya tetap F/V + volat + Top10; angka likuiditas "
        f"GMGN di baris kecilnya HIJAU bila > {gmgn_min_label()}, MERAH bila "
        f"< {gmgn_min_label()}, selain itu tetap hitam (bendera safeguard "
        "Jupiter "
        "disajikan lewat kolom RugCheck, bukan filter server, supaya token "
        "seperti PAID tidak hilang diam-diam dari listing). Kolom "
        "**STRATEGY** (paling kanan, hanya tabel utama) menulis saran "
        "penempatan likuiditas dari ambang yang sama dengan warna likuiditas "
        f"GMGN ({gmgn_min_label()}): likuiditas total di atas ambang memakai "
        "split hybird 70/30 (bidask 30/70), di bawahnya \u2014 termasuk tepat "
        "di ambang dan angka yang tidak terbaca \u2014 split 50/50, keduanya "
        "dengan \u0022full range\u0022. Teks selnya verbatim permintaan user "
        "2026-09-19; angkanya dibaca dari laporan likuiditas yang sama dengan "
        "kolom RugCheck, dan kolom ini juga hanya informasi (tidak pernah "
        "membuang baris). Sorot "
        "hijau tua menyala di tabel utama: sel volatility terbesar, sel F/V "
        "tertinggi, dan sel Fee/TVL tertinggi (kalau seri, semua di puncak "
        "ikut ditandai; tabel dilewati tidak ditandai)."
    )



# Lebar kolom listing (permintaan user 2026-09-14: "kita tata kolomnya baik
# untuk 24jam maupun 30menit — Dust hapus — Token F/V Volat Dust %MC, 4 kolom
# ini diletakkan paling awal"): Token, F/V, Fee/TVL, Volat di depan, lalu
# Active Range, LPs, konteks pasar (Fee %, MC, A.TVL, volume 24 jam, Top10),
# RugCheck, Pool (+ **STRATEGY** di paling kanan, hanya tabel utama). Kolom
# **Dust** (jumlah wallet) dihapus hari yang sama;
# kolom **Dust %MC** dan **tombol ⭐ watchlist** dihapus 2026-09-17
# (permintaan user: "hapus kolom dust %" + "hapus tombol favorit /
# watchlist") — kolom Pool juga menyerap tombol 📋 copy link HawkFi
# ("tambahkan copy link hawkfi dibagian scan") jadi bobotnya dinaikkan
# 0,8 → 1,05 supaya tiga ikon muat; total turun dari 15 ke 13 kolom, sempat
# naik ke 14 kolom 2026-09-18 dengan **Bubble Map** (cluster + top holder +
# warning), lalu **kembali 13 kolom** 2026-09-19 karena kolom Bubble Map
# dihapus (permintaan user: "hapus tentang bubblemap, sisakan hyperlink ke
# bubblemapnya saja") — tautan 🫧-nya pindah ke kolom Pool. Kolom
# **STRATEGY** (2026-09-19, permintaan user: "Kasih kolom baru dipaling kanan
# STRATEGY") menambah satu kolom lagi HANYA di tabel utama (14 kolom), tabel
# "▶ N pool dilewati" tetap 13 kolom (konfirmasi user 2026-09-19) — karena
# itu lebar kolom dibaca lewat ``_col_spec(show_strategy)`` dan judulnya
# lewat ``_lane_titles(lane, show_strategy)`` supaya header, lebar, dan sel
# selalu satu jumlah.
# Penataan 2026-09-16 (permintaan user): **Active Range** pindah ke
# kanan Volat, **LPs** mengikuti tepat di kanannya, dan kolom **RugCheck**
# ditambah sebelum Pool. Judul kolom volume dulu mengikuti lane-nya
# (``_lane_titles``: 24H "Vol 24h", 30M "Vol 30m"); sejak lane 30M dihapus
# judulnya selalu "Vol 24h" — kolom Src sudah lama dihapus bersama pemisahan
# lane.
# Kolom **Fee %** (fee trading pool, mis. 0.5%, 2%) ditambah 2026-09-14 tepat
# setelah Dust %MC (permintaan user: "tambahkan detail pool fee % … setelah
# dust%MC … ini maksudnya fee di pool tersebut, misal 0.5%, 2%, dll").
# Kolom **Fee/TVL** dipindah tepat di kanan **F/V** hari yang sama
# (permintaan user: "kolom Fee/TVL taruh sebelah kanan F/V") — pembilang F
# menempel pada rasio F/V-nya; Volat, Dust %MC, dan semua kolom di kanannya
# bergeser satu posisi.
# Kolom **Active Range** ditambah 2026-09-14 (permintaan user: "tambahkan
# Active Range, tapi % saja, misal -30% +40") tepat di kanan **A.TVL**: dua
# angka itu sama-sama soal bentuk likuiditas pool. Isinya persen saja —
# berapa harga masih boleh turun / naik sebelum keluar dari bin berisi
# likuiditas (``meteora_screener.active_range_pct``); harga bin mentah +
# jumlah bin ada di tooltip sel.
# Lebar **F/V** dinaikkan 2026-09-15 (0,7 → 1,0): angka rasio kini bulat +
# pemisah ribuan (``6,328,266×``, lihat ``meteora_screener.format_fv_ratio``)
# sehingga butuh ruang lebih; Token juga naik tipis (1,4 → 1,45) karena kolom
# itu sekarang memuat baris pasangan pool (``ALLINU/SOL``). Yang dikurangi
# kolom informasi (MC, Top10, Fee %) supaya total masih seimbang.
# Bobot 2026-09-16 (kolom ke-15): sama seperti sebelumnya, hanya digeser —
# Active Range + LPs naik ke kanan Volat, RugCheck dapat bagian dari MC/A.TVL
# (0,6→0,55 / 0,72→0,68) dan Pool (0,95→0,8); Token 1,45→1,4 karena baris
# pasangan tetap satu baris pendek.
# Bobot 2026-09-17 (15 → 13 kolom): Dust %MC (0,8) dan ⭐ (0,4) dicabut;
# Pool 0,8 → 1,05 karena kini memuat tautan 🌊Meteora + 🦅HawkFi + tombol 📋
# copy link HawkFi (permintaan user: "tambahkan copy link hawkfi dibagian
# scan", "hapus kolom dust %", "hapus tombol favorit / watchlist").
# Bobot 2026-09-19: kolom **Bubble Map** (1,0) dicabut dari daftar — bobot
# 13 kolom dasar TIDAK diubah sama sekali (kolom lain tidak melebar/menyempit,
# permintaan user "agak perbesar tulisan table semuanya ya, tapi tidak
# mempengaruhi tampilan" dijawab dengan ukuran huruf, bukan lebar kolom);
# kolom Pool tetap 1,05 walau kini memuat ikon ke-4 (🫧) karena tautan 🫧
# hanya satu emoji dan ``.pool-links`` sudah flex-wrap. **STRATEGY** dapat
# 1,35 (``STRATEGY_COL_WIDTH``) karena teksnya paling panjang di tabel
# ("hybird 7030, bidask 3070 - full range") dan ditulis nowrap per frasa.
_COL_SPEC = [1.4, 1.0, 0.75, 0.58, 0.95, 0.5, 0.58, 0.55, 0.68, 0.8,
             0.6, 1.0, 1.05]

#: Indeks kolom **Pool** di ``_COL_SPEC`` (kolom terakhir tabel "dilewati").
POOL_COL_INDEX = 12

#: Bobot kolom **STRATEGY** (paling kanan, hanya tabel utama — 2026-09-19).
STRATEGY_COL_WIDTH = 1.35


def _col_spec(*, show_strategy: bool = True) -> list[float]:
    """Lebar kolom satu tabel: 13 kolom dasar + STRATEGY bila diminta.

    Tabel utama (pool lolos) memakai ``show_strategy=True`` → 14 kolom dengan
    **STRATEGY** di paling kanan; tabel "▶ N pool dilewati" memakai
    ``False`` → 13 kolom tanpa STRATEGY (konfirmasi user 2026-09-19: kolom
    STRATEGY hanya untuk tabel utama). Daftar dasarnya tidak pernah
    dimutasi, jadi kedua tabel bisa dirender bergantian tanpa lebar yang
    saling menular.
    """
    spec = list(_COL_SPEC)
    if show_strategy:
        spec.append(STRATEGY_COL_WIDTH)
    return spec


def _lane_titles(lane, *, show_strategy: bool = True) -> list[str]:
    """Judul kolom satu tabel — kolom volume dinamai sesuai window lane-nya.

    API Meteora mengembalikan volume/fee window ``timeframe`` yang diminta,
    jadi judul kolom volume dulu mengikuti lane (penataan kolom 2026-09-14:
    "baik untuk 24jam maupun 30menit"). Sejak 30M dihapus (2026-09-16) window
    yang diminta selalu 24 jam, jadi judulnya tetap "Vol 24h" untuk input apa
    pun — fungsi ini tetap menerima ``lane`` supaya pemanggil lama tidak
    berubah.

    **Active Range** (ditambah 2026-09-14) duduk di kanan **Volat** dan
    **LPs** di kanannya (permintaan user 2026-09-16: *"Active Range kolom ini
    pindah ke kanan volat"* + *"kolom LPs pindah ke kanan active range setelah
    dipindah"*) — Volat, Active Range dan LPs sama-sama soal bentuk +
    pergerakan likuiditas, jadi ketiganya dibaca sekali lirikan. Isinya persen
    saja (``-34.5% / +19.0%``).

    **Dust %MC** dan kolom **⭐** watchlist tidak lagi ada sejak 2026-09-17
    (permintaan user: *"hapus kolom dust %"* + *"hapus tombol favorit /
    watchlist"*). Kolom **Bubble Map** (sempat ditambah 2026-09-18)
    **dihapus 2026-09-19** (permintaan user: *"hapus tentang bubblemap,
    sisakan hyperlink ke bubblemapnya saja"*) sehingga kolom terakhir tabel
    "dilewati" kembali **Pool** — tautan 🫧 ke v2.bubblemaps.io kini ikut di
    kolom Pool. ``show_strategy=True`` (tabel utama) menambah judul
    **STRATEGY** di paling kanan (*"Kasih kolom baru dipaling kanan
    STRATEGY"*), jadi tabel utama 14 kolom dan tabel "▶ N pool dilewati" 13
    kolom — jumlahnya harus selalu sama dengan ``_col_spec()``.
    """
    from meteora_screener import normalize_best_lane

    # Satu judul volume saja: lane 30M dihapus 2026-09-16, window API selalu
    # 24 jam — ``normalize_best_lane`` masih menerima alias lama (dipetakan ke
    # 24H) jadi penamaan kolom tidak pernah bisa lagi tertulis "Vol 30m".
    _ = normalize_best_lane(lane)
    titles = ["Token", "F/V", "Fee/TVL", "Volat", "Active Range", "LPs",
              "Fee %", "MC", "A.TVL", "Vol 24h", "Top10",
              "RugCheck", "Pool"]
    if show_strategy:
        titles.append("STRATEGY")
    return titles


# Hijau tua menyala penanda sel tertinggi di tabel utama (permintaan user
# 2026-09-14: "tandai volatility paling besar …" + "tandai f/v tertinggi …
# menjadi warna hijau menyala" + lanjutan: "yang paling tinggi nilainya kasih
# warna hijau menyala, hijau tua menyala" → F/V, Fee/TVL, Volat tertinggi
# semua memakai satu warna hijau tua menyala). Dipakai sel Volat, sel F/V,
# dan sel Fee/TVL.
TOP_HIGHLIGHT_COLOR = "#15803d"


#: Hijau kolom **LPs** (permintaan user 2026-09-16: "LPs jika lebih dari 100,
#: kasih warna hijau jika tidak, tidak ada perubahan"). Strict: tepat 100 LP
#: masih hitam. Warna #16a34a = hijau yang sama dengan Δ volume naik / label
#: "OK" lama — sengaja BUKAN ``TOP_HIGHLIGHT_COLOR`` supaya penanda "tertinggi
#: di tabel" tetap punya artinya sendiri.
LP_GREEN_COLOR = "#16a34a"
LP_GREEN_MIN_LP = 100.0


#: Ukuran huruf judul kolom tabel (permintaan user 2026-09-19: *"agak
#: perbesar tulisan table semuanya ya, tapi tidak mempengaruhi tampilan"*).
#: Dulu ``0.72rem`` ditulis inline di :func:`_render_best_table`; sekarang
#: jadi konstanta yang **dipakai class ``.bp-col-title``** di
#: ``dashboard_components.render_styles`` — tes memastikan CSS-nya memakai
#: nilai ini, jadi menaikkan ukuran huruf cukup mengubah satu angka di sini.
#: Kenaikannya sengaja kecil (0.72 → 0.82rem) dan hanya menyangkut ukuran
#: huruf: lebar kolom (``_COL_SPEC``), jumlah kolom, garis pembatas, dan tinggi
#: baris tidak berubah — judul tetap satu baris karena ``white-space:nowrap``
#: di class-nya. Ukuran huruf ISI sel (nilai + baris kecil + tautan) ikut
#: dinaikkan di CSS yang sama lewat class ``.watchlist-*``/``.pool-links``.
HEADER_FONT_SIZE = "0.82rem"


def _top_span(text: str) -> str:
    """Bungkus isi sel dengan hijau tua menyala + bold — penanda tertinggi tabel."""
    return (f'<span style="color:{TOP_HIGHLIGHT_COLOR};font-weight:800;">'
            f'{text}</span>')


#: Judul kolom STRATEGY (permintaan user 2026-09-19, huruf besar semua).
STRATEGY_COL_TITLE = "STRATEGY"


def _strategy_cell_html(text: str) -> str:
    """Isi sel **STRATEGY**: teks verbatim user, dipenggal sebelum ``- full``.

    Teksnya panjang untuk satu kolom (``hybird 7030, bidask 3070 - full
    range``), jadi frasa ``- full range`` dijaga tetap utuh (``nowrap`` lewat
    class ``.bp-strategy-range`` di ``dashboard_components.render_styles``)
    sementara bagian depannya boleh melipat — supaya kolomnya tidak perlu
    dilebarkan (permintaan user 2026-09-19: *"agak perbesar tulisan table
    semuanya ya, tapi tidak mempengaruhi tampilan"*: tampilan/lebar kolom
    tetap, hanya ukuran huruf yang naik). Tanpa pemisah `` - `` teksnya
    ditulis apa adanya.
    """
    import html as _html

    body = str(text or "")
    if not body:
        return "—"
    head, sep, tail = body.rpartition(" - ")
    if not sep:
        return _html.escape(body)
    # ``rpartition`` memisahkan " - " sehingga ``head`` berakhir tanpa spasi
    # dan ``sep`` memuat spasinya: spasi tunggal di dalam span nowrap supaya
    # frasa "- full range" tidak pernah terpenggal di tengah.
    return (f'{_html.escape(head)}<span class="bp-strategy-range">'
            f'{_html.escape(sep + tail)}</span>')


def _strategy_cell(row) -> tuple[str, str, str]:
    """Sel **STRATEGY** (paling kanan, tabel utama) + bukti di baris kecil.

    Permintaan user (verbatim, 2026-09-19): *"Kasih kolom baru dipaling kanan
    STRATEGY — jika total likuiditas >500K, dikolom strategy ditulis, hybird
    7030, bidask 3070 - full range — jika total likuiditas <500K, dikolom
    strategy ditulis, hybird 5050, bidask - full range"*.

    Aturannya tidak disalin di sini: teks + ambangnya tinggal dibaca dari
    :func:`gmgn_liquidity.row_strategy` (satu sumber dengan warna likuiditas
    kolom RugCheck), dan angka pembandingnya pun angka yang sama dengan yang
    ditulis kolom RugCheck (:func:`gmgn_liquidity.row_total_liquidity_usd`) —
    jadi STRATEGY tidak pernah menyarankan 70/30 untuk baris yang angka
    likuiditasnya tampil merah. Baris kecil menulis angka likuiditas +
    ambangnya (``$884.9K > $500K``) supaya sarannya bisa diverifikasi sekali
    lihat; likuiditas tak terukur menulis ``liq —`` dan alasannya ada di
    tooltip (kolom informasi: tidak pernah membuang baris, tidak pernah
    menulis sel kosong).
    """
    from gmgn_liquidity import MIN_LABEL, compact_usd, row_strategy

    info = row_strategy(row)
    value = _strategy_cell_html(info.get("text"))
    usd = info.get("usd")
    sub = (f"liq {compact_usd(usd)} · {MIN_LABEL}" if usd is not None
           else f"liq — · {MIN_LABEL}")
    tip = (f"STRATEGY dari likuiditas total: {info.get('reason')} → "
           f"\"{info.get('text')}\" (teks verbatim permintaan user 2026-09-19; "
           f"saldo > {MIN_LABEL} ambil cabang 70/30, < {MIN_LABEL} ambil "
           "cabang 50/50; ambangnya sama dengan warna angka likuiditas kolom "
           "RugCheck) — hanya saran penempatan likuiditas, bukan saringan: "
           "barisnya tidak pernah dibuang karena kolom ini")
    if usd is None:
        tip += (" · likuiditas total tidak terbaca (GMGN/rugchecker.cc tidak "
                "menjawab) sehingga dipakai cabang di bawah ambang")
    return value, sub, tip


def _finite_number(value):
    """``float`` finite atau ``None`` — untuk mencari nilai tertinggi tabel."""
    import math as _math

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if _math.isfinite(number) else None


def _table_tops(rows: list) -> tuple:
    """``(volatility tertinggi, F/V tertinggi, Fee/TVL tertinggi)`` di tabel.

    Dipakai untuk sorot hijau tua menyala (permintaan user 2026-09-14 —
    lanjutan: Fee/TVL tertinggi ikut ditandai). Baris tanpa angka valid
    diabaikan; bila beberapa baris seri di puncak, SEMUANYA ikut ditandai
    (tidak ada pemenang acak). Setiap kolom dicari maksimumnya
    sendiri-sendiri, jadi baris pemegang Fee/TVL tertinggi bisa berbeda dari
    baris pemegang F/V tertinggi. Hanya tabel utama yang memanggil ini —
    tabel "dilewati" 24H sengaja tidak ditandai (barisnya sudah dianotasi
    merah gugur-ambang).
    """
    from meteora_screener import row_fv_ratio

    top_vol = top_fv = top_fee_tvl = None
    for row in rows or []:
        vol = _finite_number((row or {}).get("volatility"))
        if vol is not None:
            top_vol = vol if top_vol is None else max(top_vol, vol)
        ratio = row_fv_ratio(row)
        if ratio is not None and _finite_number(ratio) is not None:
            top_fv = ratio if top_fv is None else max(top_fv, ratio)
        fee_tvl = _finite_number((row or {}).get("fee_active_tvl_ratio"))
        if fee_tvl is not None:
            top_fee_tvl = (fee_tvl if top_fee_tvl is None
                           else max(top_fee_tvl, fee_tvl))
    return top_vol, top_fv, top_fee_tvl


def _best_head_html(rows: list, hidden: int, lane: str,
                    *, showing_hidden: bool = False) -> str:
    """Header card: judul + pill lane aktif + jumlah pool / yang disembunyikan.

    Pill **🏆 BEST POOL** dihapus 2026-09-13 per permintaan user
    (\"tulisan tentang dust holder BEST POOL aman dll hapus juga\"). Pill
    **24H/30M** ditambah hari yang sama: tombol dan tabel sudah dipisah per
    timeframe, jadi kepala card yang menunjukkan lane mana yang sedang tampil.
    """
    from dashboard_components import card_head_html
    from meteora_screener import BEST_CARD_TITLE

    label, color, gate = best_lane_detail(lane)
    pills = [f'<span class="lp-count" style="color:#ffffff;background:{color};">'
             f'{label} · {gate}</span>',
             f'<span class="lp-count">{len(rows)} pool</span>']
    # ``hidden`` = kandidat 24H yang gugur saringan layar; pool volatility 0
    # dibuang sebelum tabel (permintaan user: tidak ada pergerakan), jadi
    # jumlahnya tidak pernah ikut di sini.
    if hidden:
        tone = ("color:#1e3a8a;background:#bfdbfe;" if showing_hidden
                else "color:#334155;background:#e2e8f0;")
        pills.append(f'<span class="lp-count" style="{tone}">'
                     f"{hidden} disembunyikan</span>")
    return card_head_html(BEST_CARD_TITLE, pills, tooltip=best_pool_tooltip())


def _signed_pct(value) -> tuple[str, str]:
    """Persen dengan tanda +/− + warna (hijau naik, merah turun).

    Dipakai untuk **Δ volume** (baris kecil kolom Vol 24h) — rasio volume
    24 jam / active TVL adalah kunci urut KETIGA card (Fee/TVL lalu F/V di
    depannya sejak 2026-09-15), jadi angka volume + arah perubahannya tetap
    harus terbaca sekali lihat.
    ``None`` → ``—``.
    """
    if value is None:
        return "—", ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—", ""
    text = f"{number:+.1f}%"
    color = "#16a34a" if number > 0 else ("#dc2626" if number < 0 else "")
    return text, color


def _pct_or_dash(value, pattern: str = ".1f") -> str:
    """Persen siap tampil, aman ``None`` (``—``, bukan ``—%`` yang aneh)."""
    from dashboard_components import _number

    return "—" if value is None else f"{_number(value, pattern)}%"


def _num_or_dash(value, pattern: str = ".0f") -> str:
    """Angka biasa siap tampil (``None`` → ``—``)."""
    from dashboard_components import _number

    return "—" if value is None else _number(value, pattern)


def _pct_full(value) -> str:
    """Persen **penuh** untuk tooltip sel F/V (``—`` bila tidak ada).

    Angka normal ditulis 2 desimal seperti sebelumnya (``40.00%``), tetapi
    persen yang sangat kecil tidak boleh dibulatkan jadi ``0.00%``: pool
    tenang bisa punya ``volatility`` 2,06e-09% (pool GOLD-XAUt0, dilaporkan
    user 2026-09-15 — justru angka itulah penyebab F/V-nya jutaan), dan
    ``0.00%`` di tooltip membuat pembacanya tidak bisa memverifikasi apa pun.
    Di bawah 0,005% nilainya ditulis 3 angka penting (``2.06e-09%``).
    """
    number = _finite_number(value)
    if number is None:
        return "—"
    if number != 0 and abs(number) < 0.005:
        return f"{number:.3g}%"
    return f"{number:,.2f}%"


def _usd_or_dash(value, compact: bool = True) -> str:
    """USD siap tampil: ringkas (``$24.0K``) atau penuh (``$24,000``).

    Data lama di ``session_state`` bisa tidak punya field baru (fee /
    volume_change) — ``None`` harus jadi ``—``, bukan ``$0``.
    """
    if value is None:
        return "—"
    if compact:
        from dashboard_components import _compact

        return _compact(value)
    from dashboard_components import _number

    return f"${_number(value, ',.0f')}"


def _cell(value: str, sub: str = "", title: str = "") -> str:
    """Satu sel metrik listing: angka + baris kecil (boleh HTML, mis. warna).

    ``title`` = tooltip browser dengan angka penuh (persen/USD mentah dari
    API Meteora) supaya angka ringkas di card tetap bisa diverifikasi.
    """
    import html as _html

    tip = f' title="{_html.escape(str(title))}"' if title else ""
    return ('<div class="watchlist-metric">'
            f'<div class="watchlist-metric-value">{value}</div>'
            f'<div class="watchlist-metric-sub"{tip}>{sub}</div></div>')


def _price_or_dash(value) -> str:
    """Harga bin mentah siap tampil (6 angka penting — harga memecoin kecil).

    Harga bin DLMM memecoin sering 1e-05, jadi ``.2f`` akan menulis ``0.00``;
    ``.6g`` tetap terbaca (``1.49369e-05``).
    """
    try:
        return f"{float(value):.6g}"
    except (TypeError, ValueError):
        return "—"


def _range_part(value, *, down: bool) -> str:
    """Satu sisi **Active Range** dengan warna: turun merah, naik hijau.

    ``0.0%`` sengaja ditulis tanpa tanda dan tanpa warna — artinya harga
    persis di tepi range likuiditas (contoh nyata ROUTER-SOL 2026-09-14:
    ``min_price`` == ``pool_price``), dan ``+0.0%``/``-0.0%`` hanya
    membingungkan.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    signed = -number if down else number
    if abs(signed) < 0.05:
        return "0.0%"
    color = "#dc2626" if signed < 0 else "#16a34a"
    return f'<span style="color:{color};">{signed:+.1f}%</span>'


def _active_range_cell(row) -> tuple[str, str, str]:
    """Sel **Active Range**: ``-34.5% / +19.0%`` (turun / naik) + lebar range.

    Persen saja sesuai permintaan user 2026-09-14 ("tambahkan Active Range,
    tapi % saja, misal -30% +40"); harga bin mentah, lebar range, dan jumlah
    bin yang berisi likuiditas tetap ada di tooltip sel. Baris lama di
    ``session_state`` (hasil scan sebelum kolom ini ada) atau pool yang
    payload-nya tanpa ``pool_price``/``min_price``/``max_price`` → ``—``,
    bukan ``-0.0% / +0.0%`` palsu.
    """
    from meteora_screener import (active_range_bins, active_range_pct,
                                  active_range_width_pct)

    row = row or {}
    down, up = active_range_pct(row)
    if down is None or up is None:
        return ("—", "range",
                "active range tidak terbaca — hasil scan sebelum kolom ini "
                "ada (2026-09-14) atau API Meteora tidak mengirim pool_price / "
                "min_price / max_price untuk pool ini; tekan tombol scan lagi")
    value = (f"{_range_part(down, down=True)} / "
             f"{_range_part(up, down=False)}")
    width = active_range_width_pct(row)
    sub = f"lebar {_pct_or_dash(width)}" if width is not None else "range"
    bins = active_range_bins(row)
    bins_txt = (f"{bins[0]} bin berisi likuiditas ({bins[1]} bin di bawah "
                f"harga, {bins[2]} bin di atasnya) · bin_step "
                f"{_num_or_dash(row.get('bin_step'), '.4g')} bp"
                if bins else "")
    tip = ("active range = rentang bin DLMM yang masih berisi likuiditas "
           f"(min_price … max_price API Meteora): harga boleh turun "
           f"{_pct_or_dash(down)} atau naik {_pct_or_dash(up)} dari harga "
           f"pool sekarang ({_price_or_dash(row.get('pool_price'))}) sebelum "
           "keluar range — di luar itu posisi LP berhenti menghasilkan fee · "
           f"lebar range {_pct_or_dash(width)} · tepi "
           f"{_price_or_dash(row.get('range_min_price'))} … "
           f"{_price_or_dash(row.get('range_max_price'))}"
           + (f" · {bins_txt}" if bins_txt else "")
           + " — informasi, bukan saringan")
    return value, sub, tip


def _fv_cell(row: dict, lane: str, *, top: bool = False) -> tuple[str, str, str]:
    """Sel **F/V** = ``fee_active_tvl_ratio ÷ volatility`` satu baris + lane.

    Hanya ada **satu lane** sejak 2026-09-16 (30M dihapus), jadi sel selalu
    menulis angkanya — label "OK" hijau khusus 30M (aturan 2026-09-14) ikut
    dicabut bersama lane itu. **Format angkanya** (permintaan user 2026-09-15:
    *"gold menunjukkan 6328266.1 F/V — perbaiki"*) dibaca dari
    :func:`meteora_screener.format_fv_ratio` — satu desimal di bawah 100×
    (``10,1×``), bilangan bulat berpemisah ribuan di atasnya
    (``6,328,266×``), jadi rasio ekstrem tidak lagi tampil mentah sebagai
    ``6328266.1×``. ``top=True`` (F/V tertinggi di tabel utama) mengubahnya
    jadi **hijau tua menyala + bold**, baik untuk sel angka 24H maupun sel OK
    30M (permintaan user: "tandai f/v tertinggi tersebut menjadi warna hijau
    menyala" — lanjutan: "yang paling tinggi nilainya kasih warna hijau
    menyala, hijau tua menyala"). Baris gagal ambang (hanya mungkin muncul
    di listing "disembunyikan" lane 24H, yang tidak pernah diberi tanda)
    tetap merah + alasan, supaya jelas kenapa holdernya tidak ikut di-scan.
    """
    from meteora_screener import format_fv_ratio, row_best_gaps, row_fv_ratio

    ratio = row_fv_ratio(row)
    label, _, gate = best_lane_detail(lane)
    fails = row_best_gaps(row, lane=lane)
    value = format_fv_ratio(ratio)
    sub = f"syarat {gate}"
    if value is None:
        value, color = "—", "#dc2626"
    else:
        # Angka (atau ∞ warisan hasil scan lama): tanpa warna khusus —
        # penanda hijau hanya untuk F/V tertinggi tabel (``top``).
        color = ""
    tip = (f"fee_active_tvl_ratio {_pct_full(row.get('fee_active_tvl_ratio'))}"
           f" ÷ volatility {_pct_full(row.get('volatility'))} = "
           f"{_num_or_dash(ratio, ',.2f')}× — "
           f"berapa kali fee pool lebih besar dari volatility; kunci urut "
           f"kedua listing {label} + syarat lane ({gate}); "
           "lebih tinggi = fee lebih dominan")
    if fails:
        # Gugur F/V, volatility di luar 1%–10%, atau Top10 >= 20% — semuanya
        # dibaca dari satu sumber (row_best_gaps) supaya teks sel tidak pernah
        # ketinggalan aturan baru.
        sub = f"gugur: {fails[0].split(': ', 1)[-1]}"
        shown = f'<span style="color:#dc2626;">{value}</span>'
    elif top:
        tip += " — F/V tertinggi di tabel ini"
        shown = _top_span(value)
    elif color:
        shown = f'<span style="color:{color};">{value}</span>'
    else:
        shown = value
    return shown, sub, tip


def _render_best_table(rows: list, *, lane: str,
                       key_prefix: str = "best-pool",
                       mark_tops: bool = True,
                       show_strategy: bool = True) -> None:
    """Tabel listing Best Pool untuk **satu** lane (utama atau disembunyikan).

    Susunan kolom 2026-09-19 (14 kolom di tabel utama, 13 di tabel
    "dilewati"): Token · **F/V · Fee/TVL** (tepat
    di kanan F/V, permintaan user) · **Volat** · **Active Range** (persen
    saja: ``-34.5% / +19.0%`` = harga boleh turun / naik sebelum keluar dari
    bin berisi likuiditas) · **LPs** ·
    **Fee %** (fee trading pool, mis. 0.5% / 2%) · MC · A.TVL · Vol 24h ·
    Top10 · **RugCheck** · **Pool** · **STRATEGY** — kolom Dust (jumlah
    wallet) lebih dulu dihapus 2026-09-14;
    **kolom Dust %MC dihapus 2026-09-17** (permintaan user: *"hapus kolom
    dust %"*) dan **tombol ⭐ watchlist dihapus** hari yang sama
    (*"hapus tombol favorit / watchlist"*); **kolom Bubble Map (sempat
    ditambah 2026-09-18) dihapus 2026-09-19** (*"hapus tentang bubblemap, sisakan
    hyperlink ke bubblemapnya saja"* — cluster/top holder/warning tidak
    ditampilkan lagi, hanya tautan 🫧 yang tersisa dan tautan itu pindah ke
    kolom Pool). Kolom Pool kini memuat tautan
    🌊Meteora/🦅HawkFi **plus tombol 📋 copy link HawkFi** (*"tambahkan
    copy link hawkfi dibagian scan"*) **plus tautan 🫧 Bubblemaps**
    (:func:`links.bubblemap_icon_link_html`), dan tiap kolom dibatasi
    **garis vertikal** (*"batasi per kolom dengan garis naik turun"* — marker
    ``.bp-cols-next`` sebelum header + tiap baris data, CSS-nya di
    ``dashboard_components.render_styles``, hanya layar > 768px).

    **STRATEGY** (2026-09-19, *"Kasih kolom baru dipaling kanan STRATEGY"*)
    hanya dirender bila ``show_strategy=True`` = tabel utama (pool lolos);
    tabel "▶ N pool dilewati" memanggil fungsi ini dengan ``False``
    (konfirmasi user 2026-09-19) sehingga tetap 13 kolom. Teksnya
    (:func:`_strategy_cell`) dibaca dari :func:`gmgn_liquidity.row_strategy`:
    likuiditas total > $500K → ``hybird 7030, bidask 3070 - full range``,
    selain itu → ``hybird 5050, bidask - full range`` (verbatim permintaan
    user). Ukuran huruf seluruh tabel **diperbesar** hari yang sama
    (*"agak perbesar tulisan table semuanya ya, tapi tidak mempengaruhi
    tampilan"*) — judul kolom lewat :data:`HEADER_FONT_SIZE`, isi sel lewat
    class ``.bp-*`` di ``dashboard_components.render_styles``; lebar kolom
    dan tata letak tidak diubah.
    Sejak 2026-09-15 sel Token menulis pasangan pool-nya
    (``row_pair_label``) dan sel F/V memakai ``format_fv_ratio``. Di tabel
    utama (``mark_tops=True``) sel **volatility terbesar**, sel **F/V
    tertinggi**, dan sel **Fee/TVL tertinggi** disorot hijau tua menyala
    (``TOP_HIGHLIGHT_COLOR``, seri ikut
    semua); tabel "dilewati" 24H tidak ditandai (``mark_tops=False``).
    """
    import html

    import streamlit as st

    from dashboard_components import _number
    from links import (bubblemap_icon_link_html, external_links_html,
                       hawkfi_copy_html, pool_links_html)
    from meteora_screener import (BEST_TOP10_MAX_PCT, BEST_VOL_SHOW_MAX,
                                  BEST_VOL_SHOW_MIN, normalize_best_lane,
                                  row_fv_ratio)
    from meteora_screener import row_pair_label, row_vol_tvl_ratio
    # RugCheck = kolom baru 2026-09-16; fmt-nya tinggal di modul rugchecker
    # supaya card tidak pernah menebak struktur laporan API pihak ketiga.
    from rugchecker import cell_parts as _rug_cell_parts
    # Modul ``bubblemaps`` TIDAK diimpor lagi di sini (2026-09-19): kolom
    # Bubble Map dihapus, yang tersisa hanya tautan 🫧 dari ``links``
    # (permintaan user: "hapus tentang bubblemap, sisakan hyperlink ke
    # bubblemapnya saja"). URL tautannya dihitung dari mint, dengan fallback
    # ke URL yang tersimpan di hasil scan lama (``row["bubblemap"]["url"]``)
    # supaya baris hasil scan 2026-09-18 tetap mengarah ke map yang sama.

    # Dua marker sekaligus (CSS :has, lihat dashboard_components.render_styles):
    # ``mobile-hide-next`` menyembunyikan header tabel di HP (tiap sel sudah
    # punya sub-label — volat, fee, dll — dan header yang ikut menjadi card
    # 2-kolom justru bikin bingung), dan ``bp-cols-next`` menandai horizontal
    # block ini bagian dari tabel sehingga tiap kolomnya mendapat garis
    # vertikal pembatas (permintaan user 2026-09-17: "batasi per kolom dengan
    # garis naik turun"; marker yang sama disisipkan sebelum tiap baris data
    # di bawah).
    st.markdown('<div class="mobile-hide-next bp-cols-next"></div>',
                unsafe_allow_html=True)
    col_spec = _col_spec(show_strategy=show_strategy)
    header_cols = st.columns(col_spec)
    # Judul kolom: ukuran huruf dinaikkan 2026-09-19 (permintaan user: "agak
    # perbesar tulisan table semuanya ya, tapi tidak mempengaruhi tampilan") —
    # ``HEADER_FONT_SIZE`` 0.72rem → 0.82rem. Seluruh gayanya (ukuran huruf,
    # tebal, rata tengah, nowrap) hidup di class ``.bp-col-title`` pada
    # ``dashboard_components.render_styles`` supaya tidak ada style inline yang
    # bisa disanitasi Streamlit dan header tidak pernah mengubah tinggi baris
    # maupun lebar kolom.
    for col, title in zip(header_cols,
                          _lane_titles(lane, show_strategy=show_strategy)):
        col.markdown(f'<div class="bp-col-title">{title}</div>',
                     unsafe_allow_html=True)
    st.markdown('<hr style="margin:0.4rem 0;border-color:#cbd5e1;">',
                unsafe_allow_html=True)

    top_vol, top_fv, top_fee_tvl = (_table_tops(rows) if mark_tops
                                     else (None, None, None))
    window_txt = ("30 menit" if normalize_best_lane(lane) == "30m"
                  else "24 jam")

    for index, row in enumerate(rows):
        ca = str(row.get("ca") or "")
        symbol = str(row.get("symbol") or "?").upper()
        pool = str(row.get("pool_address") or "")
        # Dust %MC tidak lagi dibaca di sini — kolomnya dihapus 2026-09-17
        # (permintaan user: "hapus kolom dust %"); angkanya tetap dipakai
        # ``sort_best_rows`` di backend sebagai tie-break urutan terakhir.
        fee = row.get("fee")
        active_tvl = row.get("active_tvl")
        ratio = row.get("fee_active_tvl_ratio")
        volume = row.get("volume")
        volume_change = row.get("volume_change_pct")
        fee_pct = row.get("fee_pct")
        fee_sub = f"fee {_usd_or_dash(fee)}"
        if fee_pct is not None:
            fee_sub += f"·{_number(fee_pct, '.4g')}%"
        delta_txt, delta_color = _signed_pct(volume_change)
        delta_html = (f'<span style="color:{delta_color};">Δ '
                      f"{delta_txt}</span>" if delta_color
                      else f"<span>Δ {delta_txt}</span>")
        # Kunci urut KEDUA (volume / active TVL dari window lane) ditulis di
        # baris kecil kolom Vol supaya urutannya bisa diperiksa sekali lihat.
        vol_tvl_ratio = row_vol_tvl_ratio(row)
        if vol_tvl_ratio is not None:
            delta_html += (f" · {_num_or_dash(vol_tvl_ratio, ',.0f')}×"
                           " A.TVL")
        # Sorot hijau tua menyala: F/V tertinggi, volatility terbesar, dan
        # Fee/TVL tertinggi tabel ini (permintaan user 2026-09-14 lanjutan).
        fv_here = row_fv_ratio(row)
        fv_top = bool(top_fv is not None and fv_here is not None
                      and fv_here == top_fv)
        fv_value, fv_sub, fv_tip = _fv_cell(row, lane, top=fv_top)
        vol_value = _pct_or_dash(row.get("volatility"))
        vol_tip = ("volatility pool "
                   f"{_num_or_dash(row.get('volatility'), ',.2f')}% — "
                   "saringan sejak 2026-09-16: hanya "
                   f"{float(BEST_VOL_SHOW_MIN):g}%–{float(BEST_VOL_SHOW_MAX):g}%"
                   " yang ditampilkan (inklusif; 0% dibuang total sejak "
                   "2026-09-14)")
        vol_here = _finite_number(row.get("volatility"))
        if top_vol is not None and vol_here is not None and vol_here == top_vol:
            vol_value = _top_span(vol_value)
            vol_tip += " — volatility terbesar di tabel ini"
        fee_tvl_value = _pct_or_dash(ratio)
        fee_tvl_tip = (f"tier fee {_num_or_dash(fee_pct, '.4g')}% · fee "
                       f"{window_txt} {_usd_or_dash(fee, compact=False)} / "
                       f"active TVL {_usd_or_dash(active_tvl, compact=False)} "
                       f"= {_num_or_dash(ratio, ',.2f')}% — kunci urut "
                       "pertama (terbesar dulu, permintaan user 2026-09-15), "
                       "bukan saringan")
        fee_tvl_here = _finite_number(ratio)
        if (top_fee_tvl is not None and fee_tvl_here is not None
                and fee_tvl_here == top_fee_tvl):
            fee_tvl_value = _top_span(fee_tvl_value)
            fee_tvl_tip += " — Fee/TVL tertinggi di tabel ini"
        # Marker pembatas kolom vertikal (permintaan user 2026-09-17:
        # "batasi per kolom dengan garis naik turun") — tepat sebelum
        # horizontal block baris data, pola yang sama dengan header di atas.
        st.markdown('<div class="bp-cols-next"></div>',
                    unsafe_allow_html=True)
        cols = st.columns(col_spec)
        # Kolom **Token** menulis pasangan pool-nya (permintaan user
        # 2026-09-15: "kolom Token sekarang akan menunjukkan pasangan pairnya,
        # misal ALLINU/SOL") — simbol `$TOKEN` tetap baris pertama, pasangan
        # pool DLMM-nya di bawahnya, alamat mint di baris paling bawah.
        pair = row_pair_label(row)
        pair_html = (
            f'<span class="watchlist-pair" title="pasangan pool '
            f'(nama pool dari API Meteora)">{html.escape(pair)}</span>'
            if pair else "")
        cols[0].markdown(
            '<div class="watchlist-token">'
            f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
            f'{pair_html}'
            f'<span class="watchlist-mint">{html.escape(ca[:8])}…</span>'
            f'<div class="watchlist-links">{external_links_html(ca)}</div>'
            "</div>", unsafe_allow_html=True)
        # Urutan sel = urutan judul di ``_lane_titles`` (tanpa Token di sini;
        # kolom Dust jumlah wallet sudah dihapus 2026-09-14 dan kolom Dust
        # %MC menyusul 2026-09-17 — permintaan user: "hapus kolom dust %";
        # Fee/TVL tepat di kanan F/V — permintaan user 2026-09-14).
        # Sel **LPs** (2026-09-16, permintaan user: "LPs jika lebih dari 100,
        # kasih warna hijau jika tidak, tidak ada perubahan") — hanya warnanya
        # yang berubah, angkanya tetap angka pool dari API Meteora.
        lps_here = _finite_number(row.get("total_lps"))
        lps_value = _num_or_dash(row.get("total_lps"))
        if lps_here is not None and lps_here > LP_GREEN_MIN_LP:
            lps_value = (f'<span style="color:{LP_GREEN_COLOR};'
                         f'font-weight:700;">{lps_value}</span>')
        # Kolom **RugCheck** (baru 2026-09-16): verdict dari rugchecker.cc +
        # likuiditas **total GMGN** (sejak 2026-09-17 — sumber angkanya
        # dipindah ke gmgn.ai, permintaan user), ditempel scan_best_lane
        # lewat modul ``rugchecker`` (angka GMGN-nya: modul ``gmgn_liquidity``).
        # Hanya verdict yang diwarnai (hijau→merah) — angka likuiditas ikut
        # diwarnai sejak 2026-09-17: HIJAU di atas ambang $500K, MERAH di
        # bawahnya (permintaan user), hitam bila tidak terukur. Warnanya
        # dihitung rugchecker.cell_parts lewat gmgn_liquidity.liq_color.
        rug_report = row.get("rugcheck") or {}
        rug_value, rug_sub, rug_tip = _rug_cell_parts(rug_report)
        rug_color = str(rug_report.get("color") or "") if isinstance(rug_report, dict) else ""
        if rug_color and rug_value != "—":
            rug_value = (f'<span style="color:{rug_color};font-weight:700;">'
                         f'{rug_value}</span>')
        # Kolom **Bubble Map** (cluster + holder terbesar + warning, dipasang
        # 2026-09-18) DIHAPUS 2026-09-19 — permintaan user: "hapus tentang
        # bubblemap, sisakan hyperlink ke bubblemapnya saja". Yang tersisa
        # hanya tautan 🫧 ke v2.bubblemaps.io, dan tautan itu pindah ke kolom
        # Pool (lihat ``bubble_html`` di bawah). ``row["bubblemap"]`` hasil
        # scan lama masih dibaca sekali untuk mengambil URL-nya supaya baris
        # yang sudah tersimpan di session/cache tetap mengarah ke map yang
        # sama; scan baru tidak lagi mengisinya (``bubblemap=False``).
        bubble_report = row.get("bubblemap")
        bubble_url_stored = (str(bubble_report.get("url") or "")
                             if isinstance(bubble_report, dict) else "")
        bubble_html = bubblemap_icon_link_html(ca, url=bubble_url_stored)

        cells = (
            (fv_value, fv_sub, fv_tip),
            (fee_tvl_value, fee_sub, fee_tvl_tip),
            (vol_value, "volat", vol_tip),
            _active_range_cell(row),
            (lps_value, "lps",
             f"jumlah liquidity provider pool — hanya informasi, bukan "
             f"saringan; HIJAU bila > {LP_GREEN_MIN_LP:g} LP (permintaan user "
             "2026-09-16: banyak LP = likuiditas tidak dipegang segelintir "
             "wallet)"),
            (_num_or_dash(fee_pct, ".4g") + "%" if fee_pct is not None
             else "—", "pool fee",
             f"fee trading pool ini (tier fee pool DLMM) = "
             f"{_num_or_dash(fee_pct, '.4g')}% (mis. 0.5%, 2%) — "
             "hanya informasi, bukan saringan"),
            (_usd_or_dash(row.get("mc")), "",
             f"market cap {_usd_or_dash(row.get('mc'), compact=False)} — "
             "DexScreener, angka yang dipakai sebagai pembagi Dust %MC"),
            (_usd_or_dash(active_tvl), "active tvl",
             f"active TVL {_usd_or_dash(active_tvl, compact=False)} · "
             f"TVL total {_usd_or_dash(row.get('tvl'), compact=False)}"),
            (_usd_or_dash(volume), delta_html,
             f"volume {window_txt} {_usd_or_dash(volume, compact=False)} · "
             f"perubahan {delta_txt} · rasio volume/active TVL "
             f"{_num_or_dash(vol_tvl_ratio, ',.2f')}% — kunci urut ketiga "
             "(terbesar dulu; setelah Fee/TVL & F/V), informasi "
             "(bukan saringan)"),
            (_pct_or_dash(row.get("top_holders_pct")), "top10",
             "10 holder teratas token base (% of supply) — saringan sejak "
             f"2026-09-16: Top10 **{BEST_TOP10_MAX_PCT:g}% atau lebih** tidak "
             "ditampilkan (permintaan user: \"jika ada top 10 >= 20% jangan "
             "tampilkan\"; tanpa angka = tidak terukur, barisnya tetap "
             "tampil)"),
            (rug_value, rug_sub, rug_tip),
        )
        if show_strategy:
            # Kolom paling kanan (permintaan user 2026-09-19: "Kasih kolom
            # baru dipaling kanan STRATEGY") — hanya di tabel utama; tabel
            # "▶ N pool dilewati" merender tanpa kolom ini
            # (``show_strategy=False``) sehingga jumlah selnya selalu sama
            # dengan jumlah judul/lebar kolom di atas.
            cells = cells + (_strategy_cell(row),)
        for position, (value, sub, tip) in enumerate(cells, start=1):
            cols[position].markdown(_cell(value, sub, tip),
                                    unsafe_allow_html=True)
        # Kolom Pool: tautan 🌊Meteora/🦅HawkFi + tombol 📋 copy link HawkFi
        # (permintaan user 2026-09-17: "tambahkan copy link hawkfi dibagian
        # scan") + **tautan 🫧 Bubblemaps** (2026-09-19: "hapus tentang
        # bubblemap, sisakan hyperlink ke bubblemapnya saja") — tombolnya
        # ``<button>`` HTML dengan JS clipboard, jadi klik tidak memicu rerun
        # Streamlit. Tombol ⭐ favorit/watchlist yang dulu menempati kolom
        # terakhir dihapus 2026-09-17 (permintaan user: "hapus tombol
        # favorit / watchlist"). Indeksnya ``POOL_COL_INDEX`` (kolom terakhir
        # tabel "dilewati"), bukan angka 13 hardcoded seperti dulu.
        pool_html = pool_links_html(pool)
        if pool_html:
            pool_html += f" {hawkfi_copy_html(pool)}"
        else:
            pool_html = ""
        if bubble_html:
            pool_html = f"{pool_html} {bubble_html}".strip()
        if not pool_html:
            pool_html = "<span>—</span>"
        cols[POOL_COL_INDEX].markdown(
            f'<div class="pool-links">{pool_html}</div>',
            unsafe_allow_html=True)
        st.markdown('<hr style="margin:0.25rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)


def _lane_result(st, lane: str) -> dict:
    """Hasil scan tersimpan satu lane (dibaca dari session_state)."""
    return st.session_state.get(best_lane_session_key(lane)) or {}


def _run_lane_scan(lane: str, *, progress=None) -> dict:
    """Satu kali scan satu lane — dipakai tombol card.

    ``progress`` dipanggil ``(index, total, label)``; kegagalan scanner
    menjadi pesan card (``error``), bukan exception yang mematikan halaman.
    ``rugcheck=False`` dipakai test/offline: kolom RugCheck menulis ``—``
    tanpa menghubungi rugchecker.cc.

    ``bubblemap=False`` (2026-09-19): kolom Bubble Map dihapus sehingga
    status cluster/holder Bubblemaps tidak dipakai lagi — permintaan user
    *"hapus tentang bubblemap, sisakan hyperlink ke bubblemapnya saja"*, dan
    tautan 🫧-nya dihitung dari mint di sisi UI tanpa laporan apa pun. Scan
    jadi lebih cepat (satu enrichment pihak ketiga hilang).
    """
    from holder_history import FULL_SCAN_MAX_WALLETS
    from meteora_screener import scan_best_lane

    try:
        # FULL scan (bukan cap kecil): urutan getTokenAccounts Helius tidak
        # urut saldo, jadi sampel kecil membuat angka dust tidak bisa dipercaya.
        return scan_best_lane(lane, max_wallets=FULL_SCAN_MAX_WALLETS,
                              workers=6, progress=progress,
                              bubblemap=False)
    except Exception as exc:  # noqa: BLE001 - kegagalan = pesan card
        return {"rows": [], "hidden_rows": [], "error": str(exc),
                "fetched": 0, "hidden_metric": 0, "hidden_dust": 0,
                "skipped_quote": 0, "dropped_volatility": 0,
                "rugcheck_failed": 0, "bubblemap_failed": 0, "lane": lane}


def render_best_pool_scan() -> None:
    """Card **🏆 Scan Best Pool Meteora** di halaman utama — satu tombol 24H.

    Dulu card ini punya dua tombol + pemilih lane (24H dan 30M, aturan
    2026-09-13). Sejak 2026-09-16 hanya lane **24H** yang tersisa —
    permintaan user: *"hapus scan 30 menit, kita sisakan yang 24 jam saja"* —
    jadi satu tombol = satu listing API (``timeframe=24h``) = satu tabel,
    disimpan di satu session key ``best_pool_scan_24h`` (+ cache berkas dengan
    nama yang sama, lihat ``scan_result_cache``). Key lama per-lane lain
    (``best_pool_scan_30m``) dan key gabungan lama (``best_pool_scan``) tidak
    pernah dibaca lagi, jadi hasil 30M tidak bisa lagi menyusup ke tabel.
    """
    import streamlit as st

    from meteora_screener import (best_gap_summary, gmgn_min_label,
                                  normalize_best_lane, row_best_gaps,
                                  row_volatility_zero, sort_best_rows)

    with st.container(border=True):
        active = normalize_best_lane("24h")
        # Bersihkan state pemilih lane lama supaya sesi yang masih menyimpan
        # "30m" tidak bisa memengaruhi apa pun.
        st.session_state.pop(BEST_ACTIVE_LANE_KEY, None)

        # Pulihkan hasil scan dari cache berkas lokal bila session_state kosong
        # — Streamlit membuat session baru setiap refresh browser (F5) / tab
        # baru, sehingga tanpa ini listing + holder FULL yang memakan menit
        # ikut hilang dan user harus menekan tombol scan lagi. Cache diisi
        # ``scan_result_cache.save_result`` sesudah scan (lihat bawah).
        try:
            import scan_result_cache

            scan_result_cache.restore_into_session(
                st, best_lane_session_key(active), best_lane_session_key(active))
        except Exception:  # noqa: BLE001 - cache hanya pelengkap
            pass

        # ---- satu tombol deteksi: 24H -------------------------------------
        label, _color, gate = best_lane_detail(active)
        if st.button(f"🏆 Scan Best Pool {label} + Holder", type="primary",
                     key=f"best-pool-scan-{active}",
                     use_container_width=True,
                     help=(f"Listing Meteora timeframe {label}, disaring "
                           f"{gate} + volatility "
                           "1%–10% + Top10 < 20% "
                           "SEBELUM scan holder — pool di bawah syarat "
                           "langsung di-skip, holdernya tidak di-fetch. Tiap "
                           "pool yang lolos dilengkapi laporan RugCheck "
                           "(verdict rugchecker.cc, angka likuiditas GMGN — "
                           "sejak 2026-09-17) dan kolom STRATEGY di paling "
                           "kanan (saran penempatan likuiditas dari ambang "
                           f"{gmgn_min_label()} — sejak 2026-09-19).")):
            bar = st.progress(0.0, text="Listing pool Meteora…")

            def _progress(index, total, note):
                bar.progress(index / max(total, 1),
                             text=f"Holder {index}/{total} · {note}")

            result = _run_lane_scan(active, progress=_progress)
            bar.empty()
            st.session_state[best_lane_session_key(active)] = result
            st.session_state[best_lane_hidden_key(active)] = False
            # Tahan refresh browser: simpan hasil ke cache berkas lokal
            # (2026-09-14). Gagal tulis tidak boleh membatalkan hasil scan.
            try:
                import scan_result_cache

                scan_result_cache.save_result(best_lane_session_key(active),
                                              result)
            except Exception:  # noqa: BLE001 - cache hanya pelengkap
                pass
            st.rerun()
        # Rekap hasil tersimpan di bawah tombol (aturan card sejak 2026-09-13:
        # tombol menunjukkan apa yang sudah ada tanpa memindai ulang) — dengan
        # satu lane cukup satu baris, tidak lagi per tombol.
        stored = _lane_result(st, active)
        st.caption(f"{len(stored.get('rows') or [])} pool tersimpan" if stored
                   else "belum di-scan")

        # ---- isi tabel ----------------------------------------------------
        result = _lane_result(st, active)
        error = str(result.get("error") or "")
        if not result:
            st.markdown(_best_head_html([], 0, active),
                        unsafe_allow_html=True)
            st.info(f"Belum ada hasil scan lane {label}. Tekan tombol "
                    f"🏆 Scan Best Pool {label} + Holder untuk memindai "
                    "listing terbaru.")
            return
        # ``scan_best_lane`` sudah mengurutkan, tapi hasil lama di
        # ``session_state`` (dari kriteria versi sebelumnya) belum —
        # diurutkan lagi dengan rule baru agar listing konsisten tanpa perlu
        # scan ulang (kolom yang dibutuhkan sort ada di baris lama juga).
        stored_rows = result.get("rows") or []
        newly_hidden = [r for r in stored_rows if row_best_gaps(r, lane=active)]
        # Pool volatility 0 (tanpa pergerakan) juga dibuang di sini — filter
        # render supaya hasil scan LAMA yang masih membawa baris vol-0 di
        # ``rows`` (era sebelum ∞ gugur) atau di ``hidden_rows`` ikut bersih
        # tanpa scan ulang (permintaan user 2026-09-14 lanjutan: "jika
        # volatility 0 jangan tampilkan"). Baris hasil scan lama juga bisa
        # membawa volatility < 1% / > 10% atau Top10 >= 20% — row_best_gaps
        # membacanya ulang, jadi tabel selalu memakai kriteria hari ini.
        stored_rows = [r for r in stored_rows if not row_volatility_zero(r)]
        rows = sort_best_rows([r for r in stored_rows
                              if not row_best_gaps(r, lane=active)])
        hidden_rows = sort_best_rows(
            [r for r in (result.get("hidden_rows") or []) + newly_hidden
             if not row_volatility_zero(r)])
        # ``hidden`` dihitung dari listing yang benar-benar bisa dilihat
        # (bukan counter mentah ``hidden_metric`` dari scan lama, yang masih
        # bisa menghitung pool vol-0), jadi pill/tombol/caption selalu cocok
        # dengan isi tabel disembunyikan.
        hidden = len(hidden_rows)
        fetched = int(result.get("fetched") or 0)
        skipped_quote = int(result.get("skipped_quote") or 0)
        rug_failed = int(result.get("rugcheck_failed") or 0)
        showing_hidden = bool(
            st.session_state.get(best_lane_hidden_key(active)))

        # Tanpa caption ambang: detail karakteristik card sudah jadi tooltip
        # judul (``best_pool_tooltip()``) — permintaan user 2026-09-10.
        st.markdown(_best_head_html(rows, hidden, active,
                                    showing_hidden=showing_hidden),
                    unsafe_allow_html=True)
        if hidden:
            # Caption/tombol = angka rekap saja; ambangnya hidup di tooltip
            # (judul card + tooltip sel F/V) — aturan card sejak 2026-09-10.
            view = ("◀ kembali ke tabel yang lolos"
                    if showing_hidden else f"▶ {hidden} pool dilewati")
            if st.button(view, key=f"best-pool-toggle-hidden-{active}",
                         help=f"Tampilkan kandidat {label} yang di-skip karena "
                              "gugur saringan F/V, volatility, atau Top10 "
                              "lane ini; "
                              "holdernya tidak pernah di-scan.",
                         use_container_width=True):
                st.session_state[best_lane_hidden_key(active)] = \
                    not showing_hidden
                st.rerun()
        if error:
            st.warning(f"Meteora API: {error}")
        gmgn_failed = int(result.get("gmgn_failed") or 0)
        if fetched:
            quote_txt = (f" · {skipped_quote} pool quote dilewati"
                         if skipped_quote else "")
            rug_txt = (f" · {rug_failed} mint tanpa laporan RugCheck"
                       if rug_failed else "")
            gmgn_txt = (f" · {gmgn_failed} likuiditas GMGN tak terbaca"
                        if gmgn_failed else "")
            # Rekap "N tanpa Bubble Map" dihapus 2026-09-19 bersama kolomnya
            # (permintaan user: "hapus tentang bubblemap, sisakan hyperlink ke
            # bubblemapnya saja") — ``bubblemap_failed`` hasil scan lama
            # (session/cache 2026-09-18) sengaja tidak dibaca lagi supaya
            # caption tidak menyebut kolom yang sudah tidak ada.
            st.caption(f"{len(rows)} pool {label} tampil · {hidden} "
                       f"dilewati · listing {fetched} pool{quote_txt}"
                       f"{rug_txt}{gmgn_txt}.")
        if showing_hidden:
            if not hidden_rows:
                st.info("Tidak ada pool tersembunyi di lane ini.")
                return
            st.caption(
                f"{len(hidden_rows)} pool {label} disembunyikan ditampilkan "
                "· detail holder tidak diambil untuk kandidat ini.")
            # Sorot hijau tua menyala khusus tabel utama — listing dilewati
            # barisnya sudah dianotasi merah gugur-ambang.
            # Tabel "dilewati" tanpa kolom STRATEGY (konfirmasi user
            # 2026-09-19: kolom baru itu hanya untuk tabel utama) — 13 kolom,
            # sama seperti sebelum STRATEGY ada.
            _render_best_table(hidden_rows, lane=active,
                               key_prefix=f"best-pool-hidden-{active}",
                               mark_tops=False, show_strategy=False)
            return
        if not rows:
            # Pesan kosong menyebut PENYEBABNYA (2026-09-17, laporan user
            # "poolnya kok jadi kosong"): rekap alasan gugur per kategori
            # + ajakan membuka daftar "dilewati" — user tidak perlu menebak
            # saringan mana yang membuang listing-nya.
            reason = best_gap_summary(hidden_rows)
            st.info(f"Tidak ada pool {label} yang lolos filter Best Pool "
                    "(atau listing kosong)."
                    + (f" {hidden} pool dilewati: {reason} — buka "
                       f"'▶ {hidden} pool dilewati' di atas untuk alasan "
                       "tiap baris." if reason else ""))
            return
        _render_best_table(rows, lane=active,
                           key_prefix=f"best-pool-{active}")

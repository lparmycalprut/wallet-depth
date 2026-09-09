# Robinhood Chain holder API — Blockscout (chain id 4663)

Referensi endpoint yang dipakai `robinhood_holders.py`. Semua contoh di
bawah **diverifikasi langsung** pada 2026-09-08 terhadap instance publik
`https://robinhoodchain.blockscout.com` (dari browser/klien yang tidak
dianggap bot). **Update 2026-09-08 sore:** instance publik memasang
bot-protection — lihat bagian *Transport: PRO API → instance publik* di
bawah; path & bentuk respons di dokumen ini berlaku identik untuk PRO
API (`https://api.blockscout.com/4663/<path yang sama>`).

Token uji:

| Token | CA | Holder |
|---|---|---|
| PONS | `0x39dBED3a2bd333467115dE45665cC57F813C4571` | ± 85.036 |
| LINK | `0x492641F648a4986844848E0beFE66D14817bCE34` | 46 |

## Kenapa bukan GMGN

`GET https://gmgn.ai/vas/api/v1/token_holders/robinhood/<CA>` membalas
`{"code": 0, "msg": "success", "data": {"list": []}}` — **list selalu
kosong**, GMGN tidak meng-index chain 4663. Kode lama memakainya sebagai
*primary*, jadi setiap scan membuang satu request lalu jatuh ke fallback
Blockscout yang **juga** rusak (lihat "offset" di bawah) → hasil akhirnya
0 holder. Jangan dipakai lagi, dan jangan mencoba slug chain GMGN lain.

## Basis chain

- Chain id **4663**, EVM (Arbitrum Orbit), address `0x…` 40 hex.
- Explorer/API publik: `https://robinhoodchain.blockscout.com`.
- **PRO API** `https://api.blockscout.com/4663/…` — mirror resmi dengan
  path identik; butuh key `proapi_…` (gratis di
  <https://dev.blockscout.com>, tanpa kartu) via header
  `Authorization: Bearer proapi_…` atau query `apikey=`. Tanpa key
  menjawab JSON `{"error":"Proceed with API key or make a X402 payment
  to continue"}` (x402 = opsi bayar per-request, tidak dipakai). Sejak
  2026-09-08 ini **jalur utama** modul bila `BLOCKSCOUT_API_KEY` ada.
  Bentuk lain yang sama-sama valid: Etherscan-style
  `https://api.blockscout.com/v2/api?chain_id=4663&module=…&action=…`
  dan JSON-RPC proxy `POST https://api.blockscout.com/4663/json-rpc`.
- Etherscan **tidak** mendukung chain 4663. Bitquery mendukung tapi berbayar
  (mulai $49/bln). DexScreener/GeckoTerminal hanya menyediakan **harga**.

---

## 1. CSV export — jalur utama, satu request untuk seluruh daftar

```
GET /api/v2/tokens/<CA>/holders/csv
```

Balasan `text/csv`, **tanpa paginasi**:

```csv
HolderAddress,Balance
0xf93f3eff7624DA69db24730f4fBEE84CD6Bd6DAc,90.15199648
0xF504473A5477F81c603C03CC2c169869c782d64a,38.45661924487300951
...
0x2Ca37ff95caF25366eF16fc2E655b78a165D125F,0.000000000000000001
```

Catatan penting:

- **Balance sudah dibagi `decimals`** — jangan dibagi `10**decimals` lagi.
  Baris terkecil (`0.000000000000000001`) = 1 wei pada token 18 desimal.
- Address ditulis **checksummed**; `fetch_holders_csv` me-lowercase-kan
  supaya cocok dengan pembanding pool/cohort di modul lain.
- Urutan menurun berdasarkan saldo.
- Plafon baris dari `GET /api/v2/config/csv-export` →
  `{"limit": 10000, "async_enabled": false}`. Sinkron, jadi respons
  langsung berisi datanya; token dengan > 10.000 holder akan terpotong dan
  harus dilengkapi jalur (2)/(3).

## 2. REST v2 keyset pagination

```
GET /api/v2/tokens/<CA>/holders?items_count=50
```

```jsonc
{
  "items": [
    {
      "address": {
        "hash": "0x…", "is_contract": true, "is_verified": true,
        "name": "UniswapV3Pool", "ens_domain_name": null,
        "proxy_type": "eip7702",
        "implementations": [{"address_hash": "0x…", "name": "SemiModularAccount7702"}],
        "metadata": {"tags": [{"name": "Gate.io", "slug": "gate-io"}]},
        "is_scam": false, "reputation": "ok"
      },
      "token_id": null,
      "value": "9000000000000000000"      // RAW, bagi 10**decimals
    }
  ],
  "next_page_params": {"address_hash": "0x…", "value": "9…", "items_count": 50}
}
```

- `items_count` **maksimum 50**; nilai lebih besar ditolak
  `"100 is larger than inclusive maximum 50"`. Jangan dinaikkan.
- Paginasi = keyset: salin **persis** isi `next_page_params` ke query
  berikutnya. `null`/absen = daftar habis. Halaman dalam tidak lebih mahal.
- Ini satu-satunya jalur yang membawa metadata pool/kontrak:
  `is_contract`, `name` (`UniswapV3Pool`, `SafeProxy`, `DexAggregator`),
  dan `metadata.tags[].name`. `robinhood_holders` menandai `is_contract`
  sebagai **bukan wallet** (`is_wallet=False`) supaya LP tidak mencemari
  bucket Wallet Depth.
- `proxy_type: "eip7702"` dengan `implementations[].name` ∈
  {`UniversalGaslessDelegate`, `SemiModularAccount7702`,
  `EIP7702StatelessDeleGator`} tetap **wallet user asli**, bukan pool.
- Biaya: 85k holder ≈ 1.700 request → hanya dipakai sebagai cadangan.

## 3. Legacy RPC (Etherscan-compatible)

```
GET /api?module=token&action=getTokenHolders&contractaddress=<CA>&page=<n>&offset=400
```

```json
{"message": "OK", "status": "1",
 "result": [{"address": "0x…", "value": "9000000000000000000"}]}
```

- ⚠️ **`offset` maksimum 400.** Nilai lebih besar (`420`, `450`, `500`,
  `1000`) dijawab `{"status":"0","message":"Something went wrong."}` pada
  token besar. Konstanta lama `HOLDER_PAGE_SIZE = 1000` inilah **akar bug
  scanner** — setiap request ditolak sehingga scan pulang 0 holder.
- `value` **RAW** → bagi `10**decimals`.
- Address sudah lowercase, urutan menurun.
- Halaman melewati akhir data membalas `{"result": [], "status": "1"}`
  (kosong, **bukan** error) → dipakai sebagai kondisi berhenti.
- Biaya: 85k holder ≈ 213 request pada `offset=400` → 8× lebih hemat
  daripada v2, karena itu dicoba **sebelum** v2 saat CSV tidak cukup.

## 4. Endpoint pendukung

```
GET /api/v2/tokens/<CA>/counters
  -> {"transfers_count": "6939118", "token_holders_count": "84990"}

GET /api/v2/tokens/<CA>
  -> {"decimals":"18","holders_count":"85036","exchange_rate":"0.738939",
      "total_supply":"…","symbol":"PONS","circulating_market_cap":"…"}

GET /api?module=token&action=getToken&contractaddress=<CA>
  -> {"decimals":"18","name":…,"symbol":…,"totalSupply":…,"type":"ERC-20"}
```

`counters` dipakai `fetch_holders_count()` sebagai sanity-check: bila
daftar yang berhasil ditarik jauh lebih pendek daripada
`token_holders_count`, hasil ditandai `truncated` / dilengkapi jalur lain.

Token yang tidak dikenal → HTTP 404 `{"message": "Not found"}`.

## Strategi di `fetch_holders()`

```
counters ──► CSV export ──(sukses & lengkap)──────────────► selesai
                │
                ├─(gagal / terpotong vs counters)
                ▼
          legacy RPC offset=400 ──(sukses)────────────────► selesai
                │
                ├─(gagal)
                ▼
          REST v2 keyset 50/hal ──────────────────────────► selesai
```

`source` pada hasil: `blockscout-csv`, `blockscout-rpc`, `blockscout-v2`
— diberi akhiran transport `@pro` / `@public` (mis. `blockscout-csv@pro`;
buang dengan `source_base()`, label UI lewat `route_label()`) — atau
`blockscout-csv(fail)` bila semuanya gagal (dengan `error` berisi alasan
tiap jalur, atau **satu** kalimat 403 bila penyebabnya bot-protection;
lihat di bawah). Hasil sukses di-cache in-memory
`_HOLDER_CACHE_TTL = 90` detik — sengaja jauh di bawah
`holder_history.LP_INTERVAL_SEC` (300 dtk) supaya scan LP 5 menit selalu
memotret data baru.

## Transport: PRO API → instance publik (sejak 2026-09-08)

Gejala yang memicu: Scan Holder Khusus untuk CA sah (Pusheen
`0x1209ec401498a1b781412576c978eee0daa0bb6e`, 409 holder) pulang
`getToken: 403 Client Error: Forbidden; csv: 403 …; v2: 403 …` — tiga
jalur ditolak **serentak** dengan status yang sama. Itu bukan CA salah
dan bukan rate limit: instance publik memasang bot-protection Cloudflare
(body HTML "Just a moment…", header `cf-mitigated: challenge`) yang
memfilter TLS fingerprint/IP server (Streamlit Cloud, runner Actions);
dari browser endpoint yang sama tetap 200. Dokumen resmi Blockscout
menyatakan akses API per-instance **deprecated** dan akses program
diarahkan ke PRO API ber-key. Header `User-Agent` browser saja tidak
cukup (sudah dipakai sejak awal).

Semua request Blockscout lewat `_blockscout_get(url)`; `url` selalu
ditulis sebagai URL instance publik dan padanan PRO-nya dibentuk
otomatis (`_pro_url`: host `api.blockscout.com` + prefiks `/4663`).

```
key PRO ada (BLOCKSCOUT_API_KEY / BLOCKSCOUT_API_KEYS / config / secrets)?
  ├─ ya ─► PRO API (Authorization: Bearer), key dipilih round-robin
  │           ├─ 2xx ─► response (route=pro, key#N)
  │           ├─ 401/403 ditolak ─► parkir key 60/5 mnt, coba key berikutnya
  │           ├─ 402 kredit habis ─► parkir 30 mnt, coba key berikutnya
  │           ├─ 429 RPS ─► parkir sesuai x-ratelimit-reset (≤60 dtk),
  │           │             coba key berikutnya
  │           └─ semua key diparkir / 404 rute ─► lanjut ke instance publik
  └─ tidak ─► instance publik:
                curl_cffi impersonate chrome → chrome136 → chrome131 →
                safari184 → safari17_0 → firefox133 (rotasi saat 403)
                └─ semua 403 ─► requests biasa + header browser
                                 └─ 403 ─► BlockscoutBlocked
```

- Key dibaca `get_pro_api_keys()` (list, digabung & dedup seperti
  `core.get_helius_keys`): env `BLOCKSCOUT_API_KEY` / `BLOCKSCOUT_API_KEYS`
  (koma/baris baru) / `BLOCKSCOUT_PRO_API_KEY` → `blockscout_api_key(s)` di
  `config.json` → `st.secrets` dengan nama yang sama. Key hanya dikirim di
  header, tidak pernah muncul di URL/log/pesan error — log memakai label
  `key#N` sesuai urutan itu.
- **Pool key** (`_ProKeyPool`, sejak 2026-09-09): kuota free tier dihitung
  per akun, jadi N akun = N × 100K kredit/hari & N × 5 RPS. Round-robin di
  antara key yang aktif; key yang diparkir dicoba lagi setelah masa parkir
  habis (probe murah). State in-memory per proses; `clear_holder_cache()`
  juga me-reset pool. `pro_key_status()` / `pro_key_summary()` untuk
  log cron & UI (sisa kredit dari header `x-credits-remaining`).
  `fetch_holders` melaporkan `pro_key` (label yang dipakai) dan `pro_keys`
  (jumlah key terpasang); `analyze_token` meneruskannya ke `holders`.
- `BlockscoutBlocked` (403, atau 503 berbadan halaman challenge)
  **bukan** transient: tidak di-retry, `is_transient_error()` → False,
  `is_blocked_error()` → True. `fetch_holders()` mengumpulkan kejadian
  ini dari semua jalur menjadi **satu** kalimat (`error`) + `blocked:
  True`; `analyze_token()` meneruskannya sebagai
  `holders["blocked"]` + `holders["fetch_error"]`, dan UI/cron menampilkan
  "pasang BLOCKSCOUT_API_KEY" alih-alih "pastikan CA valid".
- Bila PRO gagal **dan** publik 403, alasan PRO ikut disebut di detail
  (`…; PRO: PRO API 402 Out of credits (key#4)`) dan petunjuknya berganti
  dari "pasang BLOCKSCOUT_API_KEY" menjadi "key ada tetapi semuanya
  ditolak / kreditnya habis — periksa dashboard" supaya key salah/kuota
  habis tidak tersamar di balik 403 publik.
- PRO API tidak menerima `X-Robinhood…` apa pun; respons sukses = body
  Blockscout mentah (CSV tetap CSV, v2 tetap keyset), jadi parser tidak
  berubah. Header balasan berguna: `x-credits-remaining`,
  `x-ratelimit-remaining`.

## Rate limit

**PRO API** (dokumen resmi): free tier 5 RPS & 100.000 kredit/hari;
`module/action` 20 kredit per call, `api/v2/tokens/*` 30 kredit (CSV
export dihitung sebagai route tokens) → kira-kira 3.000–5.000 request
per hari, cukup untuk cron 5 menit (≈ 3 request per token per scan).
Kredit habis → 402 → modul jatuh ke instance publik. Tier berbayar:
Builder 15 RPS ($49), Pro 30 RPS ($199).

**Instance publik** tidak mempublikasikan angka resmi. Modul tetap sopan:
jeda `PAGE_SLEEP_SEC = 0.6` dtk antar halaman (± 1,7 req/dtk) plus retry
exponential-backoff untuk 429/5xx (`RETRY_ATTEMPTS`, `RETRY_BACKOFF_SEC`);
403 **tidak** di-retry (lihat atas).

# Robinhood Chain holder API — Blockscout (chain id 4663)

Referensi endpoint yang dipakai `robinhood_holders.py`. Semua contoh di
bawah **diverifikasi langsung** pada 2026-09-08 terhadap instance publik
`https://robinhoodchain.blockscout.com` (tanpa API key, tanpa captcha).

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
- Mirror PRO `https://api.blockscout.com/4663/…` **butuh** Bearer key /
  X402 payment (`{"error":"Proceed with API key or make a X402 payment"}`)
  — jangan dipakai.
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

`source` pada hasil: `blockscout-csv`, `blockscout-rpc`, `blockscout-v2`,
atau `blockscout-csv(fail)` bila semuanya gagal (dengan `error` berisi
alasan tiap jalur). Hasil sukses di-cache in-memory
`_HOLDER_CACHE_TTL = 90` detik — sengaja jauh di bawah
`holder_history.LP_INTERVAL_SEC` (300 dtk) supaya scan LP 5 menit selalu
memotret data baru.

## Rate limit

Blockscout tidak mempublikasikan angka resmi untuk instance publik dan
tidak mensyaratkan API key. Modul ini tetap sopan: jeda
`PAGE_SLEEP_SEC = 0.6` dtk antar halaman (± 1,7 req/dtk) plus retry
exponential-backoff untuk 429/5xx (`RETRY_ATTEMPTS`, `RETRY_BACKOFF_SEC`).

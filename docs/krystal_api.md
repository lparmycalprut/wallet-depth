# Krystal Cloud API — catatan lapangan (Robinhood Chain 4663)

Dipakai card **🦅 Scan Best Pool Krystal** (`krystal_screener.py` +
`krystal_pool_ui.py`). Dokumentasi resmi: <https://cloud.krystal.app/> ·
<https://krystalapp.gitbook.io/cloud-docs> · Swagger
<https://cloud-api.krystal.app/swagger/index.html> (`/swagger/doc.json`).

## Status verifikasi (14 September 2026)

| hal | status | bukti |
|---|---|---|
| `GET /v1/chains` (publik, **0 unit**) | ✅ terverifikasi live | mengembalikan 13 chain; entri `{"name":"Robinhood","id":4663,"explorer":"https://robinhoodchain.blockscout.com","supportedProtocols":["ramsescl","uniswapv4","uniswapv3","uniswapv2"]}` |
| `GET /v1/pools` tanpa key | ✅ terverifikasi | `{"error":"An API Key is required. Checkout https://cloud.krystal.app"}` |
| `GET /v1/pools?chainId=robinhood@4663` **dengan key** | ⏳ **belum terverifikasi live** | egress sandbox pengembangan hanya mengizinkan PyPI/GitHub; `KC-APIKey` harus dikirim di **header** (`securityDefinitions.ApiKeyAuth` = `apiKey` / `KC-APIKey` / `in: header`), jadi tidak bisa dipanggil lewat alat HTTP tanpa header. **Jalankan satu probe di mesinmu** (perintah di bawah) lalu tempel hasilnya — bagian "Field respons" akan disesuaikan bila Krystal ternyata mengirim nama yang beda. |
| `api.krystal.app/all/v1/lp_explorer/configs` (publik) | ✅ terverifikasi | chain `4663` = Robinhood, protokol `ramsescl`, `uniswapv2`, `uniswapv3`, `uniswapv4` — katalog yang sama dengan `/v1/chains` |
| `api.krystal.app/all/v1/lp_explorer/top_pools?chainId=4663&protocol=uniswapv3&limit=3` (jalur cadangan publik) | ❌ **tidak bisa dipakai** | `{"error":"rpc error: code = Unknown desc = chain id 4663 not supported"}` — endpoint publik lp_explorer menolak chain 4663, jadi satu-satunya sumber listing adalah Krystal Cloud ber-API key |

### Probe yang dijalankan (tanpa key)

```bash
curl -s "https://cloud-api.krystal.app/v1/chains"                       # 0 unit
curl -s "https://cloud-api.krystal.app/v1/pools?chainId=robinhood@4663&protocol=uniswapv3&sortBy=0&limit=2"
# -> {"error":"An API Key is required. Checkout https://cloud.krystal.app"}
```

### Probe yang perlu kamu jalankan sekali (butuh key-mu)

```bash
curl -s -H "KC-APIKey: $KRYSTAL_API_KEY" -H "Content-Type: application/json" \
  "https://cloud-api.krystal.app/v1/pools?chainId=robinhood@4663&protocol=uniswapv3&sortBy=0&limit=2"
```

Yang perlu dicek dari outputnya: apakah `data` berupa **list** (contoh landing
page) atau objek ber-`data` (pola umum API mereka); nama field `tvl`,
`stats24h.fee`, `stats24h.volume`, `stats24h.apr`, `poolAddress`, `protocol`,
`feeTier`, `token0/token1`. `krystal_screener` sudah membaca **kedua** bentuk
(JSON list maupun `{"data": [...]}`) dan toleran terhadap `stats24h` /
`stats_24h` / `24h`, jadi perubahan kecil tidak langsung mematahkan card.

## Endpoint

```
GET https://cloud-api.krystal.app/v1/pools          → 10 unit/call
GET https://cloud-api.krystal.app/v1/pools/:chainId/:poolAddress   → 10 unit
GET https://cloud-api.krystal.app/v1/chains         → 0 unit (publik)
GET https://cloud-api.krystal.app/v1/protocols      → 0 unit (publik)
```

Auth: header `KC-APIKey: <key>` (satu-satunya cara — tidak ada query param).
Kode HTTP: `400` bad request, `401` key tidak valid, `402` kredit habis.

### Parameter `/v1/pools` (dari swagger)

| param | tipe | default | arti |
|---|---|---|---|
| `chainId` | int/string | — | id chain (`4663`) atau format `nama@id` (`robinhood@4663`, dipakai contoh resmi) |
| `protocol` | string | — | kunci protokol (`ramsescl`, `uniswapv2`, `uniswapv3`, `uniswapv4`) |
| `factoryAddress` | string | — | filter factory / pool manager (V4) |
| `token` | string | — | filter simbol/alamat token |
| `sortBy` | int | `0` | `0` APR · `1` TVL · `2` volume 24 jam · `3` fee |
| `minTvl` | int | `1000` | TVL minimum USD |
| `minVolume24h` | int | `1000` | volume 24 jam minimum USD |
| `limit` | int | `1000` | jumlah hasil (maks 5000) |
| `offset` | int | `0` | loncat hasil |
| `withIncentives` | bool | `false` | sertakan data insentif |
| `includeTokenPrice` | bool | `false` | sertakan harga token |

Card ini mengambil **empat protokol** (satu request 10 unit per protokol = 40
unit per scan) dengan `limit=20`, `sortBy=0` (APR), `minTvl=1000`, lalu
menggabung dan mendedup per `poolAddress`.

## Field respons (bentuk terdokumentasi, contoh landing page Krystal)

```json
[
  {
    "chainId": "ethereum@1",
    "poolAddress": "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640",
    "poolPrice": "1609786418949367252210668423360793",
    "protocol": {"name": "uniswapv3", "factoryAddress": "0x1f98…"},
    "feeTier": 500,
    "token0": {"address": "0xa0b8…", "symbol": "USDC", "name": "USD Coin",
               "decimals": 6, "logo": "…"},
    "token1": {"address": "0xc02a…", "symbol": "WETH", "name": "Wrapped Ether",
               "decimals": 18, "logo": "…"},
    "tvl": "99602546.357321",
    "stats1h":  {"volume": "7394848.12",     "fee": "3697.42",    "apr": 28.432},
    "stats24h": {"volume": "143948485.934915", "fee": "71974.241481", "apr": 26.375428240880527},
    "stats7d":  {"volume": "913593636.036695", "fee": "456796.808671", "apr": 51.93536490355576},
    "stats30d": {"volume": "1612152627.851341", "fee": "806076.298494", "apr": 53.775015037784826},
    "incentives": [{"incentiveType": "Pancake Farm", "amountPerDay": 4.66,
                    "dailyRewardUsd": 11.15, "apr24h": 0.00599}]
  }
]
```

Catatan pembacaan di `krystal_screener`:

- nilai numerik dikirim sebagai **string** → semua dibaca `_maybe_float`
  (None bila tidak terbaca, bukan 0);
- **`F`** (padanan `fee_active_tvl_ratio` Meteora) = `stats24h.fee ÷ tvl × 100`
  — **bukan** `stats24h.apr`; APR Krystal sudah memasukkan insentif dan
  annualisasi, sehingga tidak sebanding dengan volatility harian;
- **`V`** (volatility) **tidak ada di payload Krystal** → dihitung dari 24
  candle hourly GeckoTerminal network `robinhood`
  (`(max high − min low) ÷ min low × 100`);
- `feeTier` satuannya beda per protokol (500 = 0,05% di Uniswap V3), jadi
  ditampilkan apa adanya (`tier 500`), tidak dikonversi ke persen;
- token base untuk scan holder = sisi **bukan** `WETH/USDC/USDT/USDG/…`
  (`KRYSTAL_QUOTE_SYMBOLS`); pool yang dua-duanya quote dibuang
  (`drop_quote_rows`), sama seperti pool SOL/USDC di Meteora.

## Kredit

`/v1/pools` = 10 unit per call. Paket gratis 50.000 unit → satu scan penuh
(4 protokol × 10 unit) menghabiskan 40 unit; tombol scan ditekan manual, bukan
cron, jadi pemakaiannya terkendali. Kode `402` = kredit habis.

## Key

`KRYSTAL_API_KEY` dibaca berurutan dari: Streamlit secrets → env → `config.json`
(`krystal_api_key`). **Jangan pernah di-commit**: `.streamlit/secrets.toml` dan
`config.json` sudah ada di `.gitignore`. Nilai key tidak pernah dicetak ke log,
tooltip, caption, maupun berkas cache hasil scan.

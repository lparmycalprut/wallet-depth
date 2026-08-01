# GMGN internal API — verified notes

Everything here was verified against a **real browser HAR capture** of
`gmgn.ai/trend?chain=sol` (captured 2026-07-28). This is an *unofficial*
API — GMGN can change it at any time, so re-capture a HAR and update this
file when the screener starts returning nothing.

## Trending list

```
POST https://gmgn.ai/trs/api/v1/trending_rank
```

### Query params

| param       | value                          | notes |
|-------------|--------------------------------|-------|
| `device_id` | random UUID4                   | any stable UUID works |
| `fp_did`    | random 32-char hex             | **new** — browser fingerprint id |
| `client_id` | `gmgn_web_<buildTag>`          | must track the live build |
| `app_ver`   | `<buildTag>`                   | same tag as `client_id` |
| `from_app`  | `gmgn`                         | |
| `tz_name`   | `Asia/Jakarta` (URL-encoded)   | |
| `tz_offset` | `25200`                        | seconds |
| `app_lang`  | `en-US`                        | capture showed `en-US`, not `en` |
| `os`        | `web`                          | |
| `worker`    | `0`                            | |

**buildTag** comes from `GET https://gmgn.ai/version.json`:

```json
{"buildTag":"20260728-2617-master-057cd43","seq":2617,"builtAt":1785253138840}
```

The web app strips the `master-` segment, i.e. it sends
`20260728-2617-057cd43`. `gmgn_screener._build_tag()` fetches and caches this
for an hour so the client never goes stale. A hard-coded old value
(the previous code used `20250101`) is what eventually gets soft-blocked.

### Auth

**None.** The trending request in the capture sent **no cookie and no
`authorization` header** — it is public. What matters is a browser-like TLS
fingerprint (`curl_cffi` `impersonate=`) plus the `sec-ch-ua*` / `origin` /
`referer` headers.

### Request body

Unchanged from what the repo already sent:

```json
{"meta":{},"params":[{"chain":"sol","interval":"24h","filter":{
  "filters":["migrated","not_wash_trading","renounced","frozen"],
  "min_created":"2880m","max_created":"43200m",
  "min_liquidity":30000,"min_marketcap":100000,"min_holder_count":1000,
  "min_gas_fee":20,"max_insider_ratio":0.15,"max_bundler_rate":0.15,
  "min_volume_24h":100000}}]}
```

Response shape: `{"code":0,"message":"success","data":[{... ,"tokens":[…]}]}`
— note `data` is a **list**, tokens live at `data[0].tokens`.

## Token fields (94 keys) — the ones we use

| key       | meaning                                   | example |
|-----------|-------------------------------------------|---------|
| `a`       | contract address                          | `7V6Sk…pump` |
| `s` / `nm`| symbol / name                             | `HBULL` |
| `p`       | price USD                                 | `0.001545` |
| `mc`      | market cap                                | `1536810` |
| `lq`      | liquidity USD                             | `123372` |
| `v`       | 24h volume                                | `712218` |
| `hd`      | holder count                              | `5822` |
| `t10`     | top-10 holder rate (**0-1**, not %)       | `0.138` |
| `smt`     | smart-money wallet count                  | `19` |
| `kol`     | KOL/influencer wallet count               | `6` |
| `rug`     | rug score (0-1)                           | `0.23` |
| `ot`      | open timestamp (unix seconds)             | `1783992332` |
| `pcp`     | 24h price change %                        | `4.10562` |
| `pcp1h`   | 1h price change %                         | `-8.25403` |

### ⚠️ Risk fields — the names that bit us

The trending payload has **no `insider_ratio` and no `bundler_rate` key**,
even though the *filter* accepts `max_insider_ratio` / `max_bundler_rate`.
The old code read those two names, always got `0`, and so **every
insider/bundler penalty silently never fired**. The real keys are:

| trending key | `token_stat` equivalent            | meaning |
|--------------|------------------------------------|---------|
| `bdrr`       | `top_bundler_trader_percentage`    | bundler-traded supply share |
| `dhr`        | `dev_team_hold_rate`               | dev/team holdings |
| `etpr`       | `top_entrapment_trader_percentage` | entrapment ("trap buyers") traders |
| `bdr`        | `bot_degen_rate`                   | bot-degen share of flow |
| `t70_shr`    | `top70_sniper_hold_rate`           | snipers still holding |
| `snp`        | —                                  | sniper wallet **count** |
| `sc`         | —                                  | GMGN's own score (unused) |

All rates are **0-1 fractions**, not percentages.

## Per-token stats (richer, one CA at a time)

```
GET https://gmgn.ai/api/v1/token_stat/sol/<CA>
```

```json
{"holder_count":3382,"bluechip_owner_count":0,"top_rat_trader_percentage":"0",
 "top_bundler_trader_percentage":"0.0857","top_entrapment_trader_percentage":"0.2157",
 "top_bot_degen_percentage":"0.1966","bot_degen_rate":"0.1966",
 "fresh_wallet_rate":"0.125","top_10_holder_rate":"0.135",
 "dev_team_hold_rate":"0.0000387798","creator_hold_rate":"0",
 "top70_sniper_hold_rate":"0.0000387798"}
```

Values are **strings** here — parse with `float()`. Not used by the screener
yet; useful if you ever want these metrics for a single CA on the Analyze
page.

## Other endpoints seen in the capture

| endpoint | use |
|---|---|
| `GET /version.json` | current build tag (used for `app_ver`) |
| `POST /api/v1/token_prices` | batch prices, body `{chain, interval, addresses[]}` |
| `POST /api/v1/token_holder_counts` | batch holder counts |
| `GET /api/v1/tokens/top_buyers/sol/<CA>` | top buyers |
| `GET /api/v1/token_fee_distribution/sol/<CA>` | fee distribution |
| `GET /mrwapi/v1/timestamp` | server time |

## Debugging

```bash
python gmgn_screener.py          # prints the scored table
```

`fetch_trending(debug=True)` prints the exact reason a fetch came back empty
(HTTP status, API `code`, or "200 OK but 0 tokens" when the filters match
nothing) instead of failing silently.

## Holder average cost & distance from ATH (`token_context.py`)

Neither number exists in the `trending_rank` payload. They used to be
**fabricated** in `gmgn_screener._get_avg_cost_and_ath` (`-65%` avg cost,
`90%` down-from-ATH whenever the field was missing — i.e. always), which is
why every scanned row read `🟢 Down 90.0% dari ATH` and the LP/Degen cards
never showed a real avg cost.

`token_context.py` now fetches the real values:

### Holder endpoint (verified from browser capture 2026-07-31)

```
GET https://gmgn.ai/vas/api/v1/token_holders/sol/<CA>
    ?limit=100&cost=20&orderby=unrealized_profit&direction=desc
    + device_id / fp_did / client_id / app_ver / from_app / tz_name /
      tz_offset / app_lang / os / worker
Referer: https://gmgn.ai/sol/token/<CA>    ← per-token, not generic
```

Params `cost`, `orderby`, `direction` are **mandatory** — without them the
response is empty or rows lack the `cost` field.

### Aggregation

The aggregate is `sum(cost) / sum(balance)` (remaining USD cost basis
divided by token count across all qualifying rows). This replaces the
earlier weighted-`avg_cost` approach because many wallets have
`avg_cost: null` (transfer-funded) while their `cost` field is still
populated, giving much wider float coverage.

AMM/pool rows (`addr_type != 0` or a non-empty `exchange` field, e.g.
`pump_amm`) are discarded — they carry no meaningful cost basis.

### Down from ATH

An explicit ATH field when present, else derived from `max_market_cap`,
else the all-time high of GeckoTerminal **daily** candles for the token's
deepest DexScreener pair.

### Failure behaviour

Both values return `None` when genuinely unresolvable; the UI renders `—`.
**Never** guess: a fabricated number is worse than a dash. Results are
cached for 5 minutes per CA and cleared by the force-rescan buttons.

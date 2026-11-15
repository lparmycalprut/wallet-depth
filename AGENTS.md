# Repository guide

## Product scope

The Streamlit application is a focused **Meteora Best Pool 12H** dashboard. Do not restore the removed wallet-depth Holder system, TEMP page, scheduled Holder workflows, Holder stores, or Holder links without a new explicit product decision.

**Telegram alerts are sanctioned again — but only for the 🌊 Sweep page** (explicit product decision, 2026-10-12). **Exception (2026-10-22):** ⚡ Early Watcher (`early_watch.py`, `scripts/early_watch.py`, `.github/workflows/early-watch.yml`) sends alerts too, because the user asked for them; it is separate from Sweep and does not change Sweep verdicts. The Holder-era alert machinery is *not* restored: the sweep feature has its own modules (`sweep_alert.py`, `sweep_store.py`, `sweep_scan.py`, `sweep_ui.py`, `pages/8_🌊_Sweep.py`, `scripts/scan_sweep.py`, `.github/workflows/sweep-scan.yml`). Keep them separate from Best Pool, do not resurrect `telegram_alerts.py` or any Holder store, and keep `app.py` free of sweep imports.

Independent market-risk fields such as Meteora's `top_holders_pct`, GMGN metrics, RugCheck, and the Bubblemaps external link are not part of the removed subsystem.

## Sweep page invariants

- the page is a **separate multipage entry** (`pages/8_🌊_Sweep.py`); `app.py` must not import sweep modules
- the watchlist is **manual** — never auto-populate it from Best Pool, GMGN, or any scanner
- Sweep structural thresholds are fixed in `sweep_screen.py`: `TOKEN_MC_MAX = 0.175` (token pool ÷ FDV; criterion 1 since 2026-10-14) and `HOLDER_MAX_PCT = 5.0`. Do not add UI/cron overrides or persist threshold settings.
- Sweep eligibility requires the cohort gate (Kohort C, 2026-10-13): both the OHLCV-derived 48-hour birth-window VWAP with `status_avg_cost ≤ -0.50` AND the GMGN holder average-cost status `gmgn_status_avg_cost ≤ -0.50` (price ÷ balance-weighted avg buy of top-100 GMGN holders, minus 1). Missing GMGN data holds the gate as `TANPA DATA — kohort GMGN` (current price at least 50% below cohort VWAP; threshold lowered from -0.70 on 2026-10-13) may pass; PLUS, shallow-minus, or missing cohort data must not be eligible.
- The sweep cost to 10x, `(sqrt(10)-1) x liq/MC / 2` (quote cash entering the pool; liq = two-sided TVL), is shown as information only (`cost_10x_mc_frac`). The former 28%-of-MC cost gate was **removed on 2026-10-15** by explicit user request: it no longer affects eligibility or the verdict, and there is no `TUNGGU — biaya 10x` status anymore.
- Sweep eligibility also requires the **holder avg-buy gate** (2026-10-13): the lowest `avg_cost` among GMGN `token_holders` with `balance > 0` must be ≥ 50% of the current price (`HOLDER_COST_MAX_GAP = 0.50`). Below that, or with no data, the verdict is `TUNGGU — avg buy holder …`. The gate runs after the cohort gate.
- The results table shows a **“Lowest buy (MC)”** column (2026-10-15): the lowest GMGN holder avg buy converted to market cap, `holder_min_avg_cost × MC ÷ price` (`screen.holder_lowest_buy_mc`), followed by how far the current price has moved since that lowest buy, `price ÷ holder_min_avg_cost − 1` (`screen.holder_price_change_vs_lowest_buy`, e.g. `$30K (harga naik 46.0%)` or `(harga turun 5.8%)`). It is display-only and does not change eligibility; the gate above uses the same lowest holder avg buy.
- **TIDAK LAYAK rows are hidden** from the main results (2026-10-15 user request) and shown in the separate hidden table, and they sort with the bottom `SKIP — kohort plus` group (`screen.is_tidak_layak`, `view_hidden`, `display_sort_key`). Scan-failed rows are never hidden. **Temporary override (2026-10-27):** `sweep_ui.SHOW_ALL_TOKENS = True` shows every mint in the main table; nothing is hidden. Set it to `False` to restore the hiding rules.
- **Order flow is info only** (2026-10-15): `screen.order_flow_info(candles_hour)` is stored as `result["order_flow"]` and shown in the detail panel. It reads hourly OHLCV only: BOS up (close above the 20-hour high), sweep-low reclaim, lower-wick rejection with close in the upper half, and the 48-hour volume-profile POC. It must never change checks, score, verdict, `eligible`, sort order, or view filters. Delta from trades is not implemented yet.
- **Delta is info only too** (2026-10-15): `scan._gmgn_trades_for_delta` fetches GMGN token trades for the last 6 hours (≤ 10 pages) only for candidates (`screen.delta_candidate`: cohort `TUNGGU`/`LOLOS`, not `TIDAK LAYAK`). `screen.delta_info` buckets buy/sell USD per hour (delta = buy − sell, CVD = running sum, quiet hours = 0) and sets flags `div_bearish`, `absorb`, `spike_no_progress`. Stored as `result["delta"]`; never changes checks, score, verdict, `eligible`, sort, or filters. Trade fetches run sequentially because `cvd` keeps global fetch status. Tests replace the fetch with `tests/_offline_delta.py`.
- **CVD & delta since lowest buy is info only** (2026-10-20): `sweep_screen.flow_episode_step` opens an episode when a mint that is visible and a delta candidate has price ≤ `holder_min_avg_cost` (lowest buy), and closes it when price is back above. Hidden mints do not fetch trades (the episode is paused, not closed). Trades come from `sweep_scan.lowest_buy_flow_for_mint` (GMGN, up to 24 h, `FLOW_MAX_PAGES` = 20). The start may be estimated from snapshot history (`flow_backfill_start`) using the current lowest buy. Per-hour records live in `state["flow_episodes"]`. The table (`sweep_ui._render_flow`) shows only currently-below visible mints. Nothing here affects verdict, eligible, order, or filters.
- **Sinyal bottom is info only** (2026-10-28): `sweep_bottom.bottom_signals` gives four indicators: CVD bullish divergence (delta buckets, 6 h, now storing `price`), token/MC stall, quote-side hold (proxy: `liq_usd − pool_base_usd`), and price above the latched shakeout low (`shakeout_low` now stored on the latched check). Shown in the "Sinyal bottom" column and the detail panel. Never changes checks, score, verdict, `eligible`, sort, or filters.
- A detected shakeout is latched per mint in `sweep_state.json` and must never be cleared just because later candles break the old low.
- alerts fire on **state transitions only** (eligibility transition, sweep cooldown), never on every scan
- theoretical and measured numbers must stay labelled as such: `est_cost_usd` is the formula `(sqrt(m)-1) * liq`, `net_inflow_usd` is a measurement (Δ liquidity between snapshots) and is `None` when unavailable — do not let the UI or alerts present the reference estimate as a measurement
- cohort average-cost status must be labeled **“perkiraan (proksi VWAP 48 jam)”**; it is derived from hourly pool OHLCV, not directly observed wallet cost basis
- the stats table is the deliverable: every alert must leave a signal row with `max_up_pct` / `max_down_pct` so hit rate can be reviewed instead of guessed
- opening the page shows the **last stored snapshot view** (`latest_view`) of each watchlist mint without a live scan; only mints with no view yet are scanned once. Live scans happen on the explicit Refresh button, auto-refresh, or the no-data retry (only mints whose cohort gate is `TANPA DATA — kohort`, 60 s apart, max 5 attempts, off while auto-refresh is on). The table is ordered by `sweep_screen.display_sort_key`, and PLUS-cohort rows always sit at the bottom
- **Manual single-CA check** (2026-10-20): `pages/9_🔍_Cek_CA_Sweep.py` (logic in `sweep_check.py`) scans exactly one pasted Solana CA live, once, with the same criteria and verdict as 🌊 Sweep. It never adds the mint to the watchlist, never writes snapshots/views/signals to `sweep_state.json`, and never sends Telegram alerts. It reads stored history (shakeout and cohort latches) from a deep copy of the state.
- the watchlist can be edited from the table (remove checked rows); removal only drops the mint from the watchlist, while its snapshots, signals, and shakeout latch stay in `sweep_state.json`

## Best Pool invariants

Scan Best Pool (2026-11-11, explicit user request; reworked 2026-11-13 and 2026-11-14) lives in `pool_flow.py` (logic, no Streamlit) and `pool_flow_ui.py` (main-page card). Everything is read from one Meteora `pool-discovery` listing at timeframe **12h**, `category=all`, with the server filter the user sent on 2026-11-15 as a curl (`FLOW_SERVER_FILTER`: `base_token_has_critical_warnings=false`, `quote_token_has_critical_warnings=false`, `base_token_has_high_supply_concentration=false`, `base_token_has_high_single_ownership=false`, `pool_type=dlmm`, `tvl>=10000`, `fee_tvl_ratio>=2`, `fee_pct>=0.5`; no `sort_by`, the local ranking decides order). Pages are fetched by cursor: each request sends `after_key` from the previous response and stops when `has_more` is false. The `page` parameter is ignored by the API and must not be used (it returned the same pools on every page). **No local selection filter (2026-11-14, user request).** The avg volume, fee/active TVL, volatility, fee tier, TVL, active TVL, holders and market cap rules that existed before were removed. Every unique pool in the listing is shown. The only local rule that can drop a pool is the security block below. Next filters will come from the user later.

- Ranking (table and Telegram alert both use it): `fee_active_tvl_ratio` descending, ties by `avg_volume` descending.
- Security rules (2026-11-14, `security_checks` in `pool_flow.py`; kept when the local filters were removed on 2026-11-14 because the user approved them separately). **Block** (pool removed from the passing list, shown only in `results` with a `keamanan:` reason): `token_x.has_mint_authority` true, `token_x.has_freeze_authority` true, `token_x.top_holders_pct` > 30 %. **Warning** (pool stays, shown in the "Peringatan keamanan" column and in the Telegram alert): `top_holders_pct` > 15 %, `token_x.dev_balance_pct` > 5 %, or `total_withdraws` > `total_deposits` while `tvl` < $50K. Missing (null) fields are never counted as a problem. Volume/TVL and trader counts are deliberately not used (weak signals).
- **Two tables** (2026-11-15, user request; this reverses the one-table rule of 2026-11-14), split by `fee_tvl_ratio` (fee ÷ TVL, %, 12H) against `volatility` (%), in `pool_flow.fee_printer_split`:
  - **FEE PRINTER (SPOT)**: `fee_tvl_ratio` > 2 × `volatility`. Heading only (bold name and pool count), no explanatory caption, because this table is still raw data until the user filters it.
  - **FEE PRINTER**: 0,5 × `volatility` ≤ `fee_tvl_ratio` ≤ 2 × `volatility` (both bounds inclusive; the user's example: volatility 1 % → fee/TVL 0,5 % or 2 % is in this table). Bold heading, then an italic line below with the pool count and the rule.
  - Pools with `volatility` unmeasurable (None or < 0,01 %) or `fee_tvl_ratio` missing are in neither table. Pools with fee/TVL < 0,5 × volatility are also in neither table; the general caption above the tables says so.
  - Each table uses the ranking above. The top pool gets the 🔥🔥🔥 row marker only in the table that contains it. There is no headline text (removed 2026-11-13).
  - Telegram alert is unchanged: it still sends the top pool of the full ranking.
- (2026-11-15, user request) The per-token pool fetch, the token dropdown (`st.expander` per token), and the token columns ("Volume 12H (token)", "Rata² swap (token)") were removed. The scan no longer calls `fetch_token_pools` or `enrich_scan_result`. Per-pool volume and average swap per pool are still shown (`pool_activity`).
- The scan writes nothing. Only the Telegram alert (`scripts/pool_flow_alert.py`, every 4 hours, `pool-flow-best.yml`) writes `pool_flow_state.json`, and that file keeps only alert numbering (`best_alert`) and `alerts`.
- The Telegram alert sends **one pool only**: the top pool of the ranking above (highest `fee_active_tvl_ratio`, ties by `avg_volume`). It uses `scan_pools` and `most_crowded` only, with **no per-token fetch** (there is none any more), and the message shows the 12h data (no risk band).
- The watchlist, net-deposit history, watch alert, and the Cek LP Keluar page/tool were removed on 2026-11-11. Do not reintroduce them without a new user request.
- Earlier Best Pool rules (Fee-IL, F/V, IL windows, GMGN/RugCheck enrichment) and the modules behind them were removed; the old modules are gone from the repo.

## Mobile UI invariant

Best Pool must retain every table column and every header on mobile. Use compact fixed-width columns and horizontal scrolling. Do not reintroduce card conversion, column hiding, or a separate reduced mobile schema.

The marker `.bp-cols-next` is emitted before the header and each data row. `dashboard_components.render_styles()` targets the following Streamlit horizontal block.

## Retained supporting code

- `core.py`, `cvd.py`, `scripts/update_cvd.py`, and `watchlist.py` retain generic CVD/Helius functionality.
- Do not remove generic Helius request helpers merely because the Holder scanner was removed.
- `links.py` contains only retained external token/pool/CVD links.
- `activity_log.py` is an in-memory application event log; it no longer renders Holder-scan credit status.

## Validation

Before finishing a change:

```bash
find . -path './.venv' -prune -o -path './.git' -prune -o -name '*.py' -print0 \
  | xargs -0 .venv/bin/python -m py_compile
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

For distribution changes, always run `tests/test_liquidity_distribution_filter.py` explicitly.

## Early Watcher invariants (2026-10-22)

- **Cek Entri LP page** (2026-11-10, user request): `pages/11_🧭_Cek_Entri_LP.py` renders `lp_entry_ui.py`, which wraps `tools/lp_entry_check/lp_entry_check.py` (stdlib logic, heuristic verdicts, thresholds in its `KONSTANTA` block). Read-only: it fetches Meteora pool data for one pasted CA, caches the result 60 s, and never writes state, touches the watchlist, or sends alerts. It is a separate multipage entry and must not import Best Pool or Sweep modules; `app.py` stays free of it.
- Separate feature: `early_watch.py` (pure logic), `scripts/early_watch.py` (runner, poll every 120 s; the workflow runs 10 segments of 30 min per job, committing state after each changed segment), `.github/workflows/early-watch.yml`, `early_ui.py` and `pages/10_⚡_Early_Watcher.py` (read-only). State is `early_watch_state.json`; the watchlist is `early_watch_watchlist.json` (5 mints only, requested by the user).
- Info only. It never changes Sweep verdict, score, `eligible`, filters, or `sweep_state.json`. It does not import from `sweep_screen`, `sweep_scan`, or `sweep_state.json`.
- Every watchlist mint is polled, even if muted or hidden in Sweep. Nothing is hidden.
- Round trip = same tx and maker with a buy leg and a sell leg in different quote markets, spread 2%–50%, leg ≥ $0.10. Active = ≥ 4 round trips from ≥ 3 wallets in 60 s (turun dari 5 pada 2026-10-22).
- **Big sell before active (2026-10-22):** an alert needs one sell ≥ `DUMP_MIN_USD` ($1,000, usulan) that is not a round-trip leg, within `DUMP_LOOKBACK_SEC` (600 s, naik dari 300 pada 2026-10-22) before the start of the active window. Activity without that dump is recorded as `AKTIF (tanpa dump)` and sends no alert.
- Alert only on the transition to active, plus a 30-minute cooldown. Dumps are kept 15 minutes in state so a dump seen in an earlier poll still counts.
- Fetch failure = status `GAGAL`. It does not change activity state, does not alert, and does not hide the mint. `partial=True` when the page cap is reached.
- Commit state only when `decision_fingerprint` changes (alerts, status, cooldown, `last_active_ts`, `burst_ok`, dumps). Log-only changes are not committed.
- Gap handling: when the last successful poll (`last_ok`) is more than 180 s old (first poll, or a missed run), the runner backfills dumps from `[now-660, now-180]` in 180 s chunks (dumps only; no activity, no alerts). A failed backfill is recorded in `rec["backfill"]` and the normal poll still runs.
- Cron runs are sparse in practice (2 scheduled runs in the first day after merge), so each job is ~5 h long to cover more time.
- Workflow runs only from the default branch, so it is inactive until merged to `main`.


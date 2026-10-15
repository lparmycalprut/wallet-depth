# Repository guide

## Product scope

The Streamlit application is a focused **Meteora Best Pool 24H** dashboard. Do not restore the removed wallet-depth Holder system, TEMP page, scheduled Holder workflows, Holder stores, or Holder links without a new explicit product decision.

**Telegram alerts are sanctioned again — but only for the 🌊 Sweep page** (explicit product decision, 2026-10-12). The Holder-era alert machinery is *not* restored: the sweep feature has its own modules (`sweep_alert.py`, `sweep_store.py`, `sweep_scan.py`, `sweep_ui.py`, `pages/8_🌊_Sweep.py`, `scripts/scan_sweep.py`, `.github/workflows/sweep-scan.yml`). Keep them separate from Best Pool, do not resurrect `telegram_alerts.py` or any Holder store, and keep `app.py` free of sweep imports.

Independent market-risk fields such as Meteora's `top_holders_pct`, GMGN metrics, RugCheck, and the Bubblemaps external link are not part of the removed subsystem.

## Sweep page invariants

- the page is a **separate multipage entry** (`pages/8_🌊_Sweep.py`); `app.py` must not import sweep modules
- the watchlist is **manual** — never auto-populate it from Best Pool, GMGN, or any scanner
- Sweep structural thresholds are fixed in `sweep_screen.py`: `TOKEN_MC_MAX = 0.175` (token pool ÷ FDV; criterion 1 since 2026-10-14) and `HOLDER_MAX_PCT = 5.0`. Do not add UI/cron overrides or persist threshold settings.
- Sweep eligibility requires the cohort gate (Kohort C, 2026-10-13): both the OHLCV-derived 48-hour birth-window VWAP with `status_avg_cost ≤ -0.50` AND the GMGN holder average-cost status `gmgn_status_avg_cost ≤ -0.50` (price ÷ balance-weighted avg buy of top-100 GMGN holders, minus 1). Missing GMGN data holds the gate as `TANPA DATA — kohort GMGN` (current price at least 50% below cohort VWAP; threshold lowered from -0.70 on 2026-10-13) may pass; PLUS, shallow-minus, or missing cohort data must not be eligible.
- The sweep cost to 10x, `(sqrt(10)-1) x liq/MC / 2` (quote cash entering the pool; liq = two-sided TVL), is shown as information only (`cost_10x_mc_frac`). The former 28%-of-MC cost gate was **removed on 2026-10-15** by explicit user request: it no longer affects eligibility or the verdict, and there is no `TUNGGU — biaya 10x` status anymore.
- Sweep eligibility also requires the **holder avg-buy gate** (2026-10-13): the lowest `avg_cost` among GMGN `token_holders` with `balance > 0` must be ≥ 50% of the current price (`HOLDER_COST_MAX_GAP = 0.50`). Below that, or with no data, the verdict is `TUNGGU — avg buy holder …`. The gate runs after the cohort gate.
- The results table shows a **“Lowest buy (MC)”** column (2026-10-15): the lowest GMGN holder avg buy converted to market cap, `holder_min_avg_cost × MC ÷ price` (`screen.holder_lowest_buy_mc`). It is display-only and does not change eligibility; the gate above uses the same lowest holder avg buy.
- A detected shakeout is latched per mint in `sweep_state.json` and must never be cleared just because later candles break the old low.
- alerts fire on **state transitions only** (eligibility transition, sweep cooldown), never on every scan
- theoretical and measured numbers must stay labelled as such: `est_cost_usd` is the formula `(sqrt(m)-1) * liq`, `net_inflow_usd` is a measurement (Δ liquidity between snapshots) and is `None` when unavailable — do not let the UI or alerts present the reference estimate as a measurement
- cohort average-cost status must be labeled **“perkiraan (proksi VWAP 48 jam)”**; it is derived from hourly pool OHLCV, not directly observed wallet cost basis
- the stats table is the deliverable: every alert must leave a signal row with `max_up_pct` / `max_down_pct` so hit rate can be reviewed instead of guessed
- opening the page shows the **last stored snapshot view** (`latest_view`) of each watchlist mint without a live scan; only mints with no view yet are scanned once. Live scans happen on the explicit Refresh button, auto-refresh, or the no-data retry (only mints whose cohort gate is `TANPA DATA — kohort`, 60 s apart, max 5 attempts, off while auto-refresh is on). The table is ordered by `sweep_screen.display_sort_key`, and PLUS-cohort rows always sit at the bottom
- the watchlist can be edited from the table (remove checked rows); removal only drops the mint from the watchlist, while its snapshots, signals, and shakeout latch stay in `sweep_state.json`

## Best Pool invariants

- `BEST_ACTIVE_TVL_MIN = 50_000.0`
- `BEST_LPS_MIN = 100.0`
- no POOL BARU/new-pool route or bypass
- `BEST_FV_24H_MIN = 10.0` for the main table
- `BEST_FV_HIDE_MIN = 5.0`: F/V 5× to <10× remains visible in `hidden_rows`; F/V <5× is dropped
- cheap listing filters run before pool-detail or third-party enrichment; only displayable rows (main + skipped) are enriched
- Token:SOL is informational only; official Meteora values are still calculated as amount × USD price
- GMGN bundler + phishing/entrapment is informational only: it never filters a pool, regardless of the combined rate or whether the report can be read
- the report may be fetched for main rows plus displayable skipped rows; report failures must not affect eligibility
- risk data uses `top_bundler_trader_percentage` plus `top_entrapment_trader_percentage`
- only main-table rows receive RugCheck/tax enrichment

Relevant implementation: `meteora_screener.py`. Relevant UI: `best_pool_ui.py`.

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

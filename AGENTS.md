# Repository guide

## Product scope

The Streamlit application is a focused **Meteora Best Pool 24H** dashboard. Do not restore the removed wallet-depth Holder system, TEMP page, scheduled Holder workflows, Telegram alerts, Holder stores, or Holder links without a new explicit product decision.

Independent market-risk fields such as Meteora's `top_holders_pct`, GMGN metrics, RugCheck, and the Bubblemaps external link are not part of the removed subsystem.

## Best Pool invariants

- `BEST_ACTIVE_TVL_MIN = 100_000.0`
- `BEST_LPS_MIN = 100.0`
- no POOL BARU/new-pool route or bypass
- all cheap listing filters run before pool-detail or third-party enrichment
- the official Meteora pool-detail distribution check is the final gate before GMGN/RugCheck/tax enrichment
- SOL-side USD liquidity must be at least 5× token-side USD liquidity
- equivalent token:SOL maximum is 1:5
- exact 1:5 passes; 1:6.52 passes; 1:4 fails
- calculate side values as amount × USD price, never from raw token counts
- missing/invalid/non-SOL/non-positive distribution data fails closed

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

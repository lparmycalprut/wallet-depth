# Wallet Depth — Best Pool Meteora

A focused Streamlit dashboard for scanning Meteora DLMM Best Pools. The app now contains one primary surface: **🏆 Scan Best Pool Meteora (24H)**.

The wallet-depth Holder subsystem and TEMP page have been removed, including their scans, history, automation, alerts, notifications, and internal links.

## Best Pool rules

A pool must satisfy all listing checks:

- DLMM, 24-hour timeframe
- active TVL **≥ $100,000**
- liquidity providers **≥ 100**
- F/V **≥ 5×**
- Fee/TVL **≥ 30%**
- volatility between **1% and 10%**, inclusive
- Meteora Top-10 supply concentration below **20%**

After those cheap checks, the final distribution gate fetches the official Meteora pool-detail response and calculates each side in USD:

```text
side USD value = token amount × token USD price
```

The pool passes only when:

```text
SOL USD value / token USD value >= 2
```

Equivalently, token:SOL must be at most **1:2**. Exact **1:2** and a more SOL-heavy ratio such as **1:6.52** pass; **1:1.5** fails. Missing details, API errors, non-SOL pairs, non-finite values, and non-positive side values fail closed.

Only passing rows continue to optional GMGN liquidity, RugCheck, and tax/dividend enrichment. There is no new-pool detection or alternate bypass path.

## Mobile layout

Best Pool remains a real table on phones. Every header and column is preserved with compact widths and horizontal scrolling. Rows are not converted into cards, and secondary columns are not hidden.

## Run locally

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Configuration

Copy `config.example.json` to `config.json` only if using the retained CVD tooling that calls Helius:

```json
{
  "helius_api_key": "YOUR_KEY",
  "helius_extra_keys": ""
}
```

Best Pool itself does not use Helius.

## Tests

```bash
python -m unittest discover -s tests -v
```

The focused liquidity-distribution regression suite is:

```bash
python -m unittest -v tests.test_liquidity_distribution_filter
```

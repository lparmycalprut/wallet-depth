# Wallet Depth — Best Pool Meteora

A focused Streamlit dashboard for scanning Meteora DLMM Best Pools. The app now contains one primary surface: **🏆 Scan Best Pool Meteora (24H)**.

The wallet-depth Holder subsystem and TEMP page have been removed, including their scans, history, automation, alerts, notifications, and internal links.

## Best Pool rules

A pool must satisfy all listing checks:

- DLMM, 24-hour timeframe
- active TVL **≥ $50,000**
- liquidity providers **≥ 100**
- F/V **≥ 10×** to appear in the main result table
- F/V **≥ 5×** to remain a Best Pool candidate; **5× to <10×** appears in **pool dilewati**, while **<5×** is dropped
- Fee/TVL is shown for comparison, but is **not a filter**
- volatility between **1% and 10%**, inclusive
- Meteora Top-10 supply concentration below **25%**

After those cheap checks, official Meteora pool details still provide the **Token:SOL** USD-value ratio, but the ratio is informational and no longer filters pools.

GMGN per-token **Bundler+Phishing** is the final risk gate after F/V. It is fetched for both main-table rows and the displayable **pool dilewati** rows, so candidates with **F/V 5× to <10×** still show their Bundler+Phishing data. A combined rate of **40% or less** passes; above **40%** (or an unreadable mandatory report) is kept out of the main table and shown as a skipped warning row. Its Bundler+Phishing cell becomes bold, bright red, and blinking. Only rows passing this final gate continue to RugCheck and tax/dividend enrichment. There is no new-pool detection or alternate bypass path.

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

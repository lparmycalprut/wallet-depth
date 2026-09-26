# Deployment

## Streamlit Community Cloud

- Entry point: `app.py`
- Python runtime: see `runtime.txt`
- Install dependencies from `requirements.txt`
- The application requires outbound HTTPS access to Meteora and its optional market/risk enrichment providers.

No GitHub Actions scanner, Holder store branch, cron chain, or Telegram credentials are required. Those systems were removed.

## Optional CVD configuration

The retained CVD command-line tooling can use Helius. Configure one or more keys through Streamlit secrets, environment variables, or a local `config.json`:

```toml
helius_api_key = "YOUR_KEY"
helius_extra_keys = "OPTIONAL_SECOND_KEY"
```

Equivalent environment variables are `HELIUS_API_KEY` and `HELIUS_API_KEYS`.

Best Pool does not require Helius.

## Health check

After deployment, confirm:

1. the main page renders **🏆 Scan Best Pool Meteora**;
2. no Holder or TEMP page appears in navigation;
3. a scan can fetch the Meteora 24H listing;
4. on a phone-sized viewport, table headers and all columns remain available through horizontal scrolling.

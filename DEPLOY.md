# Deployment

## Streamlit Community Cloud

- Entry point: `app.py`
- Python runtime: see `runtime.txt`
- Install dependencies from `requirements.txt`
- The application requires outbound HTTPS access to Meteora and its optional market/risk enrichment providers.

Best Pool itself still requires no GitHub Actions scanner, Holder store branch, cron chain, or Telegram credentials.

The **🌊 Sweep** page uses fixed screening thresholds: liq/MC ≤35% and holder/wallet ≤5%. The 48-hour birth-cohort VWAP gate must pass before any token can be eligible; thresholds are not UI/cron settings.

The **🌊 Sweep** page does need two things when you want 24/7 alerts (they are optional — without them the page still screens and records statistics):

1. **Telegram** — `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`, resolved in layers: `st.secrets` → environment → `config.json`. In GitHub Actions, add them as repository secrets (same names as the retained Pre-Pump tooling).
2. **GitHub commit access** — `github_token` (fine-grained PAT, contents: write) so the sweep watchlist, snapshots, and signal history survive Streamlit Cloud restarts. Without it the list is kept in the ephemeral filesystem plus a local `config.json` backup.

`.github/workflows/sweep-scan.yml` runs the same scan every 5 minutes and commits only when `sweep_state.json` actually changed (`store.fingerprint()`), so a 5-minute cadence does not create ~288 commits/day.

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
4. on a phone-sized viewport, table headers and all columns remain available through horizontal scrolling;
5. **🌊 Sweep** appears in navigation and renders the watchlist editor, the eligibility table, and the signal statistics section;
6. the Sweep page's Telegram line reports either *siap* (with the credential source) or the exact list of places to fill in credentials;
7. the Sweep page shows the fixed threshold text, the `Turnover (×/hari)` column, and a per-token **Kohort lahir** panel with its proxy label and cohort-gate state.

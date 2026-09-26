# Removed functionality

As of 2026-09-26, the wallet-depth Holder subsystem and TEMP page are removed rather than feature-flagged.

Removed scope includes Holder scans, analysis/history/status stores, scheduled workflows, notifications, Telegram alerts, Holder links/routes, Holder enrichment in Best Pool, Watchlist Meteora UI, and Scan Holder UI.

There is no supported switch to reactivate these paths. Reintroducing any of them requires a new product decision and a new implementation; do not depend on historical filenames or stores.

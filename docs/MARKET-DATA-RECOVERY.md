# Market data recovery — 13 November 2026

## Why earlier history was missing

`/api/history?refresh=true` previously looked back **seven calendar days** regardless of candle interval. The chart called this endpoint without a start date, so on 13 November the oldest candles were often from 7 November. The backend now uses **180 days** for minute/hour candles, **730 days** for daily/longer candles when no explicit date is supplied. The chart supplies an explicit range of **1 month, 3 months, 6 months (default), 1 year, 3 years, or 5 years**. The broker's own historical availability still applies; one request is broken into smaller windows to respect API limits. The chart loads cached candles first, then refreshes them. The selected range is not a promise that an exchange has traded on every day or that all older contracts exist.

For 1-minute candles, the chart retains a maximum of 20,000 displayed candles per request (the SQLite cache can contain additional older candles). For an exceptionally large requested range, use shorter ranges or query the database directly. Broker history is **not** synthesized when absent.

## Why Upstox live quotes were missing

Upstox V3 streams Protobuf decoded by the official SDK into dictionaries. The V3 message uses `feeds[instrument_key].ff.marketFF.ltpc` for equities and `ff.indexFF.ltpc` for indices. The former decoder looked for `fullFeed`, therefore it silently ignored normal `ff` frames. The parser now supports both forms plus `ltpc`-only frames. Official index keys and `INDEX` → `IDX` mapping are normalized. Invalid/unknown instruments are rejected *individually* rather than preventing every subscription in a shared stream.

The Upstox V3 market-quote **REST LTP** endpoint now provides an optional initial/fallback snapshot on charts, the five-index header and watchlists. These quotes are **clearly labeled as snapshots**; a successful REST response is not proof of a working WebSocket. Broker errors are displayed in the chart and in the existing drawer's feed diagnostics. SDK errors are passed to the shared feed manager rather than ignored in the broker SDK callback.

**All other brokers retain their existing adapters.** This update does not claim their streaming endpoints are live-verified.

## Windows update and tests

1. Back up `D:\personal-algo-trading`, particularly `.env`, `data\trading.db` and any local vault files. Replace application sources only; don't overwrite local data.
2. Run `powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1` from the project root to install SDKs, then `scripts\start_application.bat`.
3. Connect Upstox with an authorized live trading token **or** a read-only Analytics Token for market data (live orders remain disabled for Analytics Tokens). On the chart choose NIFTY / 15m / 6 months and press Refresh. The initial history backfill may involve several broker API calls.
4. While keeping the chart open, run `powershell -ExecutionPolicy Bypass -File .\scripts\diagnose_market.ps1` from the project root. It checks account, feed status, cached candles and the Upstox REST quote without exposing credentials.
5. If live quotes stay blank, examine the chart's `Live feed:` error and the diagnostic feed status. Check that `upstox-python-sdk` is installed in the `.venv` environment, that the token is current, and that the exchange is currently streaming. Snapshot fallback does not prove streaming works.

## Validation

- Unit/integration tests use broker mock HTTP responses, synthetic feed dictionaries, and simulated subscriptions — not a real broker session.
- Back-end tests: 166 passing; front-end chart/workspace utility tests: 9 passing.
- TSX transpilation syntax checks passed; full `npm run build` cannot be verified here without the missing npm dependencies.
- **Real Upstox WebSocket receipt, historical backfill for a live account, order placement, and other brokers' streaming still require account-side verification.** No live orders were placed.

### Official reference

- Historical Candle Data V3: https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/
- Market Data Feed V3: https://upstox.com/developer/api-documentation/v3/get-market-data-feed/
- LTP V3 REST quote: https://upstox.com/developer/api-documentation/ltp-v3/
- Search Instruments: https://upstox.com/developer/api-documentation/instrument-search/

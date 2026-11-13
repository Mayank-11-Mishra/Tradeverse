> **Website deployment:** This project now includes a production owner-login security gate, Railway FastAPI configuration, GitHub Pages workflow, and cloud OAuth callback support. Read [DEPLOY-RAILWAY-GITHUB-PAGES.md](docs/DEPLOY-RAILWAY-GITHUB-PAGES.md) before publishing. The older local-only guidance below still applies when running on Windows. Keep live order execution disabled until your broker's static-IP, tagging and order safeguards have been verified.

# TradeVerse Pro — Broker-First Personal Trading Terminal

**Local Windows development build (2026-11-12). Broker integrations are NOT live-account verified. Do NOT trade real money before you validate every integration and risk control.**

A React/TypeScript trading interface, local FastAPI application, six individually implemented Indian broker adapters, historical-data ingestion, live-feed connectors, declarative strategy engine, backtester, option payoff module, and paper trading account.

This is **a substantial functional expansion of the uploaded starter ZIP**, not a claim that every production feature or broker entitlement works end-to-end.

## Update — studies library, left drawer, chart tabs, option chain (November 12, 2026)

**This update is a local coding/tested implementation, not a verified live brokerage trading system.** The backend now contains **51 calculation engines** (including 30 additional standard studies), plus the **full 469-name study inventory in 26 categories** supplied with the request. The studies browser searches/categories all names; only implemented standard calculators are selectable. Commercial/vendor variations without a reliable documented formula are clearly marked *Pending*, not represented as functional indicators.

- **Chart Add (`+`)** opens broker instrument search, creates a chart tab, selects a symbol, and supports tab closing. The watchlist also has a working add/search control.
- **Left-side navigation drawer** offers Watchlist, Option Chain, Orderbook, Tradebook, Positions, and Live Strategies. Broker account records are fetched on demand and where supported; order cancellation requests always need confirmation.
- **Option-chain repairs:** Upstox underlying names such as `NIFTY` are translated to the broker `instrument_key`. Upstox and FYERS provide API-based expiry discovery and normalized call/put rows. Other brokers are explicitly unsupported by this option-chain view until their own formats are integrated. Analytics tokens can log into Upstox in data-only mode, without trading privileges.
- **Order/strategy checks:** live orders remain disabled by default and are never sent without explicit opt-in. A strategy start verifies the broker session and supports a feed health readout; a stream ending normally or failing stops dependent strategies. Broker order cancellation only acknowledges a *request*, not a confirmed exchange cancellation. **No live orders were submitted during tests.**
- **Validation:** Python automated regression tests cover the above features and original trading core. The React source passes TypeScript/TSX syntax parsing, but a complete frontend `npm run build` could not be run because the environment did not have the required npm dependencies. Finish testing on Windows with live broker credentials in read-only/paper mode before considering live execution.

Quick start: `powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1`, then `scripts\start_application.bat`. Back up `.env` and `data/trading.db` before replacing existing project files. The SQLite database initializes automatically; no PostgreSQL server is required.

## What you need

* Windows 10/11, Python 3.12+, Node.js 20+ and npm
* Internet access for installing dependencies and broker APIs
* A broker API subscription, account, approved credentials and permissions for the features you use
* Optional: PostgreSQL 15+; SQLite works automatically with no database server
* This runs on **127.0.0.1 only**, with no cloud hosting or Docker

## One-time setup (PowerShell)

From the project directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

This creates `.venv`, installs backend requirements, attempts optional SDKs (`kiteconnect`, `upstox-python-sdk`, `growwapi`, `fyers-apiv3`), installs npm packages, and prepares the local data directory. The SQLite database is **created automatically on the first backend start**, so no separate database initialization step is needed.

If one of the optional SDKs cannot install on your Python version, check its official release requirements. The REST adapter still loads; its live streamer requires the matching SDK. Flattrade and Finvasia stream through the `websockets` package.

## Start the full application

Double click `scripts\start_application.bat`, or run:

```bat
scripts\start_application.bat
```

Two console windows start:
* Backend: http://127.0.0.1:8000/docs (interactive REST API)
* Frontend: http://127.0.0.1:5173

Keep both windows running. Browser closure does not automatically stop the backend, but a PC sleep, expired broker token, or feed outage interrupts active strategies. Live strategy state is explicitly reset to stopped after backend restart. Close the two console windows to stop the application.

**No passwords or broker tokens are persisted.** Connect to the broker again after restarting the backend.

## Broker login

On first launch, the application opens a **broker login gate** instead of the trading terminal. Select Groww, Zerodha, Upstox, FYERS, Flattrade or Finvasia; enter the login/account information and *current, official broker-issued* session token (plus API key/client ID where required).

* **Zerodha:** Requires `api_key`, `access_token`, or an official redirect `request_token` plus `api_secret`.
* **Upstox:** Select OAuth trading token or Analytics data-only token. Analytics mode verifies access against the market-data API instead of the Profile API, and order/portfolio APIs are disabled. History, streaming, and options require valid broker entitlements.
* **Groww:** Uses official SDK access token or API key/secret approval flow. SDK required for feed and new backtesting-history methods.
* **FYERS:** Requires `client_id` plus official OAuth token. Full FYERS symbols (e.g. `NSE:RELIANCE-EQ`) should be used for derivatives/indices.
* **Flattrade Pi:** Requires a current broker session token and `user_id`; account ID must match broker account for orders.
* **Finvasia Shoonya:** Requires broker session token and `user_id`, and permissions for the underlying API.

This application does not collect broker passwords or automatically bypass official OAuth, daily approvals, OTP or TOTP. The user obtains a session via official broker channels. API subscriptions, instrument coverage and data history vary by broker.

The `mock` adapter is for tests, has no market stream, and must never be treated as a real broker.


## TradeVerse Pro frontend and required login order

The frontend now follows the supplied dark trading-terminal design reference: a top trading navigation, live-status strip, watchlist, advanced candle chart, multi-chart section, option chain, top-of-book quotes, order ticket, portfolio summary, and connected broker accounts. The layout adapts to narrower screens.

**Access order:**

1. Open `http://127.0.0.1:5173`; the broker selection/login page is displayed while no active broker session exists.
2. Select one of Groww, Zerodha, Upstox, FYERS, Flattrade, or Finvasia. Enter a local account label plus credentials/token **obtained through the broker's official API login flow**.
3. The backend validates the session with the broker's authorized endpoint (Profile API for ordinary OAuth accounts; market-quote API for Upstox Analytics Tokens). The UI checks that the backend registered a connected account. Failed/expired verification never unlocks the trading terminal.
4. After login, the app loads broker instruments for the selected symbol and requests recent authorized historical candles; the market WebSocket is then subscribed. Fund, portfolio, order, and position queries are initiated for the connected account.
5. Select a symbol, timeframe, expiry, or broker account to request fresh data. The mini-chart cards are **on-demand** to avoid needless broker API traffic. No screenshot/sample market prices are inserted.
6. Disconnect the last broker and the login page reappears. After a backend restart, log in again; broker tokens are not persisted.

**Important limitations:** real OAuth/OTP login must still occur through official broker channels before pasting the resulting API session token; no scraping or automated broker-password login is supplied. Intraday candle depth, option-chain formats, and streaming access vary by broker subscription. Full TradingView drawing tools and multilevel order depth are not present. All six broker adapters require live-account validation. Live orders remain explicitly disabled by default.

On initial sign-in, temporary broker failures or absent instrument mappings may leave the chart empty. These failures are shown as errors; they do not trigger synthetic candles or falsely claim that the broker feed is healthy.

The Python suite includes broker-login gate regression tests. The frontend TypeScript source was syntax-checked, but its production npm build was not executable in the authoring environment because the npm dependencies were unavailable; run `npm install` and `npm run build` on your Windows computer to verify installed React/Lucide chart dependencies.

## Main features

| Feature | Implemented | Verification / qualification |
|---|---|---|
| Six broker adapter classes | Yes | Current documented request paths, **not verified with live credentials** |
| Connect multiple accounts | Yes | In-memory per-broker sessions, account metadata in SQLite |
| Historical candles | Yes | Current broker data via REST/SDK, broker-aware chunking, local cache; no full-exchange preload |
| Live updates | Connectors implemented | Broker SDK/WS access and feed parsing require live validation; selected instruments only |
| Chart | React + Lightweight Charts | Candlesticks, volume, EMA overlays, crosshair, time selection; **not full TradingView Advanced Charts** |
| Indicators | 51 calculator IDs | Selectable through studies picker; 469 user-supplied names indexed, remaining vendor formulas pending |
| Strategy rules | Yes | Declarative conditions, AND/OR/NOT, crossover operators; basic EMA visual creator |
| Automated rules | Initial implementation | One-minute closed bars, running backend required; **not validated for real money** |
| Python code editor / sandbox | No | Would require isolated trusted-code runner; not falsely exposed as available |
| Backtesting | Yes | Event-driven bar simulator, illustrative charges; not broker tick-accurate fills |
| Paper trading | Yes | In-memory, simulated fills from real quote ticks; resets after backend restart |
| Option chain | Upstox/FYERS normalized | Automatically discovers broker expiries for known index/underlying keys; others not yet mapped |
| Options payoff | Yes | Multi-leg expiry payoff and Greeks library |
| Live order execution | Adapter routes implemented | OFF by default; **not live tested; no trading without further validation** |
| Risk controls | Yes (core) | Kill switch, notional, qty, stale feed, rate and reduce-only validation |
| Positions/holdings | Adapter routes implemented | Broker dependent; no universal schema guarantee until each account tested |
| CSV import | Yes | For testing/historical analysis; clearly user-uploaded, never represented as broker-verified |
| PostgreSQL | Optional | Set `DATABASE_URL`, e.g. `postgresql+psycopg://user:password@localhost:5432/mydb` |
| Windows launch | Yes | BAT and PowerShell scripts; actual Windows runtime not tested in this Linux sandbox |

## Using historical data and backtests

1. Log in to the intended broker, select an exchange/symbol/segment, and **Fetch broker history**.
2. Historical candles are cached in the local database (source-account keyed) and loaded into the chart.
3. If historical data is not available, upload your own CSV with `date,open,high,low,close,volume` columns. Uploaded data is not broker-verified.
4. Under **My strategies**, choose EMA lengths and save a rule strategy; use **Backtesting** to run the same rules over loaded candles.
5. For paper/live strategy operation, your broker must supply authorized live market data. The backend evaluates 1m candle closes; it does not invent ticks.
6. A live market subscription can fail if a symbol lacks its broker instrument token. Search/synchronize instruments using the instrument search first.

Backend REST API (including import options) is documented at http://127.0.0.1:8000/docs.

## Live trading safety (deliberately locked)

Live execution is **disabled by default** at two layers:

1. Set environment variable `ALLOW_LIVE_TRADING=yes` on the backend, **only after** separately validating broker/API permissions and safety logic.
2. In **Settings & safety**, explicitly enter `ENABLE LIVE TRADING` to activate live orders.

Market staleness, unvalidated exit flags, strategy/broker binding, notional limits, and unresolved timeout states block unsafe orders. The kill switch is available in the UI. An uncertain order must be reconciled by a human with the broker's orderbook: never blindly replay the order.

**Regulatory obligations and broker algo/API permissions still apply to personal trading in India.** A local server does not exempt API usage from broker and exchange requirements. No exchange algo registration, IP white-listing or token lifecycle automation is provided here.

## Configure the local database and optional token

Default SQLite file: `data/trading.db`. The backend creates it automatically at startup; no external database server or manual initialization is required. Broker APIs provide live and historical prices; SQLite only stores the instrument cache, optional downloaded candles, account metadata, strategy definitions and audit events for local reuse. OpenAlgo uses a similar separation of broker feeds from local storage, but its Historify feature uses DuckDB for historical candles whereas this version stores cached candles in SQLite. Do not share the file: it contains account metadata and strategies, but not OAuth tokens. For PostgreSQL set `DATABASE_URL` in the environment *before* starting the backend. The `.env.example` file documents variables; it is not automatically loaded.

To protect the local API against other processes, set `APP_LOCAL_TOKEN` as an environment variable before launching `start_application.bat`, then enter the same token in **Settings & safety** in the UI. Never expose the backend outside loopback; do not port-forward 8000.

## Tests

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

The supplied backend suite was run in the build environment: **157 tests passed** (original trading core and new mocked HTTP/API integration tests). The original **96 tests** are retained, with exit-risk expectations adjusted to enforce verified reduce-only behavior.

**Frontend limitation:** TSX source was syntax-checked with the TypeScript compiler API. `npm install` timed out in the build sandbox, so a complete Vite production build and browser run could not be verified here. Install Node dependencies on Windows before attempting to use the frontend.

## Known gaps / follow-up engineering before live money

- Real credential tests, official authentication callbacks and refresh/re-approval handling per broker.
- Verify each broker's response formats, symbol maps, order tags, and order-state transitions with sanctioned sandbox/live testing.
- Broader instrument and exchange masters, F&O contract expiry handling and broker data entitlements.
- Broker stream multiplexing (the current per-symbol feed model can exceed broker connection limits for large watchlists), subscription limits and recovery after SDK disconnects.
- Persist and reconcile paper/live positions and daily P&L with broker updates. Live OMS needs stronger exchange-specific order restrictions, margin checks, and regulatory checks.
- Full TradingView-grade technical UI (most indicators are backend-only), drawing tools, visual drag-and-drop strategy authoring, custom Python editor, options scanners, and all-broker option chains.
- Test and harden the real client-side build, settings persistence, and Windows start/stop scripts.

## References: official API documentation (please check for subsequent breaking changes)

- Zerodha Kite: https://kite.trade/docs/connect/v3/
- Upstox: https://upstox.com/developer/api-documentation/
- Groww: https://groww.in/trade-api/docs/python-sdk/
- FYERS: https://fyers.in/api-docs/v3/api/market-data/
- Flattrade Pi: https://pi.flattrade.in/docs
- Finvasia Shoonya: https://shoonya.com/api-documentation/api-structure

This is **original adapter code**, not a copy of OpenAlgo. OpenAlgo's model of routing the authenticated broker's own data is followed in spirit; no OpenAlgo dependency or market data is used.


## Upstox login troubleshooting

- Choose **Upstox**, enter any local account label, and paste the **live OAuth `access_token`** generated for your Upstox developer app. The API key is not interchangeable with the access token.
- The form accepts a plain token, a quoted token, or a token preceded by `Bearer `. It will remove that prefix when constructing the Authorization header.
- Upstox tokens normally expire at **3:30 AM IST on the next applicable expiry day**. Generate a new token if login fails. Sandbox tokens and extended tokens have different endpoint permissions.
- Trading OAuth authentication calls the official `GET https://api.upstox.com/v2/user/profile` endpoint; Analytics data-only mode uses `GET /v3/market-quote/ltp`. The login screen now shows Upstox's HTTP status and recognized `UDAPI` error code without showing secrets.
- To check your token outside the app, use the included `scripts/test_upstox_token.ps1`. This checks the broker's official API and does not save the token.
- Do not share the access token, API secret, or entire request headers.

If this fails after a direct profile check succeeds, check that your frontend and backend are running from the same updated folder.

---

### Workspace V2 update (November 2026)

The terminal now supports an arrow-only drawer, index-only broker quote header, persistent dark/light/system themes, chart-only first-run home, dockable and tabbed panes, Heikin-Ashi/Renko/Point-and-Figure charts, searchable broker instruments, broker-connected order confirmation, an extended option chain and account-scoped live WebSocket multiplexing.

For an exact change list, verified tests, security considerations, Windows setup and known gaps, read [`docs/WORKSPACE-V2.md`](docs/WORKSPACE-V2.md). Do **not** treat unverified real-broker order placement as tested or ready for live trading.

## Fetching the earliest broker API history

The default chart **automatically backfills** historical candles for its active symbol/timeframe to the earliest date documented by the connected broker's public API. The task runs in the local backend and does not block live chart use. Its progress appears below the chart toolbar, and older cached pages are loaded by scrolling left or pressing **Load older**. The SQLite history cache survives application restarts.

See [docs/FULL-BROKER-HISTORY.md](docs/FULL-BROKER-HISTORY.md) for supported date boundaries, account-tier differences, API status endpoints, and limitations. A broker's own web/mobile trading terminal may have a longer dataset than its trading API exposes.

## Chart header, tile layout, indicators and broker OAuth (V3)

See [`docs/WORKSPACE-V3-CHART-AUTH.md`](docs/WORKSPACE-V3-CHART-AUTH.md) for implementation notes, broker redirect URI setup, testing status and known limitations. See [`docs/INDICATOR-SETTINGS.md`](docs/INDICATOR-SETTINGS.md) for the full 51-indicator pane/input/settings table. The existing tab/docking layout remains available alongside the new six-tile grid mode. Trading remains paper-only by default until a broker trading session and live execution safeguards are validated.

## Groww SDK and login fix (2026-11-13)

If Groww streaming/history reports a missing `growwapi` package, install it into **the project environment**:

```powershell
cd D:\personal-algo-trading
.\.venv\Scripts\python.exe -m pip install --upgrade growwapi
.\.venv\Scripts\python.exe -m pip show growwapi
```

The Windows setup script now attempts Groww SDK installation separately, before other optional broker SDKs, and verifies it using `pip show`. The Groww API-key/secret login no longer depends on importing the SDK: it uses Groww's documented `POST /v1/token/api/access` with SHA-256 checksum and UTC epoch timestamp. Groww still requires **daily approval** for that API-key mode. Pasted access tokens are supported too.

The adapter now validates login using the current documented `GET /v1/user/detail` endpoint, checking `vendor_user_id` or `ucc`. Groww historical candles and live streaming still use `growwapi`, so install it for full Groww functionality. Real Groww login/stream/orders have not been tested with a private account; keep real orders disabled until verified.


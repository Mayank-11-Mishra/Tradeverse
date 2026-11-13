# TradeVerse Pro – Chart, Tile Mode, Indicators and Broker OAuth (V3)

## Source audit and changed components

- `frontend/src/workspaceLayout.ts` – existing nested tab/split tree, pane labels, layout version 2; **preserved tree format** and added optional tile mode, preset and order fields.
- `frontend/src/TerminalWorkspace.tsx` – pane title, tab toolbar, tile grid, chart indicators, per-chart preferences and settings dialog.
- `frontend/src/TradingChart.tsx` – chart lifecycle, resizing, visible series, overlay vs separate oscillator panes, timestamp sanitization.
- `frontend/src/IndexTicker.tsx` and `frontend/src/style.css` – one-line index quote bar, full-height responsive chart/tile CSS.
- `frontend/src/BrokerGateway.tsx` / `frontend/src/App.tsx` – broker-first login and additional broker connection screen; existing access-token path retained.
- `backend/app/brokers/oauth.py` (new), `backend/app/brokers/finvasia.py`, `backend/app/brokers/common.py` – broker authorization URLs and token exchanges, Shoonya request body/header updates, safe broker response errors.
- `backend/app/api/server.py` – local OAuth initiation/callback and configurable indicator inputs with validation.
- `frontend/src/IndicatorSettings.tsx` (new), `docs/INDICATOR-SETTINGS.md` – per-indicator dialog and complete implemented-indicator table.

## Six requested changes

1. **Chart symbols and index bar.** Chart window headers and tab labels resolve to the current symbol, with special display names for NIFTY/BANKNIFTY. Index quotes are a single row, horizontally scrollable, with last broker-supplied price and directional point/percent change; no `Snapshot` label is shown. Offline prices remain blank – no fabricated values.
2. **Tile plus preserved Tab mode.** A Tab | Tile toggle was added above the workspace. Tile supports `1x1`, `1x2`, `2x1`, `2x2`, `2x3`, `3x2`, up to six panes; drag a tile grip to reorder. Pane headers have symbol, maximize/restore and close buttons. The original docking/tab/split tree is retained unchanged when toggling; mode, preset, and ordering are stored in the existing workspace preferences/localStorage.
3. **Chart viewport.** Flex/grid children use `min-width:0`, `min-height:0`, `overflow:hidden`. Chart fills remaining panel height and uses Lightweight Charts auto-size plus `ResizeObserver`. Exact 1366×768, 1920×1080, ultrawide and small-laptop pixel/browser verification remains to be done on a Windows installation with frontend dependencies installed.
4. **No default EMA.** New charts contain price and volume only. `ema9` and `ema21` are added only for saved chart configurations explicitly containing those flags.
5. **Indicators.** The main price pane shows price overlays; oscillator calculations are assigned their own Lightweight Charts panes using `addSeries(..., paneIndex)`. Data are filtered for finite values and valid timestamps, ordered and deduplicated. The chart legend supports hide/show, gear/settings and removal. Settings dialog has Inputs/Style/Visibility tabs, apply/cancel/reset; chart/layout saves preferences. Full registered indicator table: **`docs/INDICATOR-SETTINGS.md`** (51 calculations). Known limitation: studies currently recompute from broker-cached candle data rather than on each sub-second tick, and the complete 469-item external study inventory contains formulas not implemented in this app.
6. **Broker login.** Updated three broker flows use server-side requests and localhost redirects; errors are sanitised but include provider and HTTP status where safe. The broker status indicators show connected, disconnected or error for each provider, and a closed OAuth popup clears its pending busy indicator. Existing manually pasted valid token path remains.

## IMPORTANT: broker account setup (required)

All redirect URIs must be registered with the **exact host, port, and path** (no `localhost` vs `127.0.0.1` mismatch). Your local FastAPI server must be listening on `127.0.0.1:8000` throughout the login process.

| Broker | Mode and setup | Redirect URI |
|---|---|---|
| FYERS | Create an API v3 app; supply App ID and App Secret; register redirect exactly. Exchange returned `auth_code` using `appIdHash=SHA256(app_id+":"+secret)` via the v3 `validate-authcode` endpoint. | `http://127.0.0.1:8000/api/auth/callback/fyers` |
| Flattrade | Register API key/secret and the exact redirect URI; complete auth.flattrade.in login, return `request_code`, exchange via authapi.flattrade.in with SHA256 key+code+secret. Register/whitelist the static IP where Flattrade requires it. | `http://127.0.0.1:8000/api/auth/callback/flattrade` |
| Finvasia Shoonya | **Current official Shoonya documentation prescribes OAuth, not unattended username/password/TOTP login.** Register OAuth client ID and secret, redirect URI and authorized IP; authorize through api.shoonya.com and exchange `code` for `susertoken` through `GenAcsTok`. Current Shoonya API calls use `Content-Type:text/plain` and a `jData=` request body. | `http://127.0.0.1:8000/api/auth/callback/finvasia` |

Sources (verify current documentation before entering live credentials):
- Shoonya https://shoonya.com/api-documentation/manual-authentication-oauth
- FYERS https://fyers.in/api-docs/v3/api/authentication/individual-app/authentication-flow
- Flattrade https://pi.flattrade.in/docs

### Security and limitations

- Never put broker secrets, passwords or access tokens in chat or bug screenshots.
- OAuth credentials are held in RAM only for a short-lived authorization flow; broker sessions exist in process memory and are not written to the local SQLite database. After an app restart, reconnect broker sessions. Broker app approval and login are done on the broker website, not in a simulated password dialog.
- Shoonya/Flattrade redirects do not document an OAuth state echo; local callback accepts only one outstanding authorization per provider, expires after 3 minutes, and validates a loopback callback. A stronger state-bound callback requires broker support.
- No live authenticated broker session has been exercised in this build. Broker endpoint response contracts were tested with mocked HTTP responses only.
- Real-money order execution remains disabled by default. Test with paper trading and verify each real broker's entitlements and error states before enabling live orders.
- Full frontend production build and browser viewport visual validation were blocked because npm registry access was unavailable in the execution environment. Frontend TypeScript parser/syntax checks and Node utility tests passed; they are not equivalent to a production build.

## Running locally on Windows

1. Make a backup of the existing project, `.env`, and `data/trading.db`. Do not copy a ZIP over the existing data folder.
2. Copy changed source files into your project. Keep your existing credentials local.
3. From the project root, run `powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1` and then `.\scripts\start_application.bat`.
4. Visit `http://127.0.0.1:5173`, open broker login, use the new `Sign in through broker (OAuth)` option for FYERS, Shoonya or Flattrade.
5. In the chart toolbar, use the indicators picker to add RSI/EMA/MACD, then gear icon for settings. Switch Tab | Tile in the workspace toolbar. Refresh or relogin if broker tokens have expired.

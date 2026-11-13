# TradeVerse Pro — Workspace V2 implementation & verification

This update extends the existing six-adapter local trading application. It does **not** replace the broker SDKs or authorize real-money orders automatically. Verify individual broker sessions, subscriptions, quotes, order permissions, and exchange compliance with your own account before enabling live mode.

## Files touched and why

- `frontend/src/App.tsx` — keeps mandatory broker-first login gate, removes redundant auto-history fetch, routes legacy strategy/backtesting/safety pages into the workspace.
- `frontend/src/TerminalWorkspace.tsx` — chart-only first-time home, dockable/tabbed/split/maximized/floating panes, option chain, broker-labeled orders and positions, orders cancellation/modification, auto-save and restore.
- `frontend/src/NavigationDrawer.tsx` — arrow-only slide-out drawer, focus-aware fuzzy instrument search, recent symbols, keyboard handling, account switching, saved layout controls, theme/feed status.
- `frontend/src/IndexTicker.tsx` — broker-resolved five-index header with live last-traded price and *broker previous-close* change; missing quotes stay blank.
- `frontend/src/ThemeProvider.tsx`, `frontend/index.html`, `frontend/src/style.css` — persisted dark/light/system themes with early application before React mounts, CSS tokens, responsive panels.
- `frontend/src/TradingChart.tsx`, `frontend/src/chartTransforms.ts` — candlestick/bars/line/area, HA, close-only Renko, close-based P&F and separate 1-minute-to-requested-timeframe aggregation. Chart objects persist during tick updates; full reinitialization is limited to structural changes.
- `frontend/src/OptionChainPanel.tsx` — calls/strike/puts with ATM styling, OI bars, strike-range filter, Greeks, PCR/max pain when returned by backend, virtualized rows, snapshot refresh and optional broker-streamed leg prices. B/S opens order ticket.
- `frontend/src/OrderTicket.tsx` — broker selection and margin display, cross-broker warning, remembered preference, explicit review/confirmation; read-only broker connections may submit **paper** orders but never live ones.
- `frontend/src/marketFeed.ts` — one shared browser WebSocket client per broker account, dynamic subscriptions, heartbeat, backoff and connection health.
- `frontend/src/workspaceLayout.ts` — version 2 pane/split/tab and floating layout, migration fallback for unsupported versions.
- `backend/app/api/server.py` — versioned preferences, account aggregation, dynamic multi-symbol WebSocket, feed diagnostics, option-chain metadata, broker order modification and audited cancel/submit.
- `backend/app/market_data/hub.py` — upstream account-scoped feed fan-out to charts/header/watchlist/strategies with resubscription and failure isolation.
- `backend/app/brokers/streams.py` / `base.py` — broker previous-close metadata for reliable index change percentages, where available.
- `backend/app/database/store.py` — SQLite-backed preference storage and broker instrument search.
- `backend/app/core_vault.py` — opt-in local token vault: on Windows `CryptProtectData` / DPAPI CurrentUser; on other platforms Fernet with explicit environment key. Broker sessions still verified with the upstream API on startup; active live strategies never resume automatically.

## Implemented workflows

1. **Arrow-only drawer:** the closed drawer leaves only an edge arrow; click handle, outside backdrop or Escape to close. Keyboard `/` or Ctrl+K focuses instrument search.
2. **Index-only header:** NIFTY 50, BANK NIFTY, SENSEX, FINNIFTY and MIDCPNIFTY resolved against broker instruments and subscribed to live ticks; unavailable index symbols show a dash (no synthetic pricing).
3. **Themes:** dark/light/system supported through design tokens and browser+local backend settings. Some legacy screens may retain older color styles.
4. **Charts:** HA/close Renko/close P&F with configurable brick method and P&F reversal, unit-tested. Live 1m candle updates and grouped intraday/daily candles. Close-only transforms are **not identical to high/low Renko/P&F** offered by other charting vendors.
5. **Options:** unified calls/puts/strike view, expiry/strike filters, virtualized rows, estimated OI analytics from broker records, ticket opening. Current normalized chains are Upstox and FYERS focused; other broker chain capabilities vary.
6. **Search:** fuzzy match across broker-cached instruments with suggested similar symbols and chart / chain / watchlist actions. Uncached instruments may require a broker master refresh.
7. **First-login layout:** a single chart is created when no valid saved layout exists.
8. **Docking:** split, tab stack, draggable tab tiling, resize by divider, floating/maximize/close, debounced preference saving and reset. Floating window *movement* persists; freeform manual CSS resize may not persist to the backend.
9. **Broker live data:** account-scoped upstream feed + client reconnect and re-subscribe, market heartbeat, historical/live candle stitching. The best available historical snapshot is used as volume baseline to avoid double counting; **exact overlap volume may differ until broker sync**. The API explicitly reports feed status.
10. **Multi-broker:** concurrent connected sessions, account switcher, broker-labeled portfolio, paper vs live capability restrictions, broker choice for ticket, explicit cross-broker confirmation, audit logging. Multi-broker submissions are independent, not atomic.

## Safety and testing

- `backend`: `python -m pytest -q` — 161 tests passing in the available environment; includes dynamic WebSocket fan-out, preference persistence, simulated feed tests and encrypted Fernet vault. A real Windows DPAPI runtime has not been exercised here.
- `frontend`: `node --experimental-strip-types --test tests/*.test.mjs` — 9 tests passing; HA, Renko, P&F, 15m/daily candle aggregation and workspace operations.
- All frontend TypeScript/TSX files passed syntax/transpilation inspection. **The full Vite/TypeScript production build was not verified**: npm dependencies are not installable in this sandbox. Run `npm install && npm run build` on Windows before relying on the UI.
- No real broker credentials, live WebSocket subscription or order submission was exercised. Broker capability declarations are **not** proof of real-money execution.
- Live trading remains disabled by default. API tokens should not be pasted into logs or chat. Keep the Windows vault private.

## Windows run

1. Back up your old `.env` and `data/trading.db`, and keep any personal strategy files. Do not overwrite local market data unintentionally.
2. Extract new sources over a backup copy of the old project.
3. Run `powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1` from the project root. Windows DPAPI will encrypt credential recovery files when the setting is enabled.
4. Run `.\scripts\start_application.bat`, then open `http://127.0.0.1:5173`.
5. Login to a broker and verify market-data/option-chain subscriptions with broker permission. Use paper mode to test ticket flow and orderbook first.
6. Before live trading, independently confirm broker symbol mappings, live order types, order modifications and cancellations, risk limits, token expiry, static IP/registration requirements and filled/partial order states.

## Known gaps / unverified scope

- No broker-specific live order or streaming integration tests using actual credentials; brokers may impose entitlement or exchange limitations.
- Broker-specific full option chain and Greeks normalization for all six accounts is not complete.
- Floating resize-size persistence and some legacy page theme styling require additional refinement.
- No full drag-to-draw library for all TradingView drawing tools; existing saved horizontal levels remain supported.
- Exact historical/live overlapping volume and exhaustive low-latency performance require real feed testing.
- Paper accounts and live broker positions are separate: do not assume paper balances equal actual margin availability.

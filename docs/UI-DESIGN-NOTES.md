# TradeVerse Pro UI implementation notes

Design reference: `reference-tradeverse-terminal.png` (user-supplied image).

Implemented design surfaces:
- Broker-first login page with six real broker choices and credential fields appropriate to their API adapters.
- Full-width dark terminal navigation with screenshot-inspired violet accent.
- Market strip and watchlist. Quotes intentionally remain blank until the broker actually supplies them.
- Main Lightweight Charts candle/volume view with EMA overlays and timeframe selection.
- Four on-demand mini-chart cards (fetched only after the user presses Load chart).
- Option chain preview with underlying/expiry input; direct option-chain API support varies by broker.
- Top-of-book quote panel (bid, ask, LTP, when the subscribed broker supplies them).
- Order ticket with product, order type, quantity, explicit price, stop trigger, and paper/live modes.
- Portfolio and connection/account summaries.

Access is gated on verified broker connection, including on page refresh. No broker session -> no terminal. The backend denies market history, indicators, backtesting, and strategy creation when the specified broker account has no active session.

This is a screenshot-inspired *implementation*, not a pixel-for-pixel replica or a claim that proprietary TradingView drawing tools have been licensed. The system must never show fictional prices from the screenshot as live market data.

To test on Windows: run `scripts/setup_windows.ps1`, then `scripts/start_application.bat`; open `http://127.0.0.1:5173`, enter credentials from an official broker API login flow, and verify session, history, streaming and account data with that broker. `npm run build` in `frontend` is required before considering the TypeScript build verified.

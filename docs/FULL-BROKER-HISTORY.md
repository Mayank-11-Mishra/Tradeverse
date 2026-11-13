# Full Broker Historical Data — November 2026

## What changed

* The default trading chart no longer imposes a 180-day or five-year historical-data limit.
* Opening a chart loads a small recent viewport for immediate use, then starts an **automatic background backfill** of that instrument and timeframe back to the broker's documented API history boundary.
* Each accepted API page is written to the local SQLite cache and indexed with completed date-range coverage. You can close/reopen the chart and later resume an interrupted scan without losing earlier candles.
* The chart's **History backfill** line shows `running`, `complete`, `partial`, or `paused`, with earliest cached data and the scanning date. `partial` / `paused` includes the broker's error.
* Scroll to the left edge of the chart, or click **Load older**, to load older locally cached pages. Older available pages appear progressively as the background scan continues.
* There are two new API endpoints: `POST /api/history/backfill` and `GET /api/history/backfill/status`, plus `GET /api/history?...&before=<ISO-time>&limit=4000` for cursor-based older-page retrieval.

## Important broker-vs-terminal limitations

The broker's own terminal is **not** necessarily backed by the public API available to your account. This application cannot bypass the broker's API entitlements or manufacture missing historical data.

* **Upstox V3:** historical minute/hour candles from January **2022**, daily/weekly/monthly from January **2000**, subject to instrument availability. API queries are split into supported request windows.
* **FYERS:** Standard and Prime accounts can have materially different history entitlements; Prime can provide significantly longer history. The API may reject older dates for an ordinary plan. For minute candles, the documented archive begins in 2017, but not every account can request it.
* **Groww:** the newer historical-candles backtesting API documents history from **2020**, while its older/deprecated endpoint advertises a much shorter intraday lookback. Availability depends on which API/plan your adapter and account support.
* **Zerodha, Finvasia, Flattrade:** exact earliest day varies by instrument and API. The app probes backwards with conservative request windows and stops early on repeated empty periods or explicit broker errors. It must not state "complete broker history" if an API rejected requests.
* A futures/options contract cannot have candles before it existed. Expired derivative history may require separate broker endpoints/entitlements.
* Historical **candles** are not a complete historical tick/depth database. The full tick history shown in a broker terminal may not be downloadable via its trading API.

The automatically searched oldest dates are *boundaries for exploration*, not guaranteed market-data availability. You can override dates in `.env` (backend environment), for example:

```text
HISTORY_EARLIEST_UPSTOX_INTRADAY=2022-01-01
HISTORY_EARLIEST_UPSTOX_DAILY=2000-01-01
HISTORY_EARLIEST_FYERS_INTRADAY=2017-07-03
```

Only alter these when the broker's official API actually permits those dates. More aggressive settings cannot make unavailable data accessible.

## Local installation

Copy/merge the new project sources into your existing Windows project. **Preserve `.env` and `data/trading.db`**. Do not delete existing cached history. Start the backend and frontend as before. After authenticated broker login, open an instrument chart and allow the local backend to remain running for backfill. Use the browser's `History backfill` status; no cloud service is required.

Data collection may involve dozens or hundreds of API calls per selected instrument/timeframe. Each instrument/timeframe is fetched separately; the app intentionally does **not** request historical candles for every instrument in the exchange at login, as that would overload broker APIs and storage. A terminated/restarted backend can resume previously completed history ranges; broker authentication must still be valid.

**No live broker credentials were available for this development environment**; this integration is verified against simulated adapters and unit tests, not a live Upstox account.

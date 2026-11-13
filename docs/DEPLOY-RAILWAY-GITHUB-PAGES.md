# TradeVerse Pro: Railway backend + GitHub Pages frontend

This guide applies to this repository's separate `backend/` and `frontend/` folders. **It does not deploy to your accounts automatically.** You must push the changed files and configure the services. Never add broker tokens or the owner password to GitHub.

## 0. Security checkpoint (do first)

- This patch introduces password-based **owner authentication** in production; the API, order endpoints, strategies, and WebSocket subscriptions are not available without a valid owner session.
- A broker login is **not** a substitute for owner authentication. Sign in as owner first, then connect your broker.
- Bearer sessions are short-lived (four hours), stored only in the browser tab's `sessionStorage`. They are not compiled into the frontend. Signing out revokes the owner's HTTP session until backend restart; restarting also invalidates previously issued sessions.
- Market sockets obtain **single-use, 30-second tickets** through an authenticated API endpoint, rather than putting the owner password or a long-lived token in the WebSocket URL.
- Production startup **fails** if the owner password hash, signing secret, HTTPS origins, PostgreSQL URL, or `ALLOW_MOCK_BROKER=no` are missing. This is intentional.
- Brokerage sessions are **not restored** on Railway unless explicitly configured. Default `SAVE_BROKER_TOKENS=no`; reconnect brokers after restarts. Stored strategy definitions and historical candles persist in PostgreSQL.
- Live trading is **off by default**. After individual broker validation and order/risk testing, you may set `ALLOW_LIVE_TRADING=yes`; the in-app confirmation and kill switch still apply. **Nothing here proves real orders are safe.**

## 1. Inspect your public GitHub repository

1. Back up `.env`, local history and strategies privately; these are NOT included in this deliverable.
2. Inspect Git history for accidentally committed secrets, `.env`, `data/trading.db`, `broker_sessions.vault`. If present, **revoke/rotate** affected credentials. A new `.gitignore` does NOT erase Git history.
3. Push the deployment-ready source folders and `.github/workflows/deploy.yml` to `main` of your repository.
4. Keep your root `.github/workflows/deploy.yml` from this ZIP. The repository's existing Pages workflow should be replaced rather than duplicated.
5. If you do not own `www.tradeverse.com`, remove any existing root `CNAME` file and clear the custom domain in GitHub Pages settings.

## 2. Generate the two private owner secrets locally

From the extracted project folder (with the backend Python dependencies installed):

```powershell
.\.venv\Scripts\python.exe .\scripts\generate_owner_secrets.py
```

If you have no local virtual environment, install `backend/requirements.txt` into a Python 3.12 environment first. The script prompts for a strong owner password and prints:

- `TRADEVERSE_OWNER_PASSWORD_HASH` (scrypt hash, not raw password)
- `TRADEVERSE_SESSION_SECRET` (random signing secret)

**Copy the outputs directly into Railway Variables**, not the public GitHub repository. Do not share them in chats or screenshots. If a secret is exposed, rotate it. Restarting Railway invalidates all browser owner sessions.

## 3. Create your Railway backend service

1. In [Railway Dashboard](https://railway.com/dashboard), choose **New Project -> Deploy from GitHub repo** and pick `Mayank-11-Mishra/Tradeverse`.
2. Create a service named `tradeverse-backend` with **Root Directory: `/backend`**.
3. Builder: **Railpack**. Python version is specified in `backend/.python-version` as 3.12.
4. **Start Command** (Railway service Settings):

   ```bash
   python -m uvicorn app.api.server:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers
   ```

5. Set **one replica** and **disable Serverless/App Sleep**. Strategies and broker sessions are process-local; multiple instances are not supported safely by this code.
6. Healthcheck Path: `/api/health` (returns minimal public status). Set healthcheck timeout to allow Python startup and DB init.

Note: As of November 2026 Railway recommends its new Infrastructure as Code instead of creating `railway.json` for new services. This project uses the Dashboard settings above to avoid deprecated configuration.

## 4. Add persistent PostgreSQL

On Railway's project canvas, **+ New -> Database -> PostgreSQL**. In `tradeverse-backend -> Variables`, create a **reference variable**:

| Variable | Value |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |

Replace `Postgres` if your service has another exact name. Leave the database's **Public Access disabled**. Existing local SQLite history is **not** automatically migrated; this starts a new cloud database. The backend automatically creates missing tables at startup. The code normalizes PostgreSQL URLs to `postgresql+psycopg://` for SQLAlchemy.

## 5. Set Railway backend variables

Configure these in `tradeverse-backend -> Variables`; apply/redeploy staged changes.

| Variable | Value |
|---|---|
| `APP_ENV` | `production` |
| `ALLOW_LIVE_TRADING` | `no` initially; change to `yes` only after real broker and risk checks |
| `ALLOW_MOCK_BROKER` | `no` |
| `SAVE_BROKER_TOKENS` | `no` (recommended cloud default) |
| `FRONTEND_ORIGIN` | `https://mayank-11-mishra.github.io` **without** `/Tradeverse/` |
| `DATABASE_URL` | Reference to your Railway Postgres service |
| `TRADEVERSE_OWNER_PASSWORD_HASH` | Generated scrypt hash from step 2 |
| `TRADEVERSE_SESSION_SECRET` | Generated random secret from step 2 |
| `PUBLIC_API_URL` | Your real Railway HTTPS backend origin from step 6 |

Do not use `APP_LOCAL_TOKEN` as a cloud security mechanism. Do not put any password or secret into a `VITE_` variable. The frontend gets only an owner session token **after password login**, and it is kept in the browser tab.

## 6. Obtain and configure the Railway domain

In `tradeverse-backend -> Settings -> Networking`, select **Generate Domain**. The URL will resemble `https://your-assigned-name.up.railway.app`. Use the **actual generated URL**, without a slash or `/api` suffix.

Set `PUBLIC_API_URL` to this exact URL in backend Variables. This enables HTTPS OAuth callbacks. The backend will intentionally refuse to start without a valid HTTPS origin once `APP_ENV=production`.

A health check should load at `https://YOUR_RAILWAY_DOMAIN/api/health` and return `{ "ok": true, "version": "0.3.0" }`. **The health check does not prove broker login or order execution works.** A direct `GET /api/accounts` without owner credentials should return HTTP 401.

## 7. Configure your GitHub Pages workflow

1. GitHub repository -> **Settings -> Pages -> Source: GitHub Actions**.
2. GitHub repository -> **Settings -> Secrets and variables -> Actions -> Variables**.
3. Create **repository variable** `VITE_API_BASE_URL` with the exact public Railway HTTPS origin (not `/api`, not `127.0.0.1`). This URL is intentionally public.
4. Commit `.github/workflows/deploy.yml` and the frontend changes. The workflow fails clearly if `VITE_API_BASE_URL` is missing or not HTTPS.
5. Go to **Actions -> Deploy TradeVerse Pro Frontend**, run it against `main`, and confirm a green deploy. The workflow uses `npm ci` and produces `frontend/dist`.
6. Open `https://mayank-11-mishra.github.io/Tradeverse/` in a private/incognito window.

The website should first show **TradeVerse owner sign-in**, then **broker selection/login**, then your terminal. The Vite base path `/Tradeverse/` is already set in `frontend/vite.config.ts` for this exact repository name.

## 8. OAuth redirects for brokers

The configured backend OAuth callback URLs are:

```
https://YOUR_RAILWAY_DOMAIN/api/auth/callback/fyers
https://YOUR_RAILWAY_DOMAIN/api/auth/callback/flattrade
https://YOUR_RAILWAY_DOMAIN/api/auth/callback/finvasia
```

Register the exact URLs in the respective broker developer dashboards. The backend now derives the FYERS redirect from `PUBLIC_API_URL`; it no longer assumes localhost. The OAuth popup accepts messages only from the configured backend origin.

**Broker caveat:** Some providers do not echo OAuth state; the app permits only one pending login per such provider and expires pending login after three minutes. Sessions require live broker testing. Zerodha, Upstox, and Groww authentication details and token expiry must be validated separately. No broker credentials belong in Railway's frontend variables.

## 9. Verify the site (without sending a real order)

1. Without signing in, inspect the browser Network tab: API `/api/accounts` must be 401. The public `/api/health` may return 200.
2. Use the owner password from step 2. Verify the backend returns `/api/owner/session` successfully with the session, and a broker login form appears.
3. Open **F12 -> Network**: API requests should target `https://YOUR_RAILWAY_DOMAIN/api/…` and WebSockets should use `wss://YOUR_RAILWAY_DOMAIN/ws/…`.
4. Connect a broker, check real profile, instruments and historical candles. Verify feed status and quotes while the market is open.
5. Check a paper order and stop/restart a paper strategy. Do not activate live orders during the deployment smoke test.
6. Close the owner session; further API requests with its revoked token must be rejected. After refreshing the site it should require owner password again.

## 10. Before LIVE orders or strategies

This patch does **not** certify any broker for live execution. Validate the following with the broker and your account:

- Registered **dedicated/static outbound IP**, as required by applicable broker rules. Upstox explicitly requires a customer-unique registered IP for order traffic. Railway static outbound IPs may be shared; **verify acceptance with the broker before using Railway to route real orders**. A dedicated-IP VPS or a dedicated egress gateway may be necessary.
- Algo registration/tag requirements and permitted exchange order types for that broker. Upstox V3 references `X-Algo-Name` on applicable Algo applications; the existing trading adapters need broker-by-broker certification before live deployment.
- Market streaming and order WebSocket reconnection, orderbook reconciliation, stop/kill switch, margin/risk limits, and strategy behavior after a network or service restart.
- Database backups and adequate CPU/memory/service uptime. An always-on instance with one worker is needed; Railway restarts will stop live strategies and expire in-memory brokerage sessions.
- Test on broker sandbox / smallest permitted paper size first; **never send real market orders just to test deployment**.

When these are verified, the owner may change backend `ALLOW_LIVE_TRADING=yes`, redeploy, then explicitly confirm live trading in the app. Real-money order submission is intentionally not validated or enabled by this packaging operation.

## Troubleshooting

| Symptom | Investigation |
|---|---|
| Railway service fails to start | Check logs. Missing auth secrets, `PUBLIC_API_URL`, or PostgreSQL fail *by design* |
| `401` owner session required | Enter the **owner** password, not broker token |
| Browser CORS or preflight failure | `FRONTEND_ORIGIN` must be `https://mayank-11-mishra.github.io` exactly; restart backend |
| Site loads but API calls go to GitHub Pages | `VITE_API_BASE_URL` missing at Vite build; rerun Pages workflow |
| WebSocket `1008` or reconnects | Expired owner session, invalid/used market socket ticket, invalid Origin, or disconnected broker |
| Broker OAuth returns error | Check HTTPS callback URL registration and broker API entitlement |
| History missing after migration | Old Windows SQLite data isn't copied automatically; broker backfill must run again or data migration is needed |
| `npm ci` fails on GitHub | Confirm `frontend/package-lock.json` is checked in and matches `package.json` |
| `psycopg` or SQLAlchemy startup failure | Verify PostgreSQL URL and Railway builder installed `backend/requirements.txt` |

## Important boundary

This deliverable is a **deployment-hardened source package**. Actual Railway service creation, GitHub pushes, DNS assignment, brokerage credentials, and all live network/real-order tests require your connected accounts and cannot be done by generating this ZIP alone.

### Optional Upstox algo order header

For an Upstox **Algo Trading App** with a registered Algo Name, set private backend variable `UPSTOX_ALGO_NAME` to the exact name configured in Upstox Developer Apps. The adapter now forwards this name as `X-Algo-Name` on order operations. Do not guess a name; follow broker directions and recheck supported order types. This optional header alone does not make the adapter live-order certified.

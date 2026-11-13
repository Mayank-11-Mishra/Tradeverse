# Railway FYERS + Groww dependency isolation

## Why

`fyers-apiv3` and `growwapi` depend on incompatible versions of `aiohttp`.
Installing both into one Python environment fails during pip resolution.
We keep both integrations by running the FYERS **market feed only** in a
separate Python interpreter. FYERS REST login, account APIs, history and orders
continue to run in the main FastAPI process. All other broker adapters are unchanged.

## What to commit

Commit `backend/Dockerfile`, `backend/.dockerignore`,
`backend/requirements.txt`, `backend/requirements-fyers-worker.txt`,
`backend/app/brokers/streams.py`, `backend/app/brokers/fyers_feed_worker.py`,
and `scripts/setup_windows.ps1`.

## Railway configuration

1. Set Railway service **Root Directory** to `/backend`.
2. Select the **Dockerfile** builder (or automatic Dockerfile detection).
3. Remove the old custom build command `pip install -r requirements.txt`
   from the Railway service settings; the Dockerfile installs BOTH environments.
4. Keep one replica, PostgreSQL `DATABASE_URL`, proper production secrets,
   and the existing app security controls.
5. Start Command may be left blank to use the Dockerfile `CMD`.
6. Redeploy the latest GitHub commit (not an old failed build image).
7. Verify the build has installed `/opt/tradeverse-main` and
   `/opt/tradeverse-fyers`. The Docker build executes `pip check` in each
   interpreter, so it will stop if an environment contains conflicts.

The FYERS worker is started on demand when a user subscribes to FYERS live
quotes. It receives the FYERS access token on private subprocess stdin and
streams limited market-data fields back as JSON lines on stdout. It does NOT
place orders or control the API server.

## Local Windows setup

Run `scripts/setup_windows.ps1`. It installs backend requirements into
`.venv` and creates `backend/.fyers-venv` for `fyers-apiv3`.
Do not install the FYERS SDK into `.venv`; this would recreate the conflict.

## Validation boundaries

This resolves the SDK dependency isolation and keeps all six broker adapters.
It does **not** prove FYERS or Groww live WebSocket connections work with real
credentials, nor authorize live trades. Verify the appropriate token, exchange
permissions, feed subscriptions, reconnect behavior, and broker order controls
before using real capital.

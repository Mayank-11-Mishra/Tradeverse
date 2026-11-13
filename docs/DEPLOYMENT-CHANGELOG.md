# Deployment change summary

## Files inspected

- `backend/app/api/server.py`: HTTP guard, broker/OAuth routes, websocket routes, database startup
- `backend/app/brokers/oauth.py`: FYERS callback URL; Flattrade/Shoonya broker authorization
- `backend/app/database/store.py`: SQLAlchemy SQLite/Postgres engine, tables
- `backend/app/core_vault.py`: broker session storage (disabled by default on cloud)
- `frontend/src/App.tsx`: app boot/login gate and legacy settings
- `frontend/src/BrokerGateway.tsx`: broker-first login and OAuth popup
- `frontend/src/api.ts`: API base URL and HTTP request headers
- `frontend/src/marketFeed.ts`: shared market socket and subscriptions
- `frontend/vite.config.ts`: GitHub Pages base path

## Modified / added

1. Owner password login (server-side scrypt verification and signed session), protected API routes and account trading functions; session revocation and startup-invalidated sessions.
2. Short-lived one-use WebSocket tickets in negotiated WebSocket subprotocol, not query strings.
3. Production fails closed unless HTTPS public origins, private PostgreSQL, signing secret and owner password hash are present.
4. Configurable production CORS, OPTIONS preflight, FYERS callback URL, OAuth frontend postMessage validation.
5. React owner-login screen before the existing broker-first screen; no credentials in public Vite build.
6. Public `/api/health` exposes minimal information; authenticated `/api/status` retains operational status.
7. Railway startup recipe, Python runtime marker, GitHub Pages Actions workflow, gitignore to exclude secrets, credential-generation script, deployment instructions.
8. Real broker live-stream SDK requirements for hosted backend; optional Upstox `X-Algo-Name` header from server variable.

## Not performed

- No GitHub push, Railway service creation, DNS change or internet publication (requires user accounts/permissions).
- No real brokerage login or live-money order execution.
- Full Vite bundle on Linux could not be produced from Windows-specific uploaded node_modules; registry installation was unavailable. TypeScript checks succeeded.
- No migration of local SQLite history to Railway PostgreSQL.

## Validation

- 195 backend pytest tests passed, including new production owner security tests.
- 11 frontend utility tests passed.
- TypeScript project type-check passed.
- Real Railway production startup and OAuth callback require your configured environment and broker account.

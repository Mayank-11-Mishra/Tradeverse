# Deploy TradeVerse Pro to Railway + GitHub Pages

Start with [docs/DEPLOY-RAILWAY-GITHUB-PAGES.md](docs/DEPLOY-RAILWAY-GITHUB-PAGES.md).

This archive includes production owner authentication, authorized API/WebSocket access, configurable broker OAuth callbacks, PostgreSQL support, and an Actions workflow. The backend is **not automatically deployed** by unzipping the archive.

**Do not publish** local `.env` files, `.git` history, cached brokerage databases, vaults or access tokens. Keep real-money trading off until broker/API security and compliance are verified.

**Railway SDK conflict:** see `docs/RAILWAY-FYERS-GROWW-DEPENDENCY-FIX.md` for the required Dockerfile builder and isolated FYERS environment.

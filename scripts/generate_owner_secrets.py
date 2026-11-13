"""Generate credentials OFFLINE. Never commit the output or paste it in chat."""
from __future__ import annotations
import getpass
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.api.owner_security import password_hash

password = getpass.getpass('New TradeVerse owner password (minimum 12 characters): ')
confirm = getpass.getpass('Confirm owner password: ')
if password != confirm:
    raise SystemExit('Passwords do not match. No output generated.')
try:
    result = password_hash(password)
except ValueError as exc:
    raise SystemExit(str(exc)) from exc
print('\nCopy ONLY into Railway -> tradeverse-backend -> Variables. NEVER into GitHub:')
print('TRADEVERSE_OWNER_PASSWORD_HASH=' + result)
print('TRADEVERSE_SESSION_SECRET=' + secrets.token_urlsafe(48))

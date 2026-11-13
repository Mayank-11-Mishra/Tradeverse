"""Single-owner API authentication for a self-hosted trading terminal.

Production is fail-closed. Browser sessions use short-lived HS256 JWTs in
sessionStorage, NEVER a permanent API secret compiled into the frontend.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

import jwt
from fastapi import HTTPException

ISSUER = "tradeverse-backend"
AUDIENCE = "tradeverse-owner"
SESSION_SECONDS = 60 * 60 * 4
ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
WS_TICKETS: dict[str, tuple[float,int]] = {}
REVOKED_JTIS: dict[str,int] = {}
SESSION_BOOT_ID = secrets.token_urlsafe(24)


def production() -> bool:
    # Never accidentally expose the local no-password API when deployed to Railway.
    return (os.getenv("APP_ENV", "local").lower() == "production"
            or bool(os.getenv("RAILWAY_SERVICE_ID")))


def allowed_frontend_origins() -> list[str]:
    if not production():
        return ["http://127.0.0.1:5173", "http://localhost:5173"]
    raw = os.getenv("FRONTEND_ORIGIN", "").strip().rstrip("/")
    return [raw] if raw else []


def public_api_url() -> str:
    if not production():
        return os.getenv("PUBLIC_API_URL", "http://127.0.0.1:8000").rstrip("/")
    return os.getenv("PUBLIC_API_URL", "").strip().rstrip("/")


def password_hash(password: str) -> str:
    if not password or len(password) < 12:
        raise ValueError("Owner password must have at least 12 characters")
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + salt.hex() + "$" + derived.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt" or (int(n), int(r), int(p)) != (16384, 8, 1):
            return False
        expected = bytes.fromhex(digest)
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, OverflowError):
        return False


def validate_production_config() -> None:
    if not production():
        return
    if os.getenv("RAILWAY_SERVICE_ID") and os.getenv("APP_ENV", "").lower() != "production":
        raise RuntimeError("Railway deployment must set APP_ENV=production")
    if len(os.getenv("TRADEVERSE_SESSION_SECRET", "")) < 48:
        raise RuntimeError("Production requires TRADEVERSE_SESSION_SECRET (at least 48 random characters)")
    stored = os.getenv("TRADEVERSE_OWNER_PASSWORD_HASH", "")
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        valid_hash = algo == "scrypt" and (n,r,p) == ("16384","8","1") and len(bytes.fromhex(salt)) == 16 and len(bytes.fromhex(digest)) == 32
    except (ValueError, TypeError):
        valid_hash = False
    if not valid_hash:
        raise RuntimeError("Production requires a valid TRADEVERSE_OWNER_PASSWORD_HASH (generate with scripts/generate_owner_secrets.py)")
    origin = os.getenv("FRONTEND_ORIGIN", "").rstrip("/")
    url = public_api_url()
    if urlparse(origin).scheme != "https" or not urlparse(origin).netloc or urlparse(origin).path not in ("", "/"):
        raise RuntimeError("FRONTEND_ORIGIN must be your HTTPS site origin, without /Tradeverse/")
    if urlparse(url).scheme != "https" or not urlparse(url).netloc or urlparse(url).path not in ("", "/"):
        raise RuntimeError("PUBLIC_API_URL must be the HTTPS backend origin")
    if not os.getenv("DATABASE_URL", "").startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("Production requires a persistent PostgreSQL DATABASE_URL")
    if os.getenv("ALLOW_MOCK_BROKER", "no").lower() != "no":
        raise RuntimeError("ALLOW_MOCK_BROKER must be no in production")
    if os.getenv("SAVE_BROKER_TOKENS", "no").lower() == "yes" and not os.getenv("TRADING_VAULT_KEY"):
        raise RuntimeError("SAVE_BROKER_TOKENS=yes needs a persistent TRADING_VAULT_KEY")


def check_login_rate(client: str) -> None:
    now = time.monotonic()
    attempts = ATTEMPTS[client[:128]]
    while attempts and attempts[0] < now - 600:
        attempts.popleft()
    if len(attempts) >= 8:
        raise HTTPException(429, "Too many login attempts. Try again later.")
    attempts.append(now)


def issue_owner_token() -> tuple[str, int]:
    now = int(time.time())
    payload = {"iss": ISSUER, "aud": AUDIENCE, "sub": "owner", "iat": now, "exp": now + SESSION_SECONDS,
               "jti": secrets.token_urlsafe(20), "boot": SESSION_BOOT_ID}
    return jwt.encode(payload, os.environ["TRADEVERSE_SESSION_SECRET"], algorithm="HS256"), SESSION_SECONDS


def verify_owner_token(value: str) -> dict:
    if not value or not production():
        raise HTTPException(401, {"error": "owner_auth_required", "message": "Sign in to TradeVerse first"})
    try:
        decoded = jwt.decode(value, os.environ["TRADEVERSE_SESSION_SECRET"], algorithms=["HS256"],
                             issuer=ISSUER, audience=AUDIENCE, options={"require": ["exp", "iat", "sub", "jti", "boot"]})
        if decoded.get("sub") != "owner" or decoded.get("boot") != SESSION_BOOT_ID:
            raise ValueError("Invalid owner")
        if decoded.get("jti") in REVOKED_JTIS:
            raise ValueError("Owner session revoked")
        return decoded
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(401, {"error": "owner_auth_required", "message": "Owner session expired. Sign in again."}) from exc


def revoke_owner_token(value: str) -> None:
    decoded = verify_owner_token(value)
    now = int(time.time())
    for jti, exp in list(REVOKED_JTIS.items()):
        if exp <= now:
            REVOKED_JTIS.pop(jti, None)
    REVOKED_JTIS[decoded['jti']] = int(decoded['exp'])


def bearer_from_header(value: str) -> str:
    prefix = "Bearer "
    return value[len(prefix):].strip() if value.startswith(prefix) else ""


def issue_ws_ticket(owner_payload: dict) -> str:
    # Single-use and short-lived: avoid sending 4h bearer tokens in WS headers.
    now = time.monotonic()
    for key, (expiry, _) in list(WS_TICKETS.items()):
        if expiry <= now:
            WS_TICKETS.pop(key, None)
    if len(WS_TICKETS) >= 128:
        raise HTTPException(429, 'Too many pending market-stream connections')
    ticket = secrets.token_urlsafe(32)
    WS_TICKETS[ticket] = (now + 30, int(owner_payload['exp']))
    return ticket


def validate_ws_credentials(headers, query_params) -> tuple[bool, int | None]:
    """Returns (allowed, expiry). Production never accepts token query strings."""
    if production():
        if query_params.get("token"):
            return False, None
        protocols = [s.strip() for s in headers.get("sec-websocket-protocol", "").split(",")]
        values = [s[7:] for s in protocols if s.startswith("ticket.")]
        if len(values) != 1 or "tradeverse" not in protocols:
            return False, None
        values_tuple = WS_TICKETS.pop(values[0], None)
        if not values_tuple or values_tuple[0] <= time.monotonic() or values_tuple[1] <= int(time.time()):
            return False, None
        return True, values_tuple[1]
    local_token = os.getenv("APP_LOCAL_TOKEN", "")
    return (not local_token or hmac.compare_digest(query_params.get("token", ""), local_token)), None

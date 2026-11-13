# Groww login repair — November 2026

The Groww connection screen now offers **three distinct authentication methods**. Do not paste an API key into the Access Token field; they are different credentials.

## 1. Current access token

Select **Today's access token** and paste a currently valid Groww Trading API access token from Groww's Trading APIs page. It expires daily at **06:00 IST**. You need an active Groww Trading API subscription. A pasted leading `Bearer ` prefix is accepted.

## 2. API key + secret

Select **API key + secret** and paste the pair generated from Groww Cloud API Keys. Approve the key in Groww Cloud for the current day. The backend generates a SHA-256 checksum from `api_secret + epoch_seconds` and POSTs it to `/v1/token/api/access` using `key_type=approval`. If the token request fails, the UI displays the safe Groww response code and error message (for instance, approval pending). Do not paste an access token in either of the key fields.

## 3. TOTP token + secret/code

In Groww Cloud select **Generate TOTP token**, not **Generate API key**. Use the TOTP token and its Base32 secret. The backend can generate the six-digit TOTP code from the secret, or accept a manually entered six-digit code. Keep your Windows clock synchronized (Settings > Time & language > Date & time > Sync now) because TOTP codes depend on time.

## Test the login

1. Stop and restart **both** frontend and backend after copying the patch.
2. Open the broker login screen and select Groww. Choose **one** authentication method using the dropdown; changing methods clears the other method's fields.
3. Enter credentials, connect, and observe the result. If refused, note only the **HTTP status and Groww error code/message** (such as `Groww HTTP 403: GA005: ...`); never share tokens, keys, secrets, screenshots showing them, or entire HTTP headers.
4. An HTTP 401 indicates an invalid or expired token; 403 may indicate entitlement, authorization, or approval problems. API-key exchanges can also respond with 400 if not approved or the credential type is wrong. Consult the exact Groww-provided code/message.
5. The backend checks `GET /v1/user/detail` after token exchange; only verified accounts unlock the terminal.

**Important:** These flows passed mocked HTTP/unit tests. They have **not** been verified with real Groww credentials or real-money execution. Keep live trading disabled until account-specific verification is complete.

Official docs:
- https://groww.in/trade-api/docs/curl
- https://groww.in/trade-api/docs/python-sdk
- https://groww.in/trade-api/docs/curl/user

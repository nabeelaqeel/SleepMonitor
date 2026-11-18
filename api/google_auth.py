"""Google ID-token verification for /auth/google.

Fetches Google's JWKS (https://www.googleapis.com/oauth2/v3/certs), caches
it with a short TTL, and verifies the RS256 signature plus aud/iss/exp and
the presence of a verified email. Verification is deliberately a plain
function taking the client id as an argument so /auth/google can inject it
as a FastAPI dependency — tests stub it and never touch the network.

Failures split into two types: GoogleTokenError (the token itself is bad —
maps to 401) and GoogleUnavailableError (Google's certificate endpoint is
unreachable — maps to 503, like the unset GOOGLE_CLIENT_ID gate).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

from jose import JWTError, jwt

_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
# Google rotates signing keys; a short cache keeps rotation outages short
# without hammering the endpoint on every login attempt.
_JWKS_TTL_SECONDS = 300.0
_FETCH_TIMEOUT = 5.0

_GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")


class GoogleTokenError(Exception):
    """The ID token is invalid, expired, or fails aud/iss/email checks."""


class GoogleUnavailableError(Exception):
    """Google's certificate endpoint could not be reached."""


_jwks_lock = threading.Lock()
_jwks_cache: list[dict] = []
_jwks_cached_at = 0.0


def _fetch_jwks() -> list[dict]:
    with urllib.request.urlopen(_JWKS_URL, timeout=_FETCH_TIMEOUT) as resp:
        payload = json.loads(resp.read())
    keys = payload.get("keys") or []
    if not keys:
        raise GoogleUnavailableError("Google JWKS response contained no keys")
    return keys


def _get_jwks(force: bool = False) -> list[dict]:
    """Return cached Google signing keys, refreshing past the TTL.

    A fetch failure falls back to the stale cache — previously trusted
    keys still verify tokens signed before rotation; an empty cache
    propagates as GoogleUnavailableError.
    """
    global _jwks_cache, _jwks_cached_at
    with _jwks_lock:
        expired = (time.monotonic() - _jwks_cached_at) > _JWKS_TTL_SECONDS
        if force or not _jwks_cache or expired:
            try:
                _jwks_cache = _fetch_jwks()
                _jwks_cached_at = time.monotonic()
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                if _jwks_cache and not force:
                    return _jwks_cache
                raise GoogleUnavailableError(
                    f"cannot reach Google JWKS: {exc}"
                ) from exc
        return _jwks_cache


def _key_for_kid(keys: list[dict], kid: str | None) -> dict | None:
    if kid is None:
        return None
    for key in keys:
        if key.get("kid") == kid:
            return key
    return None


def verify_google_token(id_token: str, client_id: str) -> dict:
    """Verify a Google ID token and return its claims.

    Raises GoogleTokenError for any problem with the token (bad signature,
    unknown kid, wrong aud/iss, expired, missing/unverified email) and
    GoogleUnavailableError when the JWKS cannot be fetched.
    """
    try:
        kid = jwt.get_unverified_header(id_token).get("kid")
    except JWTError as exc:
        raise GoogleTokenError("unreadable ID token header") from exc

    key = _key_for_kid(_get_jwks(), kid)
    if key is None and kid is not None:
        # Unknown kid usually means a key rotation happened inside the
        # cache TTL — force one refresh before rejecting the token.
        key = _key_for_kid(_get_jwks(force=True), kid)
    if key is None:
        raise GoogleTokenError("ID token signed with an unknown Google key")

    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=_GOOGLE_ISSUERS,
        )
    except JWTError as exc:
        raise GoogleTokenError(f"ID token rejected: {exc}") from exc

    if not claims.get("email"):
        raise GoogleTokenError("ID token carries no email claim")
    if claims.get("email_verified") is False:
        raise GoogleTokenError("ID token email is not verified")
    return claims

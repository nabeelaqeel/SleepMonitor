"""Password hashing (bcrypt) and JWT helpers for the auth API.

Passwords are never stored or transmitted in plaintext: the DB keeps only
a bcrypt hash, and login issues a short-lived HS256 JWT the app stores in
AsyncStorage. The secret comes from JWT_SECRET in .env.development; the
default is for local development only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from api.config import JWT_SECRET

JWT_ALGORITHM = "HS256"
JWT_TTL_HOURS = 12


def hash_password(plain: str) -> str:
    """bcrypt-hash a plaintext password for storage in users.password_hash."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time bcrypt check. Empty/invalid hashes always fail."""
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(user_id: str, role: str) -> str:
    """Issue a signed JWT identifying the logged-in user."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=JWT_TTL_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    """Validate a token and return its claims, or None when invalid/expired."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None

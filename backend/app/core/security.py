"""Password hashing, JWT, and X-Secure-Key validation."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECURE_KEY_BLOCK_SECONDS = 30


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(
    *,
    user_id: int,
    username: str,
    role: str,
    permissions: list[str],
    expires_delta: timedelta | None = None,
) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "permissions": permissions,
        "exp": expire,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )


def _secure_key_for_block(secret: str, block: int) -> str:
    material = f"{secret}:{block}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def generate_secure_key(
    secret: str | None = None,
    *,
    now: float | None = None,
) -> str:
    """Generate X-Secure-Key for the current 30-second block."""
    settings = get_settings()
    key_secret = secret or settings.secret_key_dynamic
    ts = now if now is not None else time.time()
    block = int(ts // SECURE_KEY_BLOCK_SECONDS) * SECURE_KEY_BLOCK_SECONDS
    return _secure_key_for_block(key_secret, block)


def verify_secure_key(
    provided: str | None,
    secret: str | None = None,
    *,
    now: float | None = None,
) -> bool:
    """Accept current block ±1 (30s tolerance each side)."""
    if not provided:
        return False
    settings = get_settings()
    key_secret = secret or settings.secret_key_dynamic
    ts = now if now is not None else time.time()
    current_block = int(ts // SECURE_KEY_BLOCK_SECONDS) * SECURE_KEY_BLOCK_SECONDS
    for offset in (-SECURE_KEY_BLOCK_SECONDS, 0, SECURE_KEY_BLOCK_SECONDS):
        expected = _secure_key_for_block(key_secret, current_block + offset)
        if provided == expected:
            return True
    return False

"""JWT admin auth and API key validation."""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from server import db

JWT_SECRET = os.environ.get("JWT_SECRET", "voice-clone-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24
API_KEY_PREFIX = "sk-voice-"
BOOTSTRAP_PREFIX = "sk-voice-local-"

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def sign_admin_token(username: str, admin_id: str) -> str:
    payload = {
        "sub": admin_id,
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_admin_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


def generate_api_key(*, bootstrap: bool = False) -> tuple[str, str, str]:
    prefix_label = BOOTSTRAP_PREFIX if bootstrap else API_KEY_PREFIX
    raw = prefix_label + secrets.token_urlsafe(24)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    prefix = raw[:20]
    return raw, key_hash, prefix


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def seed_admin() -> None:
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "password")
    if db.admin_count() == 0:
        db.create_admin(username, hash_password(password))
        print(f"[auth] seeded admin user '{username}'", flush=True)


def ensure_bootstrap_key() -> None:
    if db.get_bootstrap_key():
        return
    raw, key_hash, prefix = generate_api_key(bootstrap=True)
    db.create_api_key(
        prefix=prefix,
        key_hash=key_hash,
        raw_key=raw,
        name="local-bootstrap",
        scopes='["speech"]',
        bootstrap=True,
    )
    print("[auth] created bootstrap API key for local UI", flush=True)


def openai_error(message: str, code: str, status: int = 401) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"error": {"message": message, "type": "invalid_request_error", "code": code}},
    )


async def require_api_key(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict:
    raw = ""
    if creds and creds.credentials:
        raw = creds.credentials.strip()
    elif auth := request.headers.get("Authorization", ""):
        if auth.startswith("Bearer "):
            raw = auth[7:].strip()

    if not raw:
        raise openai_error("No API key provided.", "missing_api_key")

    key = db.get_api_key_by_hash(hash_api_key(raw))
    if not key or not key.get("active"):
        raise openai_error("Invalid API key. Generate one at /admin → Keys.", "invalid_api_key")

    db.touch_api_key(key["id"])
    request.state.api_key = key
    return key


async def require_admin(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="Authorization required")
    payload = decode_admin_token(creds.credentials)
    admin = db.get_admin_by_id(payload["sub"])
    if not admin:
        raise HTTPException(status_code=401, detail="Admin not found")
    return admin


def is_local_request(request: Request) -> bool:
    client = request.client
    if not client:
        return False
    host = client.host
    if host in {"127.0.0.1", "::1", "localhost"}:
        return True
    if host.startswith("10.") or host.startswith("192.168."):
        return True
    if host.startswith("172."):
        parts = host.split(".")
        if len(parts) == 4:
            try:
                second = int(parts[1])
                if 16 <= second <= 31:
                    return True
            except ValueError:
                pass
    return False

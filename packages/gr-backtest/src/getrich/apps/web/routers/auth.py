"""认证路由：POST /v1/auth/login, POST /v1/auth/register, POST /v1/auth/refresh。"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone as tz

import bcrypt
from fastapi import APIRouter, Depends
from psycopg import AsyncConnection
from pydantic import BaseModel, Field

from getrich.apps.web.auth import create_token
from getrich.apps.web.deps import get_db, request_id
from getrich.apps.web.errors import BadRequest, Unauthorized
from getrich.apps.web.response import success
from getrich.config import settings


router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(default="", max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Refresh token helpers (stdlib SHA-256 hashing, keep raw tokens off disk)
# ---------------------------------------------------------------------------


def _hash_token(token: str) -> str:
    """SHA-256 hex digest — stored in DB, never the raw token."""
    return hashlib.sha256(token.encode()).hexdigest()


async def create_refresh_token(user_id: str, db: AsyncConnection) -> str:
    """Generate a random refresh token, store its hash, return the raw token."""
    raw = secrets.token_hex(32)  # 64-char hex string
    token_hash = _hash_token(raw)
    expire_seconds = settings.web.jwt_refresh_expire_hours * 3600
    async with db.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
            VALUES (%(user_id)s, %(token_hash)s, NOW() + INTERVAL '1 second' * %(expire_seconds)s)
            """,
            {
                "user_id": user_id,
                "token_hash": token_hash,
                "expire_seconds": expire_seconds,
            },
        )
        await db.commit()
    return raw


async def revoke_refresh_tokens(user_id: str, db: AsyncConnection) -> None:
    """Delete all refresh tokens for a user (used on logout / rotation / revoke)."""
    async with db.cursor() as cur:
        await cur.execute(
            "DELETE FROM refresh_tokens WHERE user_id = %(user_id)s",
            {"user_id": user_id},
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Login helper: try user_auth first, fallback to users.email
# ---------------------------------------------------------------------------


async def _authenticate_via_user_auth(db: AsyncConnection, email: str) -> dict | None:
    """Query ``user_auth`` for email+password login.

    Returns a dict with keys ``user_id``, ``credential``, ``name`` when a row
    with a non-NULL credential exists. Returns ``None`` when the email has no
    password-based auth (e.g. OAuth-only user).
    """
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT ua.user_id, ua.credential,
                   COALESCE(u.display_name, u.name, '') AS name
            FROM user_auth ua
            JOIN users u ON u.id = ua.user_id
            WHERE ua.auth_type = 'email'
              AND ua.identifier = %(email)s
              AND ua.credential IS NOT NULL
            """,
            {"email": email},
        )
        return await cur.fetchone()


async def _authenticate_via_users_fallback(db: AsyncConnection, email: str) -> dict | None:
    """Fallback: query ``users.email`` for dev accounts (legacy)."""
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT id, email, password, name FROM users"
            " WHERE email = %(email)s AND is_active = TRUE"
            " AND password IS NOT NULL",
            {"email": email},
        )
        return await cur.fetchone()


# ---------------------------------------------------------------------------
# POST /v1/auth/login
# ---------------------------------------------------------------------------


@router.post("/login")
async def login(
    body: LoginRequest,
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    """Authenticate with email + password, return a JWT access token.

    Two-path resolution:
    1. Primary: ``user_auth`` table (production schema).
    2. Fallback: ``users.email`` (legacy dev accounts via ALTER-added columns).
    """
    email_normalized = body.email.strip().lower()
    password_bytes = body.password.encode("utf-8")

    # Path 1: user_auth (production)
    auth_row = await _authenticate_via_user_auth(db, email_normalized)

    if auth_row is not None:
        # Verify password against bcrypt hash in user_auth.credential
        hash_bytes = auth_row["credential"].encode("utf-8")
        if not bcrypt.checkpw(password_bytes, hash_bytes):
            raise Unauthorized("invalid email or password")

        user_id = str(auth_row["user_id"])
        name = str(auth_row["name"])
        token = create_token(
            {"sub": user_id, "email": email_normalized, "name": name},
            settings.web.jwt_secret,
            expires_in=settings.web.jwt_expire_minutes * 60,
        )
        refresh_token_val = await create_refresh_token(user_id, db)

        return success(
            {
                "access_token": token,
                "refresh_token": refresh_token_val,
                "token_type": "bearer",
                "user": {
                    "id": user_id,
                    "email": email_normalized,
                    "name": name,
                },
            },
            rid,
        )

    # Path 2: users.email fallback (legacy dev accounts)
    user_row = await _authenticate_via_users_fallback(db, email_normalized)
    if user_row is None:
        raise Unauthorized("invalid email or password")

    hash_bytes = user_row["password"].encode("utf-8")
    if not bcrypt.checkpw(password_bytes, hash_bytes):
        raise Unauthorized("invalid email or password")

    user_id = str(user_row["id"])
    token = create_token(
        {"sub": user_id, "email": user_row["email"], "name": user_row["name"]},
        settings.web.jwt_secret,
        expires_in=settings.web.jwt_expire_minutes * 60,
    )
    refresh_token_val = await create_refresh_token(user_id, db)

    return success(
        {
            "access_token": token,
            "refresh_token": refresh_token_val,
            "token_type": "bearer",
            "user": {
                "id": user_id,
                "email": user_row["email"],
                "name": user_row["name"],
            },
        },
        rid,
    )


# ---------------------------------------------------------------------------
# POST /v1/auth/register
# ---------------------------------------------------------------------------


@router.post("/register")
async def register(
    body: RegisterRequest,
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    """Register a new user account. Returns a JWT so the user is logged in immediately.

    Writes to both ``users`` (profile) and ``user_auth`` (credential) tables.
    """
    email_lower = body.email.strip().lower()

    async with db.cursor() as cur:
        # Check uniqueness in user_auth (primary auth source)
        await cur.execute(
            "SELECT id FROM user_auth WHERE auth_type = 'email' AND identifier = %(email)s",
            {"email": email_lower},
        )
        if await cur.fetchone() is not None:
            raise BadRequest("an account with this email already exists")

        # Also check users.email fallback (legacy dev accounts)
        await cur.execute(
            "SELECT id FROM users WHERE email = %(email)s",
            {"email": email_lower},
        )
        if await cur.fetchone() is not None:
            raise BadRequest("an account with this email already exists")

        # Hash password
        password_hash = bcrypt.hashpw(
            body.password.encode("utf-8"),
            bcrypt.gensalt(rounds=12),
        ).decode("utf-8")

        # Insert into users (profile)
        await cur.execute(
            """
            INSERT INTO users (name)
            VALUES (%(name)s)
            RETURNING id
            """,
            {"name": body.name.strip()},
        )
        new_user = await cur.fetchone()
        user_id = str(new_user["id"])

        # Insert into user_auth (credential)
        await cur.execute(
            """
            INSERT INTO user_auth (user_id, auth_type, identifier, credential, verified)
            VALUES (%(user_id)s, 'email', %(email)s, %(credential)s, TRUE)
            """,
            {
                "user_id": user_id,
                "email": email_lower,
                "credential": password_hash,
            },
        )
        await db.commit()

    # Generate tokens (auto-login)
    token = create_token(
        {"sub": user_id, "email": email_lower, "name": body.name.strip()},
        settings.web.jwt_secret,
        expires_in=settings.web.jwt_expire_minutes * 60,
    )
    refresh_token_val = await create_refresh_token(user_id, db)

    return success(
        {
            "access_token": token,
            "refresh_token": refresh_token_val,
            "token_type": "bearer",
            "user": {
                "id": user_id,
                "email": email_lower,
                "name": body.name.strip(),
            },
        },
        rid,
        message="registration successful",
    )


# ---------------------------------------------------------------------------
# POST /v1/auth/refresh
# ---------------------------------------------------------------------------


@router.post("/refresh")
async def refresh(
    body: RefreshRequest,
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    """Exchange a valid refresh token for a new access token + rotated refresh token."""
    token_hash = _hash_token(body.refresh_token)

    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT rt.id AS rt_id, rt.expires_at,
                   u.id AS user_id,
                   COALESCE(u.display_name, u.name, '') AS name
            FROM refresh_tokens rt
            JOIN users u ON u.id = rt.user_id
            WHERE rt.token_hash = %(token_hash)s
              AND u.is_active = TRUE
            """,
            {"token_hash": token_hash},
        )
        row = await cur.fetchone()

    if row is None:
        raise Unauthorized("invalid or expired refresh token")

    # Check expiry
    if row["expires_at"].replace(tzinfo=tz.utc) < datetime.now(tz.utc):
        raise Unauthorized("refresh token expired")

    user_id = str(row["user_id"])

    # Token rotation: revoke all existing refresh tokens, then issue new pair
    await revoke_refresh_tokens(user_id, db)

    access_token = create_token(
        {"sub": user_id, "name": row["name"]},
        settings.web.jwt_secret,
        expires_in=settings.web.jwt_expire_minutes * 60,
    )
    new_refresh_token = await create_refresh_token(user_id, db)

    return success(
        {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer",
            "user": {
                "id": user_id,
                "name": row["name"],
            },
        },
        rid,
    )

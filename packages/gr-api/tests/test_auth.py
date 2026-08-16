"""Tests for auth endpoints (login, register, refresh)."""

from __future__ import annotations

from datetime import datetime, timezone as tz

import bcrypt
from gr_api.errors import BadRequest, Unauthorized
from gr_api.routers.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    login,
    refresh,
    register,
)


class _FakeCursor:
    def __init__(self, fetchone_results: list[dict | None]) -> None:
        self._results = fetchone_results
        self.executed: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, sql, params=None):
        self.executed.append((sql, params))

    async def fetchone(self):
        return self._results.pop(0) if self._results else None


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    async def commit(self):
        self.committed = True


def _run(coro):
    import asyncio

    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

# bcrypt hash for "password" — same as the demo user seed in 003_users.sql
_BCRYPT_HASH = "$2b$12$c3lZxMMPPPn40Pg104gng.47ED584SS/eWbayiO7NoBLKtjKXUamK"


class TestLogin:
    def test_login_success_via_user_auth(self) -> None:
        """Email found in user_auth → bcrypt check → JWT returned."""
        # user_auth query returns a row; no fallback needed
        cur = _FakeCursor(
            [
                {
                    "user_id": "user-uuid-1",
                    "credential": _BCRYPT_HASH,
                    "name": "Demo User",
                },
            ]
        )
        conn = _FakeConn(cur)

        body = LoginRequest(email="demo@getrich.io", password="password")
        result = _run(login(body=body, db=conn, rid="rid-1"))

        assert result["code"] == 0
        data = result["data"]
        assert data["token_type"] == "bearer"
        assert "access_token" in data
        parts = data["access_token"].split(".")
        assert len(parts) == 3
        assert data["user"]["id"] == "user-uuid-1"
        assert data["user"]["email"] == "demo@getrich.io"
        assert data["user"]["name"] == "Demo User"

        # Verify the user_auth query used the correct email
        select_params = cur.executed[0][1]
        assert select_params["email"] == "demo@getrich.io"
        assert "user_auth" in cur.executed[0][0].lower()

    def test_login_success_via_users_fallback(self) -> None:
        """Email NOT in user_auth but found in users.email → JWT returned (legacy)."""
        # user_auth returns None → fallback to users.email returns a row
        cur = _FakeCursor(
            [
                None,  # user_auth query → no row
                {
                    "id": "user-uuid-1",
                    "email": "demo@getrich.io",
                    "password": _BCRYPT_HASH,
                    "name": "Demo User",
                },
            ]
        )
        conn = _FakeConn(cur)

        body = LoginRequest(email="demo@getrich.io", password="password")
        result = _run(login(body=body, db=conn, rid="rid-1"))

        assert result["code"] == 0
        data = result["data"]
        assert data["token_type"] == "bearer"
        assert "access_token" in data
        assert data["user"]["id"] == "user-uuid-1"
        assert data["user"]["email"] == "demo@getrich.io"
        assert data["user"]["name"] == "Demo User"

        # First query was user_auth; second was users.email fallback
        assert "user_auth" in cur.executed[0][0].lower()
        assert "from users" in cur.executed[1][0].lower()

    def test_login_wrong_password(self) -> None:
        """Correct email but wrong password → Unauthorized (user_auth path)."""
        cur = _FakeCursor(
            [
                {
                    "user_id": "user-uuid-1",
                    "credential": _BCRYPT_HASH,
                    "name": "Demo User",
                },
            ]
        )
        conn = _FakeConn(cur)

        body = LoginRequest(email="demo@getrich.io", password="WrongPassword")
        try:
            _run(login(body=body, db=conn, rid="rid-1"))
            raise AssertionError("expected Unauthorized")
        except Unauthorized as e:
            assert "invalid email or password" in e.message.lower()

    def test_login_wrong_password_fallback(self) -> None:
        """Correct email but wrong password → Unauthorized (fallback path)."""
        cur = _FakeCursor(
            [
                None,  # user_auth → no row
                {
                    "id": "user-uuid-1",
                    "email": "demo@getrich.io",
                    "password": _BCRYPT_HASH,
                    "name": "Demo User",
                },
            ]
        )
        conn = _FakeConn(cur)

        body = LoginRequest(email="demo@getrich.io", password="WrongPassword")
        try:
            _run(login(body=body, db=conn, rid="rid-1"))
            raise AssertionError("expected Unauthorized")
        except Unauthorized as e:
            assert "invalid email or password" in e.message.lower()

    def test_login_inactive_user(self) -> None:
        """Inactive user → no row from either query → Unauthorized."""
        cur = _FakeCursor([None, None])  # user_auth + fallback both return nothing
        conn = _FakeConn(cur)

        body = LoginRequest(email="inactive@test.com", password="password")
        try:
            _run(login(body=body, db=conn, rid="rid-1"))
            raise AssertionError("expected Unauthorized")
        except Unauthorized as e:
            assert "invalid email or password" in e.message.lower()

    def test_login_nonexistent_email(self) -> None:
        """Email not found → Unauthorized."""
        cur = _FakeCursor([None, None])
        conn = _FakeConn(cur)

        body = LoginRequest(email="nobody@test.com", password="password")
        try:
            _run(login(body=body, db=conn, rid="rid-1"))
            raise AssertionError("expected Unauthorized")
        except Unauthorized as e:
            assert "invalid email or password" in e.message.lower()

    def test_login_normalizes_email_user_auth(self) -> None:
        """Uppercase/whitespace email → normalized to lowercase in user_auth query."""
        cur = _FakeCursor(
            [
                {
                    "user_id": "user-uuid-1",
                    "credential": _BCRYPT_HASH,
                    "name": "Demo User",
                },
            ]
        )
        conn = _FakeConn(cur)

        body = LoginRequest(email="  DEMO@GETRICH.IO  ", password="password")
        result = _run(login(body=body, db=conn, rid="rid-1"))

        assert result["code"] == 0
        select_params = cur.executed[0][1]
        assert select_params["email"] == "demo@getrich.io"

    def test_login_normalizes_email_fallback(self) -> None:
        """Uppercase/whitespace email → normalized in fallback query."""
        cur = _FakeCursor(
            [
                None,  # user_auth → no row
                {
                    "id": "user-uuid-1",
                    "email": "demo@getrich.io",
                    "password": _BCRYPT_HASH,
                    "name": "Demo User",
                },
            ]
        )
        conn = _FakeConn(cur)

        body = LoginRequest(email="  DEMO@GETRICH.IO  ", password="password")
        result = _run(login(body=body, db=conn, rid="rid-1"))

        assert result["code"] == 0
        # user_auth query used normalized email
        assert cur.executed[0][1]["email"] == "demo@getrich.io"
        # fallback query also used normalized email
        assert cur.executed[1][1]["email"] == "demo@getrich.io"

    def test_login_oauth_user_without_password(self) -> None:
        """Email in user_auth but credential=NULL → fallback → no row → Unauthorized."""
        cur = _FakeCursor(
            [
                None,  # user_auth WHERE credential IS NOT NULL → no row
                None,  # users.email fallback → no row
            ]
        )
        conn = _FakeConn(cur)

        body = LoginRequest(email="oauth@test.com", password="password")
        try:
            _run(login(body=body, db=conn, rid="rid-1"))
            raise AssertionError("expected Unauthorized")
        except Unauthorized as e:
            assert "invalid email or password" in e.message.lower()


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


class TestRegister:
    def test_creates_user_and_returns_token(self, monkeypatch) -> None:
        """Happy path: new email → user inserted in users + user_auth, JWT returned."""
        # Three queries:
        # 1. user_auth uniqueness check → None
        # 2. users.email uniqueness check → None
        # 3. INSERT INTO users → RETURNING id
        # (INSERT INTO user_auth doesn't need a fetchone)
        cur = _FakeCursor(
            [
                None,  # user_auth uniqueness → no conflict
                None,  # users.email uniqueness → no conflict
                {"id": "user-uuid-1"},  # INSERT INTO users RETURNING id
            ]
        )
        conn = _FakeConn(cur)

        body = RegisterRequest(
            email="alice@test.com",
            password="Str0ngPass!",
            name="Alice",
        )
        result = _run(register(body=body, db=conn, rid="rid-1"))

        assert result["code"] == 0
        assert result["message"] == "registration successful"
        data = result["data"]
        assert data["token_type"] == "bearer"
        assert "access_token" in data
        assert data["user"]["id"] == "user-uuid-1"
        assert data["user"]["email"] == "alice@test.com"
        assert data["user"]["name"] == "Alice"
        assert conn.committed

        # Check INSERT INTO users was called with correct args
        insert_users = cur.executed[2]
        assert "INSERT INTO users" in insert_users[0]
        assert insert_users[1]["name"] == "Alice"

        # Check INSERT INTO user_auth was called with correct args
        insert_auth = cur.executed[3]
        assert "INSERT INTO user_auth" in insert_auth[0]
        assert "'email'" in insert_auth[0]  # auth_type is a SQL literal, not a named param
        assert insert_auth[1]["email"] == "alice@test.com"
        assert insert_auth[1]["credential"].startswith("$2b$12$")

    def test_rejects_duplicate_email_in_user_auth(self) -> None:
        """Duplicate email in user_auth → BadRequest."""
        cur = _FakeCursor(
            [
                {"id": 1},  # user_auth uniqueness check → conflict
            ]
        )
        conn = _FakeConn(cur)

        body = RegisterRequest(
            email="alice@test.com",
            password="Str0ngPass!",
            name="Alice",
        )
        try:
            _run(register(body=body, db=conn, rid="rid-1"))
            raise AssertionError("expected BadRequest")
        except BadRequest as e:
            assert "already exists" in e.message.lower()
        assert not conn.committed

    def test_rejects_duplicate_email_in_users(self) -> None:
        """Duplicate email in users.email (legacy) → BadRequest."""
        cur = _FakeCursor(
            [
                None,  # user_auth uniqueness → no conflict
                {"id": "existing-id"},  # users.email uniqueness → conflict
            ]
        )
        conn = _FakeConn(cur)

        body = RegisterRequest(
            email="alice@test.com",
            password="Str0ngPass!",
            name="Alice",
        )
        try:
            _run(register(body=body, db=conn, rid="rid-1"))
            raise AssertionError("expected BadRequest")
        except BadRequest as e:
            assert "already exists" in e.message.lower()
        assert not conn.committed

    def test_normalizes_email_to_lowercase(self) -> None:
        """Uppercase email → stored as lowercase."""
        cur = _FakeCursor(
            [
                None,  # user_auth uniqueness
                None,  # users.email uniqueness
                {"id": "user-uuid-1"},  # INSERT INTO users RETURNING id
            ]
        )
        conn = _FakeConn(cur)

        body = RegisterRequest(
            email="ALICE@TEST.COM",
            password="Str0ngPass!",
            name="Alice",
        )
        result = _run(register(body=body, db=conn, rid="rid-1"))

        assert result["data"]["user"]["email"] == "alice@test.com"

        # user_auth uniqueness check used lowercase
        assert cur.executed[0][1]["email"] == "alice@test.com"
        # user_auth INSERT used lowercase
        insert_auth = cur.executed[3]
        assert insert_auth[1]["email"] == "alice@test.com"

    def test_trims_name_and_email(self) -> None:
        """Whitespace in name/email → trimmed."""
        cur = _FakeCursor(
            [
                None,  # user_auth uniqueness
                None,  # users.email uniqueness
                {"id": "u-1"},  # INSERT INTO users RETURNING id
            ]
        )
        conn = _FakeConn(cur)

        body = RegisterRequest(
            email="  bob@test.com  ",
            password="Str0ngPass!",
            name="  Bob  ",
        )
        result = _run(register(body=body, db=conn, rid="rid-1"))
        assert result["data"]["user"]["name"] == "Bob"
        insert_users = cur.executed[2]
        assert insert_users[1]["name"] == "Bob"

    def test_empty_name_allowed(self) -> None:
        """Register with no name → stored as empty string."""
        cur = _FakeCursor(
            [
                None,  # user_auth uniqueness
                None,  # users.email uniqueness
                {"id": "u-1"},  # INSERT INTO users RETURNING id
            ]
        )
        conn = _FakeConn(cur)

        body = RegisterRequest(
            email="anon@test.com",
            password="Str0ngPass!",
        )
        result = _run(register(body=body, db=conn, rid="rid-1"))
        assert result["data"]["user"]["name"] == ""

    def test_password_is_hashed(self) -> None:
        """Verify the stored password is a bcrypt hash, not plaintext."""
        cur = _FakeCursor(
            [
                None,  # user_auth uniqueness
                None,  # users.email uniqueness
                {"id": "u-1"},  # INSERT INTO users RETURNING id
            ]
        )
        conn = _FakeConn(cur)

        body = RegisterRequest(
            email="eve@test.com",
            password="Secret123",
            name="Eve",
        )
        _run(register(body=body, db=conn, rid="rid-1"))

        # Check INSERT INTO user_auth credential is bcrypt
        insert_auth = cur.executed[3]
        stored = insert_auth[1]["credential"]
        assert stored.startswith("$2b$12$")
        assert bcrypt.checkpw(b"Secret123", stored.encode("utf-8"))


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


class TestRefresh:
    def test_refresh_valid_token(self) -> None:
        """Valid refresh token → new access_token + rotated refresh_token returned."""
        future_expiry = datetime(2099, 1, 1, tzinfo=tz.utc)
        cur = _FakeCursor(
            [
                {
                    "rt_id": "rt-uuid-1",
                    "expires_at": future_expiry,
                    "user_id": "user-uuid-1",
                    "name": "Demo User",
                },
            ]
        )
        conn = _FakeConn(cur)

        body = RefreshRequest(refresh_token="some-raw-refresh-token")
        result = _run(refresh(body=body, db=conn, rid="rid-1"))

        assert result["code"] == 0
        data = result["data"]
        assert data["token_type"] == "bearer"
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["refresh_token"] != "some-raw-refresh-token"  # rotated
        assert data["user"]["id"] == "user-uuid-1"
        assert data["user"]["name"] == "Demo User"

        # Verify the SELECT used SHA-256 hash of the input token
        import hashlib

        select_params = cur.executed[0][1]
        expected_hash = hashlib.sha256(b"some-raw-refresh-token").hexdigest()
        assert select_params["token_hash"] == expected_hash

        # Verify DELETE (revoke old tokens) was executed
        assert any("DELETE FROM refresh_tokens" in sql for sql, _ in cur.executed)

        # Verify INSERT (new refresh token) was executed
        assert any("INSERT INTO refresh_tokens" in sql for sql, _ in cur.executed)

    def test_refresh_invalid_token(self) -> None:
        """Token hash not found in DB → Unauthorized."""
        cur = _FakeCursor([None])  # SELECT returns nothing
        conn = _FakeConn(cur)

        body = RefreshRequest(refresh_token="bogus-token")
        try:
            _run(refresh(body=body, db=conn, rid="rid-1"))
            raise AssertionError("expected Unauthorized")
        except Unauthorized as e:
            assert "invalid or expired" in e.message.lower()

    def test_refresh_expired_token(self) -> None:
        """Token exists but expires_at is in the past → Unauthorized."""
        past_expiry = datetime(2020, 1, 1, tzinfo=tz.utc)
        cur = _FakeCursor(
            [
                {
                    "rt_id": "rt-uuid-1",
                    "expires_at": past_expiry,
                    "user_id": "user-uuid-1",
                    "name": "Demo User",
                },
            ]
        )
        conn = _FakeConn(cur)

        body = RefreshRequest(refresh_token="expired-token")
        try:
            _run(refresh(body=body, db=conn, rid="rid-1"))
            raise AssertionError("expected Unauthorized")
        except Unauthorized as e:
            assert "expired" in e.message.lower()

    def test_refresh_inactive_user(self) -> None:
        """User is_active=FALSE → JOIN returns no row → Unauthorized."""
        cur = _FakeCursor([None])  # JOIN fails due to is_active filter
        conn = _FakeConn(cur)

        body = RefreshRequest(refresh_token="inactive-user-token")
        try:
            _run(refresh(body=body, db=conn, rid="rid-1"))
            raise AssertionError("expected Unauthorized")
        except Unauthorized as e:
            assert "invalid or expired" in e.message.lower()

    def test_login_returns_refresh_token(self) -> None:
        """Login response now includes a refresh_token field (user_auth path)."""
        cur = _FakeCursor(
            [
                {
                    "user_id": "user-uuid-1",
                    "credential": _BCRYPT_HASH,
                    "name": "Demo User",
                },
            ]
        )
        conn = _FakeConn(cur)

        body = LoginRequest(email="demo@getrich.io", password="password")
        result = _run(login(body=body, db=conn, rid="rid-1"))

        assert "refresh_token" in result["data"]
        assert len(result["data"]["refresh_token"]) == 64  # secrets.token_hex(32)
        assert "access_token" in result["data"]
        assert "insert into refresh_tokens" in cur.executed[-1][0].lower()

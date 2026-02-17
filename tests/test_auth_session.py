from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from addon.src.auth import AuthSession, PlaywrightAuthClient
from addon.src.session_manager import (Credentials, CredentialsProvider,
                                       SessionState, SessionStore)


class DummyCredentialsProvider(CredentialsProvider):
    def __init__(self, email: str = "user@example.com", password: str = "secret") -> None:
        self._credentials = Credentials(email=email, password=password)

    def get_credentials(self) -> Credentials:
        return self._credentials


@pytest.mark.asyncio
async def test_login_persists_cookies(tmp_path) -> None:
    session_path = tmp_path / "session.json"
    store = SessionStore(path=session_path, ttl=timedelta(hours=1))
    creds = DummyCredentialsProvider()

    async def login_runner(_: Credentials):
        return [
            {"name": "JSESSIONID", "value": "abc", "expires": 0},
            {"name": "TGC", "value": "def", "expires": 0},
        ]

    client = PlaywrightAuthClient(creds, store, login_runner=login_runner)
    session = await client.ensure_session()

    assert isinstance(session, AuthSession)
    assert session.reused is False
    assert session_path.exists()

    payload = json.loads(session_path.read_text(encoding="utf-8"))
    assert payload["cookies"][0]["name"] == "JSESSIONID"


@pytest.mark.asyncio
async def test_restore_session_avoids_login(tmp_path) -> None:
    session_path = tmp_path / "session.json"
    store = SessionStore(path=session_path, ttl=timedelta(hours=6))
    now = datetime.now(tz=timezone.utc)
    state = SessionState(
        cookies=[{"name": "JSESSIONID", "value": "abc", "expires": 0}],
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    expires_at = state.expires_at or now + timedelta(hours=1)
    session_path.write_text(
        json.dumps(
            {
                "cookies": state.cookies,
                "created_at": state.created_at.isoformat(),
                "expires_at": expires_at.isoformat(),
            }
        ),
        encoding="utf-8",
    )

    async def login_runner(_: Credentials):
        raise AssertionError("login should not be called")

    client = PlaywrightAuthClient(DummyCredentialsProvider(), store, login_runner=login_runner)
    session = await client.ensure_session()

    assert session.reused is True
    assert session.cookies[0]["name"] == "JSESSIONID"


@pytest.mark.asyncio
async def test_expired_session_triggers_login(tmp_path) -> None:
    session_path = tmp_path / "session.json"
    store = SessionStore(path=session_path, ttl=timedelta(minutes=30))
    past = datetime.now(tz=timezone.utc) - timedelta(hours=2)
    session_path.write_text(
        json.dumps(
            {
                "cookies": [{"name": "DISSESSION", "value": "old", "expires": 0}],
                "created_at": past.isoformat(),
                "expires_at": (past + timedelta(minutes=10)).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    called = {"count": 0}

    async def login_runner(_: Credentials):
        called["count"] += 1
        return [{"name": "DISSESSION", "value": "new", "expires": 0}]

    client = PlaywrightAuthClient(DummyCredentialsProvider(), store, login_runner=login_runner)
    session = await client.ensure_session()

    assert called["count"] == 1
    assert session.reused is False
    assert session.cookies[0]["value"] == "new"

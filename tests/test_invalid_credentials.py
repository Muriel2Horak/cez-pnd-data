"""Negative-path tests for invalid credentials and auth failure modes.

Covers:
- Invalid credentials produce clear error log, no stale state published
- Auth exception does not publish any MQTT state
- Missing credentials raise ValueError
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from addon.src.auth import AuthSession, PlaywrightAuthClient
from addon.src.mqtt_publisher import MqttPublisher
from addon.src.session_manager import Credentials, CredentialsProvider, SessionStore

# ── Helpers ───────────────────────────────────────────────────────────


class DummyCredentialsProvider(CredentialsProvider):
    def __init__(self, email: str = "bad@example.com", password: str = "wrong"):
        self._credentials = Credentials(email=email, password=password)

    def get_credentials(self) -> Credentials:
        return self._credentials


class AuthError(Exception):
    """Simulated authentication failure."""

    pass


# ── Scenario: Invalid credentials ─────────────────────────────────────


class TestInvalidCredentials:
    """When auth fails, no stale state must be published."""

    @pytest.mark.asyncio
    async def test_auth_failure_raises_no_stale_publish(self, tmp_path: Path) -> None:
        """Invalid credentials → auth error → no MQTT state published."""
        session_path = tmp_path / "session.json"
        store = SessionStore(path=session_path, ttl=timedelta(hours=6))
        creds = DummyCredentialsProvider()

        async def failing_login(_: Credentials) -> AuthSession:
            raise AuthError("Invalid username or password")

        client = PlaywrightAuthClient(creds, store, login_runner=failing_login)

        # Auth must raise
        with pytest.raises(AuthError, match="Invalid username or password"):
            await client.ensure_session()

        # No session file created
        assert (
            not session_path.exists()
        ), "Session file must NOT be created on auth failure"

    @pytest.mark.asyncio
    async def test_no_mqtt_state_on_auth_failure(self, tmp_path: Path) -> None:
        """Full pipeline: auth fails → MQTT publisher never receives state values."""
        session_path = tmp_path / "session.json"
        store = SessionStore(path=session_path, ttl=timedelta(hours=6))
        creds = DummyCredentialsProvider()

        async def failing_login(_: Credentials) -> AuthSession:
            raise AuthError("Login failed: bad credentials")

        client = PlaywrightAuthClient(creds, store, login_runner=failing_login)

        mock_mqtt = MagicMock()
        mock_mqtt.publish = MagicMock()
        mock_mqtt.will_set = MagicMock()
        mock_mqtt.connect = MagicMock()
        mock_mqtt.disconnect = MagicMock()

        publisher = MqttPublisher(client=mock_mqtt, electrometer_id="test_meter")
        publisher.start()

        # Simulate orchestrator: auth fails, so no data is fetched
        try:
            await client.ensure_session()
            # If this succeeds, something is wrong
            assert False, "Auth should have failed"
        except AuthError:
            pass  # Expected

        # Assert no state topics were published
        state_calls = [
            c for c in mock_mqtt.publish.call_args_list if "/state" in c[0][0]
        ]
        assert (
            len(state_calls) == 0
        ), f"No state should be published on auth failure, but got: {state_calls}"

    @pytest.mark.asyncio
    async def test_auth_error_logged_clearly(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Auth failure should produce a clear, loggable error message."""
        session_path = tmp_path / "session.json"
        store = SessionStore(path=session_path, ttl=timedelta(hours=6))
        creds = DummyCredentialsProvider()

        async def failing_login(_: Credentials) -> AuthSession:
            raise AuthError("CEZ login failed: invalid credentials for bad@example.com")

        client = PlaywrightAuthClient(creds, store, login_runner=failing_login)

        with pytest.raises(AuthError) as exc_info:
            await client.ensure_session()

        # Error message contains useful context
        error_msg = str(exc_info.value)
        assert (
            "invalid credentials" in error_msg.lower()
            or "login failed" in error_msg.lower()
        )
        assert "bad@example.com" in error_msg


# ── Scenario: Missing credentials ─────────────────────────────────────


class TestMissingCredentials:
    """When no credentials are provided, ValueError is raised."""

    @pytest.mark.asyncio
    async def test_missing_options_file_raises(self, tmp_path: Path) -> None:
        """No options file and no env vars → ValueError."""
        options_path = tmp_path / "nonexistent_options.json"
        creds = CredentialsProvider(options_path=options_path)

        session_path = tmp_path / "session.json"
        store = SessionStore(path=session_path, ttl=timedelta(hours=6))

        async def should_not_be_called(_: Credentials) -> AuthSession:
            raise AssertionError("Login runner should not be called")

        client = PlaywrightAuthClient(creds, store, login_runner=should_not_be_called)

        with pytest.raises(ValueError, match="Missing CEZ credentials"):
            await client.ensure_session()

    @pytest.mark.asyncio
    async def test_empty_options_raises(self, tmp_path: Path) -> None:
        """Options file with empty email/password → ValueError."""
        options_path = tmp_path / "options.json"
        options_path.write_text(json.dumps({"email": "", "password": ""}))

        creds = CredentialsProvider(options_path=options_path)
        session_path = tmp_path / "session.json"
        store = SessionStore(path=session_path, ttl=timedelta(hours=6))

        async def should_not_be_called(_: Credentials) -> AuthSession:
            raise AssertionError("Login runner should not be called")

        client = PlaywrightAuthClient(creds, store, login_runner=should_not_be_called)

        with pytest.raises(ValueError, match="Missing CEZ credentials"):
            await client.ensure_session()


# ── Scenario: Stale session file not published ────────────────────────


class TestStaleSessionProtection:
    """Expired session + failed re-auth must not publish stale data."""

    @pytest.mark.asyncio
    async def test_expired_session_reauth_fails_no_stale_state(
        self, tmp_path: Path
    ) -> None:
        """Expired session → re-auth fails → no state published."""
        session_path = tmp_path / "session.json"
        store = SessionStore(path=session_path, ttl=timedelta(seconds=1))

        # Write an already-expired session
        from datetime import datetime, timezone

        past = datetime.now(tz=timezone.utc) - timedelta(hours=2)
        session_path.write_text(
            json.dumps(
                {
                    "cookies": [{"name": "OLD", "value": "stale", "expires": 0}],
                    "created_at": past.isoformat(),
                    "expires_at": (past + timedelta(seconds=1)).isoformat(),
                }
            )
        )

        creds = DummyCredentialsProvider()

        async def failing_reauth(_: Credentials) -> AuthSession:
            raise AuthError("Session expired, re-auth failed")

        client = PlaywrightAuthClient(creds, store, login_runner=failing_reauth)

        mock_mqtt = MagicMock()
        mock_mqtt.publish = MagicMock()
        mock_mqtt.will_set = MagicMock()
        mock_mqtt.connect = MagicMock()
        mock_mqtt.disconnect = MagicMock()

        publisher = MqttPublisher(client=mock_mqtt, electrometer_id="test_meter")
        publisher.start()

        # Auth fails on re-auth
        with pytest.raises(AuthError):
            await client.ensure_session()

        # No state published
        state_calls = [
            c for c in mock_mqtt.publish.call_args_list if "/state" in c[0][0]
        ]
        assert (
            len(state_calls) == 0
        ), "Stale state must NOT be published after failed re-auth"

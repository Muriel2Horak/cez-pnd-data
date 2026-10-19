from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import (  # type: ignore[import-not-found]
        Browser,
        BrowserContext,
    )

DEFAULT_OPTIONS_PATH = Path("/data/options.json")
DEFAULT_SESSION_PATH = Path("/data/session_state.json")
DEFAULT_SESSION_TTL = timedelta(hours=6)


@dataclass(frozen=True)
class Credentials:
    email: str
    password: str


class CredentialsProvider:
    def __init__(
        self,
        options_path: Path | None = None,
        env_prefix: str = "CEZ",
    ) -> None:
        self._options_path = options_path or DEFAULT_OPTIONS_PATH
        self._env_prefix = env_prefix

    def get_credentials(self) -> Credentials:
        prefixes = [self._env_prefix]
        if self._env_prefix == "CEZ":
            prefixes.append("CEZ_PND")
        for prefix in prefixes:
            env_email = os.getenv(f"{prefix}_EMAIL")
            env_password = os.getenv(f"{prefix}_PASSWORD")
            if env_email and env_password:
                return Credentials(email=env_email, password=env_password)

        data = self._read_options()
        email = data.get("email")
        password = data.get("password")
        if not email or not password:
            raise ValueError("Missing CEZ credentials in options or environment")
        return Credentials(email=email, password=password)

    def _read_options(self) -> dict[str, Any]:
        if not self._options_path.exists():
            return {}
        with self._options_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)


@dataclass(frozen=True)
class SessionState:
    cookies: list[dict[str, Any]]
    created_at: datetime
    expires_at: datetime | None


class SessionStore:
    def __init__(
        self,
        path: Path | None = None,
        ttl: timedelta | None = None,
    ) -> None:
        self._path = path or DEFAULT_SESSION_PATH
        self._ttl = ttl or DEFAULT_SESSION_TTL
        self._live_context: BrowserContext | None = None
        self._live_browser: Browser | None = None

    def get_live_context(self) -> BrowserContext | None:
        return self._live_context

    def get_live_browser(self) -> Browser | None:
        return self._live_browser

    def set_live_context(self, context: BrowserContext, browser: Browser) -> None:
        self._live_context = context
        self._live_browser = browser

    async def close_live_context(self) -> None:
        context, browser = self._live_context, self._live_browser
        self._live_context = None
        self._live_browser = None
        try:
            if context:
                await context.close()
        finally:
            if browser and browser.is_connected():
                await browser.close()

    async def invalidate(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        finally:
            await self.close_live_context()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> SessionState | None:
        if not self._path.exists():
            return None
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return None
        cookies = payload.get("cookies")
        created_at = self._parse_datetime(payload.get("created_at"))
        expires_at = self._parse_datetime(payload.get("expires_at"))
        if not isinstance(cookies, list) or created_at is None:
            return None
        return SessionState(
            cookies=cookies, created_at=created_at, expires_at=expires_at
        )

    def save(
        self, cookies: list[dict[str, Any]], now: datetime | None = None
    ) -> SessionState:
        timestamp = now or datetime.now(tz=timezone.utc)
        expires_at = self._compute_expiry(cookies, timestamp)
        state = SessionState(
            cookies=cookies, created_at=timestamp, expires_at=expires_at
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(
            self._path,
            "w",
            encoding="utf-8",
            opener=lambda path, flags: os.open(path, flags, 0o600),
        ) as handle:
            # Creation mode protects new files; fchmod also tightens old files.
            os.fchmod(handle.fileno(), 0o600)
            json.dump(
                {
                    "cookies": cookies,
                    "created_at": timestamp.isoformat(),
                    "expires_at": expires_at.isoformat() if expires_at else None,
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
        return state

    def is_expired(self, state: SessionState, now: datetime | None = None) -> bool:
        reference = now or datetime.now(tz=timezone.utc)
        if state.expires_at is not None:
            return reference >= state.expires_at
        return reference >= (state.created_at + self._ttl)

    def _compute_expiry(
        self, cookies: list[dict[str, Any]], created_at: datetime
    ) -> datetime | None:
        expiries = []
        for cookie in cookies:
            expires = cookie.get("expires")
            if isinstance(expires, (int, float)) and expires > 0:
                expiries.append(datetime.fromtimestamp(expires, tz=timezone.utc))
        if expiries:
            return min(expiries)
        return created_at + self._ttl

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not value or not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

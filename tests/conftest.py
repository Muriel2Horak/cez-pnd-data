"""Pytest fixtures for CEZ PND integration tests.

Provides mock Home Assistant infrastructure for testing without
installing homeassistant core.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock

import pytest
import voluptuous as vol


# ---------------------------------------------------------------------------
# Mock Home Assistant modules – installed into sys.modules so that
# ``from homeassistant.X import Y`` works inside the component code.
# ---------------------------------------------------------------------------


def _make_module(name: str, attrs: dict[str, Any] | None = None) -> ModuleType:
    """Create a fake module and register it in ``sys.modules``."""
    mod = ModuleType(name)
    if attrs:
        for k, v in attrs.items():
            setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# ── data_entry_flow results ────────────────────────────────────────────────


class FlowResultType:
    FORM = "form"
    CREATE_ENTRY = "create_entry"
    ABORT = "abort"


# ── ConfigFlow base class ──────────────────────────────────────────────────


class _ConfigFlowMeta(type):
    """Metaclass that captures ``domain=...`` from class declaration."""

    def __new__(mcs, name, bases, namespace, domain: str | None = None, **kw):
        cls = super().__new__(mcs, name, bases, namespace, **kw)
        if domain is not None:
            cls.DOMAIN = domain
        return cls


class ConfigFlow(metaclass=_ConfigFlowMeta):
    """Minimal mock of homeassistant.config_entries.ConfigFlow."""

    VERSION: int = 1
    hass: Any = None
    _unique_id: str | None = None

    def async_show_form(
        self,
        *,
        step_id: str,
        data_schema: vol.Schema | None = None,
        errors: dict[str, str] | None = None,
        description_placeholders: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": FlowResultType.FORM,
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
        }

    def async_create_entry(self, *, title: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": FlowResultType.CREATE_ENTRY,
            "title": title,
            "data": data,
        }

    def async_abort(self, *, reason: str) -> dict[str, Any]:
        return {
            "type": FlowResultType.ABORT,
            "reason": reason,
        }

    async def async_set_unique_id(self, unique_id: str) -> None:
        self._unique_id = unique_id

    def _abort_if_unique_id_configured(self) -> None:
        """Raise AbortFlow if unique_id is already configured."""
        if (
            hasattr(self, "_existing_unique_ids")
            and self._unique_id in self._existing_unique_ids
        ):
            raise AbortFlow("already_configured")


class AbortFlow(Exception):
    """Raised when a config flow must be aborted."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ── Exception types ────────────────────────────────────────────────────────


class AuthenticationError(Exception):
    pass


class ConfigEntryAuthFailed(Exception):
    pass


class ConfigEntryNotReady(Exception):
    pass


# ── Constants ──────────────────────────────────────────────────────────────

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"


# ── aiohttp helper ─────────────────────────────────────────────────────────


def async_get_clientsession(hass: Any) -> Any:
    return MagicMock()


class UpdateFailed(Exception):
    pass


class DataUpdateCoordinator:

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def __class_getitem__(cls, item):
        return cls

    def __init__(
        self,
        hass,
        logger,
        *,
        config_entry=None,
        name: str = "",
        update_interval: Any = None,
    ):
        self.hass = hass
        self.logger = logger
        self.config_entry = config_entry
        self.name = name
        self.update_interval = update_interval
        self.data: Any = None

    async def _async_update_data(self):
        raise NotImplementedError

    async def async_config_entry_first_refresh(self):
        self.data = await self._async_update_data()


# ── Register mock modules ────────────────────────────────────────────────

_make_module("homeassistant")
_make_module(
    "homeassistant.const",
    {
        "CONF_USERNAME": CONF_USERNAME,
        "CONF_PASSWORD": CONF_PASSWORD,
        "CONF_SCAN_INTERVAL": CONF_SCAN_INTERVAL,
    },
)
_make_module(
    "homeassistant.config_entries",
    {
        "ConfigFlow": ConfigFlow,
        "ConfigFlowResult": dict,
    },
)
_make_module(
    "homeassistant.data_entry_flow",
    {
        "FlowResultType": FlowResultType,
        "AbortFlow": AbortFlow,
    },
)
_make_module("homeassistant.helpers")
_make_module(
    "homeassistant.helpers.aiohttp_client",
    {
        "async_get_clientsession": async_get_clientsession,
    },
)
_make_module(
    "homeassistant.helpers.update_coordinator",
    {
        "DataUpdateCoordinator": DataUpdateCoordinator,
        "UpdateFailed": UpdateFailed,
    },
)
_make_module("homeassistant.exceptions", {
    "ConfigEntryAuthFailed": ConfigEntryAuthFailed,
    "ConfigEntryNotReady": ConfigEntryNotReady,
})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def hass():
    """Return a minimal mock Home Assistant instance."""
    _hass = MagicMock()
    _hass.config_entries = MagicMock()
    _hass.config_entries.async_entries.return_value = []
    return _hass
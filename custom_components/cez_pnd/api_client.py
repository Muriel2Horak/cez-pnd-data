"""API client for CEZ PND integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import aiohttp


class AuthenticationError(Exception):
    """Raised when authentication fails or session expires."""


@dataclass
class PndMeterReading:
    timestamp: datetime
    consumption_kw: float | None
    production_kw: float | None
    reactive_kw: float | None
    status: int
    status_text: str


@dataclass
class PndMeterData:
    has_data: bool
    size: int
    readings: list[PndMeterReading]
    columns: list[dict]


@dataclass
class PndMeter:
    electrometer_id: str
    name: str


class CezPndApiClient:
    """API client for CEZ PND."""

    CAS_LOGIN_URL = "https://cas.cez.cz/cas/login"
    OAUTH2_AUTHORIZE_URL = "https://cas.cez.cz/cas/oidc/authorize"
    PND_BASE_URL = "https://pnd.cezdistribuce.cz/cezpnd2"
    CLIENT_ID = "M7z7ZnPjX3FNMouD.onpremise.bp.pnd.prod"
    REDIRECT_URI = "https://pnd.cezdistribuce.cz/cezpnd2/login/oauth2/code/mepas-external"

    def __init__(self, username: str, password: str, session: aiohttp.ClientSession) -> None:
        self._username = username
        self._password = password
        self._session = session

    async def authenticate(self) -> str:
        """Perform CAS OAuth2/OIDC login flow.

        Returns:
            User identifier string from CAS.

        Raises:
            AuthenticationError: If credentials are invalid.
            aiohttp.ClientError: If network error occurs.
        """
        # Step 1: GET CAS login page, extract 'execution' CSRF token
        service_url = await self._get_service_url()
        login_page_url = f"{self.CAS_LOGIN_URL}?service={service_url}"
        
        async with self._session.get(login_page_url) as response:
            response.raise_for_status()
            html = await response.text()
            execution = await self._extract_execution_token(html)
        
        # Step 2: POST credentials + execution token
        login_data = {
            "username": self._username,
            "password": self._password,
            "execution": execution,
            "_eventId": "submit",
        }
        
        async with self._session.post(self.CAS_LOGIN_URL, data=login_data) as response:
            if response.status != 200:
                raise AuthenticationError(f"Login failed with status {response.status}")
            
            # Check for authentication error in response
            response_text = await response.text()
            if "invalid credentials" in response_text.lower() or "přihlašovací údaje" in response_text.lower():
                raise AuthenticationError("Invalid credentials")
        
        # Step 3-5: Follow redirect chain through OAuth2/OIDC
        # After successful login, we get redirects to authorize → oidc → mepas-external
        # We'll follow these redirects manually to capture the final session cookies
        
        # GET callbackAuthorize with ticket
        authorize_url = f"{self.OAUTH2_AUTHORIZE_URL}?response_type=code&client_id={self.CLIENT_ID}&redirect_uri={self.REDIRECT_URI}&scope=openid+profile"
        async with self._session.get(authorize_url) as response:
            response.raise_for_status()
        
        # GET oidc/authorize (redirected from callbackAuthorize)
        async with self._session.get(self.OAUTH2_AUTHORIZE_URL, params={
            "response_type": "code",
            "client_id": self.CLIENT_ID,
            "redirect_uri": self.REDIRECT_URI,
            "scope": "openid profile",
        }) as response:
            response.raise_for_status()
        
        # GET mepas-external with code (redirected from oidc/authorize)
        # This final redirect should set JSESSIONID cookie
        dashboard_url = f"{self.PND_BASE_URL}/external/dashboard/view"
        async with self._session.get(dashboard_url) as response:
            response.raise_for_status()
        
        # Return a user identifier (we'll use username as identifier since CAS doesn't return one)
        return self._username

    async def _get_service_url(self) -> str:
        """Build CAS service URL for PND OAuth2."""
        return f"{self.PND_BASE_URL}/login/oauth2/code/mepas-external"

    async def _extract_execution_token(self, html: str) -> str:
        """Parse CAS login page HTML for execution token."""
        # Look for hidden input with name="execution"
        # Pattern: <input type="hidden" name="execution" value="..."/>
        import re
        match = re.search(r'<input[^>]*name=["\']execution["\'][^>]*value=["\']([^"\']*)["\']', html)
        if match:
            return match.group(1)
        raise AuthenticationError("Could not extract execution token from CAS login page")

    async def fetch_meter_data(
        self,
        electrometer_id: str,
        assembly_id: int = -1003,
        interval_from: datetime | None = None,
        interval_to: datetime | None = None,
    ) -> PndMeterData:
        """Fetch meter data from PND API.

        Args:
            electrometer_id: Meter ID (e.g., "784703")
            assembly_id: Report type (-1003=profiles, -1027=daily registers)
            interval_from: Start datetime (default: yesterday 00:00)
            interval_to: End datetime (default: today 00:00)

        Returns:
            PndMeterData with parsed intervals
        """
        interval_from, interval_to = self._resolve_intervals(
            interval_from=interval_from,
            interval_to=interval_to,
        )
        payload = {
            "format": "table",
            "idAssembly": assembly_id,
            "idDeviceSet": None,
            "intervalFrom": self._format_pnd_datetime(interval_from),
            "intervalTo": self._format_pnd_datetime(interval_to),
            "compareFrom": None,
            "opmId": None,
            "electrometerId": electrometer_id,
        }
        url = f"{self.PND_BASE_URL}/external/data"

        async with self._session.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json;charset=UTF-8"},
        ) as response:
            if response.status == 401:
                raise AuthenticationError("PND session expired")
            response.raise_for_status()
            data = await response.json()

        return self._parse_meter_data(data)

    async def fetch_available_meters(self) -> list[PndMeter]:
        """Fetch list of available electrometers for the authenticated user."""
        url = f"{self.PND_BASE_URL}/external/dashboard/window/definition"
        async with self._session.get(url) as response:
            if response.status == 401:
                raise AuthenticationError("PND session expired")
            response.raise_for_status()
            payload = await response.json()

        meters: list[PndMeter] = []
        for meter in payload.get("electrometers", []):
            electrometer_id = meter.get("electrometerId") or meter.get("id")
            name = meter.get("name") or ""
            if electrometer_id:
                meters.append(PndMeter(electrometer_id=str(electrometer_id), name=str(name)))
        return meters

    @staticmethod
    def _parse_czech_decimal(value: str) -> float:
        """Parse Czech decimal format: '1,234' → 1.234"""
        return float(value.replace(",", "."))

    @staticmethod
    def _format_pnd_datetime(dt: datetime) -> str:
        """Format datetime to PND API format: 'DD.MM.YYYY HH:MM'"""
        return dt.strftime("%d.%m.%Y %H:%M")

    @staticmethod
    def _parse_status_codes(statuses: dict[str, dict[str, Any]]) -> dict[int, str]:
        parsed: dict[int, str] = {}
        for code, payload in statuses.items():
            try:
                code_int = int(code)
            except (TypeError, ValueError):
                continue
            parsed[code_int] = str(payload.get("n", ""))
        return parsed

    def _parse_meter_data(self, payload: dict[str, Any]) -> PndMeterData:
        has_data = bool(payload.get("hasData"))
        size = int(payload.get("size", 0) or 0)
        columns = payload.get("columns", []) or []
        values = payload.get("values", []) or []
        status_texts = self._parse_status_codes(payload.get("statuses", {}) or {})
        column_map = self._map_columns(columns)

        readings: list[PndMeterReading] = []
        for row in values:
            timestamp_str = self._extract_value(row, column_map.get("timestamp"))
            if not timestamp_str:
                continue
            timestamp = datetime.strptime(timestamp_str, "%d.%m.%Y %H:%M")
            consumption_value, consumption_status = self._extract_value_with_status(
                row, column_map.get("consumption")
            )
            production_value, production_status = self._extract_value_with_status(
                row, column_map.get("production")
            )
            reactive_value, reactive_status = self._extract_value_with_status(
                row, column_map.get("reactive")
            )
            status = self._pick_status(
                consumption_status,
                production_status,
                reactive_status,
            )
            readings.append(
                PndMeterReading(
                    timestamp=timestamp,
                    consumption_kw=self._parse_optional_decimal(consumption_value),
                    production_kw=self._parse_optional_decimal(production_value),
                    reactive_kw=self._parse_optional_decimal(reactive_value),
                    status=status,
                    status_text=status_texts.get(status, "unknown"),
                )
            )

        return PndMeterData(
            has_data=has_data,
            size=size,
            readings=readings,
            columns=columns,
        )

    @staticmethod
    def _parse_optional_decimal(value: str | None) -> float | None:
        if value is None:
            return None
        return CezPndApiClient._parse_czech_decimal(value)

    @staticmethod
    def _extract_value(row: dict[str, Any], column_id: str | None) -> str | None:
        if not column_id:
            return None
        payload = row.get(column_id)
        if not isinstance(payload, dict):
            return None
        value = payload.get("v")
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _extract_value_with_status(
        row: dict[str, Any], column_id: str | None
    ) -> tuple[str | None, int | None]:
        if not column_id:
            return None, None
        payload = row.get(column_id)
        if not isinstance(payload, dict):
            return None, None
        value = payload.get("v")
        status = payload.get("s")
        return (str(value) if value is not None else None), (
            int(status) if status is not None else None
        )

    @staticmethod
    def _pick_status(*statuses: int | None) -> int:
        for status in statuses:
            if status is not None:
                return status
        return 0

    @staticmethod
    def _map_columns(columns: list[dict[str, Any]]) -> dict[str, str]:
        column_map: dict[str, str] = {}
        for column in columns:
            column_id = str(column.get("id")) if column.get("id") is not None else None
            name = str(column.get("name") or "")
            name_lower = name.lower()
            if not column_id:
                continue
            if name_lower.startswith("datum"):
                column_map["timestamp"] = column_id
                continue
            if "+a/" in name_lower:
                column_map["consumption"] = column_id
            elif "-a/" in name_lower:
                column_map["production"] = column_id
            elif name_lower.startswith("rv/"):
                column_map["reactive"] = column_id
        return column_map

    @staticmethod
    def _resolve_intervals(
        interval_from: datetime | None,
        interval_to: datetime | None,
    ) -> tuple[datetime, datetime]:
        if interval_to is None:
            interval_to = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        if interval_from is None:
            interval_from = (interval_to - timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        return interval_from, interval_to

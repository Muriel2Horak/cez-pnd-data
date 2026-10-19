"""Resolve a complete broker configuration from environment or Supervisor."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import aiohttp


async def resolve_mqtt_config(
    *,
    service_url: str = "http://supervisor/services/mqtt",
    attempts: int = 30,
    retry_delay: float = 2,
) -> dict[str, Any]:
    if os.getenv("MQTT_HOST"):
        return {
            "host": os.environ["MQTT_HOST"],
            "port": int(os.getenv("MQTT_PORT", "1883")),
            "username": os.getenv("MQTT_USER", ""),
            "password": os.getenv("MQTT_PASSWORD", ""),
            "ssl": os.getenv("MQTT_SSL", "false").lower() == "true",
        }
    token = os.getenv("SUPERVISOR_TOKEN")
    if not token:
        raise ValueError("Set MQTT_HOST for local runs or provide SUPERVISOR_TOKEN")
    timeout = aiohttp.ClientTimeout(total=5)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for attempt in range(attempts):
            try:
                async with session.get(
                    service_url, headers={"Authorization": f"Bearer {token}"}
                ) as response:
                    response.raise_for_status()
                    envelope = await response.json()
                    if envelope.get("result") != "ok":
                        raise ValueError("MQTT service is not available")
                    data = envelope["data"]
                    if not data["host"] or not data["username"] or not data["password"]:
                        raise ValueError("Incomplete MQTT service configuration")
                    return {
                        "host": data["host"],
                        "port": int(data["port"]),
                        "username": data["username"],
                        "password": data["password"],
                        "ssl": bool(data.get("ssl", False)),
                    }
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
                if attempt + 1 == attempts:
                    raise RuntimeError(
                        "Cannot obtain MQTT service settings from Supervisor"
                    ) from None
                await asyncio.sleep(retry_delay)
    raise ValueError("MQTT discovery attempts must be positive")

"""Space-grouped PND registers must reach MQTT without losing readings."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from addon.src.mqtt_publisher import MqttPublisher
from addon.src.orchestrator import Orchestrator, OrchestratorConfig


@pytest.mark.asyncio
@pytest.mark.parametrize("separator", [" ", "\u00a0", "\u202f"])
async def test_grouped_register_values_reach_all_four_mqtt_topics(separator):
    source_columns = ["+E", "-E", "+E_NT", "+E_VT"]
    payload = {
        "hasData": True,
        "columns": [{"id": "t", "name": "Datum"}]
        + [
            {"id": str(i), "name": f"{name}/123", "unit": "kWh"}
            for i, name in enumerate(source_columns)
        ],
        "values": [
            {
                "t": {"v": "18.10.2026 00:00"},
                "0": {"v": f"12{separator}345,67"},
                "1": {"v": "0,00"},
                "2": {"v": f"10{separator}000,00"},
                "3": {"v": f"2{separator}345,67"},
            }
        ],
    }
    client = MagicMock()
    orchestrator = Orchestrator(
        OrchestratorConfig([{"electrometer_id": "123", "ean": ""}]),
        SimpleNamespace(
            ensure_session=AsyncMock(return_value=SimpleNamespace(cookies=[]))
        ),
        AsyncMock(),
        MqttPublisher(client, electrometer_id="123"),
        batch_fetcher=AsyncMock(return_value={"daily_registers": payload}),
    )
    await orchestrator.run_once()
    assert {
        call.args[0]: call.kwargs["payload"] for call in client.publish.call_args_list
    } == {
        "cez_pnd/123/register_consumption/state": "12345.67",
        "cez_pnd/123/register_production/state": "0.0",
        "cez_pnd/123/register_low_tariff/state": "10000.0",
        "cez_pnd/123/register_high_tariff/state": "2345.67",
    }

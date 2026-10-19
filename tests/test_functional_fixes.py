"""Regression tests for the functional audit, including production batch wiring."""

from __future__ import annotations

import asyncio
import signal
import subprocess
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from aiohttp import web
from playwright.async_api import async_playwright

from addon.src.auth import AuthSession, PlaywrightAuthClient, _wait_for_login_success
from addon.src.hdo_parser import UNKNOWN_HDO, parse_hdo_signals
from addon.src.main import PndFetcher, create_config, run_until_shutdown
from addon.src.mqtt_config import resolve_mqtt_config
from addon.src.mqtt_publisher import MqttPublisher
from addon.src.orchestrator import Orchestrator, OrchestratorConfig
from addon.src.pnd_protocol import PndFetchError, SessionExpiredError, request_data
from addon.src.session_manager import Credentials, CredentialsProvider, SessionStore

PRAGUE = ZoneInfo("Europe/Prague")
READING = {
    "hasData": True,
    "columns": [{"id": "t", "name": "Datum"}, {"id": "a", "name": "+A/123"}],
    "values": [{"t": {"v": "15.10.2026 12:00"}, "a": {"v": "1,5"}}],
}


@pytest_asyncio.fixture
async def http_server():
    runners = []

    async def start(handler):
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        runners.append(runner)
        return f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"

    yield start
    for runner in runners:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_supervisor_credentials_and_explicit_override(http_server, monkeypatch):
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")
    calls = []

    async def handler(request):
        calls.append(request.headers.get("Authorization"))
        return web.json_response(
            {
                "result": "ok",
                "data": {
                    "host": "core-mosquitto",
                    "port": "1883",
                    "username": "service-user",
                    "password": "service-password",
                    "ssl": False,
                },
            }
        )

    url = await http_server(handler)
    config = await resolve_mqtt_config(service_url=url)
    assert config == dict(
        host="core-mosquitto",
        port=1883,
        username="service-user",
        password="service-password",
        ssl=False,
    )
    assert calls == ["Bearer test-token"]
    monkeypatch.setenv("MQTT_HOST", "local-broker")
    monkeypatch.setenv("MQTT_USER", "local-user")
    monkeypatch.setenv("MQTT_PASSWORD", "local-password")
    assert (await resolve_mqtt_config(service_url=url))["username"] == "local-user"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_supervisor_transient_failure_and_final_failure(http_server, monkeypatch):
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return web.Response(status=503)
        return web.json_response(
            {
                "result": "ok",
                "data": {
                    "host": "broker",
                    "port": 8883,
                    "username": "u",
                    "password": "p",
                    "ssl": True,
                },
            }
        )

    url = await http_server(handler)
    assert (await resolve_mqtt_config(service_url=url, retry_delay=0))["ssl"] is True
    assert calls == 2

    async def invalid(request):
        return web.json_response({"result": "error"})

    with pytest.raises(RuntimeError, match="Supervisor"):
        await resolve_mqtt_config(
            service_url=await http_server(invalid), attempts=2, retry_delay=0
        )
    monkeypatch.delenv("SUPERVISOR_TOKEN")
    with pytest.raises(ValueError, match="MQTT_HOST"):
        await resolve_mqtt_config()


@pytest.mark.asyncio
async def test_real_playwright_original_json_encoding_and_redirect_classification(
    http_server, monkeypatch
):
    captured = []

    async def handler(request):
        if request.content_type != "application/json":
            return web.Response(
                text="<html>The requested URL was rejected.</html>",
                content_type="text/html",
            )
        captured.append((request.content_type, await request.json()))
        if request.path == "/redirect":
            raise web.HTTPFound("/login")
        return web.json_response(READING)

    base = await http_server(handler)
    async with async_playwright() as pw:
        ctx = await pw.request.new_context()
        try:
            monkeypatch.setattr("addon.src.pnd_protocol.PND_DATA_URL", base + "/data")
            assert (
                await request_data(
                    SimpleNamespace(request=ctx), "123", -1003, "today", "today"
                )
                == READING
            )
            assert captured == [
                (
                    "application/json",
                    {
                        "format": "table",
                        "idAssembly": -1003,
                        "idDeviceSet": "",
                        "intervalFrom": "today",
                        "intervalTo": "today",
                        "compareFrom": "",
                        "opmId": "",
                        "electrometerId": "123",
                    },
                )
            ]
            monkeypatch.setattr(
                "addon.src.pnd_protocol.PND_DATA_URL", base + "/redirect"
            )
            with pytest.raises(SessionExpiredError):
                await request_data(
                    SimpleNamespace(request=ctx), "123", -1003, "today", "today"
                )
            assert len(captured) == 2  # The login redirect was not followed.
        finally:
            await ctx.dispose()


def test_shared_credentials_and_legacy_auto(monkeypatch, tmp_path):
    for name in (
        "CEZ_EMAIL",
        "CEZ_PASSWORD",
        "CEZ_PND_EMAIL",
        "CEZ_PND_PASSWORD",
        "CEZ_ELECTROMETERS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CEZ_EMAIL", "current@example.invalid")
    monkeypatch.setenv("CEZ_PASSWORD", "current-password")
    monkeypatch.setenv("CEZ_PND_EMAIL", "legacy@example.invalid")
    monkeypatch.setenv("CEZ_PND_PASSWORD", "legacy-password")
    monkeypatch.setenv("MQTT_HOST", "localhost")
    monkeypatch.setenv("CEZ_ELECTROMETER_ID", "auto")
    config = create_config()
    assert config["cez"]["email"] == "current@example.invalid"
    assert config["cez"]["electrometers"] == []
    provider = CredentialsProvider(options_path=tmp_path / "absent")
    assert provider.get_credentials().password == config["cez"]["password"]
    monkeypatch.delenv("CEZ_EMAIL")
    monkeypatch.delenv("CEZ_PASSWORD")
    assert provider.get_credentials().email == "legacy@example.invalid"


def build_orchestrator(fetcher=None, meters=None, **kwargs):
    auth = SimpleNamespace(
        ensure_session=AsyncMock(return_value=AuthSession([], True, meter_ids=["123"]))
    )
    publisher = MagicMock()
    config = OrchestratorConfig(
        [{"electrometer_id": "123", "ean": ""}] if meters is None else meters,
        retry_base_delay_seconds=0,
        auto_ean="ean123",
    )
    orch = Orchestrator(
        config, auth, fetcher or AsyncMock(return_value=READING), publisher, **kwargs
    )
    return orch, auth, publisher


@pytest.mark.asyncio
async def test_auto_discovery_initializes_real_id_and_optional_ean():
    orch, auth, publisher = build_orchestrator(meters=[])
    await orch.run_once()
    publisher.set_electrometers.assert_called_once_with(
        [{"electrometer_id": "123", "ean": "ean123"}]
    )
    publisher.start.assert_called_once()
    publisher.publish_discovery.assert_called_once()
    assert publisher.publish_state.call_args.args[0]["123"]["consumption"] == 1.5


@pytest.mark.asyncio
async def test_auto_discovery_missing_and_ambiguous():
    fetch = AsyncMock(return_value={"hasData": False})
    orch, auth, publisher = build_orchestrator(fetcher=fetch, meters=[])
    auth.ensure_session.return_value.meter_ids = []
    await orch.run_once()
    fetch.assert_not_awaited()
    publisher.start.assert_not_called()
    auth.ensure_session.return_value.meter_ids = ["123", "456"]
    with pytest.raises(ValueError, match="Multiple meter"):
        await orch.run_once()
    publisher.start.assert_not_called()


@pytest.mark.asyncio
async def test_production_batch_reauth_retry_and_partial_success(monkeypatch):
    from tests.test_pnd_fetcher import _build_playwright_mocks

    mock_pw, browser, context = _build_playwright_mocks()
    fetcher = PndFetcher()
    response = AsyncMock(
        side_effect=[
            READING,
            SessionExpiredError("expired"),
            PndFetchError("down", 503),
            READING,
            PndFetchError("bad", 400),
            READING,
            READING,
            READING,
        ]
    )
    monkeypatch.setattr(fetcher, "_fetch_one_in_context", response)
    monkeypatch.setattr("addon.src.main._get_async_playwright", lambda: lambda: mock_pw)
    orch, auth, publisher = build_orchestrator(
        fetcher=fetcher.fetch, batch_fetcher=fetcher.fetch_all
    )
    new_session = AuthSession([{"name": "fresh", "value": "cookie"}], False)
    auth.ensure_session.side_effect = [AuthSession([], True), new_session]
    with patch("addon.src.main.asyncio.sleep", new=AsyncMock()):
        await orch.run_once()
    assert auth.ensure_session.call_args_list[-1].kwargs == {"force_refresh": True}
    assert auth.ensure_session.await_count == 2
    assert response.await_count == 8
    context.add_cookies.assert_any_await(new_session.cookies)
    publisher.publish_state.assert_called_once()
    browser.close.assert_awaited_once()
    context.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_second_authentication_rejection_stops_cycle():
    fetch = AsyncMock(side_effect=SessionExpiredError("expired"))
    orch, auth, publisher = build_orchestrator(fetcher=fetch)
    await orch.run_once()
    assert auth.ensure_session.await_count == 2
    assert fetch.await_count == 2
    publisher.publish_state.assert_not_called()


@pytest.mark.asyncio
async def test_force_refresh_invalidates_valid_session_and_closes_resources(tmp_path):
    store = SessionStore(tmp_path / "session.json")
    store.save([{"name": "old", "value": "cookie"}])
    context, browser = AsyncMock(), MagicMock()
    browser.close = AsyncMock()
    browser.is_connected.return_value = True
    store.set_live_context(context, browser)
    provider = MagicMock(get_credentials=MagicMock(return_value=Credentials("e", "p")))
    login = AsyncMock(return_value=AuthSession([], False))
    client = PlaywrightAuthClient(provider, store, login_runner=login)
    await client.ensure_session(force_refresh=True)
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()
    login.assert_awaited_once()


@pytest.mark.asyncio
async def test_portal_url_is_not_login_proof():
    page = AsyncMock()
    page.context.request.get.return_value = SimpleNamespace(
        status=200,
        headers={"content-type": "text/html"},
        text=AsyncMock(return_value='<form><input name="username"></form>'),
    )
    page.content.return_value = "login"
    with patch("addon.src.auth.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(SessionExpiredError):
            await _wait_for_login_success(page)


@pytest.mark.asyncio
async def test_login_probe_waits_for_sso_redirect(monkeypatch, http_server):
    authenticated = False

    async def dashboard(request):
        if request.path == "/":
            raise web.HTTPFound("/external/dashboard/view")
        return web.Response(text="<html>Portal</html>", content_type="text/html")

    base = await http_server(dashboard)
    monkeypatch.setattr("addon.src.auth.PND_BASE_URL", base)

    async def probe(*args):
        if not authenticated:
            raise PndFetchError("SSO was interrupted before the authenticated redirect")
        return ["123"]

    async def portal(route):
        nonlocal authenticated
        if route.request.url.endswith("?complete=1"):
            authenticated = True
        body = (
            "<script>setTimeout(() => location.href = "
            '"/cezpnd2/external/dashboard/view?complete=1", 200)</script>'
            if route.request.url.endswith("/login")
            else "<html>Portal</html>"
        )
        await route.fulfill(content_type="text/html", body=body)

    monkeypatch.setattr("addon.src.auth.request_meter_ids", probe)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context()
            await context.route("https://pnd.cezdistribuce.cz/**", portal)
            monkeypatch.setattr(context.request, "post", AsyncMock())
            page = await context.new_page()
            await page.goto("https://pnd.cezdistribuce.cz/cezpnd2/login")
            await asyncio.wait_for(_wait_for_login_success(page), timeout=15)
            assert authenticated
            assert page.url == base + "/external/dashboard/view"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_pnd_server_error_during_login_is_not_reported_as_expired_credentials(
    caplog,
):
    auth = SimpleNamespace(
        ensure_session=AsyncMock(side_effect=PndFetchError("HTTP 500", status_code=500))
    )
    publisher = MagicMock()
    orchestrator = Orchestrator(
        OrchestratorConfig([{"electrometer_id": "123", "ean": ""}]),
        auth,
        AsyncMock(),
        publisher,
    )
    await orchestrator.run_once()
    assert "[CEZ_FETCH_ERROR]" in caplog.text
    assert "HTTP 500" in caplog.text
    assert "[SESSION_EXPIRED]" not in caplog.text
    publisher.publish_state.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("recovers", [True, False])
async def test_login_probe_retries_temporary_non_json_but_never_accepts_it(recovers):
    page = AsyncMock()
    page.content.return_value = "Portal"
    error = PndFetchError("PND fetch returned non-JSON response")
    probe = AsyncMock(side_effect=[error, ["123"]] if recovers else error)
    with (
        patch("addon.src.auth.request_meter_ids", probe),
        patch("addon.src.auth.asyncio.sleep", new=AsyncMock()),
    ):
        if recovers:
            await _wait_for_login_success(page)
            assert probe.await_count == 2
        else:
            with pytest.raises(PndFetchError, match="non-JSON"):
                await _wait_for_login_success(page)
            assert probe.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_point", ["new_context", "goto", "verification", "cancel"]
)
async def test_failed_login_closes_unowned_browser(failure_point, tmp_path):
    browser = MagicMock()
    browser.close = AsyncMock()
    context = AsyncMock()
    page = AsyncMock()
    page.frames = []
    page.locator = MagicMock()
    page.locator.return_value.first = AsyncMock()
    context.new_page.return_value = page
    browser.new_context = AsyncMock(return_value=context)
    pw = SimpleNamespace(
        chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)),
        stop=AsyncMock(),
    )
    client = PlaywrightAuthClient(MagicMock(), SessionStore(tmp_path / "state"))
    client._playwright = pw
    if failure_point == "new_context":
        browser.new_context.side_effect = RuntimeError("context creation failed")
    elif failure_point in ("goto", "cancel"):
        page.goto.side_effect = (
            asyncio.CancelledError()
            if failure_point == "cancel"
            else RuntimeError("navigation failed")
        )
    with patch(
        "addon.src.auth._wait_for_login_success",
        new=AsyncMock(side_effect=RuntimeError("not authenticated")),
    ):
        with pytest.raises((RuntimeError, asyncio.CancelledError)):
            await client._login_via_playwright(Credentials("e", "p"))
    browser.close.assert_awaited_once()
    if failure_point != "new_context":
        context.close.assert_awaited_once()
    assert client._session_store.get_live_browser() is None


def hdo(days, now):
    return parse_hdo_signals(
        {"signals": [dict(datum=d, casy=w, signal="test") for d, w in days]}, now=now
    )


def test_hdo_full_day_and_dated_future_transitions():
    result = hdo([("15.10.2026", "00:00-24:00")], datetime(2026, 10, 15, 12))
    assert result.is_low_tariff is True
    assert result.next_switch is None
    result = hdo(
        [("16.10.2026", "00:00-08:00"), ("15.10.2026", "20:00-24:00")],
        datetime(2026, 10, 15, 23),
    )
    assert result.next_switch == datetime(2026, 10, 16, 8, tzinfo=PRAGUE)
    result = hdo(
        [("16.10.2026", "08:00-12:00"), ("15.10.2026", "20:00-24:00")],
        datetime(2026, 10, 15, 23),
    )
    assert result.next_switch == datetime(2026, 10, 16, 0, tzinfo=PRAGUE)
    assert (
        hdo([("14.10.2026", "00:00-24:00")], datetime(2026, 10, 15, 12)) == UNKNOWN_HDO
    )


def test_hdo_adjacent_intervals_and_dst_folds():
    result = hdo([("15.10.2026", "00:00-08:00;08:00-12:00")], datetime(2026, 10, 15, 7))
    assert result.next_switch == datetime(2026, 10, 15, 12, tzinfo=PRAGUE)
    for fold in (0, 1):
        now = datetime(2026, 10, 25, 2, 30, tzinfo=PRAGUE, fold=fold)
        result = hdo([("25.10.2026", "00:00-04:00")], now)
        assert result.is_low_tariff is True
        assert result.next_switch.utcoffset() == timedelta(hours=1)
    result = hdo(
        [("29.03.2026", "00:00-04:00")], datetime(2026, 3, 29, 1, 30, tzinfo=PRAGUE)
    )
    assert result.next_switch.utcoffset() == timedelta(hours=2)


def test_discovery_migration_shared_availability_and_unknown_clearing():
    client = MagicMock()
    publisher = MqttPublisher(
        client, electrometers=[{"electrometer_id": "123"}, {"electrometer_id": "456"}]
    )
    publisher.start()
    client.will_set.assert_called_once_with(
        "cez_pnd/availability", payload="offline", qos=1, retain=True
    )
    publisher.publish_discovery()
    import json

    calls = client.publish.call_args_list
    for meter in ("123", "456"):
        old = f"homeassistant/sensor/cez_pnd_{meter}/hdo_low_tariff_active/config"
        new = old.replace("/sensor/", "/binary_sensor/")
        old_index = next(i for i, c in enumerate(calls) if c.args[0] == old)
        new_index = next(i for i, c in enumerate(calls) if c.args[0] == new)
        assert old_index < new_index
        assert (
            json.loads(calls[old_index].kwargs["payload"])["unique_id"]
            == f"cez_pnd_{meter}_hdo_low_tariff_active"
        )
        payload = json.loads(calls[new_index].kwargs["payload"])
        assert "device_class" not in payload
        assert payload["unique_id"] == f"cez_pnd_{meter}_hdo_low_tariff_active_binary"
        assert payload["enabled_by_default"] is False
        assert payload["availability_topic"] == "cez_pnd/availability"
    client.publish.reset_mock()
    publisher.publish_hdo_state(UNKNOWN_HDO)
    assert len(client.publish.call_args_list) == 4
    assert all(c.kwargs["payload"] == "None" for c in client.publish.call_args_list)


@pytest.mark.asyncio
async def test_shutdown_cancels_work_and_cleans_partial_startup():
    ready, shutdown = asyncio.Event(), asyncio.Event()
    cancelled = False

    async def work():
        nonlocal cancelled
        ready.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled = True

    cleanup = AsyncMock()
    task = asyncio.create_task(run_until_shutdown(work, shutdown, cleanup))
    await ready.wait()
    shutdown.set()
    await asyncio.wait_for(task, 1)
    assert cancelled
    cleanup.assert_awaited_once()

    async def failure():
        raise ValueError("startup failed")

    with pytest.raises(ValueError):
        await run_until_shutdown(failure, asyncio.Event(), cleanup)
    assert cleanup.await_count == 2


@pytest.mark.parametrize("active", [False, True])
def test_subprocess_sigterm_cleanup(active, tmp_path):
    marker = tmp_path / "closed"
    script = """
import asyncio, signal, sys
from pathlib import Path
from addon.src.main import run_until_shutdown
async def main():
    event=asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, event.set)
    async def work():
        print("ready", flush=True)
        if sys.argv[2] == "True":
            await asyncio.Event().wait()
        else:
            await asyncio.sleep(900)
    async def cleanup():
        Path(sys.argv[1]).write_text("closed")
    await run_until_shutdown(work, event, cleanup)
asyncio.run(main())
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(marker), str(active)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "ready"
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=5) == 0
        assert marker.read_text() == "closed"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


@pytest.mark.asyncio
async def test_main_wires_supervisor_settings_and_cleans_startup_failure(monkeypatch):
    from addon.src import main as app

    monkeypatch.setenv("CEZ_EMAIL", "local@example.invalid")
    monkeypatch.setenv("CEZ_PASSWORD", "local-password")
    monkeypatch.setenv("CEZ_ELECTROMETERS", "[]")
    monkeypatch.setenv("CEZ_ELECTROMETER_ID", "123")
    auth = SimpleNamespace(close=AsyncMock())
    publisher = MagicMock()
    broker = dict(
        host="core-mosquitto",
        port=1883,
        username="service-user",
        password="service-password",
        ssl=False,
    )
    orchestrator = SimpleNamespace(
        run_loop=AsyncMock(side_effect=RuntimeError("startup failure"))
    )
    with (
        patch.object(app, "resolve_mqtt_config", new=AsyncMock(return_value=broker)),
        patch.object(app, "PlaywrightAuthClient", return_value=auth),
        patch.object(app, "MQTTClientWrapper") as transport,
        patch.object(app, "MqttPublisher", return_value=publisher),
        patch.object(app, "Orchestrator", return_value=orchestrator) as factory,
    ):
        with pytest.raises(RuntimeError, match="startup failure"):
            await app.main()
    transport.assert_called_once_with(**broker)
    assert factory.call_args.kwargs["batch_fetcher"].__name__ == "fetch_all"
    auth.close.assert_awaited_once()
    publisher.stop.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected_calls", [(429, 3), (503, 3), (400, 1)])
async def test_retry_limits_match_error_classification(status, expected_calls):
    fetch = AsyncMock(side_effect=PndFetchError("failure", status))
    orch, auth, _ = build_orchestrator(fetcher=fetch)
    with pytest.raises(PndFetchError):
        await orch._fetch_assembly([], "123", -1003, "start", "end")
    assert fetch.await_count == expected_calls
    auth.ensure_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_auth_failure_clears_stale_hdo_without_pnd_publish():
    orch, auth, publisher = build_orchestrator(hdo_fetcher=AsyncMock())
    auth.ensure_session.side_effect = RuntimeError("login failed")
    await orch.run_once()
    publisher.publish_hdo_state.assert_called_once_with(
        UNKNOWN_HDO, electrometer_id="123"
    )
    publisher.publish_state.assert_not_called()


def test_startup_script_preserves_local_environment(tmp_path):
    import json
    import os
    from pathlib import Path

    expected = {
        "CEZ_EMAIL": "local@example.invalid",
        "CEZ_PASSWORD": "local-password",
        "CEZ_ELECTROMETER_ID": "123",
        "CEZ_EAN": "ean123",
        "CEZ_ELECTROMETERS": '[{"electrometer_id":"456","ean":"ean456"}]',
    }
    # Run the actual option loading before the container-only /app entrypoint.
    shell = (
        Path("addon/run.sh").read_text().split('echo "Starting CEZ PND add-on..."')[0]
    )
    options = tmp_path / "absent-options.json"
    shell = shell.replace(
        'OPTIONS_FILE="/data/options.json"', f'OPTIONS_FILE="{options}"'
    )
    shell += """\nexec "$1" -c 'import os,json; print(json.dumps({k: os.environ[k] for k in ("CEZ_EMAIL","CEZ_PASSWORD","CEZ_ELECTROMETER_ID","CEZ_EAN","CEZ_ELECTROMETERS")}))'\n"""
    result = subprocess.run(
        ["bash", "-c", shell, "startup-check", sys.executable],
        env=dict(os.environ, **expected),
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == expected

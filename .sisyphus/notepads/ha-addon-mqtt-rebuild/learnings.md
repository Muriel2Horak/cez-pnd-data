# Learnings: HA Add-on MQTT Rebuild

## Task 2: Add-on Skeleton

### Base image
- HA provides `ghcr.io/home-assistant/{arch}-base-python:{version}-alpine{alpine_version}` images
- The `BUILD_FROM` ARG is injected by the Supervisor at build time
- For standalone `docker build`, supply a default ARG value before FROM
- S6 overlay is included in the base image; `init: true` is the default

### config.yaml schema types
- `email`, `password` – validated by HA Supervisor
- `str?` – optional string (no default required)
- `int(min,max)` – bounded integer
- `list(a|b|c)` – enum select

### MQTT prerequisite pattern
- `services: [mqtt:need]` in config.yaml prevents add-on start without MQTT
- Runtime check via `bashio::services.available "mqtt"` is belt-and-suspenders
- MQTT credentials are fetched with `bashio::services mqtt 'host'` etc.

### Dockerfile gotcha
- Cannot have two `ARG BUILD_FROM` lines (one before FROM, one after)
- The default value must be on the single `ARG` line before `FROM`

### Platform warning on Apple Silicon
- Building amd64 HA base image on arm64 Mac produces expected platform mismatch warning
- Not a real error; image runs fine via QEMU emulation in Colima/Docker Desktop

## Task 3: Auth Session Module

### Session persistence
- Session cookies stored in `/data/session_state.json` with created/expires timestamps
- Expiry detection uses cookie expiry when present, fallback TTL if not provided

### Credentials handling
- Auth reads credentials from `/data/options.json` or `CEZ_PND_EMAIL`/`CEZ_PND_PASSWORD`
- No credentials are stored in session state file

## Task 4: CEZ Data Parser

### Payload structure (evidence/pnd-playwright-data.json)
- `columns` array maps column IDs to names: `"1000"` → "Datum", `"1001"` → "+A/784703", etc.
- Column IDs are strings, not integers
- Column order is NOT guaranteed — must discover dynamically from `name` field
- Meter ID is embedded in column names: `+A/{id}`, `-A/{id}`, `Rv/{id}`

### Czech data formats
- Decimal separator is comma: `"1,42"` → `1.42`
- Timestamp format: `DD.MM.YYYY HH:MM` (e.g. `"14.02.2026 00:15"`)
- Edge case: `"24:00"` means midnight of the next day (valid in CEZ but not in Python datetime)
- Status field `"s": 32` maps to `statuses["32"]` → "naměřená data OK"

### Data volume
- 96 records per day = 96 quarter-hour (15-min) intervals
- `size` field in payload matches actual `values` array length

### Parser design decisions
- `ParsedReading` dataclass with `frozen=True` for immutability
- `CezDataParser` class discovers columns in constructor, parses lazily
- `detect_electrometer_id()` is a standalone function for use without full parser
- `get_latest_reading_dict()` returns ISO 8601 timestamp for MQTT compatibility
- All parse functions return `None` for missing/invalid data — never crash

## Task 5: MQTT Discovery & State Publishing

### HA MQTT Discovery spec
- Config topic: `homeassistant/sensor/{node_id}/{object_id}/config`
- Required fields: `unique_id`, `name`, `state_topic`, `unit_of_measurement`, `device_class`, `state_class`
- `device` block with `identifiers` array groups entities into a single HA device
- `availability_topic` enables LWT-based online/offline tracking
- Config payloads MUST be retained (`retain=True`) so new HA instances discover on startup

### LWT pattern
- `will_set()` must be called BEFORE `connect()` — sets the "last will and testament"
- After connect, immediately publish `"online"` to the availability topic
- On graceful stop, publish `"offline"` before `disconnect()`

### paho-mqtt call convention
- `client.publish(topic, payload=..., qos=..., retain=...)` — topic is positional, rest keyword
- Mock call_args: `call[0][0]` = topic (positional), `call[1]` = keyword dict
- Use `call[1]["payload"]` to access kwargs reliably, not fallback chains

### Type system gotcha
- `dict[str, float | None]` is invariant in value type — cannot accept `dict[str, float]`
- Use `Mapping[str, float | None]` (covariant) for read-only function parameters
- Pyright catches this; pytest does not (runtime duck typing)

### Topic scheme design
- Deterministic: `cez_pnd/{meter_id}/{key}/state` — no UUIDs or timestamps
- Three sensors: consumption (+A), production (-A), reactive (Rv)
- All three share a single availability topic per meter

## Task 6: Runtime Orchestrator

### Architecture
- `Orchestrator` class coordinates auth → fetch → parse → publish cycle
- `OrchestratorConfig` dataclass: `poll_interval_seconds` (default 900), `max_retries` (default 3), `retry_base_delay_seconds`, `meter_id`
- `run_loop()` is the long-running entry point; `run_once()` is a single cycle (testable)
- Loop runs until `asyncio.CancelledError` — standard asyncio shutdown pattern

### Session expiry re-auth pattern
- `SessionExpiredError` custom exception raised by fetcher on HTTP 401
- On expiry: re-auth once via `auth.ensure_session()`, retry fetch with new cookies
- `_reauthed` flag prevents infinite re-auth loops — at most 2 auth attempts per cycle
- If re-auth itself fails, cycle is aborted gracefully (logged, not raised)

### Bounded retry with backoff
- Transient errors (ConnectionError, etc.) retried up to `max_retries`
- Exponential backoff: `base_delay * 2^(attempt-1)`
- After exhausting retries, cycle is aborted with ERROR log
- Session expiry is handled separately from transient retry (different code path)

### Error sentinel pattern
- `CEZ_FETCH_ERROR`, `MQTT_PUBLISH_ERROR`, `SESSION_EXPIRED_ERROR` string constants
- Included in log messages as `[SENTINEL]` prefix for structured log filtering
- Not Python exceptions — just identifiers for log aggregation

### MQTT failure isolation
- MQTT publish failures are caught and logged but never crash the orchestrator
- Next cycle retries MQTT publish normally — no special recovery needed
- This matches HA add-on resilience expectations

### Integration with parser
- `CezDataParser(payload).get_latest_reading_dict()` returns flat dict
- Orchestrator maps `consumption_kw` → `consumption` key for MqttPublisher
- `None` readings (no data) skip publish entirely

### Testing patterns
- Fast tests: `retry_base_delay_seconds=0.01` avoids real backoff delays
- Scheduler loop tests: use short `poll_interval_seconds` (0.05-0.1s) + `asyncio.sleep` + cancel
- `FakeAuthClient`, `FakeFetcher`, `FakeMqttPublisher` stubs keep tests isolated
- `caplog` fixture validates log messages contain expected error keywords

## Task 8: E2E Verification & Release Documentation

### Lazy import pattern for Playwright
- Module-level `from playwright.async_api import async_playwright` prevents tests from running without Playwright installed
- Solution: move import inside `_login_via_playwright()` method body
- Tests inject a mock `login_runner` callable, bypassing Playwright entirely
- Production code imports Playwright only when actually executing browser automation

### Bash `set -e` + arithmetic gotcha
- `((var++))` evaluates to the OLD value; when `var=0`, `((0++))` returns exit code 1
- `set -e` treats this as a failure and aborts the script
- Fix: use `var=$((var + 1))` instead of `((var++))` in scripts with `set -e`

### E2E smoke test design
- Full pipeline test: inject fake `login_runner` → parse real sample data → verify MQTT calls
- 4 test classes: pipeline smoke, discovery schema, numeric states, session persistence
- Uses `evidence/pnd-playwright-data.json` (96-record sample) as ground truth
- Tests verify both discovery config topics AND state topics are published correctly

### Negative-path testing
- 6 tests covering: auth failure (no stale publish), missing options, empty options, expired session
- Critical invariant: auth failure must NEVER publish stale MQTT state
- `FakeMqttPublisher.publish_state` call count = 0 when auth fails
- Missing/empty options raise `ValueError` before any MQTT connection

### README architecture
- README rewritten in Czech (project language) for add-on-only architecture
- 4-step installation: install broker → install add-on → set credentials → start
- No `custom_components/` references in primary path
- Full troubleshooting matrix: auth failure, DIP timeout, MQTT unavailable, missing sensors, session expiry, empty payload

### Smoke script verification
- Bash script with 8 steps, 22 individual checks
- Validates: file presence, JSON validity, unit tests, E2E tests, negative tests, discovery schema, parser output, README content
- All checks must pass for script to exit 0
- Provides evidence for release readiness

### pyproject.toml fix
- Line 83 had unterminated string: `output = "coverage.xml` → `output = "coverage.xml"`
- Caused pytest config parsing to fail silently with some pytest versions

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

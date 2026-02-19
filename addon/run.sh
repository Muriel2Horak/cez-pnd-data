#!/usr/bin/env bash

set -euo pipefail

# HA Supervisor CEZ PND Add-on Startup Script
OPTIONS_FILE="/data/options.json"

if [[ -e "$OPTIONS_FILE" && ! -r "$OPTIONS_FILE" ]]; then
    echo "Error: Cannot read $OPTIONS_FILE (permission denied)." >&2
    echo "Please restart add-on with corrected permissions or reinstall the add-on." >&2
    exit 1
fi

read_option() {
    local key="$1"
    local default_value="${2:-}"

    if [[ -f "$OPTIONS_FILE" ]]; then
        python3 - "$OPTIONS_FILE" "$key" "$default_value" <<'PY'
import json
import sys

path, key, default = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    value = data.get(key, default)
    if value is None:
        value = default
    if isinstance(value, (dict, list)):
        print(json.dumps(value, separators=(",", ":")))
    else:
        print(str(value))
except json.JSONDecodeError as e:
    sys.stderr.write(f"Warning: Failed to parse JSON in options file '{path}': {e}\n")
    print(default)
except Exception as e:
    sys.stderr.write(f"Warning: Error reading options file '{path}': {e}\n")
    print(default)
PY
    else
        printf "%s" "$default_value"
    fi
}

export CEZ_EMAIL="$(read_option email "")"
export CEZ_PASSWORD="$(read_option password "")"
export CEZ_ELECTROMETER_ID="$(read_option electrometer_id "")"
export CEZ_EAN="$(read_option ean "")"
export CEZ_ELECTROMETERS="$(read_option electrometers "[]")"

export MQTT_HOST="${MQTT_HOST:-core-mosquitto}"
export MQTT_PORT="${MQTT_PORT:-1883}"
export MQTT_USER="${MQTT_USER:-}"
export MQTT_PASSWORD="${MQTT_PASSWORD:-}"

if [[ -z "${CEZ_EMAIL}" || -z "${CEZ_PASSWORD}" ]]; then
    echo "Error: Missing required add-on options 'email' or 'password'." >&2
    echo "Please fill them in Home Assistant add-on configuration." >&2
    exit 1
fi

wait_for_mqtt() {
    local max_attempts=30
    local attempt=1
    local sleep_seconds=2

    echo "Waiting for MQTT broker at ${MQTT_HOST}:${MQTT_PORT}..."
    while (( attempt <= max_attempts )); do
        if python3 - "$MQTT_HOST" "$MQTT_PORT" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])

try:
    with socket.create_connection((host, port), timeout=2):
        pass
except OSError:
    raise SystemExit(1)

raise SystemExit(0)
PY
        then
            echo "MQTT broker is available."
            return 0
        fi
        echo "MQTT not available yet (attempt ${attempt}/${max_attempts}), retrying in ${sleep_seconds}s..."
        attempt=$((attempt + 1))
        sleep "${sleep_seconds}"
    done

    echo "Error: MQTT broker at ${MQTT_HOST}:${MQTT_PORT} did not become available in time." >&2
    return 1
}

echo "Starting CEZ PND add-on..."
echo "Configuration loaded. Sensitive details are not printed to logs."
echo "MQTT configuration is read from Supervisor-provided environment (mqtt:need)."

wait_for_mqtt

echo "Starting main application..."
exec python3 /app/src/main.py

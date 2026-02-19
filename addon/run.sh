#!/usr/bin/env bash

set -euo pipefail

# HA Supervisor CEZ PND Add-on Startup Script
OPTIONS_FILE="/data/options.json"

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
except Exception:
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

echo "Starting CEZ PND add-on..."
echo "Email: ${CEZ_EMAIL}"
echo "Electrometer ID: ${CEZ_ELECTROMETER_ID}"
echo "MQTT Host: ${MQTT_HOST}:${MQTT_PORT}"

echo "Starting main application..."
exec python3 /app/src/main.py

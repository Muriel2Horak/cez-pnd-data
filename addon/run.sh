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

export CEZ_EMAIL="$(read_option email "${CEZ_EMAIL:-${CEZ_PND_EMAIL:-}}")"
export CEZ_PASSWORD="$(read_option password "${CEZ_PASSWORD:-${CEZ_PND_PASSWORD:-}}")"
export CEZ_ELECTROMETER_ID="$(read_option electrometer_id "${CEZ_ELECTROMETER_ID:-}")"
export CEZ_EAN="$(read_option ean "${CEZ_EAN:-}")"
export CEZ_ELECTROMETERS="$(read_option electrometers "${CEZ_ELECTROMETERS:-[]}")"

if [[ -z "${CEZ_EMAIL}" || -z "${CEZ_PASSWORD}" ]]; then
    echo "Error: Missing required add-on options 'email' or 'password'." >&2
    echo "Please fill them in Home Assistant add-on configuration." >&2
    exit 1
fi

echo "Starting CEZ PND add-on..."
echo "MQTT settings will be resolved from Supervisor or explicit environment configuration."
cd /app
exec python3 -m src.main

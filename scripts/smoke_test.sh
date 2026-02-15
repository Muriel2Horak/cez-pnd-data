#!/usr/bin/env bash
# =============================================================================
# CEZ PND Add-on — E2E Smoke Test Script
#
# Verifies the full pipeline:
#   1. Unit tests pass (parser, MQTT, auth, E2E smoke, invalid credentials)
#   2. Discovery payload JSON is valid
#   3. Sample data can be parsed
#   4. All acceptance criteria are met
#
# Usage:
#   ./scripts/smoke_test.sh
#
# Prerequisites:
#   - Python 3.9+
#   - pytest, pytest-asyncio installed
#   - evidence/pnd-playwright-data.json present
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

pass_count=0
fail_count=0

pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
    pass_count=$((pass_count + 1))
}

fail() {
    echo -e "${RED}✗ FAIL${NC}: $1"
    fail_count=$((fail_count + 1))
}

info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

header() {
    echo ""
    echo -e "${YELLOW}━━━ $1 ━━━${NC}"
}

# =============================================================================
header "Step 1: Verify prerequisite files exist"
# =============================================================================

REQUIRED_FILES=(
    "evidence/pnd-playwright-data.json"
    "evidence/poc-comparison.md"
    "addon/src/auth.py"
    "addon/src/session_manager.py"
    "addon/src/parser.py"
    "addon/src/mqtt_publisher.py"
    "tests/test_e2e_smoke.py"
    "tests/test_invalid_credentials.py"
    "tests/test_cez_parser.py"
    "tests/test_mqtt_discovery.py"
    "tests/test_auth_session.py"
    "README.md"
)

for f in "${REQUIRED_FILES[@]}"; do
    if [[ -f "${PROJECT_DIR}/${f}" ]]; then
        pass "File exists: ${f}"
    else
        fail "Missing file: ${f}"
    fi
done

# =============================================================================
header "Step 2: Validate sample payload JSON"
# =============================================================================

if python3 -m json.tool "${PROJECT_DIR}/evidence/pnd-playwright-data.json" > /dev/null 2>&1; then
    pass "Sample payload is valid JSON"
else
    fail "Sample payload is invalid JSON"
fi

# =============================================================================
header "Step 3: Run unit tests (parser + MQTT + auth)"
# =============================================================================

cd "${PROJECT_DIR}"

if python3 -m pytest tests/test_cez_parser.py tests/test_mqtt_discovery.py tests/test_auth_session.py --no-cov -q 2>&1; then
    pass "Core unit tests pass"
else
    fail "Core unit tests failed"
fi

# =============================================================================
header "Step 4: Run E2E smoke tests"
# =============================================================================

if python3 -m pytest tests/test_e2e_smoke.py --no-cov -v 2>&1; then
    pass "E2E smoke tests pass (discovery + state pipeline verified)"
else
    fail "E2E smoke tests failed"
fi

# =============================================================================
header "Step 5: Run negative-path tests (invalid credentials)"
# =============================================================================

if python3 -m pytest tests/test_invalid_credentials.py --no-cov -v 2>&1; then
    pass "Negative-path tests pass (invalid creds, no stale state)"
else
    fail "Negative-path tests failed"
fi

# =============================================================================
header "Step 6: Verify discovery payload schema"
# =============================================================================

# Quick inline Python check: all discovery payloads have required HA fields
SCHEMA_CHECK=$(python3 -c "
import json, sys
sys.path.insert(0, '.')
from addon.src.mqtt_publisher import build_discovery_payload, get_sensor_definitions

required = {'unique_id', 'name', 'state_topic', 'unit_of_measurement',
            'device_class', 'state_class', 'device', 'availability_topic'}
meter_id = '784703'
ok = True
for sensor in get_sensor_definitions():
    payload = build_discovery_payload(sensor, meter_id)
    missing = required - set(payload.keys())
    if missing:
        print(f'FAIL: {sensor.key} missing {missing}')
        ok = False
    # JSON roundtrip
    rt = json.loads(json.dumps(payload))
    if rt != payload:
        print(f'FAIL: {sensor.key} JSON roundtrip mismatch')
        ok = False
if ok:
    print('OK')
" 2>&1)

if [[ "${SCHEMA_CHECK}" == "OK" ]]; then
    pass "All discovery payloads have required HA MQTT fields"
else
    fail "Discovery payload schema check: ${SCHEMA_CHECK}"
fi

# =============================================================================
header "Step 7: Verify parser output from sample data"
# =============================================================================

PARSER_CHECK=$(python3 -c "
import json, sys
sys.path.insert(0, '.')
from addon.src.parser import CezDataParser, detect_electrometer_id

with open('evidence/pnd-playwright-data.json') as f:
    payload = json.load(f)

meter_id = detect_electrometer_id(payload)
assert meter_id == '784703', f'Expected 784703, got {meter_id}'

parser = CezDataParser(payload)
records = parser.parse_records()
assert len(records) == 96, f'Expected 96 records, got {len(records)}'

latest = parser.get_latest_reading_dict()
assert latest is not None
assert latest['consumption_kw'] is not None
assert latest['production_kw'] is not None
assert latest['reactive_kw'] is not None

print(f'OK: {len(records)} records, latest consumption={latest[\"consumption_kw\"]} kW')
" 2>&1)

if echo "${PARSER_CHECK}" | grep -q "^OK:"; then
    pass "Parser: ${PARSER_CHECK}"
else
    fail "Parser check: ${PARSER_CHECK}"
fi

# =============================================================================
header "Step 8: README validation"
# =============================================================================

README="${PROJECT_DIR}/README.md"

# Check README doesn't have custom_components as primary install path
if grep -q "custom_components" "${README}" 2>/dev/null; then
    fail "README still references custom_components"
else
    pass "README does not reference legacy custom_components path"
fi

# Check README mentions MQTT broker installation
if grep -q "MQTT broker" "${README}" || grep -q "Mosquitto" "${README}"; then
    pass "README documents MQTT broker prerequisite"
else
    fail "README missing MQTT broker documentation"
fi

# Check README mentions email/password setup
if grep -q "email" "${README}" && grep -q "password" "${README}"; then
    pass "README documents credential configuration"
else
    fail "README missing credential setup instructions"
fi

# Check troubleshooting section exists
if grep -q "DIP timeout" "${README}" || grep -q "timeout" "${README}"; then
    pass "README includes DIP timeout troubleshooting"
else
    fail "README missing DIP timeout guidance"
fi

# =============================================================================
header "RESULTS"
# =============================================================================

echo ""
echo -e "Passed: ${GREEN}${pass_count}${NC}"
echo -e "Failed: ${RED}${fail_count}${NC}"
echo ""

if [[ ${fail_count} -eq 0 ]]; then
    echo -e "${GREEN}━━━ ALL CHECKS PASSED ━━━${NC}"
    exit 0
else
    echo -e "${RED}━━━ ${fail_count} CHECK(S) FAILED ━━━${NC}"
    exit 1
fi

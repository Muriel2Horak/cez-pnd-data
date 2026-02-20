#!/usr/bin/env bash
# Local test script for CEZ PND add-on
# Validates Playwright-only runtime path and maintenance scenarios
# Usage: ./scripts/test-local.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== CEZ PND Local Test ==="
echo ""

cd "$PROJECT_DIR"

echo "1. Running Python syntax check..."
python3 -m py_compile addon/src/main.py
echo "   OK"

echo "2. Running module import test..."
cd addon
python3 -c "from src.main import create_config; print('   Import OK')"
cd "$PROJECT_DIR"

echo "3. Validating Playwright-only runtime path..."
# Verify HTTP PND client has been removed (T8)
if grep -r "pnd_client\|PndClient" addon/src/*.py 2>/dev/null | grep -v "^$"; then
    echo "   FAIL: HTTP PND client still referenced in production code"
    exit 1
fi
echo "   OK: HTTP PND client removed (Playwright-only path verified)"

echo "4. Running Playwright fetcher tests..."
python3 -m pytest tests/test_pnd_fetcher.py --no-cov -q
echo "   OK: Playwright PND fetch path validated"

echo "5. Running maintenance scenario tests..."
python3 -m pytest tests/test_dip_client.py::test_fetch_hdo_raises_maintenance_on_html_token_response \
                tests/test_dip_client.py::test_fetch_hdo_raises_maintenance_on_400_token \
                tests/test_dip_client.py::test_fetch_hdo_raises_maintenance_on_503_token \
                tests/test_runtime_orchestrator.py::TestSessionExpiry::test_session_expired_triggers_reauth_and_retry \
                --no-cov -q
echo "   OK: Maintenance scenario handling validated"

echo "6. Running full test suite..."
python3 -m pytest tests/ --no-cov -q
echo ""

echo "=== All local tests passed ==="
echo ""
echo "Summary:"
echo "  ✓ Playwright-only runtime path verified (HTTP PND client removed)"
echo "  ✓ Maintenance scenarios tested (HTML, 400/503, session expiry)"
echo "  ✓ Full test suite passes"

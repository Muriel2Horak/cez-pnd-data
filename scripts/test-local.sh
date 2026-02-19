#!/usr/bin/env bash
# Local test script for CEZ PND add-on
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

echo "3. Running test suite..."
python3 -m pytest tests/ --no-cov -q
echo ""

echo "=== All local tests passed ==="

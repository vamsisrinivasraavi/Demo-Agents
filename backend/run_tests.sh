#!/usr/bin/env bash
# ──────────────────────────────────────────────
# Schema Assistant — Test Runner
# ──────────────────────────────────────────────
# Run from the backend/ directory:
#   chmod +x run_tests.sh && ./run_tests.sh
# ──────────────────────────────────────────────

set -e

echo "═══════════════════════════════════════════"
echo " Schema Assistant — Test Suite"
echo "═══════════════════════════════════════════"

# Step 1: Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "→ Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

# Step 2: Install dependencies
echo "→ Installing dependencies..."
pip install -q -r requirements.txt

# Step 3: Set test environment variables
export JWT_SECRET_KEY="test-secret-key-for-jwt-signing-only"
export OPENAI_API_KEY="sk-test-fake-key"
export MONGO_URI="mongodb://localhost:27017"
export MONGO_DB_NAME="schema_assistant_test"
export REDIS_URL="redis://localhost:6379/15"
export QDRANT_HOST="localhost"
export QDRANT_PORT="6333"
export ENVIRONMENT="testing"
export DEBUG="true"
export LOG_LEVEL="WARNING"

# Step 4: Run tests
echo ""
echo "═══════════════════════════════════════════"
echo " Running Tests"
echo "═══════════════════════════════════════════"
echo ""

# Run with verbose output, showing each test name
python -m pytest tests/ \
    -v \
    --tb=short \
    --no-header \
    -x \
    2>&1

EXIT_CODE=$?

echo ""
echo "═══════════════════════════════════════════"
if [ $EXIT_CODE -eq 0 ]; then
    echo " ✓ ALL TESTS PASSED"
else
    echo " ✗ SOME TESTS FAILED (exit code: $EXIT_CODE)"
fi
echo "═══════════════════════════════════════════"

exit $EXIT_CODE
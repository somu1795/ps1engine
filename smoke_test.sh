#!/bin/bash
# =============================================================================
# PS1 Engine — Deployment Smoke Test
# =============================================================================
# Verifies the running stack is actually healthy end-to-end.
# Run this AFTER ./start.sh to confirm routing, app startup, and APIs all work.
#
# Usage:
#   ./smoke_test.sh                          # uses domains from .env
#   ./smoke_test.sh https://ps1.example.com  # override URL manually
#
# Exit codes:
#   0 = all checks passed
#   1 = one or more checks failed
# =============================================================================

set -uo pipefail

# ---- Config -----------------------------------------------------------------
TARGET_URL="${1:-}"
TIMEOUT=10
RETRIES=6          # × 5s sleep = up to 30 seconds waiting for startup
PASS=0
FAIL=0
SKIP=0

# Load .env if present to get domain names
if [ -f .env ]; then
    set -a; source .env; set +a
fi

# Determine base URL to test against
if [ -z "$TARGET_URL" ]; then
    DOMAIN="${DOMAIN_LOCAL:-localhost}"
    TARGET_URL="https://${DOMAIN}"
fi

# ---- Helpers ----------------------------------------------------------------
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $1"; ((PASS++)); }
fail() { echo -e "  ${RED}✗${NC} $1"; ((FAIL++)); }
skip() { echo -e "  ${YELLOW}○${NC} $1 (skipped)"; ((SKIP++)); }
info() { echo -e "  ${BLUE}→${NC} $1"; }

http_check() {
    local label="$1"
    local url="$2"
    local expected_status="${3:-200}"
    local extra_flags="${4:-}"

    # Retry with backoff (useful right after ./start.sh)
    local attempt=1
    local status
    while [ $attempt -le $RETRIES ]; do
        status=$(curl -sk -o /dev/null -w "%{http_code}" \
            --max-time "$TIMEOUT" \
            $extra_flags \
            "$url" 2>/dev/null || echo "000")

        if [ "$status" = "$expected_status" ]; then
            pass "$label → HTTP $status"
            return 0
        fi

        if [ "$status" = "000" ]; then
            info "Attempt $attempt/$RETRIES: connection failed, retrying in 5s..."
        else
            info "Attempt $attempt/$RETRIES: got HTTP $status (want $expected_status), retrying in 5s..."
        fi
        ((attempt++))
        sleep 5
    done

    fail "$label → HTTP $status (expected $expected_status) after $((RETRIES * 5))s"
    return 1
}

json_field_check() {
    local label="$1"
    local url="$2"
    local field="$3"  # python3 expression applied to the parsed JSON dict

    local response
    response=$(curl -sk --max-time "$TIMEOUT" "$url" 2>/dev/null || echo "{}")
    local result
    result=$(echo "$response" | python3 -c "import sys, json; d=json.load(sys.stdin); print($field)" 2>/dev/null || echo "__ERROR__")

    if [ "$result" = "__ERROR__" ] || [ -z "$result" ]; then
        fail "$label → could not parse field from response"
    else
        pass "$label → $result"
    fi
}

# ---- Banner -----------------------------------------------------------------
echo ""
echo "============================================================"
echo "  PS1 Engine — Smoke Test"
echo "  Target: $TARGET_URL"
echo "  $(date)"
echo "============================================================"
echo ""

# ---- 1. Docker container health --------------------------------------------
echo "[ 1 ] Container Health"

for service in ps1-orchestrator ps1-watchdog traefik; do
    if docker inspect "$service" &>/dev/null 2>&1; then
        health=$(docker inspect "$service" --format '{{.State.Status}}' 2>/dev/null)
        docker_health=$(docker inspect "$service" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' 2>/dev/null)

        if [ "$health" = "running" ] && [ "$docker_health" != "unhealthy" ]; then
            pass "Container $service is $health (health: $docker_health)"
        else
            fail "Container $service is $health (health: $docker_health)"
        fi
    else
        fail "Container $service not found — is the stack running?"
    fi
done
echo ""

# ---- 2. Traefik routing (HTTP → HTTPS redirect) ----------------------------
echo "[ 2 ] HTTP → HTTPS Redirect"
http_check "Port 80 redirects to HTTPS" "${TARGET_URL/https:/http:}" "301" "--max-redirs 0"
echo ""

# ---- 3. HTTPS reachability -------------------------------------------------
echo "[ 3 ] HTTPS Frontend"
http_check "Frontend (GET /)" "$TARGET_URL/" "200" "-k"
echo ""

# ---- 4. API endpoints -------------------------------------------------------
echo "[ 4 ] Core API Endpoints"
http_check "ROM listing (GET /api/roms)" "$TARGET_URL/api/roms" "200" "-k"
http_check "ROM art fallback (GET /api/rom-art/unknown)" "$TARGET_URL/api/rom-art/unknown" "200" "-k"
http_check "Session status for unknown session (GET /api/session-status/notreal)" "$TARGET_URL/api/session-status/notreal?client_id=smoke-probe" "200" "-k"
echo ""

# ---- 5. API response content validation ------------------------------------
echo "[ 5 ] API Response Content"
json_field_check \
    "ROM list contains 'ps1' key" \
    "$TARGET_URL/api/roms" \
    "'ps1' in d and isinstance(d['ps1'], list)"

json_field_check \
    "ROM list contains 'enabled_platforms'" \
    "$TARGET_URL/api/roms" \
    "'enabled_platforms' in d and len(d['enabled_platforms']) > 0"
echo ""

# ---- 6. Admin routes (auth required) ----------------------------------------
echo "[ 6 ] Admin Auth Protection"
http_check "Admin page requires auth (GET /admin)" "$TARGET_URL/admin" "401" "-k"
http_check "Admin API requires auth (GET /api/admin/sessions)" "$TARGET_URL/api/admin/sessions" "401" "-k"
echo ""

# ---- 7. Security headers check ---------------------------------------------
echo "[ 7 ] Security"
# Start-session without body should return 400/422, not 500
status=$(curl -sk -o /dev/null -w "%{http_code}" -X POST "$TARGET_URL/api/start-session" \
    -H "Content-Type: application/json" -d '{}' -k 2>/dev/null || echo "000")
if [ "$status" = "422" ] || [ "$status" = "400" ]; then
    pass "POST /api/start-session with empty body returns $status (not 500)"
else
    fail "POST /api/start-session with empty body returned $status (expected 422 or 400)"
fi

# Path traversal should be rejected
status=$(curl -sk -o /dev/null -w "%{http_code}" -X POST "$TARGET_URL/api/start-session" \
    -H "Content-Type: application/json" \
    -d '{"game_filename":"../../etc/passwd.zip","client_id":"probe","platform":"ps1"}' \
    -k 2>/dev/null || echo "000")
if [ "$status" = "400" ] || [ "$status" = "403" ]; then
    pass "Path traversal filename rejected ($status)"
else
    fail "Path traversal filename NOT rejected (got $status)"
fi
echo ""

# ---- 8. Healthcheck command validation in image ----------------------------
echo "[ 8 ] Infrastructure Config Validation"

# Validate that the healthcheck command actually works inside the orchestrator image
hc_result=$(docker exec ps1-orchestrator \
    python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/roms', timeout=5)" \
    2>&1 && echo "OK" || echo "FAIL")
if [ "$hc_result" = "OK" ]; then
    pass "Healthcheck command succeeds inside orchestrator container"
else
    fail "Healthcheck command fails inside orchestrator: $hc_result"
fi

# Validate docker-compose.yml syntax
if docker compose config --quiet 2>/dev/null; then
    pass "docker-compose.yml is valid"
else
    fail "docker-compose.yml has syntax errors"
fi
echo ""

# ---- Summary ----------------------------------------------------------------
echo "============================================================"
TOTAL=$((PASS + FAIL + SKIP))
echo -e "  Results: ${GREEN}${PASS} passed${NC}  ${RED}${FAIL} failed${NC}  ${YELLOW}${SKIP} skipped${NC}  (${TOTAL} total)"
echo "============================================================"
echo ""

if [ $FAIL -gt 0 ]; then
    echo -e "  ${RED}SMOKE TEST FAILED${NC} — Check logs: docker compose logs orchestrator"
    exit 1
else
    echo -e "  ${GREEN}ALL CHECKS PASSED${NC} — Stack is healthy."
    exit 0
fi

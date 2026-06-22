#!/bin/sh
# Tests for restore-drill.sh conformance to spec (issue #386)
#
# R2: when no backup file exists, should exit 0 (skip) — not exit 1 (failure)
# R3: must NOT use docker socket/docker-run; must use initdb + UNIX socket instead

set -eu

SCRIPT="/workspace/markethawk/scripts/restore-drill.sh"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS+1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL+1)); }

# --- Test 1: no-backup path exits 0 ---
TMPDIR=$(mktemp -d)
set +e
BACKUP_DIR="$TMPDIR" SEQ_URL="" PGPASSWORD="dummy" sh "$SCRIPT" >/dev/null 2>&1
RC=$?
set -e
rm -rf "$TMPDIR"
if [ "$RC" -eq 0 ]; then
    pass "R2: no-backup exits 0 (skip, not failure)"
else
    fail "R2: no-backup exits $RC (expected 0); spec requires exit 0 on fresh-deploy skip"
fi

# --- Test 2: script does not call 'docker run' (initdb approach required) ---
if grep -q 'docker run' "$SCRIPT"; then
    fail "R3: script calls 'docker run' — spec requires initdb+UNIX-socket approach (Alternative 1 was rejected)"
else
    pass "R3: script does not call 'docker run' (initdb approach confirmed)"
fi

# --- Test 3: Dockerfile apk install line does not include docker-cli ---
DOCKERFILE="/workspace/markethawk/docker/Dockerfile.restore-drill"
if grep -E 'apk (add|install).*docker-cli' "$DOCKERFILE"; then
    fail "R3: Dockerfile installs docker-cli — hermetic initdb design must not need it"
else
    pass "R3: Dockerfile does not install docker-cli"
fi

# --- Test 4: docker-compose.yml does not mount Docker socket ---
COMPOSE="/workspace/markethawk/docker-compose.yml"
if grep -A 30 'db-restore-drill:' "$COMPOSE" | grep -q 'docker.sock'; then
    fail "R3: docker-compose.yml mounts /var/run/docker.sock — spec explicitly rejected this"
else
    pass "R3: docker-compose.yml does not mount Docker socket"
fi

# --- Test 5: docker-compose.yml has no depends_on: postgres ---
if grep -A 40 'db-restore-drill:' "$COMPOSE" | grep -q 'depends_on'; then
    fail "Hermetic: db-restore-drill has depends_on (spec: 'No depends_on: [postgres]')"
else
    pass "Hermetic: db-restore-drill has no depends_on"
fi

# --- Test 6: ENV_VARIABLES.md documents RESTORE_DRILL_SCHEDULE ---
ENV_VARS="/workspace/markethawk/ENV_VARIABLES.md"
if grep -q 'RESTORE_DRILL_SCHEDULE' "$ENV_VARS"; then
    pass "R9: RESTORE_DRILL_SCHEDULE documented in ENV_VARIABLES.md"
else
    fail "R9: RESTORE_DRILL_SCHEDULE missing from ENV_VARIABLES.md"
fi

# --- Test 7: ENV_VARIABLES.md documents EXPECTED_ALEMBIC_HEAD ---
if grep -qE 'EXPECTED_ALEMBIC_HEAD|ALEMBIC_EXPECTED_HEAD' "$ENV_VARS"; then
    pass "R9: alembic head env var documented in ENV_VARIABLES.md"
else
    fail "R9: alembic head env var missing from ENV_VARIABLES.md"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]

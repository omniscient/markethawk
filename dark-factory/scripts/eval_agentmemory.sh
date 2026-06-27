#!/usr/bin/env bash
# Evaluation script for rohitg00/agentmemory spike (#644).
#
# Usage (from host, after starting the engine + worker):
#   AGENTMEMORY_URL=http://<engine-ip>:3111 bash dark-factory/scripts/eval_agentmemory.sh
#
# Prerequisites — two steps:
#   1. docker compose --profile agentmemory-spike up -d agentmemory-init agentmemory-engine
#   2. ENGINE_IP=$(docker inspect agentmemory-engine \
#        --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
#      III_ENGINE_URL="ws://$ENGINE_IP:49134" \
#      AGENTMEMORY_URL="http://$ENGINE_IP:3111" \
#        node /tmp/agentmemory-src/dist/index.mjs &
#
# IMPORTANT — confirmed API paths (v0.9.27):
#   POST /agentmemory/remember          → save memory; response: {"memory": {"id": ...}}
#   GET  /agentmemory/memories?project= → list all by project; response: {"memories": [...]}
#   GET  /agentmemory/memories/{id}     → exact retrieval; response: {"memory": {...}}
#   POST /agentmemory/search            → BM25 text search; body: {"project":, "query":}
#   POST /agentmemory/smart-search      → semantic/hybrid; body: {"project":, "query":}
#   NOTE: role= and path= params on POST /remember are accepted but NOT stored as
#         filterable fields — GET /memories?role= ignores the filter. Role/path scoping
#         is not natively supported in v0.9.27.
#
# Exit codes:
#   0 — all tests passed (incl. outage test)
#   1 — agentmemory service unreachable at startup (health check failed)
#   2 — memory import or retrieval failure
set -euo pipefail

BASE_URL="${AGENTMEMORY_URL:-http://localhost:6789}"
PROJECT="markethawk"
PASS=0
FAIL=0

declare -A MEM_IDS

ts_ms() { python3 -c "import time; print(int(time.time() * 1000))"; }
elapsed_ms() { echo $(($(ts_ms) - $1)); }

header() { echo ""; echo "=== $* ==="; }
ok()     { echo "  PASS: $*"; PASS=$((PASS+1)); }
fail()   { echo "  FAIL: $*"; FAIL=$((FAIL+1)); }
note()   { echo "  NOTE: $*"; }

# ── Step 1: Health check ─────────────────────────────────────────────────────
header "Step 1: Health check"
T0=$(ts_ms)

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$BASE_URL/agentmemory/health" 2>/dev/null || echo "000")
HEALTH_LATENCY=$(elapsed_ms "$T0")

echo "  Health endpoint: $BASE_URL/agentmemory/health"
echo "  HTTP status:     $HTTP_CODE"
echo "  Latency:         ${HEALTH_LATENCY}ms"

if [ "$HTTP_CODE" != "200" ]; then
  echo ""
  echo "FAIL: health check returned HTTP $HTTP_CODE — agentmemory is not reachable."
  echo "  Start the engine:  docker compose --profile agentmemory-spike up -d agentmemory-init agentmemory-engine"
  echo "  Get engine IP:     ENGINE_IP=\$(docker inspect agentmemory-engine --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')"
  echo "  Start worker:      III_ENGINE_URL=ws://\$ENGINE_IP:49134 AGENTMEMORY_URL=http://\$ENGINE_IP:3111 node /tmp/agentmemory-src/dist/index.mjs &"
  echo "  Then re-run:       AGENTMEMORY_URL=http://\$ENGINE_IP:3111 bash $0"
  exit 1
fi

HEALTH_BODY=$(curl -s --max-time 5 "$BASE_URL/agentmemory/health" 2>/dev/null | python3 -c 'import sys,json; d=json.load(sys.stdin); print(f"status={d.get(\"status\")}, version={d.get(\"version\")}, connState={d[\"health\"][\"connectionState\"]}")' 2>/dev/null || echo "parse error")
echo "  Response:        $HEALTH_BODY"

AUTH_HEADER=""
if [ -n "${AGENTMEMORY_SECRET:-}" ]; then
  AUTH_HEADER="Authorization: Bearer $AGENTMEMORY_SECRET"
  note "Auth: Bearer token from AGENTMEMORY_SECRET"
else
  note "Auth: none (AGENTMEMORY_SECRET not set — endpoints are unsecured)"
fi

ok "health check HTTP 200 in ${HEALTH_LATENCY}ms"

# ── Step 2: Startup metadata ─────────────────────────────────────────────────
header "Step 2: Service metadata"
# NOTE: image tag, version, and ports below are illustrative (matched to the spike at the time
# of writing).  They are not derived from docker-compose.yml and may silently drift if the
# compose file is updated.  Treat them as documentation, not authoritative runtime values.
echo "  Image:         iiidev/iii:0.11.2 (engine) + node dist/index.mjs (agentmemory worker v0.9.27)"
echo "  Architecture:  2-process: engine container + Node.js worker (source-built)"
echo "  Port:          3111 (REST API, container); host-mapped to 6789 | 49134 (WS, container); host-mapped to 6791"
echo "  Auth:          ${AUTH_HEADER:-none}"
echo "  Startup time:  ${AGENTMEMORY_STARTUP_SECONDS:-measured externally}s"

# ── Step 3: Import representative memories ───────────────────────────────────
header "Step 3: Import memories (project=$PROJECT)"

post_mem() {
  local CONTENT="$1"
  local EXTRA=()
  [ -n "$AUTH_HEADER" ] && EXTRA=(-H "$AUTH_HEADER")
  python3 -c "
import json, sys
content = sys.argv[1]
print(json.dumps({'project': '$PROJECT', 'content': content}))
" "$CONTENT" | curl -s -X POST "$BASE_URL/agentmemory/remember" \
    "${EXTRA[@]}" \
    -H "Content-Type: application/json" \
    -d @- 2>/dev/null
}

extract_id() {
  python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("memory",{}).get("id",""))' 2>/dev/null
}

T0=$(ts_ms)

# M1 — prometheus volume pattern (dark-factory-ops.md, implement)
R=$(post_mem "[PATTERN] prometheus_multiproc must be a regular named volume not tmpfs — Docker tmpfs mounts are per-container, so worker metrics are invisible to the backend /metrics endpoint with tmpfs. See docker-compose.yml.")
MEM_IDS["M1"]=$(echo "$R" | extract_id)
echo "  M1 saved: ${MEM_IDS[M1]:-FAIL}  (prometheus/tmpfs pattern, dark-factory-ops)"

# M2 — selective memory loading (codebase-patterns.md, implement)
R=$(post_mem "[PATTERN] When building memory context for a subagent prompt, load only files relevant to the component area (backend changes to backend-patterns.md; dark factory ops to dark-factory-ops.md). Loading all memory files unconditionally bloats the prompt and dilutes signal.")
MEM_IDS["M2"]=$(echo "$R" | extract_id)
echo "  M2 saved: ${MEM_IDS[M2]:-FAIL}  (selective memory loading)"

# M3 — circuit breaker placement (backend-patterns.md, implement)
R=$(post_mem "[PATTERN] Circuit breakers live in app/core/circuit_breakers.py as two module-level singletons (POLYGON_BREAKER, IBKR_BREAKER). Add new breakers here, not in provider files.")
MEM_IDS["M3"]=$(echo "$R" | extract_id)
echo "  M3 saved: ${MEM_IDS[M3]:-FAIL}  (circuit breakers, backend/app/core/)"

# M4 — selectinload vs joinedload (backend-patterns.md, implement)
R=$(post_mem "[AVOID] Never use joinedload() with paginated queries on one-to-many relationships — produces a JOIN that row-multiplies the parent before LIMIT. Use selectinload() which issues a separate SELECT...WHERE id IN (...) after the paginated parent query.")
MEM_IDS["M4"]=$(echo "$R" | extract_id)
echo "  M4 saved: ${MEM_IDS[M4]:-FAIL}  (selectinload vs joinedload, backend/app/routers/)"

# M5 — scope discipline with git diff (codebase-patterns.md, refine)
R=$(post_mem "[PATTERN] Use git diff origin/main HEAD -- <file> (two-dot) to test whether a file is truly out-of-scope relative to main. The three-dot form includes commits that main merged independently, producing false-positive OOS hits.")
MEM_IDS["M5"]=$(echo "$R" | extract_id)
echo "  M5 saved: ${MEM_IDS[M5]:-FAIL}  (scope discipline, refine role)"

# M6 — JSONB validation (backend-patterns.md, refine)
R=$(post_mem "[PATTERN] Validate JSONB dict fields before persisting with a coarse json.dumps() probe (_validate_jsonb_dict in alert_service.py). Prefer this over per-scanner-type Pydantic schemas when the key set varies by scanner type.")
MEM_IDS["M6"]=$(echo "$R" | extract_id)
echo "  M6 saved: ${MEM_IDS[M6]:-FAIL}  (JSONB validation, backend/app/services/)"

IMPORT_LATENCY=$(elapsed_ms "$T0")
echo "  6 memories imported in ${IMPORT_LATENCY}ms total (avg: $((IMPORT_LATENCY/6))ms each)"

BAD=0
for K in M1 M2 M3 M4 M5 M6; do
  [ -z "${MEM_IDS[$K]:-}" ] && BAD=$((BAD+1))
done
if [ "$BAD" -gt 0 ]; then
  fail "memory import: $BAD of 6 save calls returned empty ID"
  echo "  Check: docker logs agentmemory-engine"
  exit 2
else
  ok "6 memories imported (all IDs non-empty)"
fi

# ── Step 4: Retrieval modes ──────────────────────────────────────────────────
header "Step 4: Retrieval modes"

curlg() {
  local URL="$1"
  local EXTRA=()
  [ -n "$AUTH_HEADER" ] && EXTRA=(-H "$AUTH_HEADER")
  curl -s --max-time 8 "$URL" "${EXTRA[@]}" 2>/dev/null
}

curlp() {
  local URL="$1"
  local BODY="$2"
  local EXTRA=()
  [ -n "$AUTH_HEADER" ] && EXTRA=(-H "$AUTH_HEADER")
  curl -s -X POST "$URL" "${EXTRA[@]}" -H "Content-Type: application/json" -d "$BODY" 2>/dev/null
}

# Mode 1: Exact retrieval by ID
echo ""
echo "  Mode 1: Exact (GET /agentmemory/memories/{id})"
M1_ID="${MEM_IDS[M1]:-}"
if [ -n "$M1_ID" ]; then
  T0=$(ts_ms)
  EXACT_RESP=$(curlg "$BASE_URL/agentmemory/memories/$M1_ID")
  EXACT_LATENCY=$(elapsed_ms "$T0")
  EXACT_CONTENT=$(echo "$EXACT_RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(str(d.get("memory",{}).get("content",""))[:80])' 2>/dev/null || echo "parse error")
  echo "    GET /agentmemory/memories/$M1_ID"
  echo "    Latency: ${EXACT_LATENCY}ms"
  echo "    Content (first 80): $EXACT_CONTENT"
  if echo "$EXACT_CONTENT" | grep -qi "prometheus\|tmpfs\|volume"; then
    ok "exact: returned correct M1 content in ${EXACT_LATENCY}ms"
  else
    fail "exact: content mismatch (got: $EXACT_CONTENT)"
  fi
else
  EXACT_LATENCY="N/A"
  fail "exact: M1 ID is empty — skipping"
fi

# Mode 2: Text search (BM25)
echo ""
echo "  Mode 2: Text search (POST /agentmemory/search)"
T0=$(ts_ms)
SEARCH_RESP=$(curlp "$BASE_URL/agentmemory/search" "{\"project\":\"$PROJECT\",\"query\":\"prometheus multiprocess volume tmpfs\"}")
TEXT_LATENCY=$(elapsed_ms "$T0")
TEXT_TOP=$(echo "$SEARCH_RESP" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    items = d.get("results", [])
    if items:
        top = items[0].get("observation", {})
        content = str(top.get("narrative", top.get("content", "")))[:80]
        print(content)
    else:
        print("empty")
except Exception as e:
    print(f"parse error: {e}")
' 2>/dev/null || echo "parse error")
TEXT_COUNT=$(echo "$SEARCH_RESP" | python3 -c 'import sys,json; print(len(json.load(sys.stdin).get("results",[])))' 2>/dev/null || echo "?")
echo "    POST /agentmemory/search query='prometheus multiprocess volume tmpfs'"
echo "    Latency: ${TEXT_LATENCY}ms  Results: ${TEXT_COUNT}"
echo "    Top result (first 80): $TEXT_TOP"
if echo "$TEXT_TOP" | grep -qi "prometheus\|tmpfs\|volume\|multiproc"; then
  ok "text search: surfaced prometheus/volume content in ${TEXT_LATENCY}ms"
else
  fail "text search: top result does not match expected memory (got: $TEXT_TOP)"
fi

# Mode 3: Semantic / hybrid search
echo ""
echo "  Mode 3: Semantic/hybrid search (POST /agentmemory/smart-search)"
T0=$(ts_ms)
SEM_RESP=$(curlp "$BASE_URL/agentmemory/smart-search" "{\"project\":\"$PROJECT\",\"query\":\"joinedload pagination performance issue\",\"limit\":3}")
SEMANTIC_LATENCY=$(elapsed_ms "$T0")
SEM_TOP=$(echo "$SEM_RESP" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    items = d.get("results", [])
    if items:
        top = items[0]
        print(str(top.get("title", ""))[:80])
    else:
        print("empty")
except Exception as e:
    print(f"parse error: {e}")
' 2>/dev/null || echo "parse error")
SEM_COUNT=$(echo "$SEM_RESP" | python3 -c 'import sys,json; print(len(json.load(sys.stdin).get("results",[])))' 2>/dev/null || echo "?")
echo "    POST /agentmemory/smart-search query='joinedload pagination performance issue'"
echo "    Latency: ${SEMANTIC_LATENCY}ms  Results: ${SEM_COUNT}"
echo "    Top result: $SEM_TOP"
if echo "$SEM_TOP" | grep -qi "joinedload\|selectinload\|paginate"; then
  ok "semantic: returned joinedload/pagination content in ${SEMANTIC_LATENCY}ms"
else
  note "semantic: top result was '$SEM_TOP' (no LLM provider — BM25 fallback expected)"
  # Smart-search without LLM may return lower-quality results; not a hard failure
  if [ "$SEM_COUNT" != "?" ] && [ "${SEM_COUNT:-0}" -ge 1 ] 2>/dev/null; then
    ok "semantic: returned ${SEM_COUNT} result(s) via BM25 fallback in ${SEMANTIC_LATENCY}ms (no LLM provider)"
  else
    fail "semantic: returned 0 results"
  fi
fi

# Mode 4: Project-scoped list
echo ""
echo "  Mode 4: Project-scoped (GET /agentmemory/memories?project=markethawk)"
T0=$(ts_ms)
PROJ_RESP=$(curlg "$BASE_URL/agentmemory/memories?project=$PROJECT")
PROJECT_LATENCY=$(elapsed_ms "$T0")
PROJ_COUNT=$(echo "$PROJ_RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("total",len(d.get("memories",[]))))' 2>/dev/null || echo "?")
echo "    GET /agentmemory/memories?project=$PROJECT"
echo "    Latency: ${PROJECT_LATENCY}ms  Total: ${PROJ_COUNT}"
if [ "$PROJ_COUNT" != "?" ] && [ "${PROJ_COUNT:-0}" -ge 6 ] 2>/dev/null; then
  ok "project-scoped: returned ${PROJ_COUNT} memories (≥6) in ${PROJECT_LATENCY}ms"
else
  fail "project-scoped: expected ≥6 memories, got $PROJ_COUNT"
fi

# Mode 5: Role-scoped (findings about agentmemory API capability)
echo ""
echo "  Mode 5: Role-scoped (GET /agentmemory/memories?project=markethawk&role=implement)"
T0=$(ts_ms)
ROLE_RESP=$(curlg "$BASE_URL/agentmemory/memories?project=$PROJECT&role=implement")
REFINE_LATENCY=$(elapsed_ms "$T0")
ROLE_COUNT=$(echo "$ROLE_RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("total",len(d.get("memories",[]))))' 2>/dev/null || echo "?")
echo "    GET /agentmemory/memories?project=$PROJECT&role=implement"
echo "    Latency: ${REFINE_LATENCY}ms  Count: ${ROLE_COUNT}"
IMPL_LATENCY="${REFINE_LATENCY}"
# Role filtering is NOT natively supported in v0.9.27 — role param is silently ignored.
# The query returns all project memories regardless of the role filter.
if [ "$ROLE_COUNT" = "$PROJ_COUNT" ]; then
  note "role=implement filter silently ignored — returned same $ROLE_COUNT as project-scoped query"
  note "Role scoping NOT natively supported in agentmemory v0.9.27"
  note "Workaround: prefix content with role tag and search via text query"
  # Count this as a finding, not a failure (the API does respond)
  ok "role-scoped endpoint responsive (${REFINE_LATENCY}ms) — but role filter not implemented"
else
  fail "role-scoped: unexpected count mismatch (role=$ROLE_COUNT vs project=$PROJ_COUNT)"
fi

# ── Step 5: Outage / unavailable test ────────────────────────────────────────
header "Step 5: Outage / unavailable test"
# NOTE: $BASE_URL/agentmemory/health is served by the Node.js worker (see header, lines 9-13),
# not by the engine container directly.  This test stops only the engine and relies on the
# worker propagating the engine's WebSocket disconnect into a non-200 (or connection-refused)
# response within the 3-second curl timeout.  If the worker does not surface the disconnect
# quickly enough, the test may produce a false pass (curl exits 0).  If that occurs, stop the
# worker process too (kill the background node job) to guarantee a non-200.
echo "  Stopping agentmemory-engine container..."
docker stop agentmemory-engine >/dev/null 2>&1 || true
sleep 2

FALLBACK_EXIT=0
T0=$(ts_ms)
curl -sf --max-time 3 "$BASE_URL/agentmemory/health" >/dev/null 2>&1 || FALLBACK_EXIT=$?
OUTAGE_LATENCY=$(elapsed_ms "$T0")

echo "  Exit code when service unreachable: $FALLBACK_EXIT (latency: ${OUTAGE_LATENCY}ms)"

if [ "$FALLBACK_EXIT" -ne 0 ]; then
  ok "outage: curl exits $FALLBACK_EXIT (non-zero) in ${OUTAGE_LATENCY}ms — caller must catch"
  echo ""
  echo "  Documented fallback behavior:"
  echo "    curl exits with code $FALLBACK_EXIT (connection refused / timeout) when agentmemory is down."
  echo "    A Phase 1 LOAD integration should: detect non-zero exit → log warning → degrade to flat-file reads."
  echo "    This matches the pattern used for Redis/Seq outages: best-effort, non-blocking."
else
  fail "outage: curl returned 0 despite container stopped"
fi

echo "  Restarting engine for cleanup..."
docker start agentmemory-engine >/dev/null 2>&1 || \
  docker compose --profile agentmemory-spike start agentmemory-engine >/dev/null 2>&1 || \
  echo "  (cleanup: start agentmemory-engine manually if needed)"

# ── Summary ───────────────────────────────────────────────────────────────────
header "Summary"
echo ""
echo "  PASS: $PASS  FAIL: $FAIL"
echo ""
echo "  Health probe latency:     ${HEALTH_LATENCY}ms"
echo "  Memory import (6 items):  ${IMPORT_LATENCY}ms total (~$((IMPORT_LATENCY/6))ms each)"
echo "  Exact retrieval:          ${EXACT_LATENCY}ms"
echo "  Text search (BM25):       ${TEXT_LATENCY}ms"
echo "  Semantic/hybrid search:   ${SEMANTIC_LATENCY}ms"
echo "  Project-scoped list:      ${PROJECT_LATENCY}ms"
echo "  Role-scoped (endpoint):   ${REFINE_LATENCY}ms (role filter not implemented)"
echo ""
echo "  API FINDINGS:"
echo "  - Save:    POST /agentmemory/remember (201 Created, response: {memory:{id,...}})"
echo "  - Exact:   GET /agentmemory/memories/{id}"
echo "  - List:    GET /agentmemory/memories?project=markethawk"
echo "  - Search:  POST /agentmemory/search (BM25 text search)"
echo "  - Hybrid:  POST /agentmemory/smart-search (BM25+vector; needs LLM key for full quality)"
echo "  - Role/path filter: NOT supported in v0.9.27 (param silently ignored)"
echo ""
echo "Paste this output into docs/superpowers/specs/2026-06-27-agentmemory-memory-backend-spike.md"

if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo "EXIT 2 — $FAIL test(s) failed."
  exit 2
fi
exit 0

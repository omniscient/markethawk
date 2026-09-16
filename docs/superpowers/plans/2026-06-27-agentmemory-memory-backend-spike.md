# Plan: Memory Backend Spike — Evaluate agentmemory

**Issue:** #644  
**Spec:** `docs/superpowers/specs/2026-06-27-agentmemory-memory-backend-spike.md`  
**Date:** 2026-06-27  
**Size:** S  

## Goal

Evaluate `rohitg00/agentmemory` as a potential structured/indexed backend for the Dark Factory's
flat-file memory system (`.archon/memory/*.md`). Deliverables: a profile-gated compose service,
a runnable eval script exercising all five retrieval modes, and a filled-in spec with a verdict
on whether the existing `[AVOID]` architecture entry (expires 2026-12-02) should stand, be amended,
or be retired. Zero production Dark Factory behavior changes.

## Architecture

The spike adds `agentmemory` as a `profiles: [agentmemory-spike]` service — the same pattern used
for `factory`, `scheduler`, `tls`, and `forecasting`. It never starts in a default
`docker compose up -d` and adds no operational overhead to any existing service.

The factory container is on both `factory-network` and `stockscanner-network`, so after starting
the profile service the factory can reach `http://agentmemory:8000` directly. The eval script
uses `AGENTMEMORY_URL` env var to support both host invocation (default `http://localhost:6789`)
and factory invocation (`AGENTMEMORY_URL=http://agentmemory:8000`).

> **[AVOID] note** (`architecture.md`): The existing "Do not introduce a vector database,
> embedding model, or semantic search service for memory retrieval" entry is deliberately being
> tested here. This spike is the designated input for the 2026-12-02 renewal decision. The plan
> does NOT adopt agentmemory into production — it only evaluates it in isolation.

## Tech Stack

- **Shell**: bash 5+, `curl`, `python3 -m json.tool`
- **Docker**: `docker compose --profile agentmemory-spike`
- **No new Python packages** — only stdlib

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `docker-compose.yml` | Edit | Add `agentmemory-spike` profile service |
| `dark-factory/scripts/eval_agentmemory.sh` | Create | Eval script (all 5 retrieval modes + outage test) |
| `docs/superpowers/specs/2026-06-27-agentmemory-memory-backend-spike.md` | Edit | Fill in Results + Verdict sections |

---

## Task 1: Research upstream and add compose profile

**Files:** `docker-compose.yml`  
**Time:** ~10 min

### Steps

**1a. Research agentmemory upstream**

Browse `https://github.com/rohitg00/agentmemory` to confirm:

| Question | Default in spec | Where to check |
|----------|----------------|----------------|
| Docker image tag | `rohitg00/agentmemory:latest` | GitHub releases / Docker Hub tags |
| Internal HTTP port | `8000` | README or Dockerfile EXPOSE |
| Auth mechanism | None / API key | README "Authentication" section |
| Health probe path | `/agentmemory/health` | README or `/docs` OpenAPI |
| Memory save endpoint | `POST /agentmemory` | README or OpenAPI |
| Exact retrieval | `GET /agentmemory/{id}` | README or OpenAPI |
| Semantic search | `POST /agentmemory/search` | README or OpenAPI |
| Filtered retrieval | `GET /agentmemory?project=&role=&path=` | README or OpenAPI |
| Persistent storage | in-memory vs volume | README or env vars |
| Semantic backend | local model vs OpenAI key | README "Configuration" |

If semantic search requires an external API key (e.g. `OPENAI_API_KEY`), add it to the compose
`environment:` block using the env var name from upstream docs. If the service is fully in-memory
(no volume needed), no `volumes:` entry is required.

**1b. Write failing test (verify no service yet)**

```bash
curl -s --max-time 2 http://localhost:6789/agentmemory/health || echo "EXIT $? — expected: service not running"
```

Expected output: `curl: (7) Failed to connect to localhost port 6789` or `EXIT 7`.

**1c. Add compose service block**

Add to `docker-compose.yml` immediately before the `volumes:` section (line ~771), following the
`tls` profile pattern. Use `127.0.0.1:6789:8000` — the Docker Port Hardening pattern requires
all host-facing bindings to use `127.0.0.1:HOST:CONTAINER` format.

```yaml
  # agentmemory — spike evaluation only, never starts in default stack
  # Start with: docker compose --profile agentmemory-spike up -d agentmemory
  # Remove profile or edit docker-compose.yml when spike is complete.
  agentmemory:
    image: rohitg00/agentmemory:latest  # pin to confirmed tag from Task 1a
    container_name: agentmemory
    profiles:
      - agentmemory-spike
    ports:
      - "127.0.0.1:6789:8000"           # update internal port if Task 1a finds a different value
    environment:
      AGENTMEMORY_PROJECT: markethawk
      # OPENAI_API_KEY: ${OPENAI_API_KEY:-}  # uncomment if semantic search requires it (Task 1a)
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/agentmemory/health"]
      interval: 10s
      timeout: 5s
      retries: 3
    networks:
      - stockscanner-network
    deploy:
      resources:
        limits:
          memory: 512M
```

> **Update if different**: If Task 1a shows the internal port is not 8000, update both the
> `ports:` host mapping and the healthcheck URL. If the health probe path is different, update
> the healthcheck `test:` command and the `BASE_URL/...health` call in the eval script.

**1d. Start service and verify health (implement → green)**

```bash
docker compose --profile agentmemory-spike up -d agentmemory
# Wait for health check to pass (up to 30s)
for i in $(seq 1 6); do
  STATUS=$(docker inspect --format '{{.State.Health.Status}}' agentmemory 2>/dev/null || echo "absent")
  echo "[$i] health: $STATUS"
  [ "$STATUS" = "healthy" ] && break
  sleep 5
done

curl -s http://localhost:6789/agentmemory/health | python3 -m json.tool
```

Expected: HTTP 200, JSON payload (structure varies by upstream).

**1e. Commit**

```bash
git add docker-compose.yml
git commit -m "spike(#644): add agentmemory-spike compose profile for eval"
```

---

## Task 2: Write eval_agentmemory.sh

**Files:** `dark-factory/scripts/eval_agentmemory.sh`  
**Time:** ~15 min

### Steps

**2a. Write failing test (verify script rejects a down service)**

```bash
# With agentmemory stopped:
docker compose --profile agentmemory-spike stop agentmemory 2>/dev/null || true
bash dark-factory/scripts/eval_agentmemory.sh 2>&1 | head -5 || true
```

Expected: file not found (script not written yet) or exit 1 with connection error.

**2b. Write eval script**

Create `dark-factory/scripts/eval_agentmemory.sh`:

```bash
#!/usr/bin/env bash
# Evaluation script for rohitg00/agentmemory spike (#644).
# Usage:
#   # From host (agentmemory-spike profile running):
#   bash dark-factory/scripts/eval_agentmemory.sh
#
#   # From factory container (agentmemory on stockscanner-network):
#   AGENTMEMORY_URL=http://agentmemory:8000 bash dark-factory/scripts/eval_agentmemory.sh
#
# Prerequisites:
#   docker compose --profile agentmemory-spike up -d agentmemory
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

ts_ms() { python3 -c "import time; print(int(time.time() * 1000))"; }

header() { echo ""; echo "=== $* ==="; }
ok()     { echo "  PASS: $*"; PASS=$((PASS+1)); }
fail()   { echo "  FAIL: $*"; FAIL=$((FAIL+1)); }

# ── Step 1: Health check ─────────────────────────────────────────────────────
header "Step 1: Health check"
T0=$(ts_ms)
HTTP_CODE=$(curl -s -o /tmp/am_health.json -w "%{http_code}" \
  --max-time 5 "$BASE_URL/agentmemory/health" 2>/dev/null || echo "000")
T1=$(ts_ms)
HEALTH_LATENCY=$((T1-T0))

if [ "$HTTP_CODE" != "200" ]; then
  echo "FAIL: health check returned HTTP $HTTP_CODE (expected 200)."
  echo "Is agentmemory running? Start with:"
  echo "  docker compose --profile agentmemory-spike up -d agentmemory"
  echo "Or if running in factory:"
  echo "  AGENTMEMORY_URL=http://agentmemory:8000 bash $0"
  exit 1
fi

ok "health probe HTTP $HTTP_CODE in ${HEALTH_LATENCY}ms"
echo "  Payload: $(cat /tmp/am_health.json | python3 -m json.tool 2>/dev/null || cat /tmp/am_health.json)"

# Extract auth mechanism from health payload (best-effort)
AUTH_MECHANISM=$(cat /tmp/am_health.json | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(d.get('auth','none'))" 2>/dev/null || echo "unknown")
echo "  Auth mechanism: $AUTH_MECHANISM"

# ── Step 2: Import 6 representative memories ────────────────────────────────
header "Step 2: Import representative memories"
declare -a MEMORY_IDS

save_mem() {
  local content="$1" role="$2" path_tag="${3:-}"
  local body
  body=$(python3 - "$content" "$role" "$path_tag" <<'PYEOF'
import json, sys
content, role, path_tag = sys.argv[1], sys.argv[2], sys.argv[3]
d = {"content": content, "project": "markethawk", "role": role}
if path_tag:
    d["path"] = path_tag
print(json.dumps(d))
PYEOF
  )
  T0=$(ts_ms)
  RESP=$(curl -sf -X POST "$BASE_URL/agentmemory" \
    -H "Content-Type: application/json" \
    -d "$body" 2>/dev/null) || { echo "ERROR: save failed for role=$role"; exit 2; }
  T1=$(ts_ms)
  MID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
  echo "  Saved [role=$role path=${3:-none}] id=$MID latency=$((T1-T0))ms"
  echo "$MID"
}

# 5 memories from dark-factory-ops.md + codebase-patterns.md
M1=$(save_mem \
  "[AVOID] Never define a Docker named volume with driver_opts: type: tmpfs for cross-container sharing — Docker tmpfs mounts are per-container; each container that mounts the volume gets its own independent tmpfs, making writes from one container invisible to another. Use a regular named volume for shared-directory patterns." \
  "implement" "docker-compose.yml")
MEMORY_IDS+=("$M1")

M2=$(save_mem \
  "[PATTERN] Preview builds in the factory must use docker buildx build --builder remote tcp://buildkit:1234 --load (not compose up --build). BuildKit's gRPC build session needs an HTTP connection-hijack that HAProxy docker-socket-proxy cannot forward (403 on any --build over the proxy)." \
  "implement" "dark-factory/")
MEMORY_IDS+=("$M2")

M3=$(save_mem \
  "[PATTERN] Gate commands (conformance, code-review, validate) that need route_memory_file(), write_memory_entry(), or emit_verdict() must source dark-factory/scripts/gate_lib.sh at Phase 1 LOAD. Do NOT add set -euo pipefail in gate_lib.sh — it is sourced, not executed." \
  "implement" "dark-factory/scripts/")
MEMORY_IDS+=("$M3")

M4=$(save_mem \
  "[PATTERN] When building memory context for a subagent prompt, load only the files relevant to the component area (e.g. backend changes → backend-patterns.md; dark factory ops → dark-factory-ops.md). Loading all memory files unconditionally bloats the prompt and dilutes signal." \
  "refine" "")
MEMORY_IDS+=("$M4")

M5=$(save_mem \
  "[PATTERN] All dispatch() call sites in scheduler.sh must use 'if dispatch ...; then ... fi' guards. A bare dispatch under set -e exits the daemon on non-zero return, triggering restart:unless-stopped and wiping the retry counter — root cause of the #159 loop." \
  "implement" "scheduler.sh")
MEMORY_IDS+=("$M5")

M6=$(save_mem \
  "[PATTERN] Agent memory is stored as plain markdown files in .archon/memory/, committed to the repo. Files are read at Phase 1 load time and updated post-run. Human-readable, version-controlled, accessible to all agents without extra tooling." \
  "refine" ".archon/memory/")
MEMORY_IDS+=("$M6")

ok "Imported ${#MEMORY_IDS[@]} memories. IDs: ${MEMORY_IDS[*]}"

# ── Step 3: All five retrieval modes ────────────────────────────────────────
header "Step 3: Retrieval modes"

# Mode 1: Exact
echo "-- Mode 1: Exact (GET by ID) --"
T0=$(ts_ms)
EXACT=$(curl -s "$BASE_URL/agentmemory/${MEMORY_IDS[0]}" 2>/dev/null)
T1=$(ts_ms)
EXACT_LATENCY=$((T1-T0))
if echo "$EXACT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('id') or d.get('content')" 2>/dev/null; then
  ok "exact retrieval: ${EXACT_LATENCY}ms"
else
  fail "exact retrieval returned unexpected payload"
  echo "  Response: $EXACT"
fi
echo "  Sample: $(echo "$EXACT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(str(d)[:120])" 2>/dev/null || echo "$EXACT" | head -c 120)"

# Mode 2: Semantic search
echo "-- Mode 2: Semantic (free-text similarity) --"
T0=$(ts_ms)
SEMANTIC=$(curl -sf -X POST "$BASE_URL/agentmemory/search" \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"How should I avoid Docker tmpfs issues when sharing data between containers?\", \"project\": \"$PROJECT\"}" \
  2>/dev/null || echo '{"results":[]}')
T1=$(ts_ms)
SEMANTIC_LATENCY=$((T1-T0))
SEMANTIC_COUNT=$(echo "$SEMANTIC" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); r=d.get('results',d) if isinstance(d,dict) else d; print(len(r))" 2>/dev/null || echo "?")
if [ "$SEMANTIC_COUNT" != "?" ] && [ "$SEMANTIC_COUNT" -gt 0 ] 2>/dev/null; then
  ok "semantic search: ${SEMANTIC_LATENCY}ms, $SEMANTIC_COUNT result(s)"
else
  fail "semantic search returned 0 results or unexpected payload (latency: ${SEMANTIC_LATENCY}ms)"
  echo "  Response: $(echo "$SEMANTIC" | head -c 200)"
fi
TOP_SEMANTIC=$(echo "$SEMANTIC" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); r=d.get('results',d) if isinstance(d,dict) else d; print(r[0].get('content','')[:100] if r else 'none')" 2>/dev/null || echo "parse error")
echo "  Top result: $TOP_SEMANTIC"

# Mode 3: Path-scoped
echo "-- Mode 3: Path-scoped (path=dark-factory/scripts/) --"
T0=$(ts_ms)
PATH_RESULTS=$(curl -s \
  "$BASE_URL/agentmemory?project=${PROJECT}&path=dark-factory%2Fscripts%2F" 2>/dev/null)
T1=$(ts_ms)
PATH_LATENCY=$((T1-T0))
PATH_COUNT=$(echo "$PATH_RESULTS" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else d.get('count',len(d.get('results',[]))))" 2>/dev/null || echo "?")
if [ "$PATH_COUNT" != "?" ] && [ "$PATH_COUNT" -gt 0 ] 2>/dev/null; then
  ok "path-scoped: ${PATH_LATENCY}ms, $PATH_COUNT result(s)"
else
  fail "path-scoped returned 0 or unexpected payload (latency: ${PATH_LATENCY}ms)"
fi
echo "  path=dark-factory/scripts/ count: $PATH_COUNT"

# Mode 4: Project-scoped
echo "-- Mode 4: Project-scoped (project=markethawk) --"
T0=$(ts_ms)
PROJECT_RESULTS=$(curl -s "$BASE_URL/agentmemory?project=${PROJECT}" 2>/dev/null)
T1=$(ts_ms)
PROJECT_LATENCY=$((T1-T0))
PROJECT_COUNT=$(echo "$PROJECT_RESULTS" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else d.get('count',len(d.get('results',[]))))" 2>/dev/null || echo "?")
if [ "$PROJECT_COUNT" != "?" ] && [ "$PROJECT_COUNT" -ge 6 ] 2>/dev/null; then
  ok "project-scoped: ${PROJECT_LATENCY}ms, $PROJECT_COUNT result(s) (expect ≥6)"
else
  fail "project-scoped: expected ≥6 results, got $PROJECT_COUNT (latency: ${PROJECT_LATENCY}ms)"
fi
echo "  project=markethawk count: $PROJECT_COUNT"

# Mode 5a: Role-scoped — refine
echo "-- Mode 5a: Role-scoped (role=refine) --"
T0=$(ts_ms)
REFINE_RESULTS=$(curl -s "$BASE_URL/agentmemory?project=${PROJECT}&role=refine" 2>/dev/null)
T1=$(ts_ms)
REFINE_LATENCY=$((T1-T0))
REFINE_COUNT=$(echo "$REFINE_RESULTS" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else d.get('count',len(d.get('results',[]))))" 2>/dev/null || echo "?")
# Expect 2 refine memories (M4: memory loading, M6: flat-file pattern)
if [ "$REFINE_COUNT" != "?" ] && [ "$REFINE_COUNT" -ge 2 ] 2>/dev/null; then
  ok "role=refine: ${REFINE_LATENCY}ms, $REFINE_COUNT result(s) (expect ≥2)"
else
  fail "role=refine: expected ≥2 results, got $REFINE_COUNT (latency: ${REFINE_LATENCY}ms)"
fi
echo "  role=refine count: $REFINE_COUNT"

# Mode 5b: Role-scoped — implement
echo "-- Mode 5b: Role-scoped (role=implement) --"
T0=$(ts_ms)
IMPL_RESULTS=$(curl -s "$BASE_URL/agentmemory?project=${PROJECT}&role=implement" 2>/dev/null)
T1=$(ts_ms)
IMPL_LATENCY=$((T1-T0))
IMPL_COUNT=$(echo "$IMPL_RESULTS" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else d.get('count',len(d.get('results',[]))))" 2>/dev/null || echo "?")
# Expect 4 implement memories (M1-M3, M5)
if [ "$IMPL_COUNT" != "?" ] && [ "$IMPL_COUNT" -ge 4 ] 2>/dev/null; then
  ok "role=implement: ${IMPL_LATENCY}ms, $IMPL_COUNT result(s) (expect ≥4)"
else
  fail "role=implement: expected ≥4 results, got $IMPL_COUNT (latency: ${IMPL_LATENCY}ms)"
fi
echo "  role=implement count: $IMPL_COUNT"

# ── Step 4: Outage / fallback test ──────────────────────────────────────────
header "Step 4: Outage/fallback test"
echo "Stopping agentmemory container..."
docker stop agentmemory >/dev/null 2>&1 || docker compose --profile agentmemory-spike stop agentmemory >/dev/null 2>&1 || true
sleep 2

FALLBACK_EXIT=0
curl -sf --max-time 3 "$BASE_URL/agentmemory/health" >/dev/null 2>&1 || FALLBACK_EXIT=$?
echo "  Exit code when service unreachable: $FALLBACK_EXIT"

if [ "$FALLBACK_EXIT" -ne 0 ]; then
  ok "outage behavior: exit code $FALLBACK_EXIT (non-zero — caller must catch)"
  echo "  Documented fallback: if agentmemory is unreachable, curl exits non-zero."
  echo "  A Phase 1 LOAD integration should: detect exit $FALLBACK_EXIT → log warning → degrade to flat-file reads."
else
  fail "outage behavior: curl returned 0 despite container stopped — unexpected"
fi

echo "Restarting agentmemory for cleanup..."
docker start agentmemory >/dev/null 2>&1 || docker compose --profile agentmemory-spike start agentmemory >/dev/null 2>&1 || true

# ── Summary ──────────────────────────────────────────────────────────────────
header "Summary"
echo "  PASS: $PASS  FAIL: $FAIL"
echo ""
echo "  Health probe latency:        ${HEALTH_LATENCY}ms"
echo "  Exact retrieval latency:     ${EXACT_LATENCY}ms"
echo "  Semantic search latency:     ${SEMANTIC_LATENCY}ms"
echo "  Path-scoped latency:         ${PATH_LATENCY}ms"
echo "  Project-scoped latency:      ${PROJECT_LATENCY}ms"
echo "  Role=refine latency:         ${REFINE_LATENCY}ms"
echo "  Role=implement latency:      ${IMPL_LATENCY}ms"
echo ""
echo "Paste this output into docs/superpowers/specs/2026-06-27-agentmemory-memory-backend-spike.md Results section."

if [ "$FAIL" -gt 0 ]; then
  echo "EXIT 2 — $FAIL test(s) failed. See FAIL lines above."
  exit 2
fi
exit 0
```

**2c. Make executable and verify syntax**

```bash
chmod +x dark-factory/scripts/eval_agentmemory.sh
bash -n dark-factory/scripts/eval_agentmemory.sh && echo "syntax OK"
```

Expected: `syntax OK`

**2d. Run against stopped service (verify fail path)**

```bash
docker compose --profile agentmemory-spike stop agentmemory 2>/dev/null || true
bash dark-factory/scripts/eval_agentmemory.sh 2>&1 | head -10
echo "exit: $?"
```

Expected: exits 1 with message "FAIL: health check returned HTTP 000" and instructions to start the service.

**2e. Start service and run against live service (verify pass)**

```bash
docker compose --profile agentmemory-spike up -d agentmemory
# Wait for healthy
for i in $(seq 1 6); do
  S=$(docker inspect --format '{{.State.Health.Status}}' agentmemory 2>/dev/null || echo "absent")
  [ "$S" = "healthy" ] && echo "healthy" && break
  echo "[$i] $S — waiting..."; sleep 5
done

AGENTMEMORY_URL=http://agentmemory:8000 bash dark-factory/scripts/eval_agentmemory.sh 2>&1
echo "Exit code: $?"
```

Expected: all retrieval modes print results, `PASS: 8  FAIL: 0`, exit 0.

> **If semantic search requires an API key**: If `Mode 2: Semantic` fails with an auth error,
> check the agentmemory logs (`docker logs agentmemory`) for the required env var name and add
> it to the compose `environment:` block, then rebuild and re-run. The spec's acceptance criteria
> require semantic retrieval to work.

**2f. Commit**

```bash
git add dark-factory/scripts/eval_agentmemory.sh
git commit -m "spike(#644): add eval_agentmemory.sh — all five retrieval modes + outage test"
```

---

## Task 3: Run eval, fill in Results, write Verdict

**Files:** `docs/superpowers/specs/2026-06-27-agentmemory-memory-backend-spike.md`  
**Time:** ~10 min

### Steps

**3a. Ensure service is running and run eval**

```bash
# Confirm agentmemory is up
docker inspect --format '{{.State.Health.Status}}' agentmemory 2>/dev/null || \
  docker compose --profile agentmemory-spike up -d agentmemory

AGENTMEMORY_URL=http://agentmemory:8000 bash dark-factory/scripts/eval_agentmemory.sh \
  2>&1 | tee /tmp/eval_output.txt

echo "Exit: $?"
```

Expected: exit 0, /tmp/eval_output.txt contains full output with latency values and counts.

**3b. Fill in the Results section**

Open `docs/superpowers/specs/2026-06-27-agentmemory-memory-backend-spike.md` and replace the
`_TBD_` cells in the Results tables with values from `/tmp/eval_output.txt`:

**Health probe table** — extract from `Step 1` output:
```
Service start time    → time from compose up to healthy (measured during Task 1d)
GET /agentmemory/health status → HTTP code from Step 1
Auth mechanism        → auth value from Step 1
```

**Retrieval mode table** — extract from `Step 3` output:
```
exact        → EXACT_LATENCY, top result content[:60], Correct? (does it match M1 content?)
semantic     → SEMANTIC_LATENCY, top result[:60], Correct? (should surface M1 about tmpfs)
path-scoped  → PATH_LATENCY, result count and sample, Correct? (should return M3)
project-scoped → PROJECT_LATENCY, total count
role=refine  → REFINE_LATENCY, count (expect ≥2)
role=implement → IMPL_LATENCY, count (expect ≥4)
```

**Outage / unavailable** — extract from `Step 4` output:
```
Describe: "curl exits with code N; service connection refused. A Phase 1 LOAD integration
should catch the non-zero exit and degrade to flat-file reads without blocking the factory run."
```

**Developer ergonomics** — write observations:
```
- Setup: docker compose --profile flag, no code changes needed
- Memory format translation: entries must be converted from markdown free-text to JSON payload;
  no bulk-import or import-from-markdown tooling exists upstream (manual format mapping needed)
- Ongoing: entries written to .archon/memory/*.md would need a separate sync step to stay
  consistent with the agentmemory store; no git-native storage
- Entry count (2026-06-27): ~28 active entries — well within range where flat files are faster
```

**3c. Write the Verdict section**

Fill in the three Verdict fields based on eval output. For each recommendation option:

*"Adopt agentmemory — AVOID should be retired"* — use if:
- Semantic search surfaces the correct memory in top-3 results (correct=yes)
- All 5 retrieval modes passed
- Setup ergonomics are low-friction
- Startup time is < 5s and query latency is < 100ms

*"Adopt with scope limit — AVOID should be amended"* — use if:
- Exact/path/project/role retrieval works but semantic is unusable (wrong results or requires
  expensive external key)
- OR setup requires manual format translation that adds ongoing maintenance burden

*"Do not adopt — AVOID stands and should be renewed at 2026-12-02"* — use if:
- Semantic search does not return correct results
- OR any retrieval mode fails consistently
- OR the operational overhead (external API key, persistent volume, format translation) outweighs
  the retrieval precision improvement at < 200 entries

Fill in the reasoning with specific data from the eval:
```
**Reasoning:** "At N entries, exact retrieval latency was Xms vs ~0ms for grep. Semantic
search [returned/did not return] the expected memory for the test query. Setup required [N steps].
[Ongoing format translation / git-native storage loss] [is/is not] a meaningful overhead."

**Action on AVOID entry:** [renew / amend to allow structured-only / retire] at 2026-12-02
```

**3d. Stop the spike service (leave no running containers)**

```bash
docker compose --profile agentmemory-spike stop agentmemory
echo "agentmemory stopped"
```

**3e. Commit**

```bash
git add docs/superpowers/specs/2026-06-27-agentmemory-memory-backend-spike.md
git commit -m "spike(#644): fill in eval results and verdict for agentmemory evaluation"
```

---

## Constraints checklist (verify before final push)

- [ ] `scheduler.sh` unmodified: `git diff origin/main -- scheduler.sh` is empty
- [ ] `entrypoint.sh` unmodified: `git diff origin/main -- */entrypoint.sh` is empty
- [ ] `.archon/memory/*.md` unmodified: `git diff origin/main -- .archon/memory/` is empty
- [ ] No factory DAG node files changed: `git diff origin/main -- .archon/commands/ dark-factory/` covers only `dark-factory/scripts/eval_agentmemory.sh`
- [ ] `docker-compose.yml` change is profile-gated (no `profiles:` key omission)
- [ ] All new host port bindings use `127.0.0.1:HOST:CONTAINER` format

# Dark Factory — Hermes Agent Patterns: Agent Memory, Self-Interruption, Prompt Hardening

**Status:** design
**Date:** 2026-06-26
**Issue:** #609
**Build constraint:** Factory self-edit → **human-implemented** only. Changes to `scheduler.sh`,
`factory_core/breaker.py`, and `.archon/commands/dark-factory-implement.md` are baked; need
`docker compose build dark-factory backlog-scheduler` + `up --force-recreate backlog-scheduler`
to deploy.

## Problem

The dark factory dispatches a fresh container per ticket. Each run sees only the git-committed
`.archon/memory/*.md` files for cross-run context. The scheduler's `scheduler-state.json` tracks
bare retry counts but has no *credit assignment*: it cannot distinguish a transient rate-limit
retry from a cycle that hit the exact same logic error for the third time. This leads to:

1. **Blind retry loops** — the same broken prompt or OOS file causes three identical failures
   before the circuit-breaker trips, burning session budget with zero new information.
2. **Uninformative trip comments** — the circuit-breaker comment says "retry limit reached" with
   no indication of *why* the retries failed, making human diagnosis slow.
3. **No confidence signal** — the scheduler doesn't know whether the last dispatch decided
   "I'm stuck" vs "I made progress but hit a transient failure."

This issue evaluates Hermes Agent patterns (Nous Research, Feb 2026) and the Nie et al. 2026
credit-assignment framework to derive improvements that can be factory-implemented without external
dependencies.

## Decision

Enhance the existing architecture along three axes — no new Docker services, no changes to
per-ticket container dispatch model:

1. **Agent memory layer** — a new `agent-memory.json` on the shared `scheduler_state` volume,
   extending the scheduler's durable state with per-issue error fingerprints and decision metadata.
2. **Early self-interruption** — `factory_core/breaker.py` trips the circuit-breaker at attempt 2
   when the same error fingerprint recurs, rather than always waiting for attempt 3.
3. **Three concrete prompt hardening improvements** to `.archon/commands/dark-factory-implement.md`,
   derived from the Hermes/Nie et al. principles that can be implemented from in-repo context alone.

### Why not a true persistent daemon (Hermes-literal approach)

The `backlog-scheduler` container *is* the persistent daemon: it runs continuously under
`restart: unless-stopped`, maintains durable state across reboots, and accumulates per-cycle
knowledge. A "true persistent Claude Code session per ticket" would hold a WIP slot idle between
polls, conflict with `FACTORY_WIP_LIMIT`, and break the per-ticket container isolation that
preview stacks, OOS gates, and branch isolation all depend on. The spec targets enrichment of
what already works, not a rewrite.

### Why not reduce `MAX_RETRIES` globally to 2

That harms legitimate retries for genuinely transient failures (rate limits, flaky smoke tests,
GH API blips). The fingerprint-based early trip fires *only* when the same error recurs
identically — the third slot stays available for changed-error cases.

---

## Component 1: Agent Memory Layer

### File: `/var/lib/dark-factory/agent-memory.json`

Stored on the `scheduler_state` named volume (already mounted by both `dark-factory` and
`backlog-scheduler`). Owned and written by the scheduler; not committed to git.

**Schema:**

```json
{
  "issues": {
    "609": {
      "last_failure_fingerprint": "a3f1c9d2",
      "last_failure_type": "oos_files",
      "last_failure_at": "2026-06-26T10:28:55Z",
      "failures_by_type": {
        "oos_files": 2,
        "rate_limit": 1
      },
      "last_decision_confidence": "low",
      "last_decision_summary": "OOS gate excised 3 files; confidence low due to repeated scope spillover"
    }
  }
}
```

**Fields:**

| Field | Type | Purpose |
|---|---|---|
| `last_failure_fingerprint` | string (8-char hex) | MD5 prefix of normalized postmortem excerpt |
| `last_failure_type` | enum | Coarse error category (see below) |
| `last_failure_at` | ISO datetime | For TTL pruning |
| `failures_by_type` | object | Per-type failure count (credit assignment) |
| `last_decision_confidence` | `high`/`medium`/`low` | Written by implement agent (see Component 3) |
| `last_decision_summary` | string | Written by implement agent (see Component 3) |

### Error type taxonomy

```
rate_limit        — Polygon/GH API rate limit hit
oos_files         — OOS gate excised out-of-scope files; conformance blocked
build_failure     — docker build or alembic migration failed
test_failure      — pytest / tsc / smoke gate failure after implementation
unknown           — all other / unclassifiable
```

Classification runs inside the factory container (see Component 2). The scheduler reads the
type from the shared failure file after each dispatch exit.

---

## Component 2: Per-Issue Failure Bridge

The `factory-failures.jsonl` written by `entrypoint.sh:handle_failure()` goes to `$ARTIFACTS_DIR`
inside the container, which is not on the shared volume. To bridge to the scheduler, the
`handle_failure()` function in `entrypoint.sh` additionally writes a compact file to the shared
volume:

**Path:** `/var/lib/dark-factory/issue-<N>-last-failure.json`  
**Lifecycle:** overwritten on each failure; deleted by `reset_retry()` call on success.

**Content:**

```json
{
  "issue": 609,
  "phase": "implement",
  "fingerprint": "a3f1c9d2",
  "error_type": "oos_files",
  "postmortem_excerpt": "OOS gate excised backend/app/models/agent_state.py ...",
  "timestamp": "2026-06-26T10:28:55Z"
}
```

**Fingerprint computation** (in `entrypoint.sh`, pure bash):

```bash
# Strip timestamps, run-IDs, UUIDs from postmortem before hashing
_normalize() { sed 's/[0-9a-f]\{8\}-[0-9a-f]\{4\}-[0-9a-f]\{32\}//g; s/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}T[0-9:Z]*//g'; }
fingerprint=$(echo "$postmortem_excerpt" | _normalize | md5sum | cut -c1-8)
```

**Error type classification** (in `entrypoint.sh`, bash pattern match on postmortem):

```bash
classify_error() {
  local pm="$1"
  case "$pm" in
    *"rate limit"*|*"429"*|*"Too Many Requests"*)  echo "rate_limit" ;;
    *"OOS gate"*|*"excised"*|*"out-of-scope"*)      echo "oos_files" ;;
    *"docker build"*|*"alembic"*|*"migration"*)     echo "build_failure" ;;
    *"pytest"*|*"tsc"*|*"smoke"*|*"test fail"*)    echo "test_failure" ;;
    *)                                               echo "unknown" ;;
  esac
}
```

---

## Component 3: `factory_core/breaker.py` Extension

Three new functions added to `breaker.py`:

```python
AGENT_MEMORY_FILE = Path(
    os.environ.get("SCHEDULER_STATE_DIR", "/var/lib/dark-factory")
) / "agent-memory.json"


def read_agent_memory(state_dir: Path = AGENT_MEMORY_FILE.parent) -> dict:
    path = state_dir / "agent-memory.json"
    if not path.exists():
        return {"issues": {}}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"issues": {}}


def record_failure(
    issue_num: int,
    fingerprint: str,
    error_type: str,
    confidence: str = "unknown",
    summary: str = "",
    state_dir: Path = AGENT_MEMORY_FILE.parent,
) -> None:
    """Update agent-memory.json after a failed dispatch."""
    memory = read_agent_memory(state_dir)
    entry = memory["issues"].setdefault(str(issue_num), {
        "failures_by_type": {}
    })
    entry["last_failure_fingerprint"] = fingerprint
    entry["last_failure_type"] = error_type
    entry["last_failure_at"] = _utcnow()
    entry["failures_by_type"][error_type] = entry["failures_by_type"].get(error_type, 0) + 1
    if confidence != "unknown":
        entry["last_decision_confidence"] = confidence
    if summary:
        entry["last_decision_summary"] = summary
    path = state_dir / "agent-memory.json"
    _atomic_write(path, memory)


def should_trip_early(
    issue_num: int,
    fingerprint: str,
    state_dir: Path = AGENT_MEMORY_FILE.parent,
) -> bool:
    """Return True when the SAME fingerprint recurs — trip at attempt 2 instead of 3."""
    memory = read_agent_memory(state_dir)
    stored = memory.get("issues", {}).get(str(issue_num), {}).get("last_failure_fingerprint")
    return stored is not None and stored == fingerprint
```

**Integration in `scheduler.sh`** — after each non-zero `dispatch` exit:

```bash
# Read the failure bridge file written by the container
FAILURE_FILE="/var/lib/dark-factory/issue-${ISSUE}-last-failure.json"
if [ -f "$FAILURE_FILE" ]; then
  FINGERPRINT=$(python3 -c "import json,sys; d=json.load(open('$FAILURE_FILE')); print(d.get('fingerprint',''))")
  ERROR_TYPE=$(python3 -c "import json,sys; d=json.load(open('$FAILURE_FILE')); print(d.get('error_type','unknown'))")
  
  if python3 -c "
import sys; sys.path.insert(0,'$CLONE_DIR/dark-factory/scripts')
from factory_core.breaker import should_trip_early
sys.exit(0 if should_trip_early($ISSUE, '$FINGERPRINT') else 1)
"; then
    # Same error recurred — trip early with informative reason
    python3 ... record_failure(...)
    trip_to_blocked "$ISSUE" "implement" \
      "same error recurred (type: ${ERROR_TYPE}, fingerprint: ${FINGERPRINT})"
    continue
  fi
  python3 ... record_failure(...)
fi
increment_retry "$ISSUE"
```

### `trip_to_blocked` enrichment

The `trip_to_blocked()` function in `breaker.py` gains an optional `error_type` and
`fingerprint` parameter. When set, the circuit-breaker comment includes:

```
**Error type:** oos_files (recurred 2 times)
**Fingerprint:** a3f1c9d2 — same failure as previous attempt
```

---

## Component 4: Prompt Hardening (3 Improvements)

These are concrete additions to `.archon/commands/dark-factory-implement.md`. All are derivable
from in-repo context; they do NOT require the Hermes article to be fetched.

### Improvement 1: Stuck Detection / Self-Assessment Block

Added to **Phase 2: CONTEXT (after loading issue details)**, before planning begins:

```markdown
## Stuck Detection (Phase 1.5)

1. Read the last 3 GitHub comments on this issue:
   ```bash
   gh issue view $ISSUE_NUM --repo omniscient/markethawk --json comments \
     --jq '.comments[-3:].[].body' 2>/dev/null
   ```
2. If 2+ comments are factory failure comments (contain "Refinement Pipeline — Failed"
   or "Circuit-Breaker Tripped" or exit-code lines), extract the postmortem excerpts.
3. Compare: are the excerpts substantially similar (same root error, same file, same OOS gate)?
   - YES → post a "I am stuck" comment (see template below), add `needs-discussion` label,
     exit 0 (clean exit, not a failure). The scheduler will move the issue to Blocked; a human
     diagnosis is needed.
   - NO → prior failures were different; proceed with implementation.

**"I am stuck" comment template:**
> ## Implementation Agent — Self-Interruption
>
> I detected that the prior **{N} failures shared the same root cause** and that another
> attempt would likely hit the same error. Rather than burning another session, I am escalating.
>
> **Root cause pattern:** {one-sentence summary of the recurring error}
> **Relevant prior failure excerpt:** {excerpt}
>
> **To resume:** Address the root cause above, remove the `needs-discussion` label.
```

### Improvement 2: Confidence Reporting

Added to **Phase: COMMIT (before the final commit)** in `dark-factory-implement.md`:

```markdown
## Confidence Report (pre-commit)

Before committing, write a brief self-assessment to `$ARTIFACTS_DIR/decision.json`:

```bash
cat > "$ARTIFACTS_DIR/decision.json" << CONFIDENCE_EOF
{
  "confidence": "<high|medium|low>",
  "decision_summary": "<1-sentence summary of what was implemented>",
  "risk_factors": ["<risk 1>", "<risk 2>"]
}
CONFIDENCE_EOF
```

**Confidence levels:**
- `high`: implementation is straightforward, all tests pass, no scope ambiguity
- `medium`: minor uncertainties (e.g. edge case not covered by tests, one assumption made)
- `low`: significant uncertainty, workaround applied, or approach deviates from the spec

The scheduler reads this file on success to populate `agent-memory.json` and surface it in
status reports. A `low`-confidence implementation that later fails will carry the confidence
signal in its trip comment to guide human diagnosis.
```

### Improvement 3: Prior-Error Context Preamble

Added to **Phase 1: LOAD** in `dark-factory-implement.md`, after memory files are loaded:

```markdown
## Prior Failure Context (Phase 1, step 11)

Check for a prior-failure bridge file written by the scheduler:

```bash
PRIOR_FAILURE="/var/lib/dark-factory/issue-${ISSUE_NUM}-last-failure.json"
if [ -f "$PRIOR_FAILURE" ]; then
  PRIOR_TYPE=$(python3 -c "import json; print(json.load(open('$PRIOR_FAILURE'))['error_type'])")
  PRIOR_EXCERPT=$(python3 -c "import json; print(json.load(open('$PRIOR_FAILURE'))['postmortem_excerpt'][:300])")
  echo "PRIOR FAILURE TYPE: $PRIOR_TYPE"
  echo "PRIOR EXCERPT: $PRIOR_EXCERPT"
fi
```

Include the prior error type and excerpt in your context. Do NOT repeat the same action that
produced the prior error. If the prior error was `oos_files`, double-check your planned file
changes against the OOS allowlist before writing a single line of code. If `test_failure`,
read the prior test output carefully before re-running tests.
```

---

## Out of Scope (v1)

The following deliverables from the original issue are **explicitly deferred**:

- **17-prompt Hermes research** — The factory cannot browse external URLs (X/Twitter) and has
  no WebFetch/WebSearch MCP configured. This is a **human task**: the product owner should paste
  a summary of the Hermes article into a GitHub comment on issue #609. Any additional prompt
  improvements identified from the full 17 prompts can be filed as a follow-on issue.
- **Persistent agent daemon (Hermes-literal)** — Ruled out by architecture constraints (see
  Decision section above). The scheduler IS the persistent daemon.
- **Confidence.json → QualityGate integration** — Out of scope for v1; future enhancement.

---

## Alternatives Considered

| Alternative | Verdict |
|---|---|
| True persistent Claude Code daemon per ticket | Rejected: breaks container-isolation model; WIP-limit conflicts |
| Error fingerprinting from GitHub comment content | Rejected: comment posting can fail under rate limits; `factory-failures.jsonl` more reliable |
| Global `MAX_RETRIES=2` reduction | Rejected: harms transient-failure retry cases (rate limits, smoke flakiness) |
| Embedding `agent-memory.json` in git repo | Rejected: per-run state pollutes git history; volume-only is correct |

---

## Assumptions

- [A1] The `scheduler_state` volume at `/var/lib/dark-factory` is writable by both `dark-factory`
  and `backlog-scheduler` containers — confirmed in `docker-compose.yml`.
- [A2] `entrypoint.sh:handle_failure()` is the sole failure exit path — any new failure path
  added later must also write the bridge file.
- [A3] The Hermes article and 17-prompt content are available out-of-band to the product owner;
  implementation does not depend on fetching them.
- [A4] The Nie et al. paper's credit-assignment principle is satisfied by per-issue
  `failures_by_type` tracking in `agent-memory.json` — each cycle is no longer treated as
  independent.

---

## Open Questions (non-blocking)

- **Bridge file TTL**: Should the per-issue bridge file (`issue-N-last-failure.json`) be cleaned
  up after a successful run? Recommended yes — add cleanup to `reset_retry()`. Not blocking.
- **Memory pruning**: `agent-memory.json` will accumulate stale entries for long-closed issues.
  A TTL of 90 days post-last-failure is reasonable; implement in a scheduled cleanup or at
  `read_agent_memory()` read time. Not blocking for v1.
- **Confidence field visibility**: Should `last_decision_confidence` be surfaced in the board
  comment when the scheduler moves a ticket to Done? Nice-to-have for v2.

---

## Files Changed

| File | Change |
|---|---|
| `dark-factory/entrypoint.sh` | `handle_failure()`: add bridge file write + fingerprint + classify_error |
| `dark-factory/scripts/factory_core/breaker.py` | Add `read_agent_memory`, `record_failure`, `should_trip_early`; extend `trip_to_blocked` |
| `dark-factory/scheduler.sh` | Post-dispatch: read bridge file, call `should_trip_early`, `record_failure`; enrich trip comment |
| `.archon/commands/dark-factory-implement.md` | Add 3 prompt hardening blocks (Phase 1.5 stuck detection, Phase 1 preamble, pre-commit confidence) |
| `docs/superpowers/specs/` | This document |

**Not changed:** `.archon/memory/*.md` (remains the in-container, repo-committed layer),
`docker-compose.yml` (no new volumes or services), `config.yaml` (no new config knobs needed).

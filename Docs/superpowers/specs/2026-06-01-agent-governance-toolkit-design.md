# Agent Governance Toolkit Integration

**Date:** 2026-06-01
**Component:** `dark-factory/` (Dockerfile, entrypoint env), `.archon/commands/dark-factory-plan.md`, `.claude/skills/refinement/architect-prompt.md`, `dark-factory/agt/policy.yaml` (new)
**Approach:** Install AGT into the dark factory container; add a policy-evaluation step before the architect subagent fires in `dark-factory-plan.md` Phase 3; add audit-mode coverage in the scheduler's Priority 1 dispatch

## Problem

The dark factory's plan-generation pipeline contains a single AI-evaluates-AI gate: the architect subagent in `dark-factory-plan.md` Phase 3 reads the generated plan and emits "Approved" or "Issues Found." This gate is governed entirely by a language model prompt (`architect-prompt.md`) — there is no deterministic, policy-driven enforcement layer sitting beneath it. If the architect subagent's prompt fails to catch a dangerous plan (one that silently modifies signal scoring logic, bypasses auto-trade guards, or drops a database column without a down migration), the plan proceeds to implementation unchanged.

The Microsoft Agent Governance Toolkit (AGT) is purpose-built for exactly this layer: it operates between the agent's intent and the next action, evaluating that intent against explicit, version-controlled policy rules. Actions it denies are structurally impossible rather than "hoped not to happen." Adding AGT at the architect review gate means a plan that violates a defined policy cannot reach implementation even if the architect LLM approves it.

A secondary problem is traceability: today there is no tamper-evident record of what policy was active when an architect approved a plan, or what the scheduler decided when it dispatched a `MERGE`/`CONTINUE` for an "In review" ticket. AGT's Merkle-chained audit log fills that gap.

## Requirements

1. Install `agent-governance-toolkit[full]` (Python) and the AGT Claude Code plugin into the dark factory container image.
2. Define a version-controlled policy file at `dark-factory/agt/policy.yaml` containing five named rules (detailed in the Architecture section below).
3. Mount the policy file into the dark factory container at `/opt/agt/policy.yaml` and expose it via the `AGT_CLAUDE_POLICY_PATH` environment variable.
4. Write audit logs to `/tmp/agt-audit.json` inside the container; expose the path via `AGT_CLAUDE_AUDIT_PATH`.
5. In `dark-factory-plan.md` Phase 3, run `agt_policy_check_text` against the plan content before spawning the architect subagent. If AGT denies, count the denial as an architect "Issues Found" cycle (same loop, same 3-cycle cap, same `needs-discussion` exit).
6. The AGT check must be fail-closed: any evaluation error (package not installed, policy file unreadable, parse failure) must be treated as a denial.
7. The five policies must cover: scanner scoring protection (blocking), auto-trade guard (blocking), migration safety (blocking), scope adherence (audit), and financial data access (audit).
8. Policies 1-3 use AGT `deny` or `require_approval` actions. Policies 4-5 use `audit`.
9. Add `agt lint-policy dark-factory/agt/policy.yaml` to CI (`.github/workflows/ci.yml`) so malformed policy files block merges.
10. The `architect-prompt.md` is updated to reference that a structural policy check has already passed, so the architect focuses on the quality checks it is best suited for rather than duplicating the policy layer.
11. No changes to the scheduler's comment-classification path beyond adding an `audit` wrapper around the `classify_comments()` dispatch in Priority 1 (advisory, non-blocking).

## Architecture / Approach

### Integration Point: `dark-factory-plan.md` Phase 3 (blocking gate)

The plan content exists as a string in the orchestrator's context immediately after Phase 2 (plan writing) and before the architect subagent is spawned. This is where AGT intercepts:

```
Phase 2 → Plan written to file
          ↓
Phase 3 → [NEW] agt_policy_check_text(plan_content)
             ├─ DENY  → count as "Issues Found" cycle, fix loop
             └─ ALLOW → spawn architect subagent (existing logic unchanged)
```

The `agt_policy_check_text` tool is provided by the AGT MCP server that ships with the Claude Code plugin (`claude --plugin-dir ./agent-governance-claude-code`). It accepts a text string and the active policy path, evaluates all rules against the text, and returns a structured result containing the decision (`allow`/`deny`/`audit`) and the triggering rule if any.

The updated Phase 3 instruction block in `dark-factory-plan.md`:

```
## Phase 3: GOVERNANCE + ARCHITECT REVIEW

### Step 3a: Policy check (structural, blocking)

Before spawning the architect, call the `agt_policy_check_text` MCP tool:
- text: the full plan file content
- policy_path: /opt/agt/policy.yaml

If the result is DENY:
- Treat this as an architect "Issues Found" cycle
- Include the triggered rule name and reason in the fix notes
- Revise the plan to comply, then repeat from Step 3a
- Apply the same 3-cycle cap and needs-discussion exit as the architect loop

If the result is ALLOW or AUDIT:
- Proceed to Step 3b (AUDIT outcomes are logged automatically; no action required)

### Step 3b: Architect review (qualitative, blocking)

(existing Phase 3 logic unchanged)
```

The `agt_policy_check_text` call is synchronous and fail-closed: the orchestrator treats any exception, timeout, or malformed response as DENY.

### Policy File: `dark-factory/agt/policy.yaml`

Five policies, mounted at `/opt/agt/policy.yaml`:

```yaml
version: "1.0"
policies:

  - id: scanner-scoring-protection
    description: >
      Plans that modify signal scoring logic require explicit approval.
      Signal quality scores feed alert rules and auto-trade entry decisions;
      a silent weight change corrupts live trade signals.
    match:
      text_contains_any:
        - "signal_ranker.py"
        - "signal_ranker_weights"
        - "_NORM_CAPS"
    action: require_approval
    approvers:
      - tech-lead
    severity: high

  - id: auto-trade-guard
    description: >
      Plans touching auto-trade execution must include a paper_mode guard
      and a corresponding pytest. Bypassing the guard is structurally dangerous.
    match:
      text_contains_any:
        - "auto_trade_service.py"
        - "auto_trade_orders"
        - "tasks/trading.py"
    requires:
      text_contains_all:
        - "paper_mode"
        - "pytest"
    action: deny
    severity: high

  - id: migration-safety
    description: >
      Destructive migrations (DROP COLUMN, DROP TABLE) must include a
      down migration and a backup step. Irreversible data loss is unacceptable.
    match:
      text_contains_any:
        - "drop_column"
        - "drop_table"
        - "DROP COLUMN"
        - "DROP TABLE"
    requires:
      text_contains_any:
        - "downgrade"
        - "backup"
    action: deny
    severity: high

  - id: scope-adherence
    description: >
      Log plans that reference files outside the standard touch areas.
      Advisory — helps reviewers spot scope creep without blocking.
    match:
      text_contains_any:
        - "scheduler.sh"
        - "entrypoint.sh"
        - "docker-compose.yml"
    action: audit
    severity: low

  - id: financial-data-access
    description: >
      Log new endpoints or services that query financial tables.
      Ensures post-hoc review of data access patterns.
    match:
      text_contains_any:
        - "scanner_events"
        - "stock_aggregates"
        - "auto_trade_orders"
        - "trades"
    action: audit
    severity: low
```

### Container Changes

**`dark-factory/Dockerfile`** — two additions after the Claude Code CLI install:

```dockerfile
# AGT Python package
RUN pip install agent-governance-toolkit[full]

# AGT Claude Code plugin (ships PreToolUse/PostToolUse hooks + MCP server)
RUN npm install -g @microsoft/agent-governance-claude-code
```

**`docker-compose.yml`** — environment block for the dark-factory service:

```yaml
environment:
  AGT_CLAUDE_POLICY_PATH: /opt/agt/policy.yaml
  AGT_CLAUDE_AUDIT_PATH: /tmp/agt-audit.json
```

**`dark-factory/Dockerfile`** — mount the policy directory:

```dockerfile
COPY dark-factory/agt/ /opt/agt/
```

### Scheduler: Advisory Audit Wrapper (Priority 1)

In `dark-factory/scheduler.sh`, the `classify_comments()` call that emits MERGE/CONTINUE/SKIP for "In review" tickets currently has no traceability. Wrap the dispatch in a thin `agt review-log` call (the AGT CLI's audit subcommand) immediately after the dispatch fires:

```bash
agt review-log \
  --policy "$AGT_CLAUDE_POLICY_PATH" \
  --action "$DISPATCH_ACTION" \
  --issue "$ISSUE" \
  --outcome "$VERDICT" \
  --audit-path "$AGT_CLAUDE_AUDIT_PATH" || true
```

The `|| true` ensures the scheduler never blocks on an AGT failure — this is advisory only. The audit log record captures: timestamp, issue number, verdict (MERGE/CONTINUE/SKIP), and the policy version active at the time.

### CI: Policy Lint Step

Add to `.github/workflows/ci.yml` in the backend job (or a dedicated `governance` job):

```yaml
- name: Lint AGT policy
  run: |
    pip install agent-governance-toolkit[full]
    agt lint-policy dark-factory/agt/policy.yaml
```

This validates YAML syntax, policy schema, and rule consistency on every PR that touches `dark-factory/agt/`.

### Updated `architect-prompt.md` Preamble

Add a single paragraph at the top of `architect-prompt.md`:

```
A structural policy check (AGT) has already run against this plan and confirmed it
does not violate any hard governance rules (scanner scoring protection, auto-trade
guard, migration safety). Your review covers quality: spec coverage, file path
consistency, task decomposition, codebase conventions, and placeholder detection.
Do not duplicate the structural policy checks — focus on what only you can judge.
```

This prevents the architect from spending cycles on things AGT already enforces deterministically.

## Alternatives Considered

### A. Standalone Archon workflow that wraps `dark-factory-plan`

A new Archon workflow could call `archon-dark-factory.yaml`'s plan node and then invoke AGT as a post-step. This was ruled out because: (1) the dark factory enforces a single-container-at-a-time concurrency guard in `entrypoint.sh` — a factory-in-a-factory deadlocks on that guard; (2) AGT is middleware designed to be called from within agent execution, not from a wrapper pipeline; (3) it would add a second container invocation for every plan generation, doubling cost with no architectural benefit.

### B. Pre-commit hook on plan files

A git pre-commit hook could run `agt lint` against any plan file staged in `Docs/superpowers/plans/`. This runs on the developer's machine and catches plans committed by humans but does nothing inside the dark factory container (the factory commits directly, bypassing local hooks). It also runs after the plan is complete, not before the architect review gate where intervention is cheapest. Ruled out as insufficient — a CI step covers the human-commit case better, and the in-pipeline gate covers the agent-commit case.

### C. FastAPI backend service exposing governance as an endpoint

Placing AGT in a new FastAPI service that the dark factory calls over HTTP was considered to centralise policy management. Ruled out because: (1) the dark factory container has no network route to the backend service during a run (it operates on a feature branch, not against the live stack); (2) AGT is an application-layer library, not a web service — wrapping it in HTTP adds latency and a network failure mode with no benefit; (3) it conflates the stock-scanning application layer with the agent infrastructure layer.

## Implementation Plan

### Task 1 — Policy file and Dockerfile

**Files:** `dark-factory/agt/policy.yaml` (new), `dark-factory/Dockerfile`

1. Create `dark-factory/agt/` directory.
2. Write `dark-factory/agt/policy.yaml` with the five policies listed in the Architecture section.
3. Run `pip install agent-governance-toolkit[full] && agt lint-policy dark-factory/agt/policy.yaml` to confirm zero lint errors.
4. Add `RUN pip install agent-governance-toolkit[full]` to `dark-factory/Dockerfile` after the Claude Code CLI install line.
5. Add `RUN npm install -g @microsoft/agent-governance-claude-code` after the pip install.
6. Add `COPY dark-factory/agt/ /opt/agt/` to the Dockerfile before the `WORKDIR /workspace` line.
7. Build and smoke-test the image: `docker compose --profile factory build dark-factory && docker compose --profile factory run --rm dark-factory agt doctor`.
8. Commit: `git add dark-factory/agt/policy.yaml dark-factory/Dockerfile && git commit -m "feat(agt): install AGT into dark factory container with policy file"`.

### Task 2 — Environment variables

**Files:** `docker-compose.yml`, `docker-compose.preview.yml` (if it has a dark-factory service definition)

1. Add `AGT_CLAUDE_POLICY_PATH: /opt/agt/policy.yaml` and `AGT_CLAUDE_AUDIT_PATH: /tmp/agt-audit.json` to the `dark-factory` service's `environment` block in `docker-compose.yml`.
2. Check `dark-factory/docker-compose.preview.yml` — if it defines the dark-factory service, add the same env vars.
3. Update `.archon/.env.example` (if it exists) with a comment noting these two vars are set by docker-compose and do not need to be in `.archon/.env`.
4. Commit.

### Task 3 — Governance step in `dark-factory-plan.md`

**Files:** `.archon/commands/dark-factory-plan.md`

1. Replace the Phase 3 header and opening paragraph with the updated "Step 3a / Step 3b" instruction block from the Architecture section.
2. Ensure the fail-closed rule is explicit: "If `agt_policy_check_text` raises any exception, treat it as DENY."
3. Verify the 3-cycle cap and `needs-discussion` exit path still refer to both Step 3a denials and Step 3b architect issues (both count toward the same counter).
4. Commit.

### Task 4 — Architect prompt update

**Files:** `.claude/skills/refinement/architect-prompt.md`

1. Prepend the preamble paragraph from the Architecture section to `architect-prompt.md`.
2. Remove the "No Placeholders" section's bullet on `TODO` / `TBD` — AGT's policy lint step now catches structural violations; the architect should focus on quality checks only.
3. Commit.

### Task 5 — CI lint step

**Files:** `.github/workflows/ci.yml`

1. Add a `lint-agt-policy` job (or a step in an existing job) that runs:
   ```bash
   pip install agent-governance-toolkit[full]
   agt lint-policy dark-factory/agt/policy.yaml
   ```
2. Set the job to run only when `dark-factory/agt/**` is in the changed files, using a `paths` filter on the workflow trigger, to avoid installing AGT on every backend CI run.
3. Confirm the job appears in the PR check list by running the workflow on a branch that modifies `dark-factory/agt/policy.yaml`.
4. Commit.

### Task 6 — Scheduler audit wrapper

**Files:** `dark-factory/scheduler.sh`

1. Locate the `classify_comments()` call in the Priority 1 loop (approximately line 474 per the codebase research).
2. After the dispatch block for each MERGE/CONTINUE verdict, add the `agt review-log` call from the Architecture section.
3. Wrap in `|| true` so scheduler never exits on AGT failure.
4. Validate with `bash -n dark-factory/scheduler.sh`.
5. Commit.

### Task 7 — End-to-end smoke test

1. Run `docker compose --profile factory run --rm dark-factory "Plan issue #148"` against a branch with a test plan that triggers the `auto-trade-guard` rule (include the string `auto_trade_service.py` without `paper_mode`).
2. Confirm the orchestrator reports a DENY, counts it as a cycle, and the log at `/tmp/agt-audit.json` contains the denial record.
3. Fix the plan to include `paper_mode` and re-run; confirm the policy check passes and the architect fires.
4. Document the smoke test result in the PR description.

## Open Questions

- The AGT `require_approval` action (used by the `scanner-scoring-protection` rule) requires an approvals mechanism. Until AGT's human-approval flow is wired to a notification channel (e.g., GitHub comment or Slack), plans that trigger this rule will block indefinitely. For v1, treat `require_approval` as `deny` at the enforcement point by adding a comment to the policy YAML clarifying this, and revisit the approval flow in a follow-up issue.
- `agt review-log` may not be a real AGT CLI subcommand — the AGT CLI research confirms `agt doctor`, `agt verify`, `agt lint-policy`, and `agt red-team scan`, but not `review-log`. The scheduler audit step should fall back to writing a JSON line to `$AGT_CLAUDE_AUDIT_PATH` directly if the subcommand does not exist, verified during Task 6 implementation.

## Assumptions

- `agent-governance-toolkit[full]` is installable inside the dark factory's Ubuntu 24.04 + Python 3.12 environment without dependency conflicts with the existing pip packages.
- The AGT Claude Code plugin (`@microsoft/agent-governance-claude-code`) exposes `agt_policy_check_text` as an MCP tool callable from within an Archon workflow session. If the MCP server does not auto-register, an explicit `--mcp-server` flag will be added to the `claude` invocation in the Archon workflow node.
- The `text_contains_any` and `text_contains_all` match operators exist in AGT's YAML policy schema. If the actual schema uses different operator names, the policy file is updated to match — the intent (substring match against plan content) is stable.
- Policy denials during Phase 3 count toward the same 3-cycle cap as architect rejections. If AGT and the architect both run in the same cycle and both find issues, it still counts as one cycle.
- The `dark-factory/agt/` directory is committed to the repo (not gitignored). The audit log at `/tmp/agt-audit.json` is ephemeral (inside the container) and is not committed.

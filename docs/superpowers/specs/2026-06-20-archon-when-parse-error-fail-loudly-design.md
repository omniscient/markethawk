# Archon: Unparseable `when:` Expression Should Fail the Run — Design

**Date:** 2026-06-20
**Issue:** #402
**Status:** Spec — pending implementation
**Author:** Brainstormed with Claude (Sonnet 4.6)

## Problem

Between 2026-06-12 ~14:54 and ~20:05 UTC, every implement run completed its local work then
exited 0 while discarding the result — no PR, no issue comment, no board move. Root cause:
`classify-preview` carried a parenthesised `when:` expression (introduced in commit b675ecd,
PR #359) that Archon's parser could not evaluate. The engine marked the node **skipped**
(fail-closed); the default `all_success` cascade skipped every downstream node; the DAG
finished with `anyFailed=false` and exited as a success. Ten Max-window runs burned
re-executing identical no-op cycles before the issue was traced.

The engine treated a workflow that discarded a feature branch as **success**. That is worse
than a hard failure: an operator who sees a failure investigates; one who sees a success
assumes the run was fine.

## Goal

When Archon's `when:` expression parser encounters a syntax it cannot evaluate, **fail the
node loudly** instead of silently skipping it. A workflow author who writes an unsupported
expression must see their run fail immediately with a clear diagnostic.

## Non-Goals

- Extending the `when:` expression grammar to support parentheses or mixed operators.
- Changing the behavior when a valid expression *evaluates* to `false` (that still skips
  the node, which is correct).
- Changes to `check_workflow_when.py` (the CI lint gate stays in place as defense-in-depth).

## Requirements

1. **Node state** — A node with an unparseable `when:` expression must enter state `failed`,
   not `skipped`.
2. **Error log** — Log at `ERROR` level (already done; the log event
   `dag_node_skipped_condition_parse_error` should be renamed to
   `dag_node_failed_condition_parse_error` for accuracy).
3. **Platform message** — The operator-facing message must use ❌ (not ⚠️) and say
   **"run failed"** rather than "node skipped (fail-closed)". The syntax guidance (what
   expressions *are* supported) must remain so the author can fix it.
4. **Store event** — Persist `node_failed` (not `node_skipped`) to the workflow event store.
5. **Emitter event** — Emit `node_failed` (not `node_skipped`) to in-process listeners.
6. **Run summary** — `anyFailed = nodeCounts.failed > 0` becomes `true`; the workflow calls
   `failWorkflowRun`, not `completeWorkflowRun`. No DAG-level code changes are needed — the
   existing `nodeCounts` loop at line 3067 already handles this once node state is `failed`.
7. **Downstream cascade** — Downstream nodes with the default `all_success` trigger rule must
   cascade-skip when their upstream is in `failed` state. This is already implemented in
   `checkTriggerRule` and requires no separate change.
8. **Tests** — Three existing tests in `when condition parse errors (fail-closed)` describe
   block must be updated to assert failure, not skip (see § Implementation Notes below).

## Architecture / Approach

The fix is surgical: one branch in one function in `dag-executor.ts`. No new state,
no new interfaces, no changes to `condition-evaluator.ts` logic.

### Files to Change

| File | Change |
|---|---|
| `packages/workflows/src/dag-executor.ts` | Change the `!conditionParsed` branch (lines ~2641-2680) — see § Implementation Notes |
| `packages/workflows/src/dag-executor.test.ts` | Update three existing tests in the parse-error describe block |
| `packages/workflows/src/condition-evaluator.ts` | Update JSDoc on `evaluateCondition` (the return-type comment says "fail-closed = skip the node"; update to "fail-closed = fail the node") |

### Change in `dag-executor.ts` (`!conditionParsed` branch)

**Before:**
```typescript
if (!conditionParsed) {
  const parseErrMsg = `⚠️ Node '${node.id}': unparseable \`when:\` expression "${node.when}" — node skipped (fail-closed). Check syntax: ...`;
  await safeSendMessage(platform, conversationId, parseErrMsg, {...});
  getLog().error({ nodeId: node.id, when: node.when }, 'dag_node_skipped_condition_parse_error');
  await logNodeSkip(logDir, workflowRun.id, node.id, 'when_condition_parse_error').catch(...);
  deps.store.createWorkflowEvent({
    workflow_run_id: workflowRun.id,
    event_type: 'node_skipped',
    step_name: node.id,
    data: { reason: 'when_condition_parse_error', expr: node.when },
  }).catch(...);
  emitter.emit({ type: 'node_skipped', runId: ..., nodeId: ..., nodeName: ..., reason: 'when_condition_parse_error' });
  return { nodeId: node.id, output: { state: 'skipped' as const, output: '' } };
}
```

**After (four changes in bold):**
1. **Platform message** — change ⚠️ to ❌, change "node skipped (fail-closed)" to "run
   failed — fix the expression and re-run"
2. **Log event** — rename `dag_node_skipped_condition_parse_error` to
   `dag_node_failed_condition_parse_error`; use `logNodeError` (not `logNodeSkip`)
3. **Store event** — `event_type: 'node_failed'` (not `'node_skipped'`)
4. **Emitter + return** — emit `node_failed`; return `{ state: 'failed' as const, output: '',
   error: parseErrMsg }`

### Test Updates

**Test 1 — "skips node … when when: expression is unparseable"**
- Rename to: "fails node (does not run it) when when: expression is unparseable"
- Keep assertion: `mockSendQueryDag.mock.calls.length === 1` (guarded node still never runs)
- Add assertion: `store.failWorkflowRun` was called (run is marked failed)
- Add assertion: `store.createWorkflowEvent` was called with `event_type: 'node_failed'`
  and `step_name: 'guarded'`

**Test 2 — "sends a platform warning message naming the node and stating it was skipped"**
- Rename to: "sends an error message naming the node and stating the run failed"
- Update finder: `messages.find(m => m.includes('gate') && m.includes('failed'))`
- Keep: `expect(warning).toBeDefined()`
- Change: `expect(warning).not.toMatch(/skipped/i)` (not just "not node ran")
- Keep: `expect(warning).not.toMatch(/node ran/i)`

**Test 3 — "workflow completes without throwing when all nodes are skipped via parse error"**
- Rename to: "fails the workflow run (without throwing) when the only node has a parse error"
- Keep: `.resolves.toBeUndefined()` — `executeDagWorkflow` resolves normally; failure is
  recorded via `failWorkflowRun`, not a thrown JS exception (the CLI uses run status, not
  exception propagation, to determine exit code)
- Add: assertion that `store.failWorkflowRun` was called for `workflowRun.id`
- Add: assertion that `store.createWorkflowEvent` was called with `event_type: 'node_failed'`
  and `step_name: 'only'`

## Alternatives Considered

**A. Add a `parse_error` fourth node state.** Explicit, queryable. Rejected: adds state
management complexity to all trigger-rule logic and store schemas, with no benefit over
reusing `failed`. Callers already handle `failed` correctly; they should treat a bad
expression the same as a crashed node.

**B. Fail the workflow at YAML-load time (reject unparseable expressions up front).** Safer
for authoring, but the `condition-evaluator` is called at runtime with live node outputs —
the grammar could theoretically be extended later to support runtime introspection. Also, the
YAML loader has already run successfully; failing at load time would require a second parse
pass. Rejected for complexity and mismatch with the existing architecture.

**C. Emit a warning, let the operator decide (current behavior with better messaging).**
Rejected: the issue documents a real incident where this cost 10 Max-window runs and 5+ hours.
A warning the operator cannot act on in real time is not sufficient.

## Open Questions (Non-Blocking)

- Should the `condition-evaluator.ts` file-level comment (currently "fail-closed = skip the
  node") also be updated? Minor JSDoc accuracy change, safe to include.

## Assumptions

- The `check_workflow_when.py` CI lint gate is **not** removed — it catches unsupported
  expressions before they merge, providing defense-in-depth. The engine fix handles expressions
  that slip through (or are added without the lint check).
- `executeDagWorkflow` continues to resolve (not reject) on run failure; the CLI/caller
  reads run status from the store to determine exit code.
- No dark-factory Docker image rebuild is required (the change is in the Archon engine,
  not the command/workflow files).

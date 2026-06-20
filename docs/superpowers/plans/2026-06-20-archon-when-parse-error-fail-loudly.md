# Archon: Unparseable `when:` Expression Should Fail the Run — Implementation Plan

**Date:** 2026-06-20
**Issue:** #402
**Spec:** `docs/superpowers/specs/2026-06-20-archon-when-parse-error-fail-loudly-design.md`
**Author:** MarketHawk Refinement Pipeline

---

## Goal

Change Archon's DAG executor so that an unparseable `when:` expression marks the node as `failed` (not `skipped`) and propagates `anyFailed=true` through the existing run-summary logic, causing `failWorkflowRun` to be called instead of `completeWorkflowRun`.

## Architecture

One-branch surgical change in `dag-executor.ts` — the `if (!conditionParsed)` block at lines ~2641–2680. No new state, no new interfaces, no changes to `condition-evaluator.ts` logic or `checkTriggerRule`. The existing `nodeCounts` loop at line 3067 and `anyFailed` branch at line 3111 already route to `failWorkflowRun` once node state is `'failed'`.

## Tech Stack

TypeScript · Bun test runner (`bun:test`) · source files in `/opt/archon/packages/workflows/src/`

## File Structure

| File | Change |
|---|---|
| `/opt/archon/packages/workflows/src/dag-executor.test.ts` | Rename and expand 3 tests in the `when condition parse errors` describe block |
| `/opt/archon/packages/workflows/src/dag-executor.ts` | Replace `!conditionParsed` branch: message, log event, log function, store event, emitter event, return value |
| `/opt/archon/packages/workflows/src/condition-evaluator.ts` | Update file-level JSDoc line 14: "skip the node" → "fail the node" |

---

## Task 1 — Update Tests to Assert Failure Semantics (Red Phase)

**File:** `/opt/archon/packages/workflows/src/dag-executor.test.ts`

The three existing tests in `describe('executeDagWorkflow -- when condition parse errors (fail-closed)', ...)` currently assert skip semantics. Update them to assert failure semantics so they fail against the current implementation before we change production code.

### Step 1.1 — Rename and expand Test 1 (line 1735)

**Before:**
```typescript
  it('skips node (does not run it) when when: expression is unparseable', async () => {
    const mockDeps = createMockDeps();
    const platform = createMockPlatform();
    const workflowRun = makeWorkflowRun('parse-err-skip-run');

    const nodes: DagNode[] = [
      { id: 'unconditional', command: 'my-cmd' },
      // Single = is not valid syntax — will fail to parse
      {
        id: 'guarded',
        command: 'my-cmd',
        depends_on: ['unconditional'],
        when: "$unconditional.output = 'yes'",
      },
    ];

    await executeDagWorkflow(
      mockDeps,
      platform,
      'conv-parse-err-skip',
      testDir,
      { name: 'parse-err-skip-test', nodes },
      workflowRun,
      'claude',
      undefined,
      join(testDir, 'artifacts'),
      join(testDir, 'logs'),
      'main',
      'docs/',
      minimalConfig
    );

    // Only the unconditional node should have triggered an AI call.
    // The guarded node must be skipped (fail-closed), not executed.
    expect(mockSendQueryDag.mock.calls.length).toBe(1);
  });
```

**After:**
```typescript
  it('fails node (does not run it) when when: expression is unparseable', async () => {
    const mockDeps = createMockDeps();
    const platform = createMockPlatform();
    const workflowRun = makeWorkflowRun('parse-err-skip-run');

    const nodes: DagNode[] = [
      { id: 'unconditional', command: 'my-cmd' },
      // Single = is not valid syntax — will fail to parse
      {
        id: 'guarded',
        command: 'my-cmd',
        depends_on: ['unconditional'],
        when: "$unconditional.output = 'yes'",
      },
    ];

    await executeDagWorkflow(
      mockDeps,
      platform,
      'conv-parse-err-skip',
      testDir,
      { name: 'parse-err-skip-test', nodes },
      workflowRun,
      'claude',
      undefined,
      join(testDir, 'artifacts'),
      join(testDir, 'logs'),
      'main',
      'docs/',
      minimalConfig
    );

    // Only the unconditional node should have triggered an AI call.
    // The guarded node must NOT be executed, but the run must be marked failed.
    expect(mockSendQueryDag.mock.calls.length).toBe(1);
    expect(mockDeps.store.failWorkflowRun as ReturnType<typeof mock>).toHaveBeenCalled();
    const eventCalls = (mockDeps.store.createWorkflowEvent as ReturnType<typeof mock>).mock.calls;
    const nodeFailedEvents = eventCalls.filter(
      (call: unknown[]) =>
        (call[0] as Record<string, unknown>).event_type === 'node_failed' &&
        (call[0] as Record<string, unknown>).step_name === 'guarded'
    );
    expect(nodeFailedEvents.length).toBe(1);
  });
```

### Step 1.2 — Rename and update Test 2 (line 1772)

**Before:**
```typescript
  it('sends a platform warning message naming the node and stating it was skipped', async () => {
    const mockDeps = createMockDeps();
    const platform = createMockPlatform();
    const workflowRun = makeWorkflowRun('parse-err-warn-run');

    const nodes: DagNode[] = [{ id: 'gate', command: 'my-cmd', when: 'not a valid condition' }];

    await executeDagWorkflow(
      mockDeps,
      platform,
      'conv-parse-err-warn',
      testDir,
      { name: 'parse-warn-test', nodes },
      workflowRun,
      'claude',
      undefined,
      join(testDir, 'artifacts'),
      join(testDir, 'logs'),
      'main',
      'docs/',
      minimalConfig
    );

    const sendMessage = platform.sendMessage as ReturnType<typeof mock>;
    const messages = sendMessage.mock.calls.map((call: unknown[]) => call[1] as string);
    const warning = messages.find(m => m.includes('gate') && m.includes('skipped'));
    expect(warning).toBeDefined();
    // Must NOT indicate the node ran (the old fail-open behavior)
    expect(warning).not.toMatch(/node ran/i);
  });
```

**After:**
```typescript
  it('sends an error message naming the node and stating the run failed', async () => {
    const mockDeps = createMockDeps();
    const platform = createMockPlatform();
    const workflowRun = makeWorkflowRun('parse-err-warn-run');

    const nodes: DagNode[] = [{ id: 'gate', command: 'my-cmd', when: 'not a valid condition' }];

    await executeDagWorkflow(
      mockDeps,
      platform,
      'conv-parse-err-warn',
      testDir,
      { name: 'parse-warn-test', nodes },
      workflowRun,
      'claude',
      undefined,
      join(testDir, 'artifacts'),
      join(testDir, 'logs'),
      'main',
      'docs/',
      minimalConfig
    );

    const sendMessage = platform.sendMessage as ReturnType<typeof mock>;
    const messages = sendMessage.mock.calls.map((call: unknown[]) => call[1] as string);
    const warning = messages.find(m => m.includes('gate') && m.includes('failed'));
    expect(warning).toBeDefined();
    expect(warning).not.toMatch(/skipped/i);
    // Must NOT indicate the node ran (the old fail-open behavior)
    expect(warning).not.toMatch(/node ran/i);
  });
```

### Step 1.3 — Rename and expand Test 3 (line 1803)

**Before:**
```typescript
  it('workflow completes without throwing when all nodes are skipped via parse error', async () => {
    const mockDeps = createMockDeps();
    const platform = createMockPlatform();
    const workflowRun = makeWorkflowRun('parse-err-all-skip-run');

    const nodes: DagNode[] = [{ id: 'only', command: 'my-cmd', when: 'bad expression' }];

    await expect(
      executeDagWorkflow(
        mockDeps,
        platform,
        'conv-all-skipped',
        testDir,
        { name: 'all-skipped-test', nodes },
        workflowRun,
        'claude',
        undefined,
        join(testDir, 'artifacts'),
        join(testDir, 'logs'),
        'main',
        'docs/',
        minimalConfig
      )
    ).resolves.toBeUndefined();
  });
```

**After:**
```typescript
  it('fails the workflow run (without throwing) when the only node has a parse error', async () => {
    const mockDeps = createMockDeps();
    const platform = createMockPlatform();
    const workflowRun = makeWorkflowRun('parse-err-all-skip-run');

    const nodes: DagNode[] = [{ id: 'only', command: 'my-cmd', when: 'bad expression' }];

    await expect(
      executeDagWorkflow(
        mockDeps,
        platform,
        'conv-all-skipped',
        testDir,
        { name: 'all-skipped-test', nodes },
        workflowRun,
        'claude',
        undefined,
        join(testDir, 'artifacts'),
        join(testDir, 'logs'),
        'main',
        'docs/',
        minimalConfig
      )
    ).resolves.toBeUndefined();
    // executeDagWorkflow resolves normally; failure recorded in the store, not thrown.
    expect(mockDeps.store.failWorkflowRun as ReturnType<typeof mock>).toHaveBeenCalled();
    const eventCalls = (mockDeps.store.createWorkflowEvent as ReturnType<typeof mock>).mock.calls;
    const nodeFailedEvents = eventCalls.filter(
      (call: unknown[]) =>
        (call[0] as Record<string, unknown>).event_type === 'node_failed' &&
        (call[0] as Record<string, unknown>).step_name === 'only'
    );
    expect(nodeFailedEvents.length).toBe(1);
  });
```

### Step 1.4 — Run tests and confirm red

```bash
cd /opt/archon/packages/workflows && bun test src/dag-executor.test.ts --testNamePattern "when condition parse errors"
```

Expected output: 2–3 failures. Test 1 fails on `failWorkflowRun` and `node_failed` event assertions. Test 2 fails because `messages.find(... 'failed' ...)` returns `undefined` (current message uses "skipped"). Test 3 fails on `node_failed` event assertion (current event type is `node_skipped`).

### Step 1.5 — Commit

```bash
cd /opt/archon/packages/workflows && git add src/dag-executor.test.ts
git commit -m "test(archon): update parse-error tests to assert failure semantics (#402)"
```

---

## Task 2 — Implement `!conditionParsed` → `failed` in `dag-executor.ts` (Green Phase)

**File:** `/opt/archon/packages/workflows/src/dag-executor.ts`

Apply four changes to the `if (!conditionParsed)` block at lines ~2641–2680. The `logNodeError` import is already present at line 60 — no new import needed.

### Step 2.1 — Replace the `!conditionParsed` block

**Before (lines ~2641–2681):**
```typescript
            if (!conditionParsed) {
              const parseErrMsg = `⚠️ Node '${node.id}': unparseable \`when:\` expression "${node.when}" — node skipped (fail-closed). Check syntax: \`$nodeId.output == 'VALUE'\`, \`$nodeId.output > '5'\`, or compound \`$a.output == 'X' && $b.output != 'Y'\`.`;
              await safeSendMessage(platform, conversationId, parseErrMsg, {
                workflowId: workflowRun.id,
                nodeName: node.id,
              });
              getLog().error(
                { nodeId: node.id, when: node.when },
                'dag_node_skipped_condition_parse_error'
              );
              await logNodeSkip(
                logDir,
                workflowRun.id,
                node.id,
                'when_condition_parse_error'
              ).catch((err: Error) => {
                getLog().warn({ err, nodeId: node.id }, 'dag.node_skip_log_write_failed');
              });
              deps.store
                .createWorkflowEvent({
                  workflow_run_id: workflowRun.id,
                  event_type: 'node_skipped',
                  step_name: node.id,
                  data: { reason: 'when_condition_parse_error', expr: node.when },
                })
                .catch((err: Error) => {
                  getLog().error(
                    { err, workflowRunId: workflowRun.id, eventType: 'node_skipped' },
                    'workflow_event_persist_failed'
                  );
                });
              const emitter = getWorkflowEventEmitter();
              emitter.emit({
                type: 'node_skipped',
                runId: workflowRun.id,
                nodeId: node.id,
                nodeName: node.command ?? node.id,
                reason: 'when_condition_parse_error',
              });
              return { nodeId: node.id, output: { state: 'skipped' as const, output: '' } };
            }
```

**After (four changes: message emoji+text, log event name+function, store event_type, emitter type+fields, return state):**
```typescript
            if (!conditionParsed) {
              const parseErrMsg = `❌ Node '${node.id}': unparseable \`when:\` expression "${node.when}" — run failed — fix the expression and re-run. Check syntax: \`$nodeId.output == 'VALUE'\`, \`$nodeId.output > '5'\`, or compound \`$a.output == 'X' && $b.output != 'Y'\`.`;
              await safeSendMessage(platform, conversationId, parseErrMsg, {
                workflowId: workflowRun.id,
                nodeName: node.id,
              });
              getLog().error(
                { nodeId: node.id, when: node.when },
                'dag_node_failed_condition_parse_error'
              );
              await logNodeError(
                logDir,
                workflowRun.id,
                node.id,
                parseErrMsg
              ).catch((err: Error) => {
                getLog().warn({ err, nodeId: node.id }, 'dag.node_error_log_write_failed');
              });
              deps.store
                .createWorkflowEvent({
                  workflow_run_id: workflowRun.id,
                  event_type: 'node_failed',
                  step_name: node.id,
                  data: { reason: 'when_condition_parse_error', expr: node.when },
                })
                .catch((err: Error) => {
                  getLog().error(
                    { err, workflowRunId: workflowRun.id, eventType: 'node_failed' },
                    'workflow_event_persist_failed'
                  );
                });
              const emitter = getWorkflowEventEmitter();
              emitter.emit({
                type: 'node_failed',
                runId: workflowRun.id,
                nodeId: node.id,
                nodeName: node.command ?? node.id,
                error: parseErrMsg,
              });
              return { nodeId: node.id, output: { state: 'failed' as const, output: '', error: parseErrMsg } };
            }
```

Explanation of each change:
1. **Message** — `⚠️ … node skipped (fail-closed)` → `❌ … run failed — fix the expression and re-run`
2. **Log event** — `dag_node_skipped_condition_parse_error` → `dag_node_failed_condition_parse_error`; `logNodeSkip(…, 'when_condition_parse_error')` → `logNodeError(…, parseErrMsg)` (logNodeError already imported at line 60)
3. **Store event** — `event_type: 'node_skipped'` → `event_type: 'node_failed'`
4. **Emitter + return** — `type: 'node_skipped', reason: …` → `type: 'node_failed', error: parseErrMsg` (matches `NodeFailedEvent` interface in `event-emitter.ts`); return `state: 'failed' as const` with `error: parseErrMsg` so the `anyFailed` branch at line 3111 can surface the message

### Step 2.2 — Run parse-error tests and confirm green

```bash
cd /opt/archon/packages/workflows && bun test src/dag-executor.test.ts --testNamePattern "when condition parse errors"
```

Expected: All 3 tests pass.

### Step 2.3 — Run full dag-executor test suite

```bash
cd /opt/archon/packages/workflows && bun test src/dag-executor.test.ts
```

Expected: All tests pass. (The existing `node_skipped` paths for valid-but-false conditions and trigger-rule skips are unchanged.)

### Step 2.4 — Run TypeScript type check

```bash
cd /opt/archon/packages/workflows && bun x tsc --noEmit
```

Expected: 0 errors. The `NodeFailedEvent` interface in `event-emitter.ts` requires `{ type, runId, nodeId, nodeName, error }` — our emitter call supplies all fields. The `NodeSkippedEvent`'s `reason` field is no longer emitted from this branch.

### Step 2.5 — Commit

```bash
git add /opt/archon/packages/workflows/src/dag-executor.ts
git commit -m "fix(archon): unparseable when: expression fails the node and run (#402)"
```

---

## Task 3 — Update JSDoc in `condition-evaluator.ts`

**File:** `/opt/archon/packages/workflows/src/condition-evaluator.ts`

The file-level JSDoc at line 14 still says "fail-closed = skip the node". Update for accuracy.

### Step 3.1 — Update file-level JSDoc comment (line 14)

**Before:**
```typescript
 * Invalid/unparseable expressions default to false (fail-closed = skip the node).
```

**After:**
```typescript
 * Invalid/unparseable expressions default to false (fail-closed = fail the node).
```

### Step 3.2 — Verify tests still pass

```bash
cd /opt/archon/packages/workflows && bun test src/dag-executor.test.ts && bun test src/condition-evaluator.test.ts && bun x tsc --noEmit
```

Expected: All tests pass, 0 type errors.

### Step 3.3 — Commit

```bash
git add /opt/archon/packages/workflows/src/condition-evaluator.ts
git commit -m "docs(archon): update condition-evaluator JSDoc: fail-closed fails the node (#402)"
```

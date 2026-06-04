# Dark Factory vs. Agyn: Structured Comparison

**Date**: 2026-06-04
**Issue**: [#184](https://github.com/omniscient/markethawk/issues/184)
**Reference**: Benkovich & Valkov, "Agyn: A Multi-Agent System for Team-Based Autonomous Software Engineering", arXiv:2602.01465v2

---

## Executive Summary

MarketHawk's Dark Factory and Agyn are both production-deployed autonomous software engineering systems that use GitHub as their coordination medium and target real-world issue resolution — but they diverge sharply in organizational model. Dark Factory uses a rigid five-stage sequential pipeline (refine → plan → implement → conformance → validate) where a single agent owns each stage; Agyn uses a manager-coordinated team of four concurrently-operating specialized agents (manager, researcher, engineer, reviewer) whose interaction pattern emerges dynamically from task complexity. The most actionable gap is the absence of any quantitative benchmark for Dark Factory: Agyn reports 72.2% on SWEBench 500, while we have no comparable metric to track progress or regressions. The strongest Dark Factory advantage is its task-ingestion infrastructure — the backlog scheduler with label dispatch, WIP limits, retry counters, CI gates, and a circuit breaker has no Agyn equivalent described in the paper.

---

## Alignment Matrix

| # | Dimension | Dark Factory | Agyn | Alignment |
|---|-----------|-------------|------|-----------|
| 1 | Agent topology | Sequential 5-stage pipeline; one agent per stage; subagents spawned only for spec review | 4-role concurrent team (manager, researcher, engineer, reviewer); manager dynamically chooses next agent | **Differs** |
| 2 | Coordination / communication | GitHub branch + issue comments + artifacts directory; Archon node dependencies as stage handoff | Manager-centric `manage` tool; all comms flow through manager; separate GitHub accounts per agent role | **Partial** |
| 3 | Task ingestion | Backlog scheduler with label dispatch, WIP limits, priority queues, retry counters, CI gate, circuit breaker | Not described for production; SWEBench evaluation uses one-off task-per-fork setup | **Advantage** |
| 4 | Isolation & infrastructure | Ephemeral `--rm` container + docker-socket-proxy + per-issue `mh-preview-{N}` stacks | Per-agent isolated environments with shell + Nix; output truncated at 50k tokens; no preview stacks | **Partial** |
| 5 | Verification / quality gates | Conformance agent (spec-fidelity), validate stage (pytest + tsc + curl), CI failure gate | Test-driven execution; reviewer agent does inline PR review with explicit approve/request-changes | **Partial** |
| 6 | Evaluation / benchmarking | No quantitative benchmark | 72.2% on SWEBench 500; outperforms mini-SWE-agent + GPT-5 (65.0%) and matches OpenHands + GPT-5 (71.8%) | **Gap** |
| 7 | Resumability & statelessness | "Continue issue #N" reconstructs from branch + PR; stateless container per run; GitHub is durable state | Continuation from persisted GitHub artifacts without prompt modification; tested in production | **Aligned** |

Alignment key: **Aligned** / **Partial** / **Differs** / **Gap** (we lack) / **Advantage** (we lead)

---

## Dimension Analysis

### 1. Agent Topology

**Dark Factory:**
The pipeline has five sequential stages each corresponding to an Archon workflow node: **refine** (brainstorming + spec), **plan** (implementation plan with architect review), **implement** (code agent), **conformance** (spec-fidelity review), and **validate** (test runner + endpoint smoke tests). Each stage launches a single Claude session. Within the `refine` and `plan` stages, a second-tier Agent tool call spawns a product-owner or architect subagent for adversarial review — but these are subordinate to the primary session and do not operate concurrently. Only one issue is processed at a time (single-factory-container guard in `entrypoint.sh`). The `refine` WIP limit in `scheduler.sh` allows up to two concurrent refinement sessions, but the implementation pipeline is strictly serial.

**Agyn:**
Agyn configures a four-agent team: **manager** (orchestration, process control), **researcher** (issue understanding, repository exploration, task specification), **engineer** (implementation, test-running, iterative fix), **reviewer** (inline PR review, approve/request-changes). Each agent has its own isolated execution environment, role-specific prompt, and tailored model assignment — reasoning-heavy agents (manager, researcher) use larger models (GPT-5); implementation agents (engineer, reviewer) use smaller code-specialized models (GPT-5-Codex). The interaction pattern is not fixed: the manager dynamically decides which agent to invoke next based on intermediate results. The number of review/revision cycles is open-ended.

**Comparison:**
Both systems decompose software engineering into specialized roles, but the decomposition models are fundamentally different. Dark Factory's stages are a directed acyclic graph hardcoded in the YAML workflow, with no branching or backtracking between stages; Agyn's manager-coordinated team can iterate freely across research, implementation, and review phases as many times as needed. Dark Factory's "single agent per stage" approach concentrates heterogeneous reasoning — issue analysis, code writing, and test debugging — into one `implement` session, while Agyn separates issue analysis (researcher) from coding (engineer), enabling role-specific model allocation. The key tradeoff: Dark Factory's sequential model is simpler to debug and reason about; Agyn's concurrent team better reflects how human engineering teams work and enables research/implementation to proceed in parallel.

---

### 2. Coordination / Communication

**Dark Factory:**
State flows through GitHub (branches, issue comments, PR reviews) and a per-run artifacts directory (`$ARTIFACTS_DIR`). Stage handoffs are mediated by Archon workflow node `depends_on` edges — each node receives the prior node's stdout as `$<node>.output`. Within a stage, the implement agent reconstructs context by reading issue data (fetched in `fetch-issue` node), the current branch, and memory files. Inter-stage data is passed via flat text files (`implementation.md`, `validation.md`, `conformance.md`, `preview_env.sh`). The backlog scheduler (`scheduler.sh`) mediates cross-run coordination: it reads board state, PR status, and CI check results to determine what to dispatch next.

**Agyn:**
All inter-agent communication is explicitly mediated by the manager agent via a `manage` tool. No direct agent-to-agent messaging exists — every message routes through the manager, which serves as the single coordination point. This design simplifies tracing and control flow. GitHub serves as the persistent state store; each agent role uses a dedicated GitHub account so contributions are traceable by role. The `gh` CLI (plus the custom `gh-pr-review` extension for inline comments) provides compact GitHub interaction. Context summarization is applied automatically when history exceeds a token threshold to maintain bounded context windows.

**Comparison:**
Both systems treat GitHub as the canonical durable state store and avoid agent-to-agent direct messaging. The key difference is in how handoffs happen within a run: Dark Factory uses Archon workflow dependency edges (a static DAG), while Agyn's manager dynamically routes context using the `manage` tool. Dark Factory's flat artifact files (`preview_env.sh`, `implementation.md`) are simpler but less structured than Agyn's manage-tool invocation model, which carries explicit per-agent context packages. Agyn's separate GitHub accounts per role produce a richer audit trail; Dark Factory uses a single "MarketHawk Factory" identity for all commits.

---

### 3. Task Ingestion

**Dark Factory:**
`scheduler.sh` is a polling daemon that fetches the GitHub project board state every 60 seconds (configurable). Tasks enter via GitHub Issues with labels: `ready-for-agent` enables backlog auto-refinement; board column transitions (Backlog → Refined → Ready → In Progress → In Review → Done) drive the dispatch priority queue. Six priority tiers: (0) CI-red PRs gate from In Review → Blocked; (1) In Review items with new human comments dispatch Continue/Close; (2) Ready items dispatch Fix; (3) Blocked items retry (max 3 attempts) with branch-awareness; (4) Refined items trigger plan generation; (5) Backlog items trigger refinement. A circuit breaker (`trip_to_blocked`) adds `needs-discussion` after MAX_RETRIES and posts an explanatory comment. WIP limits are read from project board column descriptions. The `direct-to-pr` label triggers grace-window auto-advancement bypassing human review.

**Agyn:**
The paper evaluates Agyn on SWEBench 500 using a one-off task-per-fork model (one forked repo per task, no scheduling discussed). In production, Agyn is used for "day-to-day engineering workflows" but no scheduler, label system, WIP limits, or retry mechanism is described.

**Comparison:**
Dark Factory's task ingestion is substantially more sophisticated than anything described for Agyn. The backlog scheduler handles the complete issue lifecycle — refinement, planning, implementation, review, retry, and board state — without human intervention. This is a genuine advantage for continuous-delivery use cases. The `direct-to-pr` label and grace-window auto-advancement are sophisticated features with no Agyn analogue. The caveat is that Agyn may have equivalent production tooling that simply wasn't described in the academic paper.

---

### 4. Isolation & Infrastructure

**Dark Factory:**
The factory container is ephemeral (`--rm`) and stateless per run — no host filesystem bind-mounts, clones fresh from GitHub each time. Docker API access is restricted via `tecnativa/docker-socket-proxy`: allowed API surface is CONTAINERS, IMAGES, NETWORKS, VOLUMES, BUILD; SERVICES and EXEC are blocked. Per-issue `mh-preview-{N}` stacks spin up a full application environment (postgres, redis, backend, celery, frontend) for live endpoint validation. Ports follow `1{NN}33` (frontend) / `1{NN}80` (backend) with collision-free slot allocation. Credentials are injected from `.archon/.env` (gitignored) rather than the project `.env`. The `classify-preview` node skips the preview stack for docs/config/test-only changes, saving minutes per docs run.

**Agyn:**
Each agent has its own isolated execution environment with shell access. Environments are intentionally minimal — agents use Nix to install project-specific dependencies on demand rather than using preconfigured environments (which were found to introduce conflicting assumptions). Command output exceeding 50,000 tokens is auto-redirected to a temp file; agents receive a file reference and can inspect selectively. Evaluation was run on a single MacBook Pro with multiple tasks in parallel, encountering OOM failures at high parallelism — highlighting the need for resource-aware scheduling. No preview application stacks or port schemes are described.

**Comparison:**
The two systems solve different isolation problems. Dark Factory isolates the factory itself from the host (docker-socket-proxy, non-root user) and provides a per-issue full-application preview for live smoke testing. Agyn isolates each agent from other agents (separate execution environments) to prevent workspace contamination during concurrent work. Dark Factory's preview stacks have no Agyn equivalent — Agyn validates by running tests within the engineer's environment rather than spinning up a full running application. Agyn's Nix-based dependency management is more flexible than Dark Factory's dependency pre-installation in the Docker image, but adds per-run overhead.

---

### 5. Verification / Quality Gates

**Dark Factory:**
Three layers: (1) **Conformance stage** (`dark-factory-conformance.md`) spawns a subagent that compares the implementation diff against the approved spec, classifies as Conforms/Minor/Material, and can trigger up to `MAX_CYCLES` reconcile loops where code is modified to match the spec. (2) **Validate stage** (`dark-factory-validate.md`) runs pytest, `npx tsc --noEmit`, and curl smoke tests against the preview stack's live endpoints. (3) **CI gate** in `scheduler.sh`: In Review PRs with failing CI checks are moved back to Blocked automatically, not silently waiting for human review. Additionally, the architect subagent in the `plan` stage reviews the plan before implementation starts.

**Agyn:**
The engineer agent follows a test-driven execution strategy: run the test suite before and after each substantive change. The reviewer agent performs formal inline PR review using the `gh-pr-review` extension — it leaves inline comments and explicitly approves or requests changes. A task is considered complete only when the PR is explicitly approved by the reviewer; a natural-language "done" message from any agent is insufficient. The manager enforces this by requiring a `finish` tool invocation rather than accepting textual completion signals.

**Comparison:**
Both systems gate completion on passing tests and a code-review step. Agyn's reviewer agent is a specialized AI peer reviewer that can leave detailed inline comments on specific lines — a more nuanced feedback mechanism than Dark Factory's conformance check (which compares against a spec document rather than doing open-ended code review). Dark Factory's conformance stage adds a spec-fidelity layer that Agyn lacks: Agyn validates implementation quality but not adherence to a pre-approved design specification. Dark Factory's CI gate (auto-moving CI-red PRs out of review) is an operational advantage not present in Agyn's academic setup.

---

### 6. Evaluation / Benchmarking

**Dark Factory:**
No quantitative benchmark exists. There is no SWEBench evaluation, no internal accuracy metric tracking how often Dark Factory produces a correct implementation on the first attempt, and no regression test that would detect if a workflow change degraded implementation quality. Success is measured qualitatively (did the PR pass CI and human review?) with no aggregate statistics across runs.

**Agyn:**
Evaluated on SWEBench 500 in a fully automated setting (post hoc, not tuned for the benchmark). Result: **72.2%** resolution rate. Baseline comparisons using GPT-5-family models: OpenHands + GPT-5 (71.8%), mini-SWE-agent + GPT-5.2 high reasoning (71.8%), mini-SWE-agent + GPT-5 medium (65.0%). The system achieves the highest resolution rate in the GPT-5 subset without benchmark-specific tuning. Evaluation artifacts (forked repos, opened issues/PRs, agent communication traces) are publicly available.

**Comparison:**
This is the most asymmetric dimension. Agyn has a validated, reproducible, publicly reported quantitative benchmark. Dark Factory has no comparable metric. This means it is currently impossible to answer "is Dark Factory getting better or worse over time?" or "how does Dark Factory compare to the state of the art?" Running Dark Factory against SWEBench 500 (or even a 50-task subset) would immediately place it on the academic map and create an internal quality signal that doesn't currently exist.

---

### 7. Resumability & Statelessness

**Dark Factory:**
The factory container is stateless per run — it clones fresh from GitHub, installs dependencies, and runs the Archon workflow. If a run is interrupted mid-way (host reboot, OOM, manual kill), the next invocation uses "Continue issue #N" to reconstruct context by: checking out the existing branch, reading the open PR body, reading issue comments (including the Dark Factory run report), and loading memory files. The scheduler detects orphaned In Progress items (factory not running but issue still in that column) and moves them to Blocked for automatic retry. GitHub serves as the durable state store — no local persistent state is needed.

**Agyn:**
When execution is interrupted (environment failure, resource exhaustion), Agyn resumes from persisted GitHub artifacts — partially created issues, partial implementations, or interrupted PRs — without modifying agent prompts, tool configurations, or intermediate outputs. The paper explicitly notes this continuation behavior was used during SWEBench evaluation when infrastructure failures disrupted execution mid-run. Agents reconstruct state from GitHub history, mirroring how human developers resume work after an interruption.

**Comparison:**
Both systems use the same fundamental strategy: GitHub as the durable state store, reconstruction rather than checkpointing. The approaches are closely aligned. Dark Factory adds scheduler-level orphan recovery (automatic detection and retry) and an explicit "Continue issue #N" command with defined semantics (checks out branch, reads PR, acknowledges feedback). Agyn's continuation was tested more aggressively in production conditions (SWEBench evaluation with OOM failures) and demonstrated that the GitHub-as-state approach handles interruptions gracefully at scale. Neither system requires a local state database; both can survive container restarts with zero data loss.

---

## Notable Gaps

### G1: No Quantitative Benchmark
**Severity**: Critical

Dark Factory has no SWEBench-equivalent or internal accuracy metric. Without a benchmark, it is impossible to measure whether changes to the pipeline improve or degrade implementation quality, to compare Dark Factory against academic baselines, or to detect regressions when the underlying model or workflow changes. Agyn achieves 72.2% on SWEBench 500 without benchmark-specific tuning, demonstrating that a production-first system can be evaluated post hoc. This maps to Dimension 6. The absence of any quantitative signal is the single largest gap between the two systems.

### G2: Single-Agent Sequential Pipeline vs. Concurrent Specialist Team
**Severity**: High

Dark Factory's implement stage is a single Claude session that must simultaneously analyze the issue, understand the codebase, write code, and debug tests. Agyn splits these into a researcher (issue analysis + task spec) and engineer (implementation + testing), each with a role-specific model allocation. The researcher uses a larger general-purpose model for deep context understanding; the engineer uses a smaller code-specialized model for rapid iteration. Forcing heterogeneous reasoning into one session leads to longer contexts, potential reasoning interference between "understanding" and "coding" modes, and sub-optimal model cost. This maps to Dimension 1.

### G3: No Inline Code Review Agent
**Severity**: Medium

Dark Factory's conformance stage compares implementation against a pre-written spec (a structured but brittle gate). Agyn's reviewer agent performs open-ended inline code review — leaving specific line-level comments, identifying issues not covered by the spec, and enforcing an explicit approve/request-changes signal. Dark Factory's human reviewer sees only the PR diff; an AI reviewer agent could catch issues (missed edge cases, poor naming, logic errors) before the PR reaches human review, reducing round-trip latency. This maps to Dimension 5.

---

## Prioritized Improvements (Agyn-Inspired)

### P1: Internal Accuracy Benchmark
**Priority**: High
**Effort**: M
**Source**: Dimension 6

Select 30–50 historical Dark Factory issues where the "correct" output is known (issues that were eventually merged cleanly after a single factory run) and create a repeatable evaluation harness that runs the factory against them. Track a first-attempt resolution rate (PR passes CI and gets approved without a Continue run). Even a 50-issue internal benchmark would provide a quality signal for model upgrades, prompt changes, and workflow modifications, and would lay the groundwork for a SWEBench comparison.

### P2: Extract a Researcher Sub-Stage within the Implement Command
**Priority**: Medium
**Effort**: M
**Source**: Dimension 1

Split the current `dark-factory-implement.md` Phase 3 (IMPLEMENT) into two sub-phases: a **Research** phase (issue analysis, codebase exploration, task spec writing — using the stronger Claude Sonnet model or Opus) and a **Code** phase (implementation + tests — potentially using a lighter model). The Research phase produces a concise task spec document that guides the Code phase, reducing context pollution and enabling tighter prompts. This does not require switching to a full multi-agent architecture: it can be a two-step within the same `implement` command with a handoff via an artifact file.

### P3: Add an AI Reviewer Sub-Stage in the Validate Command
**Priority**: Medium
**Effort**: S
**Source**: Dimension 5

After pytest/tsc pass, spawn a code-reviewer subagent using the Agent tool (analogous to how conformance spawns a conformance-reviewer). The reviewer receives `git diff main...HEAD` and reviews for correctness, edge cases, naming, and security issues — producing a structured finding list. Findings rated "high severity" block the PR (added to conformance blockers); lower-severity findings become inline PR review comments. This extends the existing conformance subagent pattern and requires no workflow-level changes.

### P4: Role-Specific Model Allocation
**Priority**: Low
**Effort**: S
**Source**: Dimension 1

Agyn assigns larger models to reasoning-heavy agents (manager, researcher) and smaller models to code-iteration agents (engineer). Dark Factory can adopt the same principle without a full architectural change: the `refine` and `plan` stages (heavy reasoning, spec writing) stay on Sonnet/Opus; the `validate` stage (mechanical curl/pytest runner) switches to Haiku. This is a one-line model override in each command's YAML `model:` field and reduces token cost for validation-heavy runs with no quality tradeoff.

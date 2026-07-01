# Architecture Slice — targeted ARCHITECTURE.md loading for Dark Factory agents

**Status:** design  
**Date:** 2026-07-01  
**Issue:** #666  
**Epic:** #663 (Dark Factory platform — maintenance, telemetry)

## Problem

`ARCHITECTURE.md` is 598 lines (~58 KB, ~14,500 tokens). Every Dark Factory agent invocation that touches the `architecture_md` context section loads the full document, regardless of whether it needs the Frontend Architecture section for a backend-only change or the Live Scanner section for a Dark Factory ops ticket. This wastes context budget and dilutes agent focus on the relevant sections.

`context_budget.py` already emits per-section telemetry for other context sources; the `architecture_md` section currently reports a single monolithic `"status": "included"` with no section-level detail.

## Requirements

1. New module `dark-factory/scripts/architecture_slice.py` — both a library and a CLI.
2. Parse `ARCHITECTURE.md` by its `##`-level headings; expose a static `COMPONENT_SECTION_MAP` dict mapping four component keys (`backend`, `frontend`, `dark-factory`, `infrastructure`) to relevant section names.
3. Accept `--spec-component` as an explicit caller-passed argument (primary resolution signal). When absent, derive the component from `--changed-files` path prefixes, then from `--spec-file` filename keywords; if still unresolved, fall back to the full document.
4. Expose `infer_component(spec_file, changed_files, labels) -> str | None` as a public helper so callers (e.g. `context_budget.py`) that do not know the component upfront can call it rather than re-implementing keyword matching.
5. Fall back to the full `ARCHITECTURE.md` when:
   - Component inference fails (zero sections matched or no component resolved).
   - Issue labels or title/body contain keywords matching `dispatch_ceiling.keywords` or `epic_autopilot.sensitive_keywords` from `config.yaml`.
   - Changed files match any path in `epic_autopilot.hard_exclude_paths` or are cross-cutting infra files (`ARCHITECTURE.md` itself, `docker-compose*.yml`, `backend/app/core/`, `backend/app/main.py`).
6. Embed omitted-section metadata as an HTML comment at the top of every returned slice (so the consuming agent knows it received a slice and which sections were dropped).
7. Return a `SliceResult` dataclass with fields: `text`, `component`, `scenario`, `included_sections`, `omitted_sections`, `section_hashes`, `fallback`, `fallback_reason`.
8. Extend `context_budget.py`'s `architecture_md` handler to call `slice_architecture()` and record the `SliceResult` as an `"included_slice"` entry in `context-budget.json`, or `"included"` with `"fallback": true` when full-doc fallback fires.
9. Wire slices into the `refine`, `plan`, and `implement` scenarios in `context_budget.py` (currently listed as `architecture_md` in `_SECTION_REGISTRY`).
10. Tests in `dark-factory/tests/test_architecture_slice.py` covering backend, frontend, dark-factory, and infrastructure component slicing, plus fallback paths.

## Architecture

### Module layout

```
dark-factory/scripts/
  architecture_slice.py   ← new library + CLI (this issue)
  context_budget.py       ← existing; updated to call slice_architecture()
  token_estimate.py       ← existing; unchanged
dark-factory/tests/
  test_architecture_slice.py   ← new
```

### `architecture_slice.py` internals

#### Section parsing

`_parse_sections(path: str) -> dict[str, str]`  — reads `ARCHITECTURE.md`, splits on `^## ` headings (level-2 only), returns `{heading_title: content}`. Headings are matched exactly as they appear; the initial `# Architecture` level-1 heading is dropped. Current sections (validated against the file):

```
Service Topology
Scan Execution Flow
Backend Module Map
Frontend Architecture
Error Tracking System
IB Gateway Integration
Live Scanner
Celery Task Architecture
Catch Up Feature (Universe Aggregate Backfill)
Metrics and Observability
Test Architecture
```

An additional implicit entry, `Container Users`, is a table nested under `Service Topology`; it is treated as part of that section rather than split out separately (it has no `##`-level heading of its own).

#### Component→section map

```python
COMPONENT_SECTION_MAP: dict[str, list[str]] = {
    "backend": [
        "Scan Execution Flow",
        "Backend Module Map",
        "Error Tracking System",
        "Celery Task Architecture",
        "Test Architecture",
    ],
    "frontend": [
        "Frontend Architecture",
        "Backend Module Map",   # API contract awareness
        "Error Tracking System",
    ],
    "dark-factory": [
        "Service Topology",
        "Celery Task Architecture",
        "Metrics and Observability",
    ],
    "infrastructure": [
        "Service Topology",
        "IB Gateway Integration",
        "Live Scanner",
        "Celery Task Architecture",
        "Catch Up Feature (Universe Aggregate Backfill)",
        "Metrics and Observability",
    ],
}
```

#### Component inference order (when `--spec-component` is absent)

1. **Changed-file path prefixes** — first-match against the table below:
   | Path prefix | Component |
   |---|---|
   | `backend/app/` | `backend` |
   | `frontend/src/` | `frontend` |
   | `dark-factory/` | `dark-factory` |
   | `docker-compose` | `infrastructure` |

2. **Spec filename keywords** — parse the hyphen-delimited slug from the spec file path (e.g. `2026-06-20-epic-autopilot-design.md` → tokens `epic`, `autopilot`, `design`), match against keyword tables:
   | Token(s) | Component |
   |---|---|
   | `backend`, `scanner`, `api`, `celery`, `database`, `migration` | `backend` |
   | `frontend`, `ui`, `react`, `page`, `component` | `frontend` |
   | `factory`, `archon`, `scheduler`, `dark`, `refine`, `plan`, `pipeline` | `dark-factory` |
   | `infrastructure`, `docker`, `ibkr`, `gateway`, `prometheus`, `grafana` | `infrastructure` |

3. **Issue labels** — direct label-to-component match (`Dark Factory` → `dark-factory`, `frontend` → `frontend`, etc.).

4. **Fallback** — return `None`; caller uses full document.

#### Safety fallback triggers (any one fires full-doc load)

All keyword lists read from `config.yaml` at call time (resolves relative to `--clone-dir`); hardcoded defaults used when the file is absent.

| Trigger | Source | Default value |
|---|---|---|
| Safety keywords in labels/title | `dispatch_ceiling.keywords` | `migration\|migrate\|performance\|perf\|architectur\|refactor` |
| Sensitive keywords in labels/title | `epic_autopilot.sensitive_keywords` | `trading\|ibkr\|live order\|notional\|authentication\|authorization\|authn\|authz\|jwt\|oauth\|rbac` |
| Sensitive file paths | `epic_autopilot.hard_exclude_paths` | `app/services/trading`, `app/tasks/trading.py`, `app/core/auth`, `app/routers/auth` |
| Cross-cutting infra files (hardcoded) | — | `ARCHITECTURE.md`, `docker-compose*.yml`, `backend/app/core/`, `backend/app/main.py` |

Each trigger records a `fallback_reason` string (e.g. `safety_keyword:migration`, `safety_file:backend/app/core/config.py`) in `SliceResult`.

#### `SliceResult` dataclass

```python
@dataclass
class SliceResult:
    text: str                        # markdown content ready for prompt injection
    component: str | None            # resolved component, or None on fallback
    scenario: str
    included_sections: list[str]     # section titles present in text
    omitted_sections: list[str]      # section titles excluded
    section_hashes: dict[str, str]   # {section_title: sha256[:12]} for included sections
    fallback: bool                   # True = full ARCHITECTURE.md returned
    fallback_reason: str | None      # e.g. "component_unresolved", "safety_keyword:migration"
```

#### Inline HTML comment (top of every returned slice)

```markdown
<!-- architecture-slice: component=backend scenario=implement
     included: Scan Execution Flow, Backend Module Map, Error Tracking System, Celery Task Architecture, Test Architecture
     omitted: Service Topology, Frontend Architecture, IB Gateway Integration, Live Scanner, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability
     (load full ARCHITECTURE.md if your change touches an omitted area) -->
```

When `fallback=True`, the comment instead reads:

```markdown
<!-- architecture-slice: component=None scenario=refine fallback=true reason=component_unresolved
     full ARCHITECTURE.md loaded -->
```

### `context_budget.py` changes

The `architecture_md` section handler in `build_budget()` is replaced:

```python
elif sec == "architecture_md":
    arch_path = os.path.join(clone_dir, "ARCHITECTURE.md")
    result = slice_architecture(
        arch_path=arch_path,
        scenario=scenario,
        spec_component=spec_component,      # new kwarg to build_budget()
        spec_file=spec_file,
        changed_files=changed_files,        # new kwarg to build_budget()
        labels=labels,                       # new kwarg to build_budget()
        clone_dir=clone_dir,
    )
    status = "included" if result.fallback else "included_slice"
    sections[sec] = {
        "status": status,
        "tokens": te.estimate_tokens(result.text),
        "component": result.component,
        "included_sections": result.included_sections,
        "omitted_sections": result.omitted_sections,
        "section_hashes": result.section_hashes,
        "fallback": result.fallback,
        "fallback_reason": result.fallback_reason,
    }
    source_hashes["ARCHITECTURE.md"] = te.hash_file(arch_path) or ""
```

New kwargs to `build_budget()`: `spec_component: str | None = None`, `changed_files: list[str] | None = None`, `labels: list[str] | None = None`. Existing call sites pass `None` (no behaviour change until wired).

The entrypoint script does not need changes for the initial wire-in — `context_budget.py` is invoked by the factory run scripts before the agent prompt is assembled, so the slice is computed once per run.

### CLI interface

```bash
python3 dark-factory/scripts/architecture_slice.py \
  --clone-dir /workspace/markethawk \
  --scenario implement \
  --spec-component backend \       # optional; inferred if absent
  --spec-file docs/superpowers/specs/2026-07-01-foo-design.md \  # optional
  --changed-files backend/app/services/scanner.py \   # optional; repeatable
  --labels "backend" "performance" \  # optional; repeatable
  --out /tmp/slice.md              # optional; stdout if absent
```

Returns exit code 0 always (fallback is not an error). Writes `SliceResult` JSON to `--out.json` alongside the markdown when `--out` is specified (for debugging/telemetry).

## Alternatives considered

### A: Subprocess call from `context_budget.py`
`context_budget.py` shells out to `architecture_slice.py` as a subprocess. Consistent with the `claude -p` subprocess pattern used by `epic_autopilot.py` and `main_red_fixer.py`.

**Rejected**: subprocess overhead (~100 ms) on every context-pack probe; adds serialisation/deserialisation of `SliceResult` as JSON over stdout; `token_estimate.py` already establishes the "library imported by context_budget" pattern and that precedent fits better here.

### B: Pre-compute slice in `entrypoint.sh`, pass as file
`entrypoint.sh` runs `architecture_slice.py` once at startup before cloning (or after), writes the result to `$ARTIFACTS_DIR/architecture-slice.md`, and passes `--architecture-slice-file` to `context_budget.py` instead of `--clone-dir`.

**Rejected**: slicing signals (changed files, labels, spec path) are not all available at entrypoint startup; `entrypoint.sh` is already complex and adding slice logic there would scatter the context-pack responsibility. Library import keeps all context assembly inside `context_budget.py`.

## Open questions (non-blocking)

- **`token_optimization:` config section**: A future issue could add a kill-switch to config.yaml (e.g. `token_optimization.architecture_slice: enabled: true`) to allow toggling slicing without a code deploy. Out of scope here — the slicer always runs when called; the caller decides whether to call it.

- **Scenario-level section overrides**: Some scenarios may need extra sections beyond the component default (e.g. `validate` scenario might always want `Test Architecture`). A per-scenario section addition list in `COMPONENT_SECTION_MAP` or a second dict `SCENARIO_EXTRA_SECTIONS` could handle this. Deferred to a follow-up.

## Assumptions

- `ARCHITECTURE.md` `##`-level heading titles are stable across minor edits; the section parser does not need fuzzy matching.
- The four component keys (`backend`, `frontend`, `dark-factory`, `infrastructure`) cover the large majority of factory issues; an unknown component gracefully falls back to the full document.
- `context_budget.py` is the only caller that needs updating for the initial wire-in; `entrypoint.sh` shell scripts are not changed by this issue.
- The `escalation.opus_only_for` config key mentioned in brainstorming does not exist in the current `config.yaml`; the spec uses `dispatch_ceiling.keywords` and `epic_autopilot.sensitive_keywords` as the safety keyword sources instead.
- Blast-radius score-based fallback (querying codeindex for hotspot score ≥ 5.0) is a future enhancement; this issue does not implement codeindex integration inside the slicer.

## Tests (`dark-factory/tests/test_architecture_slice.py`)

| Test | Assertion |
|---|---|
| `test_backend_slice` | `--spec-component backend` → includes `Backend Module Map`, excludes `Frontend Architecture`; `fallback=False` |
| `test_frontend_slice` | `--spec-component frontend` → includes `Frontend Architecture`, excludes `Live Scanner`; `fallback=False` |
| `test_dark_factory_slice` | `--spec-component dark-factory` → includes `Service Topology`, excludes `Test Architecture`; `fallback=False` |
| `test_infrastructure_slice` | `--spec-component infrastructure` → includes `IB Gateway Integration`, excludes `Backend Module Map`; `fallback=False` |
| `test_infer_backend_from_changed_files` | `changed_files=["backend/app/services/scanner.py"]` → component `backend` inferred |
| `test_infer_frontend_from_changed_files` | `changed_files=["frontend/src/pages/Scanner/index.tsx"]` → component `frontend` inferred |
| `test_infer_dark_factory_from_changed_files` | `changed_files=["dark-factory/scripts/context_budget.py"]` → component `dark-factory` |
| `test_fallback_no_signals` | No spec-component, no changed files → `fallback=True`, `fallback_reason="component_unresolved"` |
| `test_fallback_safety_keyword_label` | `labels=["trading"]` → `fallback=True`, `fallback_reason` contains `safety_keyword:trading` |
| `test_fallback_safety_file` | `changed_files=["backend/app/core/config.py"]` → `fallback=True`, `fallback_reason` contains `safety_file` |
| `test_omitted_comment_in_slice` | Returned `text` starts with `<!-- architecture-slice:` |
| `test_explicit_component_overrides_inference` | `spec_component="frontend"` with `changed_files=["backend/app/..."]` → frontend sections returned |
| `test_context_budget_included_slice_status` | `build_budget()` with a fixture `ARCHITECTURE.md` and `spec_component="backend"` → `architecture_md.status == "included_slice"` |
| `test_context_budget_fallback_status` | `build_budget()` with safety label → `architecture_md.status == "included"`, `architecture_md.fallback == True` |

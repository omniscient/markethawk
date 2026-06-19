# Narrative Provenance and Forbidden-Claim Enforcement

**Date:** 2026-06-19
**Status:** Spec — Pending Review
**Issue:** #474
**Parent:** #450 (Epic: Optional LLM Narrative and Semantic Intelligence)
**Blocked by:** #473 (Add cached scanner event narrative generation)

## Overview

Generated narratives from scanner event briefs must be auditable and safe. A narrative that makes an unsupported claim — or asserts something explicitly marked forbidden in the `ai_signal_brief` — must not be persisted or shown to the user without a visible explanation. This spec adds two interlocking controls:

1. **Provenance**: each key claim in a generated narrative is linked to the specific `ai_signal_brief` field that grounds it.
2. **Forbidden-claim enforcement**: claims listed in `ai_signal_brief.forbidden_claims` are injected into the generation prompt as negative constraints, then validated post-generation with a deterministic substring check. Violations are rejected before persistence.

Both controls are stored on the narrative cache row from issue #473 and surfaced through the existing narrative API response.

## Requirements

From the acceptance criteria and Q&A:

- **R1** — The narrative cache table gains two nullable columns: `provenance` (JSONB) and `rejection_reason` (text).
- **R2** — A `status` enum field (`"accepted"` / `"rejected"`) is added to the narrative cache table to make the row's disposition explicit.
- **R3** — At generation time, `forbidden_claims` from the brief are injected into the LLM prompt as explicit negative constraints alongside the brief facts.
- **R4** — After generation, a post-generation validation gate runs a case-insensitive substring check of the narrative text against each string in `forbidden_claims`. If any forbidden string is found, the narrative is rejected.
- **R5** — If the generated narrative has no `provenance` mapping (empty list or missing) for a key claim, the narrative is rejected as unsupported.
- **R6** — Rejected narratives are persisted to the cache row with `status="rejected"`, `rejection_reason` set to a human-readable explanation (e.g., `"Forbidden claim detected: 'guarantees profit'"` or `"Provenance missing for key claims"`), and `narrative_text=null`.
- **R7** — The narrative API response Pydantic schema includes `status`, `narrative_text` (nullable), `rejection_reason` (nullable), and `provenance` (nullable list of claim→brief-field mappings). Rejected responses carry the deterministic `ai_signal_brief` payload so the user always has useful content.
- **R8** — The TypeScript API client types in `frontend/src/api/` are updated to carry the new fields. The existing narrative/scanner-event component renders a dismissible inline warning when `status == "rejected"`, displaying the `rejection_reason`. Full provenance UI (rendering each claim against its brief-field citation) is deferred to issue #481.
- **R9** — Tests cover: a narrative that passes all checks (accepted, provenance present), a narrative containing a forbidden claim (rejected, correct reason), a narrative with missing provenance (rejected, correct reason), and a narrative when the feature is disabled (no generation, brief returned as-is, no rejection row created).

## Architecture and Approach

### Narrative cache schema (extends #473)

The narrative cache table from #473 gains three columns added via an Alembic migration:

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `status` | `VARCHAR` (enum: `accepted`, `rejected`) | No | Disposition of the generation attempt |
| `provenance` | `JSONB` | Yes | List of `{claim, brief_field}` mappings; null on rejection |
| `rejection_reason` | `TEXT` | Yes | Human-readable reason; null on acceptance |

`provenance` is a JSONB list, for example:
```json
[
  {"claim": "Volume is 3.2x the 30-day average", "brief_field": "facts.volume_ratio"},
  {"claim": "Price gapped above VWAP", "brief_field": "facts.above_vwap"},
  {"claim": "Elevated short interest adds tail risk", "brief_field": "risks[0]"}
]
```

### Generation flow (extends NarrativeService from #473)

```
NarrativeService.generate_and_cache(event_id, brief)
  │
  ├─ 1. Check feature flag (from #472) → if disabled, return brief as-is, no cache row
  │
  ├─ 2. Build generation prompt
  │       • Brief facts, why, risks, data_quality_warnings
  │       • Inject forbidden_claims as negative constraints:
  │         "You must NOT claim or imply any of the following: {forbidden_claims}"
  │       • Instruct model to return structured JSON:
  │         {narrative: "...", provenance: [{claim, brief_field}, ...]}
  │
  ├─ 3. Call LLM (provider from #472)
  │
  ├─ 4. Post-generation validation gate (ProvenanceValidator)
  │       a. Forbidden-claim check: for each string in brief.forbidden_claims,
  │          case-insensitive substring search in narrative text.
  │          → If hit: reject with reason "Forbidden claim detected: '{match}'"
  │       b. Provenance check: if provenance list is empty or missing:
  │          → Reject with reason "Provenance missing for key claims"
  │
  ├─ 5a. ACCEPT → persist {status="accepted", narrative_text, provenance, rejection_reason=null}
  └─ 5b. REJECT → persist {status="rejected", narrative_text=null, rejection_reason, provenance=null}
```

### ProvenanceValidator service

A thin, pure-function module at `backend/app/services/provenance_validator.py`:

```python
@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    rejection_reason: str | None

def validate(
    narrative_text: str,
    provenance: list[dict],
    forbidden_claims: list[str],
) -> ValidationResult:
    for claim in forbidden_claims:
        if claim.lower() in narrative_text.lower():
            return ValidationResult(accepted=False, rejection_reason=f"Forbidden claim detected: '{claim}'")
    if not provenance:
        return ValidationResult(accepted=False, rejection_reason="Provenance missing for key claims")
    return ValidationResult(accepted=True, rejection_reason=None)
```

No database calls; all logic is deterministic and side-effect free. Called from `NarrativeService` after LLM response is parsed.

### API schema (extends #473 narrative response)

```python
class NarrativeProvenanceItem(BaseModel):
    claim: str
    brief_field: str  # e.g. "facts.volume_ratio", "risks[0]"

class NarrativeResponse(BaseModel):
    event_id: int
    status: Literal["accepted", "rejected"]
    narrative_text: str | None
    rejection_reason: str | None
    provenance: list[NarrativeProvenanceItem] | None
    ai_signal_brief: AiSignalBriefSchema  # always present — deterministic content
    cached_at: datetime
    model_version: str | None
```

### Frontend (minimal scope)

- Update `frontend/src/api/scanner/` (or equivalent) TypeScript client to surface the new `status`, `rejection_reason`, `provenance` fields.
- In the existing narrative component (Scanner Results / Stock Detail), add: if `status === "rejected"`, render a dismissible inline warning with `rejection_reason`. No new pages. Full provenance panel (claim-by-claim citations) is deferred to #481.

## Alternatives Considered

### LLM-based semantic forbidden-claim check

After generation, send the narrative + `forbidden_claims` back to the LLM with a prompt like "Does this narrative assert any of: [list]?" The model can detect paraphrases that substring matching misses.

**Rejected because:** adds a second LLM round-trip (cost + latency), introduces nondeterminism to a validation gate that must be reliably testable, and exceeds size:M scope. The risk is acceptable because prompt injection (R3) is the primary prevention; the substring check is a backstop, not the sole defense. Paraphrase detection can be added as a follow-up if the prompt-injection path proves insufficient.

### Separate `narrative_provenance` table

Normalized relational table with one row per claim per narrative, enabling cross-event analytics ("which brief fields are cited most often").

**Rejected because:** JSONB on the cache row is the established MarketHawk pattern for variable-shape payloads that are always read alongside their parent row (e.g. `scanner_events.explanation`, `scanner_events.indicators`). The analytical use case (citation frequency) is not in scope for #474, and PostgreSQL JSONB operators support it without a separate table if needed later.

### Silent fallback to `ai_signal_brief` on rejection

Return the deterministic brief with no mention of the rejection. Rejection reason stored only in the database.

**Rejected because:** the acceptance criterion requires "rejected with a visible reason." Hiding the rejection from the user fails that criterion.

## Open Questions

- **OQ1**: The structured JSON output format (narrative + provenance as a JSON object) assumes the LLM from #472 supports structured/constrained output. If the provider returns free text, provenance must be parsed heuristically or extracted post-generation. Implementation should confirm the output format contract with the #472/#473 provider interface before committing to structured parsing.
- **OQ2**: Should `rejected` narratives be retried automatically (e.g. Celery task with `max_retries=1`) or remain rejected until the brief changes? This decision belongs to the orchestration layer from #473 and is not in scope here. The spec assumes a rejected row stays rejected.

## Assumptions

- **[ASSUMPTION]** Issue #473 has established a `NarrativeCache` SQLAlchemy model (or equivalent) with `narrative_text`, `model_version`, and `cached_at` columns. This spec adds `status`, `provenance`, and `rejection_reason` via an Alembic migration. If #473's schema differs, the migration strategy may need adjustment.
- **[ASSUMPTION]** `ai_signal_brief.forbidden_claims` is a flat list of strings (as shown in the parent design spec). The substring check performs case-insensitive matching against the full narrative text. If forbidden claims are structured objects with severity or match-type fields, the enforcement logic will need updating.
- **[ASSUMPTION]** The LLM prompt from #473's narrative generation is extensible — forbidden claims can be injected into the existing prompt template without a new LLM call. If #473 uses a fixed prompt, a thin wrapper or prompt-builder extension is needed.

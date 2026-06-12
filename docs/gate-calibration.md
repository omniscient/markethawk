# Gate Calibration Audit

**Status**: PENDING — audit not yet run.

This document records the calibration audit for MarketHawk's LLM judge gates (conformance and code-review). Complete this before changing `fail_open: false` or raising `block_on_material` thresholds. The 5-step process is defined in the spec for issue #334.

---

## Audit Results

| Gate | Sample size | Correct | Incorrect | Agreement rate | Calibrated? |
|------|-------------|---------|-----------|----------------|-------------|
| Conformance | — | — | — | — | — |
| Code-review | — | — | — | — | — |

---

## Step 1 — Sample

### Conformance (target: 20–30 verdicts)

```bash
# Enumerate spillover tickets (root cause set for conformance over-blocking)
gh issue list --label scope-spillover --limit 50 --json number,title,url \
  | jq '.[] | "\(.number) \(.title)"'

# Find "Spec Conformance — Blocked" comments directly
gh search issues "Spec Conformance Blocked" --repo omniscient/markethawk \
  --json number,title --limit 30
```

**Sampled verdicts** (fill in after running the queries above):

| Issue # | Verdict | Correct? | Reason |
|---------|---------|----------|--------|
| | | | |

### Code-review (target: 20–30 verdicts)

```bash
# Find factory-posted code reviews
gh pr list --state merged --limit 50 --json number,reviews \
  | jq '.[] | select(.reviews | length > 0) | {pr: .number, reviews: [.reviews[] | select(.author.login=="omniscient")]}'
```

**Sampled verdicts** (fill in after running the query above):

| PR # | Verdict | Correct? | Reason |
|------|---------|----------|--------|
| | | | |

---

## Step 2 — Label

For each verdict, mark **correct** or **incorrect**:
- Conformance block: was the flagged deviation genuinely out-of-scope or material? Check the spec.
- Code-review block: was the flagged finding a real bug/security issue?
- Pass (no block): spot-check that the change was clean.

---

## Step 3 — Score

```
agreement_rate = correct_count / total_count
```

| Gate | correct_count | total_count | agreement_rate |
|------|---------------|-------------|----------------|
| Conformance | | | |
| Code-review | | | |

≥75% agreement → gate is calibrated for blocking power.
<75% → tune the gate first; see Step 4.

---

## Step 4 — Calibrate

Update `.claude/skills/refinement/config.yaml` per the result:

| Gate | Under-agreement signal | Config lever |
|------|----------------------|--------------|
| Conformance | Over-blocks (excise FPs) | Set `conformance.excise_out_of_scope: false` (backlog only); or raise `block_on_material` threshold |
| Code-review | Under-blocks (0 findings = rubber stamp) | Set `code_review.fail_open: false` once agreement ≥75% confirms the judge is calibrated |

**Config changes made** (fill in after audit):

```yaml
# Changes applied to .claude/skills/refinement/config.yaml:
# (none yet)
```

---

## Step 5 — Document

**Audit date**: _not yet performed_
**Auditor**: _human owner_
**Conformance agreement rate**: _—_
**Code-review agreement rate**: _—_
**Config changes**: _none_
**Rationale**: _—_

---

*Runbook defined in issue #334. Fill in Sections 1–5 after running the audit.*

# Plan: Configurable Token Optimization Policy

**Date:** 2026-07-01
**Issue:** #671
**Spec:** docs/superpowers/specs/2026-07-01-configurable-token-optimization-policy-design.md
**Branch:** refine/issue-671-add-configurable-token-optimization-poli

---

## Goal

Add a `token_optimization:` top-level block to `.claude/skills/refinement/config.yaml`, following
the established pattern of every other policy block in that file. This is a declaration-first step
so that future per-scenario enforcement tickets under epic #663 have a stable config schema to wire
against. No code reads the new block yet; consumption is entirely deferred.

## Architecture

Single file change: `.claude/skills/refinement/config.yaml` — append a `token_optimization:` block
with safe defaults (`enabled: true`, `enforce_budgets: false`) and `# env:` override comments on
the four hot-changeable keys.

No code changes, no migrations, no new services, no scheduler behaviour changes.

## Tech Stack

YAML (`.claude/skills/refinement/config.yaml`). Validated by a Python read-back one-liner and a
Docker rebuild smoke check.

---

## File Structure

| File | Change |
|------|--------|
| `.claude/skills/refinement/config.yaml` | Append `token_optimization:` block (~20 lines) |

---

## Tasks

### Task 1 — Add `token_optimization:` block to `config.yaml`

**Files:** `.claude/skills/refinement/config.yaml`

#### TDD steps

**Step 1.1 — Write failing validation script**

Run the read-back check against the current file; it must fail because the key does not exist yet:

```bash
python3 -c "
import yaml, sys
d = yaml.safe_load(open('.claude/skills/refinement/config.yaml'))
if 'token_optimization' not in d:
    print('FAIL: token_optimization block missing (expected)')
    sys.exit(1)
" && echo "UNEXPECTED PASS — block already present" || echo "CONFIRMED FAIL — block not present yet"
```

Expected output:
```
FAIL: token_optimization block missing (expected)
CONFIRMED FAIL — block not present yet
```

**Step 1.2 — Implement: append the block to `config.yaml`**

Append the following to the end of `.claude/skills/refinement/config.yaml`:

```yaml

token_optimization:
  enabled: true              # env: TOKEN_OPTIMIZATION_ENABLED overrides
  enforce_budgets: false     # env: TOKEN_OPTIMIZATION_ENFORCE_BUDGETS overrides — false = measure only, never hard-stop
  default_budget_tokens: 24000  # env: TOKEN_OPTIMIZATION_DEFAULT_BUDGET_TOKENS overrides
  architecture:
    mode: slice              # slice = load relevant sections only (full = load entire file)
    max_tokens: 3000
  memory:
    mode: top_k              # top_k = keep the N most-relevant entries
    max_entries: 8
    max_tokens: 1500
  comments:
    digest_after_factory_marker: true   # digest comments after the "Refinement Pipeline" marker
    max_tokens: 2000
  diff:
    max_review_tokens: 6000
  escalation:
    cheap_model_first: true  # env: TOKEN_OPTIMIZATION_CHEAP_MODEL_FIRST overrides
    opus_only_for:
      - security
      - trading
      - auth
      - high_blast_radius
      - material_conformance_uncertainty
```

**Step 1.3 — Verify: read-back check passes**

```bash
python3 -c "
import yaml, sys
d = yaml.safe_load(open('.claude/skills/refinement/config.yaml'))
tok = d.get('token_optimization', {})
assert tok.get('enabled') == True,           f'enabled wrong: {tok.get(\"enabled\")}'
assert tok.get('enforce_budgets') == False,  f'enforce_budgets wrong: {tok.get(\"enforce_budgets\")}'
assert tok.get('default_budget_tokens') == 24000, f'default_budget_tokens wrong: {tok.get(\"default_budget_tokens\")}'
assert tok['architecture']['mode'] == 'slice',       'architecture.mode wrong'
assert tok['architecture']['max_tokens'] == 3000,    'architecture.max_tokens wrong'
assert tok['memory']['mode'] == 'top_k',             'memory.mode wrong'
assert tok['memory']['max_entries'] == 8,            'memory.max_entries wrong'
assert tok['memory']['max_tokens'] == 1500,          'memory.max_tokens wrong'
assert tok['comments']['digest_after_factory_marker'] == True, 'comments.digest_after_factory_marker wrong'
assert tok['comments']['max_tokens'] == 2000,        'comments.max_tokens wrong'
assert tok['diff']['max_review_tokens'] == 6000,     'diff.max_review_tokens wrong'
assert tok['escalation']['cheap_model_first'] == True, 'escalation.cheap_model_first wrong'
expected_opus = ['security','trading','auth','high_blast_radius','material_conformance_uncertainty']
assert tok['escalation']['opus_only_for'] == expected_opus, f'opus_only_for wrong: {tok[\"escalation\"][\"opus_only_for\"]}'
print('OK — all assertions pass')
"
```

Expected output:
```
OK — all assertions pass
```

**Step 1.4 — Docker rebuild smoke check**

The file is baked into the Dark Factory image at build time. Verify the image picks it up:

```bash
docker compose --profile factory build dark-factory
docker compose --profile factory run --rm dark-factory \
  python3 -c "import yaml; d=yaml.safe_load(open('/opt/refinement-skills/config.yaml')); print(d['token_optimization'])"
```

Expected output: a dict containing `enabled`, `enforce_budgets`, `default_budget_tokens`, etc.

**Step 1.5 — Commit**

```bash
git add .claude/skills/refinement/config.yaml
git commit -m "feat: add token_optimization config block to refinement config (#671)

Declaration-first step for epic #663. Adds the token_optimization: policy
block with safe defaults (enabled=true, enforce_budgets=false). No code reads
the block yet; per-scenario wiring is deferred to child tickets.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

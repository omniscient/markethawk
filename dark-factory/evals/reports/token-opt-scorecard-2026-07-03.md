# Token Optimization Scorecard — 2026-07-03

**Issue:** [#672](https://github.com/omniscient/markethawk/issues/672)
**Script:** `dark-factory/evals/token_opt_eval.py`

---

## Per-Issue Savings (Enforcement scenarios: refine / plan / implement / conformance / code-review)

| Issue | Component | Scenario | Baseline (tok) | Optimized (tok) | Savings % | Safety | Sliced? |
|-------|-----------|----------|----------------|-----------------|-----------|--------|---------|
| #215 | dark-factory | refine | 21,239 | 9,336 | 56.0% | ✅ PASS | yes |
| #215 | dark-factory | plan | 21,239 | 9,335 | 56.0% | ✅ PASS | yes |
| #215 | dark-factory | implement | 16,981 | 5,077 | 70.1% | ✅ PASS | yes |
| #215 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #215 | — | code-review | 4,316 | 4,316 | 0.0% | ⚠️ GAP | no (fallback) |
| #224 | infrastructure | refine | 21,934 | 12,067 | 45.0% | ✅ PASS | yes |
| #224 | infrastructure | plan | 21,934 | 12,066 | 45.0% | ✅ PASS | yes |
| #224 | infrastructure | implement | 17,676 | 7,808 | 55.8% | ✅ PASS | yes |
| #224 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #224 | — | code-review | 5,011 | 5,011 | 0.0% | ⚠️ GAP | no (fallback) |
| #249 | — | refine | 21,291 | 21,291 | 0.0% | ✅ PASS | no (fallback) |
| #249 | — | plan | 21,291 | 21,291 | 0.0% | ✅ PASS | no (fallback) |
| #249 | — | implement | 17,033 | 17,033 | 0.0% | ✅ PASS | no (fallback) |
| #249 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #249 | — | code-review | 4,368 | 4,368 | 0.0% | ⚠️ GAP | no (fallback) |
| #276 | infrastructure | refine | 21,551 | 11,684 | 45.8% | ✅ PASS | yes |
| #276 | infrastructure | plan | 21,551 | 11,683 | 45.8% | ✅ PASS | yes |
| #276 | infrastructure | implement | 17,293 | 7,425 | 57.1% | ✅ PASS | yes |
| #276 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #276 | — | code-review | 4,628 | 4,628 | 0.0% | ⚠️ GAP | no (fallback) |
| #285 | — | refine | 21,408 | 21,408 | 0.0% | ✅ PASS | no (fallback) |
| #285 | — | plan | 21,408 | 21,408 | 0.0% | ✅ PASS | no (fallback) |
| #285 | — | implement | 17,150 | 17,150 | 0.0% | ✅ PASS | no (fallback) |
| #285 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #285 | — | code-review | 4,485 | 4,485 | 0.0% | ⚠️ GAP | no (fallback) |
| #286 | — | refine | 21,463 | 21,463 | 0.0% | ✅ PASS | no (fallback) |
| #286 | — | plan | 21,463 | 21,463 | 0.0% | ✅ PASS | no (fallback) |
| #286 | — | implement | 17,205 | 17,205 | 0.0% | ✅ PASS | no (fallback) |
| #286 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #286 | — | code-review | 4,540 | 4,540 | 0.0% | ⚠️ GAP | no (fallback) |
| #287 | — | refine | 21,437 | 21,437 | 0.0% | ✅ PASS | no (fallback) |
| #287 | — | plan | 21,437 | 21,437 | 0.0% | ✅ PASS | no (fallback) |
| #287 | — | implement | 17,179 | 17,179 | 0.0% | ✅ PASS | no (fallback) |
| #287 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #287 | — | code-review | 4,514 | 4,514 | 0.0% | ⚠️ GAP | no (fallback) |
| #289 | infrastructure | refine | 21,463 | 21,467 | -0.0% | ✅ PASS | no (fallback) |
| #289 | infrastructure | plan | 21,463 | 21,467 | -0.0% | ✅ PASS | no (fallback) |
| #289 | infrastructure | implement | 17,205 | 17,209 | -0.0% | ✅ PASS | no (fallback) |
| #289 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #289 | — | code-review | 4,540 | 4,540 | 0.0% | ⚠️ GAP | no (fallback) |
| #299 | — | refine | 21,762 | 21,762 | 0.0% | ✅ PASS | no (fallback) |
| #299 | — | plan | 21,762 | 21,762 | 0.0% | ✅ PASS | no (fallback) |
| #299 | — | implement | 17,504 | 17,504 | 0.0% | ✅ PASS | no (fallback) |
| #299 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #299 | — | code-review | 4,839 | 4,839 | 0.0% | ⚠️ GAP | no (fallback) |
| #332 | infrastructure | refine | 21,625 | 11,758 | 45.6% | ✅ PASS | yes |
| #332 | infrastructure | plan | 21,625 | 11,757 | 45.6% | ✅ PASS | yes |
| #332 | infrastructure | implement | 17,367 | 7,499 | 56.8% | ✅ PASS | yes |
| #332 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #332 | — | code-review | 4,702 | 4,702 | 0.0% | ⚠️ GAP | no (fallback) |
| #503 | — | refine | 21,431 | 21,431 | 0.0% | ✅ PASS | no (fallback) |
| #503 | — | plan | 21,431 | 21,431 | 0.0% | ✅ PASS | no (fallback) |
| #503 | — | implement | 17,173 | 17,173 | 0.0% | ✅ PASS | no (fallback) |
| #503 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #503 | — | code-review | 4,508 | 4,508 | 0.0% | ⚠️ GAP | no (fallback) |
| #523 | — | refine | 21,520 | 21,520 | 0.0% | ✅ PASS | no (fallback) |
| #523 | — | plan | 21,520 | 21,520 | 0.0% | ✅ PASS | no (fallback) |
| #523 | — | implement | 17,262 | 17,262 | 0.0% | ✅ PASS | no (fallback) |
| #523 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #523 | — | code-review | 4,597 | 4,597 | 0.0% | ⚠️ GAP | no (fallback) |
| #564 | — | refine | 21,513 | 21,513 | 0.0% | ✅ PASS | no (fallback) |
| #564 | — | plan | 21,513 | 21,513 | 0.0% | ✅ PASS | no (fallback) |
| #564 | — | implement | 17,255 | 17,255 | 0.0% | ✅ PASS | no (fallback) |
| #564 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #564 | — | code-review | 4,590 | 4,590 | 0.0% | ⚠️ GAP | no (fallback) |
| #579 | — | refine | 21,375 | 21,375 | 0.0% | ✅ PASS | no (fallback) |
| #579 | — | plan | 21,375 | 21,375 | 0.0% | ✅ PASS | no (fallback) |
| #579 | — | implement | 17,117 | 17,117 | 0.0% | ✅ PASS | no (fallback) |
| #579 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #579 | — | code-review | 4,452 | 4,452 | 0.0% | ⚠️ GAP | no (fallback) |
| #632 | — | refine | 21,267 | 21,267 | 0.0% | ✅ PASS | no (fallback) |
| #632 | — | plan | 21,267 | 21,267 | 0.0% | ✅ PASS | no (fallback) |
| #632 | — | implement | 17,009 | 17,009 | 0.0% | ✅ PASS | no (fallback) |
| #632 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #632 | — | code-review | 4,344 | 4,344 | 0.0% | ⚠️ GAP | no (fallback) |
| #673 | infrastructure | refine | 21,397 | 21,401 | -0.0% | ✅ PASS | no (fallback) |
| #673 | infrastructure | plan | 21,397 | 21,401 | -0.0% | ✅ PASS | no (fallback) |
| #673 | infrastructure | implement | 17,139 | 17,143 | -0.0% | ✅ PASS | no (fallback) |
| #673 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #673 | — | code-review | 4,474 | 4,474 | 0.0% | ⚠️ GAP | no (fallback) |
| #695 | dark-factory | refine | 21,504 | 21,508 | -0.0% | ✅ PASS | no (fallback) |
| #695 | dark-factory | plan | 21,504 | 21,507 | -0.0% | ✅ PASS | no (fallback) |
| #695 | dark-factory | implement | 17,246 | 17,250 | -0.0% | ✅ PASS | no (fallback) |
| #695 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #695 | — | code-review | 4,581 | 4,581 | 0.0% | ⚠️ GAP | no (fallback) |
| #696 | infrastructure | refine | 21,525 | 21,529 | -0.0% | ✅ PASS | no (fallback) |
| #696 | infrastructure | plan | 21,525 | 21,529 | -0.0% | ✅ PASS | no (fallback) |
| #696 | infrastructure | implement | 17,267 | 17,271 | -0.0% | ✅ PASS | no (fallback) |
| #696 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #696 | — | code-review | 4,602 | 4,602 | 0.0% | ⚠️ GAP | no (fallback) |
| #697 | dark-factory | refine | 21,527 | 9,624 | 55.3% | ✅ PASS | yes |
| #697 | dark-factory | plan | 21,527 | 9,623 | 55.3% | ✅ PASS | yes |
| #697 | dark-factory | implement | 17,269 | 5,365 | 68.9% | ✅ PASS | yes |
| #697 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #697 | — | code-review | 4,604 | 4,604 | 0.0% | ⚠️ GAP | no (fallback) |
| #698 | infrastructure | refine | 21,530 | 21,534 | -0.0% | ✅ PASS | no (fallback) |
| #698 | infrastructure | plan | 21,530 | 21,534 | -0.0% | ✅ PASS | no (fallback) |
| #698 | infrastructure | implement | 17,272 | 17,276 | -0.0% | ✅ PASS | no (fallback) |
| #698 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #698 | — | code-review | 4,607 | 4,607 | 0.0% | ⚠️ GAP | no (fallback) |
| #699 | dark-factory | refine | 21,525 | 21,529 | -0.0% | ✅ PASS | no (fallback) |
| #699 | dark-factory | plan | 21,525 | 21,528 | -0.0% | ✅ PASS | no (fallback) |
| #699 | dark-factory | implement | 17,267 | 17,271 | -0.0% | ✅ PASS | no (fallback) |
| #699 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #699 | — | code-review | 4,602 | 4,602 | 0.0% | ⚠️ GAP | no (fallback) |
| #700 | infrastructure | refine | 21,465 | 21,469 | -0.0% | ✅ PASS | no (fallback) |
| #700 | infrastructure | plan | 21,465 | 21,469 | -0.0% | ✅ PASS | no (fallback) |
| #700 | infrastructure | implement | 17,207 | 17,211 | -0.0% | ✅ PASS | no (fallback) |
| #700 | — | conformance | 4,259 | 4,259 | 0.0% | ⚠️ GAP | no (fallback) |
| #700 | — | code-review | 4,542 | 4,542 | 0.0% | ⚠️ GAP | no (fallback) |

---

## Safety Check Details

Status values: `pass` | `gap:pre-existing` | `gap:regression`

| Rule | #224/refine | #224/plan | #224/implement | #224/conformance | #224/code-review | #332/refine | #332/plan | #332/implement | #332/conformance | #332/code-review | #289/refine | #289/plan | #289/implement | #289/conformance | #289/code-review | #299/refine | #299/plan | #299/implement | #299/conformance | #299/code-review | #286/refine | #286/plan | #286/implement | #286/conformance | #286/code-review | #276/refine | #276/plan | #276/implement | #276/conformance | #276/code-review | #287/refine | #287/plan | #287/implement | #287/conformance | #287/code-review | #215/refine | #215/plan | #215/implement | #215/conformance | #215/code-review | #285/refine | #285/plan | #285/implement | #285/conformance | #285/code-review | #249/refine | #249/plan | #249/implement | #249/conformance | #249/code-review | #579/refine | #579/plan | #579/implement | #579/conformance | #579/code-review | #564/refine | #564/plan | #564/implement | #564/conformance | #564/code-review | #523/refine | #523/plan | #523/implement | #523/conformance | #523/code-review | #503/refine | #503/plan | #503/implement | #503/conformance | #503/code-review | #632/refine | #632/plan | #632/implement | #632/conformance | #632/code-review | #673/refine | #673/plan | #673/implement | #673/conformance | #673/code-review | #695/refine | #695/plan | #695/implement | #695/conformance | #695/code-review | #696/refine | #696/plan | #696/implement | #696/conformance | #696/code-review | #697/refine | #697/plan | #697/implement | #697/conformance | #697/code-review | #698/refine | #698/plan | #698/implement | #698/conformance | #698/code-review | #699/refine | #699/plan | #699/implement | #699/conformance | #699/code-review | #700/refine | #700/plan | #700/implement | #700/conformance | #700/code-review |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| `alembic upgrade head` | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | pass | pass | pass | pass | gap:pre-existing | pass | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing |
| `alembic revision --autogenerate` | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing |
| `npx tsc --noEmit` | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing |
| `docker-compose logs backend` | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing |
| `models/__init__.py` | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing |
| `Import and add it to` | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing |
| `curl` | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | pass | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing | pass | pass | pass | gap:pre-existing | gap:pre-existing |

---

## Section Coverage

| Issue | Component | Sections kept | Sections omitted |
|-------|-----------|---------------|------------------|
| #215 | dark-factory | Service Topology, Celery Task Architecture, Metrics and Observability | Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Catch Up Feature (Universe Aggregate Backfill), Test Architecture |
| #224 | infrastructure | Service Topology, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability | Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, Test Architecture |
| #249 | — | Service Topology, Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability, Test Architecture | none |
| #276 | infrastructure | Service Topology, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability | Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, Test Architecture |
| #285 | — | Service Topology, Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability, Test Architecture | none |
| #286 | — | Service Topology, Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability, Test Architecture | none |
| #287 | — | Service Topology, Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability, Test Architecture | none |
| #289 | infrastructure | Service Topology, Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability, Test Architecture | none |
| #299 | — | Service Topology, Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability, Test Architecture | none |
| #332 | infrastructure | Service Topology, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability | Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, Test Architecture |
| #503 | — | Service Topology, Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability, Test Architecture | none |
| #523 | — | Service Topology, Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability, Test Architecture | none |
| #564 | — | Service Topology, Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability, Test Architecture | none |
| #579 | — | Service Topology, Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability, Test Architecture | none |
| #632 | — | Service Topology, Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability, Test Architecture | none |
| #673 | infrastructure | Service Topology, Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability, Test Architecture | none |
| #695 | dark-factory | Service Topology, Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability, Test Architecture | none |
| #696 | infrastructure | Service Topology, Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability, Test Architecture | none |
| #697 | dark-factory | Service Topology, Celery Task Architecture, Metrics and Observability | Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Catch Up Feature (Universe Aggregate Backfill), Test Architecture |
| #698 | infrastructure | Service Topology, Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability, Test Architecture | none |
| #699 | dark-factory | Service Topology, Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability, Test Architecture | none |
| #700 | infrastructure | Service Topology, Scan Execution Flow, Backend Module Map, Frontend Architecture, Error Tracking System, IB Gateway Integration, Live Scanner, Celery Task Architecture, Catch Up Feature (Universe Aggregate Backfill), Metrics and Observability, Test Architecture | none |

---

## Recommendations

**Scenarios safe to enforce (hard budget) first:**
- `refine` — avg savings 11.3%, no regressions
- `plan` — avg savings 11.3%, no regressions
- `implement` — avg savings 14.0%, no regressions
- `conformance` — avg savings 0.0%, no regressions
- `code-review` — avg savings 0.0%, no regressions

---

*Generated by `dark-factory/evals/token_opt_eval.py`*

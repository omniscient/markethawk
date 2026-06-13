# Trivy Blocking Gate + Password Min-Length Policy

**Date:** 2026-06-13
**Issue:** #293
**Status:** Spec

---

## Problem

Two security gaps surfaced in the v3 architecture review (R08):

1. **Trivy scans are advisory-only.** `.github/workflows/ci-publish.yml` runs
   the `scan` job with `continue-on-error: true` at the job level *and*
   `exit-code: "0"` in the `aquasecurity/trivy-action` step. A CRITICAL CVE
   lands only in the GitHub Security tab; nothing stops the image push. `pip-audit`
   and `npm audit` already block — Trivy is the remaining advisory gate.

2. **No password policy on register.** `POST /api/auth/register` accepts any
   password string. This is the single account that controls live trading
   positions.

---

## Requirements

1. Trivy blocks the `ci-publish` publish job on any **HIGH or CRITICAL** CVE
   that has an available fix.
2. The SARIF upload always runs (`if: always()`) so all findings remain visible
   in the Security tab even on a passing scan.
3. A `.trivyignore` file exists at the repo root so accepted/known findings can
   be suppressed without modifying the workflow.
4. Registering with a password shorter than 12 characters returns **422**.
5. Registering with a password that is on the common-passwords blocklist returns
   **422**.
6. The password policy is enforced via Pydantic validation so no route-level
   boilerplate is needed.

---

## Architecture / Approach

### 1. Trivy blocking gate

**Two-step scan pattern** — one step gates the job; one step uploads SARIF.

The `aquasecurity/trivy-action` at version 0.28.0 does not reliably honour
`exit-code` when `format: sarif` is set (the SARIF formatter and the exit-code
gate are separate code paths). The robust approach is two steps per matrix item:

```yaml
- name: Scan ${{ matrix.image }} — gate (table)
  uses: aquasecurity/trivy-action@0.28.0
  with:
    image-ref: ${{ matrix.image }}:latest
    format: table
    exit-code: "1"
    severity: HIGH,CRITICAL
    ignore-unfixed: true

- name: Scan ${{ matrix.image }} — SARIF upload
  uses: aquasecurity/trivy-action@0.28.0
  if: always()
  with:
    image-ref: ${{ matrix.image }}:latest
    format: sarif
    output: ${{ matrix.sarif }}
    exit-code: "0"

- name: Upload Trivy SARIF for ${{ matrix.image }}
  uses: github/codeql-action/upload-sarif@v3
  if: always()
  with:
    sarif_file: ${{ matrix.sarif }}
    category: trivy-${{ matrix.image }}
```

Two changes also required at the job level:
- Remove `continue-on-error: true` (or set it to `false`).
- The `exit-code: "1"` table step already carries the blocking signal once the
  job-level flag is gone.

**Scope:** `severity: HIGH,CRITICAL` plus `ignore-unfixed: true` keeps the gate
actionable — findings with no upstream fix are unresolvable on our side and
would only force `.trivyignore` entries, eroding gate trust.

**`.trivyignore`:** Create an empty file at repo root with a comment header:

```
# Accepted/known findings — one CVE-ID per line.
# Format: CVE-YYYY-NNNNN [optional expiry date]
# Example: CVE-2023-12345 exp:2026-12-31
```

### 2. Password policy

Add `Field(min_length=12)` plus a Pydantic v2 `field_validator` to
`RegisterRequest` in `backend/app/routers/auth.py`:

```python
_COMMON_PASSWORDS: frozenset[str] = frozenset({
    "password123456", "123456789012", "qwertyuiop12",
    "letmein123456", "welcome12345", "monkey123456",
    "dragon123456", "master123456", "iloveyou1234",
    "sunshine12345", "princess12345", "football12345",
    "shadow123456", "superman12345", "michael12345",
    "jessica12345", "password1234", "charlie12345",
    "donald123456", "batman123456", "trustno112345",
    "starwars1234", "passw0rd1234", "baseball12345",
    "superman1234", "abc123456789", "111111111111",
    "000000000000", "123123123123", "aaaaaaaaaaaa",
})

class RegisterRequest(BaseModel):
    username: str
    password: str = Field(min_length=12)

    @field_validator("password")
    @classmethod
    def password_not_common(cls, v: str) -> str:
        if v.lower() in _COMMON_PASSWORDS:
            raise ValueError("password is too common")
        return v
```

`Field(min_length=12)` handles the length constraint; the validator only needs
to check the blocklist. Pydantic raises a **422** automatically, satisfying the
acceptance criterion with no route-level changes.

The `_COMMON_PASSWORDS` constant is module-level in `auth.py` (not in a shared
module) because there is currently one call site. If a password-change endpoint
is added later, extract it to `app/core/auth.py` at that point.

---

## Alternatives Considered

### Trivy: single scan step

Use a single step with `format: sarif` + `exit-code: "1"`. Simpler YAML, but
Trivy action 0.28.0 does not reliably honour `exit-code` in SARIF mode. Rejected
in favour of the two-step pattern.

### Trivy: block on all severities

Remove the `severity` filter so LOW/MEDIUM findings also fail the job. Rejected —
the issue explicitly scopes to HIGH/CRITICAL, and LOW/MEDIUM noise would
immediately require a `.trivyignore` sprawl that undermines the gate.

### Password: min-length only (no blocklist)

`Field(min_length=12)` alone rejects "password" and "123456" (too short), but
passes "password123456" and "123456789012" — common 12+ char passwords that are
trivially guessable. Rejected in favour of the small hardcoded blocklist.

### Password: zxcvbn library

More comprehensive scoring. Adds a new pip dependency (and therefore additional
Trivy scan surface — ironic given this issue). Rejected as out of scope for
`size: S`.

---

## Open Questions

- None blocking.
- The acceptance criterion for Trivy ("a test image with a known HIGH CVE fails
  ci-publish") is an integration test that must be verified manually or via a
  purpose-built test image. The implementer should confirm the chosen test CVE
  has an available fix so `ignore-unfixed: true` does not inadvertently pass it.

---

## Assumptions

- `aquasecurity/trivy-action@0.28.0` does not reliably honour `exit-code` in
  SARIF mode; hence the two-step pattern. The implementer should verify this
  against the action's changelog and may use a single step if the version in use
  supports it.
- The `_COMMON_PASSWORDS` list covers passwords ≥12 chars that bypass the length
  check. Classic short passwords ("password", "123456") are already rejected by
  `min_length=12` and need not be in the set.
- No password-change or reset endpoint exists currently; single call site
  justifies inline placement.

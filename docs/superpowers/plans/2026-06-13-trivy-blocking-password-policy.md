# Trivy Blocking Gate + Password Min-Length Policy

**Goal:** Close two security gaps identified in the v3 architecture review (R08): (1) make Trivy block CI publish on HIGH/CRITICAL CVEs with available fixes, and (2) enforce a minimum 12-character password with a common-passwords blocklist on `POST /api/auth/register`.

**Issue:** #293  
**Spec:** `docs/superpowers/specs/2026-06-13-trivy-blocking-password-policy-design.md`  
**Date:** 2026-06-13

---

## Architecture

The changes span two independent areas with no shared code:

1. **CI workflow** (`.github/workflows/ci-publish.yml`) — replace the single advisory `trivy-action` step in the `scan` job with two steps per matrix item: a `table` step that blocks on `HIGH,CRITICAL` + `ignore-unfixed` and a `sarif` step with `if: always()` for the Security tab. Remove `continue-on-error: true` from the job.

2. **Auth router** (`backend/app/routers/auth.py`) — add `Field(min_length=12)` and a `field_validator` for the common-passwords blocklist to `RegisterRequest`. Pydantic v2 raises 422 automatically; no route-level change needed.

---

## Tech Stack

- GitHub Actions / `aquasecurity/trivy-action@0.28.0`
- FastAPI + Pydantic v2 (`Field`, `field_validator`)
- pytest + `TestClient`

---

## File Structure

| File | Change |
|------|--------|
| `.github/workflows/ci-publish.yml` | Remove `continue-on-error: true`; split single Trivy step into two steps |
| `.trivyignore` | Create at repo root with comment header |
| `backend/app/routers/auth.py` | Add `_COMMON_PASSWORDS` frozenset, `Field(min_length=12)`, `@field_validator("password")` |
| `backend/tests/api/test_auth.py` | Add 2 new policy tests; update existing tests to use valid passwords |

---

## Task 1 — Trivy blocking gate (CI workflow + .trivyignore)

**Files:** `.github/workflows/ci-publish.yml`, `.trivyignore`

CI/workflow changes have no unit test. The correctness check is a YAML diff review against the spec's two-step pattern.

### Steps

**1.1 Remove `continue-on-error: true` from the `scan` job**

In `.github/workflows/ci-publish.yml`, line 107, remove the `continue-on-error: true` line from the `scan` job definition:

```yaml
  scan:
    runs-on: ubuntu-latest
    needs: [build-backend, build-frontend, build-dark-factory]
    # continue-on-error: true  <-- removed; Trivy must block publish
    strategy:
```

**1.2 Replace the single Trivy step with the two-step pattern**

Remove the existing single `Scan ${{ matrix.image }} with Trivy` step (lines 127–134) and the `Upload Trivy SARIF` step (lines 135–141). Replace them with three steps per matrix item:

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

**Rationale for two steps:** `aquasecurity/trivy-action@0.28.0` does not reliably honour `exit-code` when `format: sarif` is set — the SARIF formatter and the exit-code gate are separate code paths. The table step provides the blocking signal; the SARIF step runs with `if: always()` so findings always reach the Security tab.

**1.3 Create `.trivyignore` at repo root**

```
# Accepted/known findings — one CVE-ID per line.
# Format: CVE-YYYY-NNNNN [optional expiry date]
# Example: CVE-2023-12345 exp:2026-12-31
```

**1.4 Verify the workflow YAML**

```bash
# Confirm no syntax errors (requires GitHub CLI or local yamllint)
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci-publish.yml'))" && echo "YAML OK"

# Confirm continue-on-error is gone
grep -n "continue-on-error" .github/workflows/ci-publish.yml || echo "Not present — correct"

# Confirm both step names exist
grep -n "gate (table)\|SARIF upload\|Upload Trivy SARIF" .github/workflows/ci-publish.yml
```

Expected output:
```
YAML OK
Not present — correct
119:      - name: Scan ghcr.io/... — gate (table)
127:      - name: Scan ghcr.io/... — SARIF upload
134:      - name: Upload Trivy SARIF for ghcr.io/...
```

**1.5 Commit**

```bash
git add .github/workflows/ci-publish.yml .trivyignore
git commit -m "ci: make Trivy block on HIGH/CRITICAL CVEs with available fixes (#293)

- Remove continue-on-error: true from the scan job
- Two-step pattern per matrix image: table step gates (exit-code 1), SARIF step
  uploads with if: always() so Security tab always receives findings
- Scope: severity HIGH,CRITICAL + ignore-unfixed keeps gate actionable
- Create .trivyignore at repo root for accepted/known finding suppression"
```

---

## Task 2 — Password policy on `RegisterRequest`

**Files:** `backend/app/routers/auth.py`, `backend/tests/api/test_auth.py`

### Steps

**2.1 Write failing tests for the policy violations**

Add the following tests to the end of `backend/tests/api/test_auth.py`:

```python
def test_register_short_password_returns_422(db):
    response = client.post(
        "/api/auth/register",
        json={"username": "admin", "password": "short"},
    )
    assert response.status_code == 422


def test_register_common_password_returns_422(db):
    response = client.post(
        "/api/auth/register",
        json={"username": "admin", "password": "password123456"},
    )
    assert response.status_code == 422
```

**2.2 Verify these tests fail (no validation yet)**

```bash
docker-compose exec backend python -m pytest backend/tests/api/test_auth.py::test_register_short_password_returns_422 backend/tests/api/test_auth.py::test_register_common_password_returns_422 -v 2>&1 | tail -15
```

Expected output (both fail — currently no length or blocklist validation):
```
FAILED tests/api/test_auth.py::test_register_short_password_returns_422 - AssertionError: assert 200 == 422
FAILED tests/api/test_auth.py::test_register_common_password_returns_422 - AssertionError: assert 200 == 422
```

**2.3 Implement the password policy in `auth.py`**

Add `Field` and `field_validator` to the existing Pydantic import line, and add the `_COMMON_PASSWORDS` frozenset and updated `RegisterRequest` class.

In `backend/app/routers/auth.py`, update the import from pydantic:

```python
from pydantic import BaseModel, Field, field_validator
```

Add `_COMMON_PASSWORDS` at module level, immediately above the `RegisterRequest` class (after all imports):

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

`Field(min_length=12)` handles the length constraint and Pydantic v2 emits a 422 automatically. The validator only needs to check the blocklist.

**2.4 Update existing tests to use a valid password**

Existing tests in `backend/tests/api/test_auth.py` use `"hunter2"` (7 chars) which will now fail the `min_length=12` constraint. Replace all occurrences of `"hunter2"` with `"correct-horse-staple"` (20 chars, not on blocklist):

Affected tests: `test_register_creates_first_user`, `test_register_blocked_when_user_exists`, `test_login_sets_cookies`, `test_login_wrong_password_returns_401`, `test_me_returns_current_user`, `test_logout_clears_cookies`, `test_login_cookies_have_correct_flags`.

Replace every `"password": "hunter2"` with `"password": "correct-horse-staple"` in the file. There are 9 occurrences (some tests call register twice or use the password in login too):

```python
# All lines with "hunter2" become "correct-horse-staple"
# "wrongpassword" (used in test_login_wrong_password_returns_401) is 13 chars — no change needed
```

**2.5 Verify all tests pass**

```bash
docker-compose exec backend python -m pytest backend/tests/api/test_auth.py -v 2>&1 | tail -20
```

Expected output:
```
PASSED tests/api/test_auth.py::test_auth_status_returns_bootstrapped_false_when_no_users
PASSED tests/api/test_auth.py::test_register_creates_first_user
PASSED tests/api/test_auth.py::test_register_blocked_when_user_exists
PASSED tests/api/test_auth.py::test_login_sets_cookies
PASSED tests/api/test_auth.py::test_login_wrong_password_returns_401
PASSED tests/api/test_auth.py::test_me_returns_current_user
PASSED tests/api/test_auth.py::test_logout_clears_cookies
PASSED tests/api/test_auth.py::test_cookie_secure_defaults_to_true
PASSED tests/api/test_auth.py::test_login_cookies_have_correct_flags
PASSED tests/api/test_auth.py::test_register_short_password_returns_422
PASSED tests/api/test_auth.py::test_register_common_password_returns_422
11 passed in Xs
```

**2.6 Confirm backend reloaded and hit the endpoint**

```bash
docker-compose logs backend --tail=5

# Short password → 422
curl -s -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"short"}' | python -m json.tool
# Expected: {"detail": [{"type": "string_too_short", ...}]}

# Common password → 422
curl -s -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"password123456"}' | python -m json.tool
# Expected: {"detail": [{"type": "value_error", "msg": "Value error, password is too common", ...}]}

# Valid password → 200
curl -s -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"correct-horse-staple"}' | python -m json.tool
# Expected: {"id": "...", "username": "testuser", "created_at": "..."}
```

**2.7 Commit**

```bash
git add backend/app/routers/auth.py backend/tests/api/test_auth.py
git commit -m "feat(auth): enforce min 12-char password + common-passwords blocklist (#293)

- Add Field(min_length=12) to RegisterRequest.password — Pydantic v2 returns
  422 automatically for short passwords, no route changes needed
- Add _COMMON_PASSWORDS frozenset (module-level) + @field_validator to reject
  12+ char passwords that are trivially guessable
- Update existing tests to use 20-char valid password (correct-horse-staple)
- Add test_register_short_password_returns_422 and test_register_common_password_returns_422"
```

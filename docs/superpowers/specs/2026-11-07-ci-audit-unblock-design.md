# CI Dependency-Audit Unblock (pip-audit / npm audit) — Design Spec

**Issue:** #889
**Date:** 2026-11-07
**Status:** Proposed — pending implementation plan

## 1. Overview / Problem Statement

Every PR opened against `main` since 2026-10-16 fails CI on two independent, unrelated
dependency-audit steps, blocking all open Dependabot PRs (#883–#888) from merging:

1. **Backend `test` job, `pip-audit`**: `python-jose 3.5.0` is flagged for
   **PYSEC-2026-4298** (CVSS 3.1: 9.1, aliases CVE-2024-33663 / CVE-2026-85394 /
   GHSA-3qf3-8w2g-rqmx / GHSA-6c5p-j8vq-pqhj). No fixed python-jose release exists —
   the advisory affects every version through 3.5.0.
2. **Frontend `frontend` job, `npm audit --audit-level=high`**: `@humanfs/node <0.16.8`
   (GHSA-p498-v437-472g, moderate, transitive dev dep of `eslint`) and
   `@vitest/mocker 2.1.0–4.1.10` (GHSA-82fw-gwwq-j7x9, moderate, transitive dev dep of
   `vitest`). Both have a direct `npm audit fix` resolution.

`main` itself still reports green only because nothing has re-run its CI since
2026-10-09; it will fail on the same two steps the next time it runs.

## 2. Requirements (from Q&A)

1. `pip-audit -r backend/requirements.txt` passes on a fresh PR against `main`.
2. `npm audit --audit-level=high` (in `frontend/`) passes on a fresh PR against `main`.
3. The python-jose fix must not silently suppress a reachable vulnerability — the
   suppression (if chosen) must be backed by a concrete reachability analysis, written
   down the same way the two existing ignored advisories are (dated comment,
   advisory ID, reasoning), not a bare `--ignore-vuln`.
4. No change to `backend/app/core/auth.py`, `backend/app/main.py`, or any JWT
   behavior — this is a CI-unblock bug (`size: S`), not an auth migration.
5. Dependabot PRs #883–#888 re-run green (or are closed as superseded) once `main`'s
   CI is unblocked — a verification step, not new code.

## 3. Architecture / Approach

### 3.1 Backend: suppress PYSEC-2026-4298 with a dated, reasoned ignore (chosen)

**Reachability analysis** (confirmed against the live OSV record via
`https://api.osv.dev/v1/vulns/PYSEC-2026-4298`): the advisory's attack is an
RS256→HS256 algorithm-confusion forgery — "attackers holding the service's public key
can forge HS256 tokens that pass verification **when algorithms are not explicitly
restricted**." Checked against this codebase:

- `backend/app/core/config.py:83` — `JWT_ALGORITHM = "HS256"` is the only algorithm
  ever used; there is no asymmetric keypair and therefore no public key for an
  attacker to hold.
- `backend/app/core/auth.py:56` and `backend/app/main.py` (`AuthMiddleware`,
  `jwt.decode(token, _settings.JWT_SECRET_KEY, algorithms=[_settings.JWT_ALGORITHM])`)
  — both decode call sites already pass `algorithms=[...]` explicitly, which is
  precisely the mitigating condition the advisory names as the one that defeats the
  bypass.

Both necessary preconditions for the exploit (an exposed public key, and
unrestricted algorithm negotiation at decode time) are absent. This mirrors the
existing suppressions for PYSEC-2022-42969 / PYSEC-2026-1325 (ecdsa Minerva timing
side-channels) already present in this exact dependency chain at
`.github/workflows/ci.yml:47-59` and `backend/requirements.txt:54-62` — same
pattern, same file, same justification style.

**Change**: add `--ignore-vuln PYSEC-2026-4298` to the `pip-audit` invocation in
`.github/workflows/ci.yml`, with a dated (2026-11) comment in the existing "Accepted
advisories" block giving the CVSS score, the advisory's named mitigating condition,
and the two code-site references above. Add the matching note to the comment block
above `python-jose[cryptography]==3.5.0` in `backend/requirements.txt`, repeating the
existing "Revisit if we migrate off python-jose (e.g. to PyJWT)" line so the
suppression isn't mistaken for a closed decision.

Migrating off python-jose (PyJWT/joserfc) is explicitly **out of scope** for this
spec — see Alternatives Considered.

### 3.2 Frontend: `npm audit fix`

Both flagged packages are transitive dev-only dependencies (`eslint` → `@humanfs/node`,
`vitest` → `@vitest/mocker`) with a direct audit-fix resolution and no production
code path. Run `npm audit fix` in `frontend/`, commit the resulting
`frontend/package-lock.json` diff. No `package.json` version-range changes are
expected since these are transitive pins; if `npm audit fix` needs
`--force` to reach a passing state, stop and re-evaluate rather than forcing a
major bump of `eslint`/`vitest` themselves (that would be a separate, larger change).

### 3.3 Verification

1. Push the branch, confirm the `test` and `frontend` CI jobs go green on this PR.
2. Re-run (or close as superseded, if Dependabot has since replaced them) PRs
   #883–#888 once `main` is green.

## 4. Alternatives Considered

- **Replace python-jose with PyJWT** (4 call sites: `auth.py`, `main.py`, two test
  files). Rejected for this spec: the vulnerability is not reachable in this app's
  usage (see 3.1), so a library swap changes security-sensitive auth code (flagged
  as sensitive by this repo's own tooling — see `dark-factory/config/config.yaml`'s
  `epic_autopilot.sensitive_keywords`) for no security benefit, well beyond a
  `size: S` CI-unblock fix. Left as a candidate for a separate, human-reviewed
  follow-up issue, referenced from both inline comments added in 3.1.
- **Bump python-jose to a newer release.** Ruled out — PYSEC-2026-4298 affects all
  versions through 3.5.0 (the version already pinned); no fixed release exists.
- **`npm audit fix --force` or manual `eslint`/`vitest` major bump.** Not needed —
  both findings have a direct non-forcing fix path per the issue and `npm audit`'s
  own output.

## 5. Open Questions (non-blocking)

- None. The one judgment call (ignore vs. replace python-jose) was resolved in Q&A
  below.

## 6. Assumptions (flagged)

- `npm audit fix` resolves both findings without requiring `--force` or a major
  version bump of `eslint`/`vitest`; the issue text states a non-forcing fix is
  available for both. If the implementing agent finds this is no longer true (e.g.
  package registry state has changed since this spec was written), stop and treat
  it as a new, larger decision rather than forcing it through.
- PRs #883–#888 are Dependabot version-bump PRs with no overlapping changes to
  `.github/workflows/ci.yml`, `backend/requirements.txt`, or
  `frontend/package-lock.json`; re-running them after `main` is green should not
  require manual conflict resolution. If any of them do touch these files, rebase
  conflicts are expected and are a normal part of step 3.3, not a spec gap.

# Plan: CI — Validate .archon/workflows/*.yaml Before Merge
**Issue:** #143
**Goal:** Add a step to the existing `test` CI job that fails the build if any `.archon/workflows/*.yaml` file fails YAML parsing, preventing a recurrence of the silent syntax-error regression from PR #138.
**Date:** 2026-06-01
**Branch:** refine/issue-143-ci--validate--archon-workflows---yaml-pa

## Architecture

Only one layer is touched: the GitHub Actions CI pipeline (`.github/workflows/ci.yml`). No application code, no backend models, no frontend changes.

The new step is inserted into the existing `test` job, immediately after the `Install dependencies` step. At that point in the job, Python 3.12 is already available (provisioned by `actions/setup-python@v5`) and the pip cache is warm. The step installs `pyyaml` explicitly (one-liner, resolves from cache instantly if already present transitively), then runs an inline Python script that globs `.archon/workflows/*.yaml`, calls `yaml.safe_load()` on each file, and exits 1 on the first batch of failures — printing each filename and YAML error before exiting.

No new jobs, no new runners, no new external dependencies (Bun, Archon CLI, yq) are introduced.

## Tech Stack

- **GitHub Actions** — CI platform
- **Python 3.12** — already on the `test` runner
- **PyYAML** (`pyyaml`) — installed explicitly in the step; standard Python YAML parser

## File Structure

| File | Action | Notes |
|------|--------|-------|
| `.github/workflows/ci.yml` | Modify | Insert one new step after `Install dependencies` in the `test` job |

No files are created. No other files are modified.

---

## Task 1 — Reproduce the failure locally (TDD red phase)

Introduce a deliberate YAML syntax error into a workflow file, run the validation script locally, and confirm it exits non-zero. This establishes the baseline that the CI step must catch.

**Files:** `.archon/workflows/archon-dark-factory.yaml` (temporary mutation — reverted after verification)

### Steps

1. **Write a throwaway broken YAML file to verify the script fails on it:**

   ```bash
   python3 - <<'PYEOF'
   import sys, yaml

   broken = "key: [\nunclosed bracket"
   try:
       yaml.safe_load(broken)
       print("ERROR: parsed without exception — test invalid")
       sys.exit(1)
   except yaml.YAMLError as e:
       print(f"Confirmed: yaml.safe_load raises on broken YAML: {e}")
       sys.exit(0)
   PYEOF
   ```

   Expected output (exit 0):
   ```
   Confirmed: yaml.safe_load raises on broken YAML: ...
   ```

2. **Run the full validation script against the current `.archon/workflows/` directory to confirm all existing files parse cleanly (green baseline):**

   ```bash
   python3 - <<'PYEOF'
   import sys, glob, yaml

   files = sorted(glob.glob(".archon/workflows/*.yaml"))
   if not files:
       print("No .archon/workflows/*.yaml files found — skipping.")
       sys.exit(0)

   errors = []
   for path in files:
       try:
           with open(path) as f:
               yaml.safe_load(f)
           print(f"  ok  {path}")
       except yaml.YAMLError as e:
           print(f"  FAIL  {path}: {e}")
           errors.append(path)

   if errors:
       print(f"\n{len(errors)} file(s) failed YAML validation.")
       sys.exit(1)

   print(f"\nAll {len(files)} workflow file(s) parsed successfully.")
   PYEOF
   ```

   Expected output (exit 0):
   ```
     ok  .archon/workflows/archon-dark-factory.yaml

   All 1 workflow file(s) parsed successfully.
   ```

3. **Inject a YAML syntax error and confirm the script exits non-zero (red phase):**

   Append a broken line to the workflow file temporarily:
   ```bash
   echo "broken: [unclosed" >> /workspace/markethawk/.archon/workflows/archon-dark-factory.yaml
   ```

   Re-run the validation script from step 2.

   Expected output (exit 1):
   ```
     FAIL  .archon/workflows/archon-dark-factory.yaml: ...

   1 file(s) failed YAML validation.
   ```

4. **Revert the injected error immediately:**

   ```bash
   git -C /workspace/markethawk checkout -- .archon/workflows/archon-dark-factory.yaml
   ```

   Verify the file is clean:
   ```bash
   git -C /workspace/markethawk diff .archon/workflows/archon-dark-factory.yaml
   ```

   Expected output: (empty — no diff)

---

## Task 2 — Insert the validation step into `.github/workflows/ci.yml`

Edit the CI workflow to add the `Validate Archon workflow YAML` step immediately after the `Install dependencies` step in the `test` job.

**Files:** `.github/workflows/ci.yml`

### Steps

1. **Read the current `test` job to locate the insertion point.**

   Open `/workspace/markethawk/.github/workflows/ci.yml`. The relevant section currently reads:

   ```yaml
         - name: Install dependencies
           run: pip install -r backend/requirements.txt

         - name: Dependency audit
   ```

   The new step is inserted between `Install dependencies` and `Dependency audit`.

2. **Apply the edit** — insert the following block between those two steps:

   ```yaml
         - name: Validate Archon workflow YAML
           run: |
             pip install pyyaml --quiet
             python - <<'EOF'
             import sys, glob, yaml

             files = sorted(glob.glob(".archon/workflows/*.yaml"))
             if not files:
                 print("No .archon/workflows/*.yaml files found — skipping.")
                 sys.exit(0)

             errors = []
             for path in files:
                 try:
                     with open(path) as f:
                         yaml.safe_load(f)
                     print(f"  ok  {path}")
                 except yaml.YAMLError as e:
                     print(f"  FAIL  {path}: {e}")
                     errors.append(path)

             if errors:
                 print(f"\n{len(errors)} file(s) failed YAML validation.")
                 sys.exit(1)

             print(f"\nAll {len(files)} workflow file(s) parsed successfully.")
             EOF
   ```

   After the edit, the `test` job steps must appear in this order:
   - `actions/checkout@v4`
   - `Set up Python`
   - `Install dependencies`
   - **`Validate Archon workflow YAML`** ← new
   - `Dependency audit`
   - `Run tests`
   - `Upload coverage report`

3. **Validate the edited `ci.yml` is itself valid YAML:**

   ```bash
   python3 -c "import yaml; yaml.safe_load(open('/workspace/markethawk/.github/workflows/ci.yml'))" && echo "ci.yml: OK"
   ```

   Expected output:
   ```
   ci.yml: OK
   ```

4. **Verify the new step appears in the file at the correct position:**

   ```bash
   grep -n "Validate Archon" /workspace/markethawk/.github/workflows/ci.yml
   ```

   Expected output (line number will be around 38–40):
   ```
   38:      - name: Validate Archon workflow YAML
   ```

   Also confirm ordering by checking surrounding context:
   ```bash
   grep -n -A2 "Install dependencies\|Validate Archon\|Dependency audit" /workspace/markethawk/.github/workflows/ci.yml | head -20
   ```

   Expected: `Install dependencies` line < `Validate Archon` line < `Dependency audit` line.

5. **Commit the change:**

   ```bash
   git -C /workspace/markethawk add .github/workflows/ci.yml
   git -C /workspace/markethawk commit -m "$(cat <<'EOF'
   ci: validate .archon/workflows/*.yaml parses on every PR

   Adds a Python yaml.safe_load step to the test job that fails CI if any
   Archon workflow YAML file has a syntax error, preventing a recurrence of
   the regression in #138 that broke the dark-factory toolchain for a day.

   Closes #143

   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
   EOF
   )"
   ```

---

## Task 3 — Verify the step behaviour end-to-end in a local simulation

Simulate both the passing and failing cases of the new CI step locally, without pushing to GitHub, to confirm the script behaves identically to what will run on the Actions runner.

**Files:** `.archon/workflows/archon-dark-factory.yaml` (temporary mutation — reverted), `.github/workflows/ci.yml` (read-only verification)

### Steps

1. **Passing case — run the exact step `run:` body locally:**

   ```bash
   cd /workspace/markethawk && pip install pyyaml --quiet && python3 - <<'EOF'
   import sys, glob, yaml

   files = sorted(glob.glob(".archon/workflows/*.yaml"))
   if not files:
       print("No .archon/workflows/*.yaml files found — skipping.")
       sys.exit(0)

   errors = []
   for path in files:
       try:
           with open(path) as f:
               yaml.safe_load(f)
           print(f"  ok  {path}")
       except yaml.YAMLError as e:
           print(f"  FAIL  {path}: {e}")
           errors.append(path)

   if errors:
       print(f"\n{len(errors)} file(s) failed YAML validation.")
       sys.exit(1)

   print(f"\nAll {len(files)} workflow file(s) parsed successfully.")
   EOF
   ```

   Expected exit code: `0`
   Expected output includes:
   ```
     ok  .archon/workflows/archon-dark-factory.yaml

   All 1 workflow file(s) parsed successfully.
   ```

2. **Failing case — inject a syntax error and confirm exit 1:**

   ```bash
   echo "broken: [unclosed" >> /workspace/markethawk/.archon/workflows/archon-dark-factory.yaml
   ```

   Re-run the same script block from step 1.

   Expected exit code: `1`
   Expected output includes:
   ```
     FAIL  .archon/workflows/archon-dark-factory.yaml: ...

   1 file(s) failed YAML validation.
   ```

3. **Revert the injected error:**

   ```bash
   git -C /workspace/markethawk checkout -- .archon/workflows/archon-dark-factory.yaml
   ```

   Confirm the file is back to a clean state:
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('/workspace/markethawk/.archon/workflows/archon-dark-factory.yaml')); print('clean')"
   ```

   Expected output: `clean`

4. **Confirm no unintended files are staged or modified:**

   ```bash
   git -C /workspace/markethawk status
   ```

   Expected: working tree clean (the only commit was `ci.yml` in Task 2).

---

## Acceptance Checklist

Before marking this issue done, verify all of the following:

- [ ] `.github/workflows/ci.yml` contains a step named `Validate Archon workflow YAML` in the `test` job, positioned after `Install dependencies`
- [ ] The step uses `pip install pyyaml --quiet` followed by an inline `python -` heredoc
- [ ] The script globs `.archon/workflows/*.yaml` (full directory, not PR diff)
- [ ] The script exits 0 on success and prints a count line (`All N workflow file(s) parsed successfully.`)
- [ ] The script exits 1 on any parse failure and prints the failing filename(s) and YAML error(s)
- [ ] The script handles an empty directory gracefully (exits 0 with a skip message)
- [ ] Running the script locally against the current `.archon/workflows/` directory exits 0 (all files parse)
- [ ] `.github/workflows/ci.yml` itself is valid YAML (`python3 -c "import yaml; yaml.safe_load(open('...'))"` exits 0)
- [ ] No other files were modified

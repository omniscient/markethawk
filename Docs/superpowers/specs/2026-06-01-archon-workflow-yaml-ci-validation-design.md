# CI: Validate .archon/workflows/*.yaml Before Merge

## Overview

On 2026-05-30, the dark-factory toolchain was broken for an entire day because `.archon/workflows/archon-dark-factory.yaml` was merged in PR #138 with a raw YAML syntax error (a heredoc dedented out of a `bash: |` block scalar). Archon's loader aborts on parse failure, causing every workflow dispatch to exit 1 during workflow discovery. This produced 28 consecutive failed plan runs on issue #140 before the root cause was identified and fixed in PR #142.

The broken file merged green because CI never validates Archon workflow YAML. This spec covers adding a validation step that would have caught the regression before merge.

## Requirements

- A PR that introduces any unparseable `.archon/workflows/*.yaml` file must fail CI.
- CI must pass on `main` once PR #142 has landed.
- All `.archon/workflows/*.yaml` files are validated on every PR, not just changed files, to catch breakage introduced by rebases or merge conflict resolution.
- The check must use tooling already present in CI with zero additional setup cost.
- The check must be fast enough that it adds no meaningful latency to the build.
- The step must be clearly named in the CI summary so failures are immediately understandable.

## Architecture / Approach

Add a single step to the existing `test` job in `.github/workflows/ci.yml`. The `test` job already provisions a Python 3.12 runner, so no new runner setup is required. PyYAML is not listed directly in `backend/requirements.txt` but is available as a transitive dependency of `alembic`; to avoid fragile reliance on that transitive availability, the step installs `pyyaml` explicitly before running the validation script.

The step runs a short Python one-liner that globs all `.archon/workflows/*.yaml` files, attempts `yaml.safe_load()` on each, and exits non-zero if any file fails to parse, printing the filename and the YAML error.

**Validation step (inline):**

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

This step must be placed **after** the `Install dependencies` step (`pip install -r backend/requirements.txt`) in the `test` job so that the pip cache is warm and the `pip install pyyaml` line resolves instantly if pyyaml is already present transitively.

## Alternatives Considered

### A: Archon CLI validation via `archon workflow list`

Install Bun and the Archon CLI in CI, run `archon workflow list`, and assert no `failed to load` / `parse error` output appears.

**Advantage:** Uses Archon's real loader, catching both raw YAML syntax errors and Archon-specific schema errors (missing required fields, invalid node types, etc.).

**Disadvantages:**
- Archon is not currently installed in CI. Installing it requires adding Bun (via `oven-sh/setup-bun`), then running `bun link` from the Archon source repo — a fragile step that depends on network availability, Bun version compatibility, and the source repo being accessible.
- Adds approximately 30 seconds of setup time for runner provisioning plus dependency installation.
- Introduces a new external dependency that can itself be the source of CI failures unrelated to the workflows being validated.
- The incident that motivated this issue was a raw YAML syntax error, not a schema error, so the additional coverage does not address the known failure class.

### B (chosen): Python `yaml.safe_load` check

Use Python 3.12 and PyYAML (installed explicitly in the step) to parse all workflow files.

**Advantage:** Zero new runner-level dependencies, sub-second execution, catches the exact failure class (raw YAML syntax errors) that caused the incident.

**Disadvantage:** Does not catch Archon-specific schema errors (e.g., a workflow missing a required `nodes` field that parses as valid YAML). If schema errors become a pain point, a follow-up issue can add schema validation on top of this gate.

### C: Validate only changed files (not chosen)

Scope the check to files modified in the PR diff rather than all `.archon/workflows/*.yaml` files.

**Disadvantage:** Does not catch breakage introduced by a bad rebase or merge conflict resolution touching a file not present in the PR diff. The check is sub-second across 20+ files, so there is no performance justification for this scoping. Rejected in favor of the full-directory sweep.

## Open Questions

- **Schema validation follow-up:** If Archon schema errors (valid YAML, invalid Archon structure) become a recurring source of broken workflows, a follow-up issue should evaluate adding the Archon CLI to CI or writing a lightweight schema check against a known-good JSON Schema derived from the Archon spec. This is explicitly out of scope for this issue.
- **Workflow file count growth:** The glob pattern `*.yaml` covers all future workflow files without requiring CI changes as the catalog grows. No action needed unless a non-workflow YAML file is placed in `.archon/workflows/`, which would be a directory layout concern, not a CI concern.

## Assumptions

- PyYAML is not listed in `backend/requirements.txt` but is installed explicitly by the validation step (`pip install pyyaml --quiet`) to ensure availability regardless of transitive dependency changes.
- The `test` job runs on `ubuntu-latest` with Python 3.12. The inline `python -` heredoc syntax is compatible with the default shell (`bash`) on ubuntu-latest GitHub Actions runners.
- `.archon/workflows/` contains only Archon workflow definitions. If non-workflow YAML files are added to that directory, they will also be validated; this is acceptable behavior.
- The `test` job is the correct job to host this step. If the job structure of `ci.yml` changes significantly (e.g., the `test` job is split or removed), the step should be moved to whichever job first has Python available.

## Implementation Notes

Open `.github/workflows/ci.yml` and locate the `test` job. Find the `Install dependencies` step (`pip install -r backend/requirements.txt`). Insert the following step immediately after it:

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

No other files require changes. The step name "Validate Archon workflow YAML" will appear in the GitHub Actions job summary, making failures immediately identifiable without requiring the developer to inspect logs.

## Review Checklist
1. Placeholder scan: any "TBD", "TODO", "[...]", incomplete sections?
2. Consistency: do sections contradict each other?
3. Scope: focused enough for a single implementation task?
4. Ambiguity: could any requirement be read two different ways?

If issues found, return the CORRECTED spec (full content).
If no issues, return the spec unchanged.

Return ONLY the markdown content. No preamble.

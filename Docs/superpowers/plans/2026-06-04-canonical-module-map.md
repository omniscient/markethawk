# Plan: Canonical Module Map — Strip PROJECT_STRUCTURE.md Prose

**Goal**: Remove all inline prose annotations from `PROJECT_STRUCTURE.md`'s directory tree so `ARCHITECTURE.md` is the single source for per-file responsibility descriptions.  
**Architecture**: Pure documentation edit — no code changes, no migrations, no model changes.  
**Tech Stack**: Python 3 (verification script), bash (git)

## File Structure

| File | Action |
|------|--------|
| `PROJECT_STRUCTURE.md` | Strip `# inline prose` from every tree line; preserve filenames and "Notes for Navigation" |
| `Docs/superpowers/specs/2026-06-04-canonical-module-map-design.md` | Created (spec) |
| `Docs/superpowers/plans/2026-06-04-canonical-module-map.md` | Created (this plan) |

---

## Task 1 — Strip inline prose from `PROJECT_STRUCTURE.md`

**Files**: `PROJECT_STRUCTURE.md`

**Context**: The tree block (between the opening ` ``` ` and closing ` ``` `) contains ~150 file/directory lines, most of which have a trailing prose annotation: `│   ├── somefile.py                     # Description here`. The "Notes for Navigation" section below the fence must be preserved unchanged.

### Step 1 — Write a failing verification check

Create `scripts/check_project_structure_annotations.py` (temporary verification script):

```python
#!/usr/bin/env python3
"""Verify no inline prose annotations remain in PROJECT_STRUCTURE.md tree block."""
import re, sys

content = open('PROJECT_STRUCTURE.md').read()
lines = content.split('\n')
violations = []
in_fence = False

for i, line in enumerate(lines, 1):
    stripped = line.strip()
    if stripped.startswith('```'):
        in_fence = not in_fence
        continue
    if in_fence and re.search(r'\S\s{2,}#\s\S', line):
        violations.append((i, line.rstrip()))

if violations:
    print(f"FAIL: {len(violations)} tree lines still have inline prose:")
    for lineno, text in violations[:15]:
        print(f"  Line {lineno}: {text[:100]}")
    sys.exit(1)
else:
    print(f"PASS: No inline prose in tree ({i} lines checked)")
```

### Step 2 — Verify the check fails (prose annotations exist)

```bash
cd /workspace/markethawk
python3 scripts/check_project_structure_annotations.py
```

Expected output (non-zero exit):
```
FAIL: N tree lines still have inline prose:
  Line 8: │   ├── main.py                     # Entry point: connects to IB Gateway...
  ...
```

### Step 3 — Strip the annotations

Create and run `scripts/strip_project_structure_annotations.py`:

```python
#!/usr/bin/env python3
"""Strip inline # prose comments from PROJECT_STRUCTURE.md tree block.

Only modifies lines inside the ``` fence that match the pattern:
  <tree-drawing chars + filename>  <2+ spaces>  # <prose>
Lines outside the fence (headings, notes) are untouched.
"""
import re

path = 'PROJECT_STRUCTURE.md'
content = open(path).read()
lines = content.split('\n')
result = []
in_fence = False
changed = 0

for line in lines:
    stripped = line.strip()
    if stripped.startswith('```'):
        in_fence = not in_fence
        result.append(line)
        continue

    if in_fence:
        # Pattern: any non-whitespace followed by 2+ spaces then # prose
        new_line = re.sub(r'(\S)\s{2,}#\s.*$', r'\1', line)
        if new_line != line:
            changed += 1
        result.append(new_line)
    else:
        result.append(line)

open(path, 'w').write('\n'.join(result))
print(f"Stripped annotations from {changed} lines in {path}")
```

Run it:

```bash
python3 scripts/strip_project_structure_annotations.py
```

Expected output:
```
Stripped annotations from N lines in PROJECT_STRUCTURE.md
```

### Step 4 — Verify the check now passes

```bash
python3 scripts/check_project_structure_annotations.py
```

Expected output (zero exit):
```
PASS: No inline prose in tree (N lines checked)
```

### Step 5 — Verify "Notes for Navigation" is intact

```bash
grep -c 'Notes for Navigation' PROJECT_STRUCTURE.md
```

Expected: `1`

```bash
grep -A 8 'Notes for Navigation' PROJECT_STRUCTURE.md
```

Expected: the six navigation bullet points are still present.

### Step 6 — Remove temporary scripts and commit

```bash
rm scripts/check_project_structure_annotations.py
rm scripts/strip_project_structure_annotations.py
git add PROJECT_STRUCTURE.md Docs/superpowers/specs/2026-06-04-canonical-module-map-design.md Docs/superpowers/plans/2026-06-04-canonical-module-map.md
git commit -m "$(cat <<'EOF'
docs(#169): strip inline prose from PROJECT_STRUCTURE.md tree

ARCHITECTURE.md is now the single source for per-file responsibility
descriptions. PROJECT_STRUCTURE.md is paths only — no duplicate prose
to drift independently.
EOF
)"
```

---

## Validation Checklist

- [ ] `python3 scripts/check_project_structure_annotations.py` exits 0 after stripping
- [ ] `grep -c 'Notes for Navigation' PROJECT_STRUCTURE.md` returns `1`
- [ ] No binary or Python files are staged (pure docs commit)
- [ ] ARCHITECTURE.md is unchanged (diff shows no modifications)
- [ ] Docs/database-schema.md is unchanged

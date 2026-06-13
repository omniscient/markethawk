"""
OOS entry deduplication classifier for dark-factory conformance scope enforcement.

Usage:
    python3 dedupe_oos.py --oos '<json array>' --spillovers '<json array>'

Classifies each [OOS] entry as:
  create      - no existing match; file a new ticket
  comment:<n> - existing issue <n> has the same embedded dedup-key; post a comment
  suppress    - ruff-reformat class or within-run duplicate; drop silently

Exits 0 on success (JSON to stdout). Exits non-zero on error (message to stderr).
Caller must handle non-zero exit as fail-open fallback (no finding silently lost).
"""
import argparse
import json
import re
import sys

SUPPRESSION_KEYWORDS = [
    "ruff",
    "reformat",
    "formatter",
    "isort",
    "import order",
    "import-ordering",
    "whitespace rewrap",
]

FINDING_TYPES = {
    "ts-type-error":     ["ts2322", "ts2345", "ts type", "typescript", "type error", "type mismatch"],
    "missing-test":      ["missing test", "test coverage", "no test", "untested", "out-of-scope test"],
    "seed-drift":        ["seed", "seed file", "seed drift", "default config", "default value"],
    "unused-import":     ["unused import", "import not used", "f401"],
    "lint-error":        ["lint", "pylint", "flake8", "mypy"],
    "missing-migration": ["migration", "alembic", "schema change"],
    "ts-missing-type":   ["ts2339", "ts2304", "property does not exist", "cannot find name"],
    "ruff-reformat":     ["ruff", "reformat", "formatter", "isort", "import order", "import-ordering"],
}


def _normalize_slug(text, max_len=50):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower().strip())[:max_len]
    slug = slug.strip("-")
    return slug if slug else "other"


def classify_entry(entry, seen_keys, spillovers):
    """
    Classify one [OOS] entry. Returns dict with 'entry', 'action', 'key'.
    Modifies seen_keys in place for within-run dedup.
    """
    # Parse: split on first em-dash separator, fall back to hyphen-dash
    if " — " in entry:
        parts = entry.split(" — ", 1)
    elif " - " in entry:
        parts = entry.split(" - ", 1)
    else:
        parts = [entry, entry]

    file_or_area = parts[0]
    if file_or_area.upper().startswith("[OOS]"):
        file_or_area = file_or_area[5:].strip()
    description = parts[1] if len(parts) > 1 else entry

    # Step 2: Suppression check — raw keyword scan before normalization
    desc_lower = description.lower()
    for kw in SUPPRESSION_KEYWORDS:
        if kw in desc_lower:
            key = f"{file_or_area.lower()}|ruff-reformat"
            return {"entry": entry, "action": "suppress", "key": key}

    # Step 3: Finding-type extraction (first-match wins; skip ruff-reformat safety net)
    finding_type = None
    for type_name, keywords in FINDING_TYPES.items():
        if type_name == "ruff-reformat":
            continue
        for kw in keywords:
            if kw in desc_lower:
                finding_type = type_name
                break
        if finding_type:
            break
    if finding_type is None:
        finding_type = _normalize_slug(description[:50])

    # Step 4: Build normalized key
    key = f"{file_or_area.lower()}|{finding_type}"

    # Step 5: Within-run dedup
    if key in seen_keys:
        return {"entry": entry, "action": "suppress", "key": key}
    seen_keys.add(key)

    # Step 6: Cross-run dedup — primary path via embedded dedup-key
    for issue in sorted(spillovers, key=lambda i: i.get("number", 0)):
        body = issue.get("body") or ""
        m = re.search(r"<!--\s*dedup-key:\s*([^>]+?)\s*-->", body)
        if m and m.group(1).strip() == key:
            return {"entry": entry, "action": f"comment:{issue['number']}", "key": key}

    # Best-effort fallback for keyless legacy issues (advisory; may miss)
    for issue in sorted(spillovers, key=lambda i: i.get("number", 0)):
        body = issue.get("body") or ""
        if re.search(r"<!--\s*dedup-key:", body):
            continue  # has a key but didn't match; skip fallback for keyed issues
        fa_match = re.search(r"\*\*File/area:\*\*\s*(.+)", body)
        if fa_match:
            fa_norm = fa_match.group(1).strip().lower()
            if fa_norm and fa_norm in file_or_area.lower():
                return {"entry": entry, "action": f"comment:{issue['number']}", "key": key}

    return {"entry": entry, "action": "create", "key": key}


def classify_all(oos_entries, spillovers):
    """Classify all OOS entries. Returns list of action dicts."""
    seen_keys = set()
    return [classify_entry(entry, seen_keys, spillovers) for entry in oos_entries]


def main():
    parser = argparse.ArgumentParser(description="OOS entry deduplication classifier")
    parser.add_argument("--oos", required=True, help="JSON array of OOS entry strings")
    parser.add_argument("--spillovers", required=True,
                        help="JSON array of existing open scope-spillover issue objects")
    args = parser.parse_args()

    oos_entries = json.loads(args.oos)
    spillovers = json.loads(args.spillovers)
    results = classify_all(oos_entries, spillovers)
    print(json.dumps(results))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"dedupe_oos.py error: {e}", file=sys.stderr)
        sys.exit(1)

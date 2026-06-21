#!/usr/bin/env python3
"""Smoke tests for ceiling_revisit.py decision logic (issue #355)."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from ceiling_revisit import (
    success_rate,
    classify_keyword,
    build_keyword_analysis,
    build_bucket_table,
    find_new_keyword_candidates,
)

PASS = 0
FAIL = 0

def assert_eq(label, got, expected):
    global PASS, FAIL
    if got == expected:
        print(f"PASS: {label}")
        PASS += 1
    else:
        print(f"FAIL: {label} — got={got!r} expected={expected!r}")
        FAIL += 1

# --- success_rate ---
assert_eq("success_rate: normal",   success_rate({"merged_clean": 3, "merged_with_edits": 1, "closed": 1, "open": 2}), 0.8)
assert_eq("success_rate: all open", success_rate({"merged_clean": 0, "merged_with_edits": 0, "closed": 0, "open": 5}), None)
assert_eq("success_rate: zeros",    success_rate({"merged_clean": 0, "merged_with_edits": 0, "closed": 0, "open": 0}), None)

# --- classify_keyword ---
# (m_baseline=0.70)
assert_eq("classify: n<5 → insufficient",   classify_keyword(n=3, rate=0.40, m_baseline=0.70), "insufficient data — no change")
assert_eq("classify: rate>=baseline → remove", classify_keyword(n=6, rate=0.75, m_baseline=0.70), "remove")
assert_eq("classify: rate>=baseline-0 → remove", classify_keyword(n=5, rate=0.70, m_baseline=0.70), "remove")
assert_eq("classify: ambiguous band",        classify_keyword(n=5, rate=0.58, m_baseline=0.70), "ambiguous — leave unchanged")
assert_eq("classify: rate<baseline-0.15 → keep", classify_keyword(n=5, rate=0.54, m_baseline=0.70), "keep")
assert_eq("classify: n=0 → insufficient",   classify_keyword(n=0, rate=None, m_baseline=0.70), "insufficient data — no change")

# --- build_keyword_analysis ---
prs = [
    {"title": "Run database migration for users", "size": "M", "classification": "merged_clean"},
    {"title": "Another migration task", "size": "M", "classification": "closed"},
    {"title": "Add migration chart feature", "size": "M", "classification": "merged_clean"},
    {"title": "Migration cleanup work", "size": "M", "classification": "merged_clean"},
    {"title": "Big migration project", "size": "M", "classification": "merged_with_edits"},
    {"title": "MIGRATION: remove old table", "size": "M", "classification": "merged_clean"},
]
m_baseline = 0.70
rows = build_keyword_analysis(prs, "migration", m_baseline)
assert_eq("kw analysis: n=6", rows["n"], 6)
assert_eq("kw analysis: rate", rows["rate"], 5/6)
assert_eq("kw analysis: decision → remove", rows["decision"], "remove")

# --- build_bucket_table (spot check) ---
by_size = {
    "S": {"merged_clean": 5, "merged_with_edits": 1, "closed": 0, "open": 1},
    "M": {"merged_clean": 3, "merged_with_edits": 1, "closed": 2, "open": 0},
    "L": {"merged_clean": 0, "merged_with_edits": 0, "closed": 2, "open": 1},
    "XL": {"merged_clean": 0, "merged_with_edits": 1, "closed": 1, "open": 0},
}
table = build_bucket_table(by_size)
# M: (3+1)/(3+1+2) = 0.667
assert_eq("bucket table: M rate", round(table["M"]["rate"], 3), 0.667)
# L+XL combined: (0+0+0+1)/(0+0+0+1+2+1) = 1/4 = 0.25
assert_eq("bucket table: L+XL combined n", table["L+XL"]["n"], 4)
assert_eq("bucket table: L+XL rate", table["L+XL"]["rate"], 0.25)

# --- find_new_keyword_candidates ---
# Needs >=5 M-size *closed* PRs with recurring substring AND >=15pt below M_baseline
prs_new_kw = [
    {"title": "Add rollback logic for deploy", "size": "M", "classification": "closed"},
    {"title": "Improve rollback on failed deploy", "size": "M", "classification": "closed"},
    {"title": "Rollback safety for scanner restart", "size": "M", "classification": "closed"},
    {"title": "Rollback mechanism after DB upgrade", "size": "M", "classification": "closed"},
    {"title": "Add rollback to migration flow", "size": "M", "classification": "closed"},
    # Not enough for "deploy" alone but "rollback" has n=5
]
candidates = find_new_keyword_candidates(prs_new_kw, "migration|migrate|performance|perf|architectur|refactor", m_baseline=0.70)
# "rollback" appears 5 times, all closed → rate=0.0, well below M_baseline-0.15=0.55 → candidate
assert_eq("find_new_kw: rollback is candidate", any("rollback" in c["keyword"] for c in candidates), True)
# "deploy" appears only 2 times → n<5 → not a candidate
assert_eq("find_new_kw: deploy not candidate (n<5)", any("deploy" == c["keyword"] for c in candidates), False)

print(f"\nResults: {PASS} passed, {FAIL} failed")
sys.exit(0 if FAIL == 0 else 1)

"""Unit tests for budget_enforce.py — per-scenario budget derivation."""
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import budget_enforce as be


# ── helpers ──────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "token_optimization": {
        "issue_context": {"reserve_tokens": 2000},
        "architecture": {"max_tokens": 5000, "min_tokens": 2500},
        "memory": {"max_tokens": 1500, "min_tokens": 750},
        "comments": {"max_tokens": 2000, "min_tokens": 1000},
        "diff": {"max_review_tokens": 6000, "min_review_tokens": 3000},
    }
}


def make_sections(
    claude_md_tokens=18000,
    arch_tokens=3000,
    arch_fallback=False,
    issue_context_tokens=500,
    memory_tokens=1500,
    comments_tokens=2000,
    diff_tokens=6000,
    include_arch=True,
    include_issue=True,
    include_memory=True,
    include_comments=True,
    include_diff=True,
    include_claude_md=True,
):
    """Build a minimal sections dict (as context-budget.json would contain)."""
    sections = {}
    if include_claude_md:
        sections["claude_md"] = {"status": "included", "tokens": claude_md_tokens}
    if include_arch:
        sections["architecture_md"] = {
            "status": "included" if arch_fallback else "included_slice",
            "tokens": arch_tokens,
            "fallback": arch_fallback,
        }
    if include_issue:
        sections["issue_context"] = {"status": "included", "tokens": issue_context_tokens}
    if include_memory:
        sections["memory_context"] = {"status": "included", "tokens": memory_tokens}
    if include_comments:
        sections["comments"] = {"status": "included", "tokens": comments_tokens}
    if include_diff:
        sections["diff"] = {"status": "included", "tokens": diff_tokens}
    return sections


# ── Test 1: reserved breakdown — claude_md present ────────────────────────────

def test_reserved_claude_md_present():
    sections = make_sections(claude_md_tokens=18000, arch_fallback=False)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=DEFAULT_CONFIG)
    assert result.claude_md_tokens == 18000


# ── Test 2: reserved breakdown — claude_md absent ─────────────────────────────

def test_reserved_claude_md_absent():
    sections = make_sections(include_claude_md=False, arch_fallback=False)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=DEFAULT_CONFIG)
    assert result.claude_md_tokens == 0


# ── Test 3: reserved breakdown — arch fallback=True reserves arch tokens ──────

def test_reserved_arch_fallback_true():
    sections = make_sections(arch_tokens=5000, arch_fallback=True)
    result = be.derive_caps(sections, budget=60000, arch_fallback=True, config=DEFAULT_CONFIG)
    # architecture_md is reserved when fallback=True
    assert result.reserved_tokens >= sections["claude_md"]["tokens"] + 5000


# ── Test 4: reserved breakdown — arch fallback=False does NOT reserve arch ────

def test_reserved_arch_fallback_false():
    sections = make_sections(
        claude_md_tokens=5000,
        arch_tokens=3000,
        arch_fallback=False,
        issue_context_tokens=2500,
    )
    result = be.derive_caps(sections, budget=60000, arch_fallback=False, config=DEFAULT_CONFIG)
    # only claude_md + issue_context reserved (not arch)
    assert result.reserved_tokens == 5000 + max(2500, 2000)


# ── Test 5: issue_context reservation — floor 2000 applied when actual < 2000 ─

def test_issue_context_floor_applied_when_actual_small():
    sections = make_sections(issue_context_tokens=100, arch_fallback=False, claude_md_tokens=0)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=DEFAULT_CONFIG)
    assert result.issue_context_tokens == 2000


# ── Test 6: issue_context reservation — actual used when actual > 2000 ────────

def test_issue_context_actual_used_when_large():
    sections = make_sections(issue_context_tokens=4500, arch_fallback=False, claude_md_tokens=0)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=DEFAULT_CONFIG)
    assert result.issue_context_tokens == 4500


# ── Test 7: issue_context reservation — exact floor boundary ─────────────────

def test_issue_context_exact_at_floor():
    sections = make_sections(issue_context_tokens=2000, arch_fallback=False, claude_md_tokens=0)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=DEFAULT_CONFIG)
    assert result.issue_context_tokens == 2000


# ── Test 8: allowance = max(0, budget - reserved) when budget > reserved ──────

def test_allowance_positive():
    sections = make_sections(claude_md_tokens=5000, issue_context_tokens=2000, arch_fallback=False)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=DEFAULT_CONFIG)
    expected_reserved = 5000 + 2000  # claude_md + issue_context (floor)
    assert result.allowance == max(0, 30000 - expected_reserved)
    assert result.allowance > 0


# ── Test 9: allowance = 0 when reserved > budget ──────────────────────────────

def test_allowance_zero_when_over_budget():
    sections = make_sections(claude_md_tokens=25000, issue_context_tokens=10000, arch_fallback=False)
    result = be.derive_caps(sections, budget=5000, arch_fallback=False, config=DEFAULT_CONFIG)
    assert result.allowance == 0


# ── Test 10: over_budget=True when reserved >= budget ─────────────────────────

def test_over_budget_true():
    sections = make_sections(claude_md_tokens=25000, issue_context_tokens=10000, arch_fallback=False)
    result = be.derive_caps(sections, budget=5000, arch_fallback=False, config=DEFAULT_CONFIG)
    assert result.over_budget is True


# ── Test 11: over_budget=False when budget > reserved ─────────────────────────

def test_over_budget_false():
    sections = make_sections(claude_md_tokens=5000, issue_context_tokens=2000, arch_fallback=False)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=DEFAULT_CONFIG)
    assert result.over_budget is False


# ── Test 12: proportional distribution — normal case ─────────────────────────

def test_proportional_distribution_normal():
    sections = make_sections(
        claude_md_tokens=0,
        issue_context_tokens=2000,
        arch_fallback=False,
    )
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=DEFAULT_CONFIG)
    # All 4 optimizable sections present; allowance = 30000 - 2000 = 28000
    # Sum of defaults = 5000 + 1500 + 2000 + 6000 = 14500
    # Each should be at its default (28000 >> 14500)
    assert result.derived_caps.get("architecture_md") == 5000
    assert result.derived_caps.get("memory_context") == 1500
    assert result.derived_caps.get("comments") == 2000
    assert result.derived_caps.get("diff") == 6000


# ── Test 13: proportional distribution — floor clamp when allowance tiny ──────

def test_proportional_distribution_floor_clamp():
    sections = make_sections(
        claude_md_tokens=0,
        issue_context_tokens=2000,
        arch_fallback=False,
    )
    # allowance = 1000 - 2000 = 0... need budget > reserve
    # budget=3000, reserve=2000, allowance=1000 (much less than sum of floors=7250)
    result = be.derive_caps(sections, budget=3000, arch_fallback=False, config=DEFAULT_CONFIG)
    # Each section should be clamped to its floor
    assert result.derived_caps.get("architecture_md") == 2500
    assert result.derived_caps.get("memory_context") == 750
    assert result.derived_caps.get("comments") == 1000
    assert result.derived_caps.get("diff") == 3000


# ── Test 14: proportional distribution — default clamp when allowance large ───

def test_proportional_distribution_default_clamp():
    sections = make_sections(
        claude_md_tokens=0,
        issue_context_tokens=0,
        arch_fallback=False,
    )
    # budget=200000, reserve=2000 (floor), allowance=198000 >> 14500 (sum of defaults)
    result = be.derive_caps(sections, budget=200000, arch_fallback=False, config=DEFAULT_CONFIG)
    # Each capped at default
    assert result.derived_caps.get("architecture_md") == 5000
    assert result.derived_caps.get("memory_context") == 1500
    assert result.derived_caps.get("comments") == 2000
    assert result.derived_caps.get("diff") == 6000


# ── Test 15: observe mode — no stdout ─────────────────────────────────────────

def test_observe_mode_no_stdout(tmp_path, capsys):
    cb_json = tmp_path / "context-budget.json"
    cb_json.write_text(json.dumps({
        "scenario": "implement",
        "sections": make_sections(claude_md_tokens=5000, issue_context_tokens=500, arch_fallback=False),
    }))
    be.run_cli([
        "--context-budget-json", str(cb_json),
        "--budget-tokens", "30000",
        "--mode", "observe",
    ])
    captured = capsys.readouterr()
    assert captured.out == ""


# ── Test 16: enforce mode — KEY=VALUE lines to stdout ─────────────────────────

def test_enforce_mode_stdout(tmp_path, capsys):
    cb_json = tmp_path / "context-budget.json"
    cb_json.write_text(json.dumps({
        "scenario": "implement",
        "sections": make_sections(
            claude_md_tokens=5000,
            issue_context_tokens=500,
            arch_fallback=False,
            include_diff=False,  # only 3 optimizable sections present
        ),
    }))
    be.run_cli([
        "--context-budget-json", str(cb_json),
        "--budget-tokens", "30000",
        "--mode", "enforce",
    ])
    captured = capsys.readouterr()
    lines = captured.out.strip().splitlines()
    assert any(l.startswith("TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS=") for l in lines)
    assert any(l.startswith("TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS=") for l in lines)
    assert any(l.startswith("TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS=") for l in lines)
    # diff not present → must NOT appear
    assert not any("DIFF" in l for l in lines)


# ── Test 17: enforce mode — each line is KEY=<positive int> ───────────────────

def test_enforce_mode_values_are_positive_ints(tmp_path, capsys):
    cb_json = tmp_path / "context-budget.json"
    cb_json.write_text(json.dumps({
        "scenario": "implement",
        "sections": make_sections(claude_md_tokens=5000, issue_context_tokens=500, arch_fallback=False),
    }))
    be.run_cli([
        "--context-budget-json", str(cb_json),
        "--budget-tokens", "30000",
        "--mode", "enforce",
    ])
    captured = capsys.readouterr()
    for line in captured.out.strip().splitlines():
        key, _, value = line.partition("=")
        assert key.startswith("TOKEN_OPTIMIZATION_"), f"Unexpected key: {key}"
        assert int(value) > 0


# ── Test 18: config-driven floors ─────────────────────────────────────────────

def test_config_driven_floors():
    custom_config = {
        "token_optimization": {
            "issue_context": {"reserve_tokens": 2000},
            "architecture": {"max_tokens": 3000, "min_tokens": 100},
            "memory": {"max_tokens": 1500, "min_tokens": 100},
            "comments": {"max_tokens": 2000, "min_tokens": 100},
            "diff": {"max_review_tokens": 6000, "min_review_tokens": 100},
        }
    }
    sections = make_sections(
        claude_md_tokens=0,
        issue_context_tokens=2000,
        arch_fallback=False,
    )
    # allowance = 1 → raw proportional would be tiny → clamp to custom floor 100
    result = be.derive_caps(sections, budget=2001, arch_fallback=False, config=custom_config)
    assert result.derived_caps.get("architecture_md") == 100
    assert result.derived_caps.get("memory_context") == 100
    assert result.derived_caps.get("comments") == 100
    assert result.derived_caps.get("diff") == 100


# ── Test 19: absent-section skipping ─────────────────────────────────────────

def test_absent_section_skipped():
    sections = make_sections(
        claude_md_tokens=0,
        issue_context_tokens=2000,
        arch_fallback=False,
        include_diff=False,
        include_comments=False,
    )
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=DEFAULT_CONFIG)
    assert "diff" not in result.derived_caps
    assert "comments" not in result.derived_caps
    assert "architecture_md" in result.derived_caps
    assert "memory_context" in result.derived_caps


# ── Test 20: sections_skipped list populated ─────────────────────────────────

def test_sections_skipped_populated():
    sections = make_sections(
        claude_md_tokens=0,
        issue_context_tokens=2000,
        arch_fallback=False,
        include_diff=False,
    )
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=DEFAULT_CONFIG)
    assert "diff" in result.sections_skipped


# ── Test 21: would_trim=True when any cap < default ──────────────────────────

def test_would_trim_true():
    sections = make_sections(
        claude_md_tokens=0,
        issue_context_tokens=2000,
        arch_fallback=False,
    )
    # Small budget forces some caps below default
    result = be.derive_caps(sections, budget=4000, arch_fallback=False, config=DEFAULT_CONFIG)
    assert result.would_trim is True


# ── Test 22: would_trim=False when all caps at default ───────────────────────

def test_would_trim_false():
    sections = make_sections(
        claude_md_tokens=0,
        issue_context_tokens=2000,
        arch_fallback=False,
    )
    # Large budget → all caps at default
    result = be.derive_caps(sections, budget=200000, arch_fallback=False, config=DEFAULT_CONFIG)
    assert result.would_trim is False


# ── Test 23: int() truncation — proportional raw values are truncated ─────────

def test_int_truncation_produces_non_negative_caps():
    """Proportional raw values truncated via int() — caps must remain >= floor."""
    sections = make_sections(
        claude_md_tokens=0,
        issue_context_tokens=2000,
        arch_fallback=False,
    )
    # allowance=3 → raw per section << floor → clamp to floor
    result = be.derive_caps(sections, budget=2003, arch_fallback=False, config=DEFAULT_CONFIG)
    for sec, cap in result.derived_caps.items():
        assert cap >= 0, f"Negative cap for {sec}"


# ── Test 24: missing config → hardcoded defaults ─────────────────────────────

def test_missing_config_uses_hardcoded_defaults():
    """When config path is missing/invalid, derive_caps falls back to hardcoded defaults."""
    config = be._load_config("/nonexistent/path/config.yaml")
    # Should return defaults without error
    assert config is not None
    assert config["token_optimization"]["architecture"]["max_tokens"] == 5000
    assert config["token_optimization"]["architecture"]["min_tokens"] == 2500


# ── Test 25: comment_digest (continue scenario) maps to COMMENTS env var ──────

def test_comment_digest_maps_to_comments_env_var(tmp_path, capsys):
    sections = {
        "claude_md": {"status": "included", "tokens": 5000},
        "architecture_md": {"status": "included_slice", "tokens": 3000, "fallback": False},
        "issue_context": {"status": "included", "tokens": 500},
        "memory_context": {"status": "included", "tokens": 1500},
        "comment_digest": {"status": "included", "tokens": 2000},  # continue scenario
    }
    cb_json = tmp_path / "context-budget.json"
    cb_json.write_text(json.dumps({"scenario": "continue", "sections": sections}))
    be.run_cli([
        "--context-budget-json", str(cb_json),
        "--budget-tokens", "30000",
        "--mode", "enforce",
    ])
    captured = capsys.readouterr()
    assert any(l.startswith("TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS=") for l in captured.out.splitlines())


# ── Test 26: over_budget — derived_caps use floors, not zero ─────────────────

def test_over_budget_derives_floor_caps():
    """Even when over_budget, optimizable sections still receive floor caps."""
    sections = make_sections(claude_md_tokens=25000, issue_context_tokens=10000, arch_fallback=False)
    result = be.derive_caps(sections, budget=5000, arch_fallback=False, config=DEFAULT_CONFIG)
    assert result.over_budget is True
    # Caps should still be set to floor values, not zero
    for sec in ("architecture_md", "memory_context", "comments", "diff"):
        if sec in result.derived_caps:
            assert result.derived_caps[sec] > 0


# ── Test 27: enforce mode — status printed to stderr not stdout ───────────────

def test_enforce_mode_status_on_stderr(tmp_path, capsys):
    cb_json = tmp_path / "context-budget.json"
    cb_json.write_text(json.dumps({
        "scenario": "implement",
        "sections": make_sections(claude_md_tokens=5000, issue_context_tokens=500, arch_fallback=False),
    }))
    be.run_cli([
        "--context-budget-json", str(cb_json),
        "--budget-tokens", "30000",
        "--mode", "enforce",
    ])
    captured = capsys.readouterr()
    # Status/diagnostic messages go to stderr, not stdout
    # stdout should only have KEY=VALUE lines
    for line in captured.out.strip().splitlines():
        assert "=" in line, f"Non KEY=VALUE line on stdout: {line!r}"


# ── Test 28: load_config from actual config.yaml ─────────────────────────────

def test_load_config_reads_real_yaml(tmp_path):
    yaml_content = (
        "token_optimization:\n"
        "  issue_context:\n"
        "    reserve_tokens: 2500\n"
        "  architecture:\n"
        "    max_tokens: 4000\n"
        "    min_tokens: 2000\n"
        "  memory:\n"
        "    max_tokens: 1200\n"
        "    min_tokens: 600\n"
        "  comments:\n"
        "    max_tokens: 1800\n"
        "    min_tokens: 900\n"
        "  diff:\n"
        "    max_review_tokens: 5000\n"
        "    min_review_tokens: 2500\n"
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_content)
    config = be._load_config(str(cfg_path))
    to = config["token_optimization"]
    assert to["issue_context"]["reserve_tokens"] == 2500
    assert to["architecture"]["max_tokens"] == 4000
    assert to["architecture"]["min_tokens"] == 2000
    assert to["memory"]["min_tokens"] == 600
    assert to["comments"]["min_tokens"] == 900
    assert to["diff"]["min_review_tokens"] == 2500


# ── Test 29: write-back in observe mode — six fields written to JSON ──────────

def test_writeback_observe_mode(tmp_path):
    cb_json = tmp_path / "context-budget.json"
    cb_json.write_text(json.dumps({
        "scenario": "implement",
        "schema_version": 2,
        "sections": make_sections(claude_md_tokens=5000, issue_context_tokens=500, arch_fallback=False),
    }))
    be.run_cli([
        "--context-budget-json", str(cb_json),
        "--budget-tokens", "30000",
        "--mode", "observe",
    ])
    data = json.loads(cb_json.read_text())
    assert "over_budget" in data
    assert "would_trim" in data
    assert "derived_caps" in data
    assert "scenario_budget" in data
    assert "reserved_tokens" in data
    assert "allowance" in data
    assert data["scenario_budget"] == 30000
    assert isinstance(data["derived_caps"], dict)


# ── Test 30: write-back in enforce mode — six fields also written ──────────────

def test_writeback_enforce_mode(tmp_path, capsys):
    cb_json = tmp_path / "context-budget.json"
    cb_json.write_text(json.dumps({
        "scenario": "refine",
        "schema_version": 2,
        "sections": make_sections(claude_md_tokens=5000, issue_context_tokens=500, arch_fallback=False),
    }))
    be.run_cli([
        "--context-budget-json", str(cb_json),
        "--budget-tokens", "30000",
        "--mode", "enforce",
    ])
    data = json.loads(cb_json.read_text())
    assert "over_budget" in data
    assert "would_trim" in data
    assert "derived_caps" in data
    assert "scenario_budget" in data
    assert data["scenario_budget"] == 30000
    assert isinstance(data["over_budget"], bool)


# ── Test 31: write-back fail-open — unwritable path raises no exception ────────

def test_writeback_fail_open_on_missing_path(tmp_path):
    cb_json = tmp_path / "context-budget.json"
    cb_json.write_text(json.dumps({
        "scenario": "implement",
        "schema_version": 2,
        "sections": make_sections(claude_md_tokens=5000, issue_context_tokens=500, arch_fallback=False),
    }))
    # Pass a nonexistent directory as the JSON path — write-back should not raise
    bad_path = str(tmp_path / "nonexistent" / "context-budget.json")
    # run_cli will fail on the *read* step for a missing file — use the valid file for
    # reading but simulate write failure by making the directory read-only after read.
    # Simpler: just verify that run_cli with a valid file does not raise even if the
    # file cannot be re-written (chmod the file to read-only after writing).
    import stat
    # Write valid content, then remove write permission
    cb_json.chmod(stat.S_IRUSR | stat.S_IRGRP)
    try:
        # Should not raise even though write-back will fail
        be.run_cli([
            "--context-budget-json", str(cb_json),
            "--budget-tokens", "30000",
            "--mode", "observe",
        ])
    finally:
        cb_json.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)


# ── Test 32: write-back preserves existing fields ─────────────────────────────

def test_writeback_preserves_existing_fields(tmp_path):
    cb_json = tmp_path / "context-budget.json"
    original = {
        "scenario": "implement",
        "schema_version": 2,
        "estimated_input_tokens": 42000,
        "savings_tokens": 1200,
        "savings_pct": 5,
        "sections": make_sections(claude_md_tokens=5000, issue_context_tokens=500, arch_fallback=False),
    }
    cb_json.write_text(json.dumps(original))
    be.run_cli([
        "--context-budget-json", str(cb_json),
        "--budget-tokens", "30000",
        "--mode", "observe",
    ])
    data = json.loads(cb_json.read_text())
    assert data["scenario"] == "implement"
    assert data["schema_version"] == 2
    assert data["estimated_input_tokens"] == 42000
    assert data["savings_tokens"] == 1200
    assert data["savings_pct"] == 5

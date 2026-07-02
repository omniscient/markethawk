"""Tests for per-feature token optimization flags (R1) — T1, T2, T6."""
import pathlib

import pytest
import yaml

CONFIG = pathlib.Path(__file__).resolve().parents[2] / ".claude/skills/refinement/config.yaml"


def _tok_opt():
    return yaml.safe_load(CONFIG.read_text()).get("token_optimization", {})


# ── T1: config.yaml enabled flags ────────────────────────────────────────────

def test_architecture_enabled_flag_exists():
    assert "enabled" in _tok_opt().get("architecture", {}), \
        "architecture sub-section must have an 'enabled' key"


def test_memory_enabled_flag_exists():
    assert "enabled" in _tok_opt().get("memory", {}), \
        "memory sub-section must have an 'enabled' key"


def test_comments_enabled_flag_exists():
    assert "enabled" in _tok_opt().get("comments", {}), \
        "comments sub-section must have an 'enabled' key"


def test_diff_enabled_flag_exists():
    assert "enabled" in _tok_opt().get("diff", {}), \
        "diff sub-section must have an 'enabled' key"


# ── T2: scheduler.sh env var wiring ──────────────────────────────────────────

def _scheduler_content():
    return (pathlib.Path(__file__).resolve().parents[1] / "scheduler.sh").read_text()


def test_scheduler_wires_architecture_enabled():
    content = _scheduler_content()
    assert "TOKEN_OPTIMIZATION_ARCHITECTURE_ENABLED" in content
    assert ".token_optimization.architecture.enabled" in content


def test_scheduler_wires_memory_enabled():
    content = _scheduler_content()
    assert "TOKEN_OPTIMIZATION_MEMORY_ENABLED" in content
    assert ".token_optimization.memory.enabled" in content


def test_scheduler_wires_comments_enabled():
    content = _scheduler_content()
    assert "TOKEN_OPTIMIZATION_COMMENTS_ENABLED" in content
    assert ".token_optimization.comments.enabled" in content


def test_scheduler_wires_diff_enabled():
    content = _scheduler_content()
    assert "TOKEN_OPTIMIZATION_DIFF_ENABLED" in content
    assert ".token_optimization.diff.enabled" in content


# ── T6: workflow YAML comment digest gate ─────────────────────────────────────

def test_workflow_gates_comment_digest_on_env_var():
    content = (
        pathlib.Path(__file__).resolve().parents[2]
        / ".archon/workflows/archon-dark-factory.yaml"
    ).read_text()
    assert "TOKEN_OPTIMIZATION_COMMENTS_ENABLED" in content

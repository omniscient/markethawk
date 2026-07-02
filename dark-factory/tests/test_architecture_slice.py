"""Tests for architecture_slice.py — 12 slicer unit tests."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import architecture_slice as aslice

# ── fixture helpers ───────────────────────────────────────────────────────────

_ARCH_CONTENT = textwrap.dedent("""\
    # Architecture

    ## Service Topology

    Service topology content here.

    ## Scan Execution Flow

    Scan execution flow content here.

    ## Backend Module Map

    Backend module map content here.

    ## Frontend Architecture

    Frontend architecture content here.

    ## Error Tracking System

    Error tracking content here.

    ## IB Gateway Integration

    IBKR gateway content here.

    ## Live Scanner

    Live scanner content here.

    ## Celery Task Architecture

    Celery content here.

    ## Catch Up Feature (Universe Aggregate Backfill)

    Catch up content here.

    ## Metrics and Observability

    Metrics content here.

    ## Test Architecture

    Test architecture content here.
""")


@pytest.fixture()
def arch_file(tmp_path):
    p = tmp_path / "ARCHITECTURE.md"
    p.write_text(_ARCH_CONTENT)
    return str(p)


def make_config(tmp_path, hard_exclude_paths=None):
    """Write a minimal config.yaml with hardcoded safe defaults (no dark-factory/ exclusion)."""
    paths = hard_exclude_paths or ["app/services/trading", "app/tasks/trading.py",
                                   "app/core/auth", "app/routers/auth"]
    path_lines = "\n".join(f'    - "{p}"' for p in paths)
    content = textwrap.dedent(f"""\
        dispatch_ceiling:
          keywords: "migration|migrate|performance|perf|architectur|refactor"
        epic_autopilot:
          sensitive_keywords: "trading|ibkr|live order|notional|authentication|authorization|authn|authz|jwt|oauth|rbac"
          hard_exclude_paths:
        {path_lines}
    """)
    p = tmp_path / ".claude" / "skills" / "refinement" / "config.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return str(tmp_path)


# ── 1: Section parsing ────────────────────────────────────────────────────────

def test_parse_sections_returns_all_headings(arch_file):
    sections = aslice._parse_sections(arch_file)
    expected = {
        "Service Topology",
        "Scan Execution Flow",
        "Backend Module Map",
        "Frontend Architecture",
        "Error Tracking System",
        "IB Gateway Integration",
        "Live Scanner",
        "Celery Task Architecture",
        "Catch Up Feature (Universe Aggregate Backfill)",
        "Metrics and Observability",
        "Test Architecture",
    }
    assert set(sections.keys()) == expected


def test_parse_sections_content_includes_heading(arch_file):
    sections = aslice._parse_sections(arch_file)
    assert "## Backend Module Map" in sections["Backend Module Map"]
    assert "Backend module map content here" in sections["Backend Module Map"]


# ── 2: Component slicing ──────────────────────────────────────────────────────

def test_backend_slice_includes_correct_sections(arch_file, tmp_path):
    clone_dir = make_config(tmp_path)
    result = aslice.slice_architecture(
        arch_path=arch_file, scenario="implement",
        spec_component="backend", clone_dir=clone_dir,
    )
    assert not result.fallback
    assert result.component == "backend"
    for sec in aslice.COMPONENT_SECTION_MAP["backend"]:
        assert sec in result.included_sections
    assert "Frontend Architecture" in result.omitted_sections
    assert "IB Gateway Integration" in result.omitted_sections


def test_frontend_slice_includes_correct_sections(arch_file, tmp_path):
    clone_dir = make_config(tmp_path)
    result = aslice.slice_architecture(
        arch_path=arch_file, scenario="refine",
        spec_component="frontend", clone_dir=clone_dir,
    )
    assert not result.fallback
    assert result.component == "frontend"
    for sec in aslice.COMPONENT_SECTION_MAP["frontend"]:
        assert sec in result.included_sections
    assert "Scan Execution Flow" in result.omitted_sections
    assert "IB Gateway Integration" in result.omitted_sections


def test_dark_factory_slice_includes_correct_sections(arch_file, tmp_path):
    clone_dir = make_config(tmp_path)
    result = aslice.slice_architecture(
        arch_path=arch_file, scenario="plan",
        spec_component="dark-factory", clone_dir=clone_dir,
    )
    assert not result.fallback
    assert result.component == "dark-factory"
    for sec in aslice.COMPONENT_SECTION_MAP["dark-factory"]:
        assert sec in result.included_sections
    assert "Scan Execution Flow" in result.omitted_sections
    assert "Frontend Architecture" in result.omitted_sections


def test_infrastructure_slice_includes_correct_sections(arch_file, tmp_path):
    clone_dir = make_config(tmp_path)
    result = aslice.slice_architecture(
        arch_path=arch_file, scenario="implement",
        spec_component="infrastructure", clone_dir=clone_dir,
    )
    assert not result.fallback
    assert result.component == "infrastructure"
    for sec in aslice.COMPONENT_SECTION_MAP["infrastructure"]:
        assert sec in result.included_sections
    assert "Backend Module Map" in result.omitted_sections


# ── 3: Fallback paths ─────────────────────────────────────────────────────────

def test_fallback_on_component_inference_failure(arch_file, tmp_path):
    clone_dir = make_config(tmp_path)
    result = aslice.slice_architecture(
        arch_path=arch_file, scenario="implement",
        spec_component=None, changed_files=[], labels=[], clone_dir=clone_dir,
    )
    assert result.fallback
    assert result.fallback_reason == "component_unresolved"
    assert result.component is None
    assert "## Service Topology" in result.text


def test_fallback_on_safety_keyword_in_labels(arch_file, tmp_path):
    clone_dir = make_config(tmp_path)
    result = aslice.slice_architecture(
        arch_path=arch_file, scenario="implement",
        spec_component="backend",
        labels=["migration", "size: S"],
        clone_dir=clone_dir,
    )
    assert result.fallback
    assert result.fallback_reason is not None
    assert "safety_keyword" in result.fallback_reason


def test_fallback_on_hard_exclude_path(arch_file, tmp_path):
    clone_dir = make_config(tmp_path)
    result = aslice.slice_architecture(
        arch_path=arch_file, scenario="implement",
        spec_component="backend",
        changed_files=["backend/app/core/auth.py"],
        clone_dir=clone_dir,
    )
    assert result.fallback
    assert result.fallback_reason is not None
    assert "safety_file" in result.fallback_reason


def test_fallback_on_cross_cutting_infra_file(arch_file, tmp_path):
    clone_dir = make_config(tmp_path)
    result = aslice.slice_architecture(
        arch_path=arch_file, scenario="implement",
        spec_component="backend",
        changed_files=["docker-compose.yml"],
        clone_dir=clone_dir,
    )
    assert result.fallback
    assert result.fallback_reason is not None
    assert "safety_file" in result.fallback_reason


# ── 4: Component inference ────────────────────────────────────────────────────

def test_infer_component_from_changed_files():
    assert aslice.infer_component(
        spec_file=None,
        changed_files=["backend/app/routers/scanner.py"],
        labels=[],
    ) == "backend"
    assert aslice.infer_component(
        spec_file=None,
        changed_files=["frontend/src/components/Scanner.tsx"],
        labels=[],
    ) == "frontend"
    assert aslice.infer_component(
        spec_file=None,
        changed_files=["dark-factory/scripts/context_budget.py"],
        labels=[],
    ) == "dark-factory"
    assert aslice.infer_component(
        spec_file=None,
        changed_files=["docker-compose.yml"],
        labels=[],
    ) == "infrastructure"


def test_infer_component_from_spec_file():
    assert aslice.infer_component(
        spec_file="docs/superpowers/specs/2026-01-01-celery-backend-scanner.md",
        changed_files=[],
        labels=[],
    ) == "backend"
    assert aslice.infer_component(
        spec_file="docs/superpowers/specs/2026-01-01-frontend-ui-react.md",
        changed_files=[],
        labels=[],
    ) == "frontend"
    assert aslice.infer_component(
        spec_file="docs/superpowers/specs/2026-01-01-dark-factory-plan.md",
        changed_files=[],
        labels=[],
    ) == "dark-factory"


# ── 5: Slice metadata ─────────────────────────────────────────────────────────

def test_slice_has_html_comment_header(arch_file, tmp_path):
    clone_dir = make_config(tmp_path)
    result = aslice.slice_architecture(
        arch_path=arch_file, scenario="implement",
        spec_component="backend", clone_dir=clone_dir,
    )
    assert result.text.startswith("<!-- architecture-slice:")
    assert "component=backend" in result.text
    assert "scenario=implement" in result.text


def test_fallback_html_comment_indicates_full_load(arch_file, tmp_path):
    clone_dir = make_config(tmp_path)
    result = aslice.slice_architecture(
        arch_path=arch_file, scenario="refine",
        spec_component=None, changed_files=[], labels=[], clone_dir=clone_dir,
    )
    assert result.text.startswith("<!-- architecture-slice:")
    assert "fallback=true" in result.text
    assert "full ARCHITECTURE.md loaded" in result.text


def test_section_hashes_present_for_included_sections(arch_file, tmp_path):
    clone_dir = make_config(tmp_path)
    result = aslice.slice_architecture(
        arch_path=arch_file, scenario="implement",
        spec_component="backend", clone_dir=clone_dir,
    )
    for sec in result.included_sections:
        assert sec in result.section_hashes
        assert len(result.section_hashes[sec]) == 12


# ── T3: feature-disabled bypass (R1/R4) ─────────────────────────────────────

def test_slice_bypasses_when_feature_disabled(arch_file, tmp_path):
    """slice_architecture() must return full-doc fallback when architecture.enabled is false."""
    cfg_dir = tmp_path / ".claude" / "skills" / "refinement"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(textwrap.dedent("""\
        token_optimization:
          architecture:
            enabled: false
    """))
    result = aslice.slice_architecture(
        arch_path=arch_file,
        scenario="implement",
        spec_file="backend/app/services/scanner.py",
        clone_dir=str(tmp_path),
    )
    assert result.fallback is True
    assert result.fallback_reason == "feature_disabled"


def test_slice_proceeds_when_feature_enabled(arch_file, tmp_path):
    """slice_architecture() must NOT bypass slicing when architecture.enabled is true."""
    cfg_dir = tmp_path / ".claude" / "skills" / "refinement"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(textwrap.dedent("""\
        token_optimization:
          architecture:
            enabled: true
    """))
    result = aslice.slice_architecture(
        arch_path=arch_file,
        scenario="implement",
        spec_file="backend/app/services/scanner.py",
        clone_dir=str(tmp_path),
    )
    assert result.fallback_reason != "feature_disabled"

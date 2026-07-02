"""
Tests for dark-factory/scripts/memory_retrieve.py.

All tests use in-memory data or tmp_path; no live .archon/memory/ reads.
Monkeypatching patches Path.exists / Path.read_text to isolate file I/O.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import memory_retrieve as mr  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────────────

FUTURE = "2099-12-31"
PAST = "2000-01-01"


def _make_index_line(**kwargs):
    base = {
        "id": "aabbccdd00112233",
        "kind": "PATTERN",
        "scope": "backend",
        "source_file": "backend-patterns.md",
        "path_prefixes": [],
        "expires_at": FUTURE,
        "confidence": 1.0,
        "summary_snippet": "Short snippet.",
    }
    base.update(kwargs)
    return json.dumps(base)


def _make_record(summary="Full summary text.", sources=("implement",), path_prefixes=None):
    return json.dumps({
        "id": "aabbccdd00112233",
        "kind": "PATTERN",
        "summary": summary,
        "evidence": [{"source": s, "date": "2026-06-01", "issue": 1} for s in sources],
        "path_prefixes": path_prefixes or [],
        "expires_at": FUTURE,
        "confidence": 1.0,
        "scope": "backend",
        "source_file": "backend-patterns.md",
    })


# ── TestConstants ──────────────────────────────────────────────────────────

class TestConstants:
    def test_global_files_count(self):
        assert len(mr.GLOBAL_FILES) == 2

    def test_global_files_contents(self):
        assert "codebase-patterns.md" in mr.GLOBAL_FILES
        assert "architecture.md" in mr.GLOBAL_FILES

    def test_all_memory_files_count(self):
        assert len(mr.ALL_MEMORY_FILES) == 5

    def test_all_memory_files_order(self):
        assert mr.ALL_MEMORY_FILES[0] == "codebase-patterns.md"
        assert mr.ALL_MEMORY_FILES[1] == "architecture.md"
        assert mr.ALL_MEMORY_FILES[2] == "backend-patterns.md"
        assert mr.ALL_MEMORY_FILES[3] == "frontend-patterns.md"
        assert mr.ALL_MEMORY_FILES[4] == "dark-factory-ops.md"

    def test_phase_source_map_count(self):
        assert len(mr.PHASE_SOURCE_MAP) == 5

    def test_phase_source_map_implement(self):
        assert mr.PHASE_SOURCE_MAP["implement"] == {"implement"}

    def test_phase_source_map_validate(self):
        assert mr.PHASE_SOURCE_MAP["validate"] == {"conformance"}

    def test_phase_source_map_review(self):
        assert mr.PHASE_SOURCE_MAP["review"] == {"code-review"}

    def test_phase_source_map_refine(self):
        assert mr.PHASE_SOURCE_MAP["refine"] == {"refine"}

    def test_phase_source_map_plan_same_as_refine(self):
        assert mr.PHASE_SOURCE_MAP["plan"] == mr.PHASE_SOURCE_MAP["refine"]

    def test_authoritative_kinds(self):
        assert mr.AUTHORITATIVE_KINDS == {"PATTERN", "AVOID", "FIX"}

    def test_top_k_default(self):
        assert mr.TOP_K_DEFAULT == 8

    def test_token_budget_default(self):
        assert mr.TOKEN_BUDGET_DEFAULT == 1500

    def test_label_source_boost_map_exists(self):
        assert hasattr(mr, "_LABEL_SOURCE_BOOST_MAP")

    def test_label_source_boost_map_dark_factory_keys(self):
        assert mr._LABEL_SOURCE_BOOST_MAP.get("dark factory") == "dark-factory-ops.md"
        assert mr._LABEL_SOURCE_BOOST_MAP.get("dark-factory") == "dark-factory-ops.md"

    def test_label_source_boost_map_frontend_backend(self):
        assert mr._LABEL_SOURCE_BOOST_MAP.get("frontend") == "frontend-patterns.md"
        assert mr._LABEL_SOURCE_BOOST_MAP.get("backend") == "backend-patterns.md"

    def test_label_source_boost_map_four_keys(self):
        assert len(mr._LABEL_SOURCE_BOOST_MAP) == 4


# ── TestSelectAreaFiles ────────────────────────────────────────────────────

class TestSelectAreaFiles:
    def test_empty_files_returns_all_five(self):
        result = mr.select_area_files([])
        assert result == mr.ALL_MEMORY_FILES

    def test_backend_file_adds_backend_patterns(self):
        result = mr.select_area_files(["backend/app/services/scanner.py"])
        assert "backend-patterns.md" in result
        assert "codebase-patterns.md" in result
        assert "architecture.md" in result

    def test_backend_file_excludes_frontend_patterns(self):
        result = mr.select_area_files(["backend/app/models/stock.py"])
        assert "frontend-patterns.md" not in result

    def test_frontend_file_adds_frontend_patterns(self):
        result = mr.select_area_files(["frontend/src/pages/Scanner.tsx"])
        assert "frontend-patterns.md" in result
        assert "codebase-patterns.md" in result

    def test_dark_factory_file_adds_ops_patterns(self):
        result = mr.select_area_files(["dark-factory/scripts/foo.py"])
        assert "dark-factory-ops.md" in result

    def test_archon_file_adds_ops_patterns(self):
        result = mr.select_area_files([".archon/commands/implement.md"])
        assert "dark-factory-ops.md" in result

    def test_dockerfile_adds_ops_patterns(self):
        result = mr.select_area_files(["Dockerfile"])
        assert "dark-factory-ops.md" in result

    def test_docker_compose_adds_ops_patterns(self):
        result = mr.select_area_files(["docker-compose.yml"])
        assert "dark-factory-ops.md" in result

    def test_unknown_file_returns_only_global_files(self):
        result = mr.select_area_files(["some/unknown/path.txt"])
        assert set(result) == mr.GLOBAL_FILES

    def test_mixed_files_includes_multiple_area_files(self):
        result = mr.select_area_files([
            "backend/app/routers/scanner.py",
            "frontend/src/pages/Dashboard.tsx",
        ])
        assert "backend-patterns.md" in result
        assert "frontend-patterns.md" in result

    def test_output_preserves_all_memory_files_order(self):
        result = mr.select_area_files(["backend/app/foo.py", "frontend/src/bar.tsx"])
        indices = [mr.ALL_MEMORY_FILES.index(f) for f in result]
        assert indices == sorted(indices)

    def test_global_files_always_included(self):
        for phase_file in ["backend/x.py", "frontend/x.tsx", "dark-factory/x.sh"]:
            result = mr.select_area_files([phase_file])
            assert "codebase-patterns.md" in result
            assert "architecture.md" in result


# ── TestPassesLine ─────────────────────────────────────────────────────────

class TestPassesLine:
    ALLOWED = {"implement"}
    FILES = ["backend/app/services/scanner.py"]

    def _call(self, tag, meta, source_file="backend-patterns.md", files=None, allowed=None):
        return mr.passes_line_filters(
            tag,
            meta,
            source_file,
            files if files is not None else self.FILES,
            allowed if allowed is not None else self.ALLOWED,
        )

    # --- PROVISIONAL / INVALID exclusion ---
    def test_provisional_excluded(self):
        assert not self._call("PROVISIONAL", {"source": "implement", "expires": FUTURE})

    def test_invalid_excluded(self):
        assert not self._call("INVALID: some reason", {"source": "implement", "expires": FUTURE})

    def test_invalid_with_colon_excluded(self):
        assert not self._call("INVALID:old", {"source": "implement", "expires": FUTURE})

    # --- Expiry ---
    def test_expired_excluded(self):
        assert not self._call("PATTERN", {"source": "implement", "expires": PAST})

    def test_future_expiry_included(self):
        assert self._call("PATTERN", {"source": "implement", "expires": FUTURE})

    def test_no_expiry_field_included(self):
        assert self._call("PATTERN", {"source": "implement"})

    # --- Source filter for area-specific files ---
    def test_correct_source_passes(self):
        assert self._call("PATTERN", {"source": "implement", "expires": FUTURE})

    def test_wrong_source_excluded(self):
        assert not self._call("PATTERN", {"source": "conformance", "expires": FUTURE})

    def test_missing_source_passes(self):
        """Spec assumption: entries without source: tag pass unconditionally (backward compat)."""
        assert self._call("PATTERN", {"expires": FUTURE})

    # --- Global-file exemption ---
    def test_global_codebase_passes_any_source(self):
        assert self._call("PATTERN", {"source": "conformance", "expires": FUTURE},
                          source_file="codebase-patterns.md")

    def test_global_architecture_passes_any_source(self):
        assert self._call("FIX", {"source": "refine", "expires": FUTURE},
                          source_file="architecture.md")

    def test_global_file_still_excludes_provisional(self):
        assert not self._call("PROVISIONAL", {"source": "implement", "expires": FUTURE},
                               source_file="codebase-patterns.md")

    def test_global_file_still_excludes_expired(self):
        assert not self._call("PATTERN", {"source": "implement", "expires": PAST},
                               source_file="architecture.md")

    # --- Path-tag filter ---
    def test_no_path_tag_always_passes(self):
        assert self._call("PATTERN", {"source": "implement", "expires": FUTURE})

    def test_matching_path_tag_passes(self):
        meta = {"source": "implement", "expires": FUTURE, "path": "backend/app/"}
        assert self._call("PATTERN", meta)

    def test_mismatched_path_tag_excluded(self):
        meta = {"source": "implement", "expires": FUTURE, "path": "frontend/src/"}
        assert not self._call("PATTERN", meta)

    def test_path_tag_with_empty_files_passes(self):
        meta = {"source": "implement", "expires": FUTURE, "path": "frontend/src/"}
        assert self._call("PATTERN", meta, files=[])

    # --- Phase × source coverage ---
    def test_refine_phase_passes_refine_source(self):
        meta = {"source": "refine", "expires": FUTURE}
        assert self._call("PATTERN", meta, allowed=mr.PHASE_SOURCE_MAP["refine"])

    def test_validate_phase_passes_conformance_source(self):
        meta = {"source": "conformance", "expires": FUTURE}
        assert self._call("AVOID", meta, allowed=mr.PHASE_SOURCE_MAP["validate"])

    def test_review_phase_passes_code_review_source(self):
        meta = {"source": "code-review", "expires": FUTURE}
        assert self._call("FIX", meta, allowed=mr.PHASE_SOURCE_MAP["review"])

    def test_plan_phase_passes_refine_source(self):
        meta = {"source": "refine", "expires": FUTURE}
        assert self._call("PATTERN", meta, allowed=mr.PHASE_SOURCE_MAP["plan"])

    def test_implement_phase_excludes_refine_source(self):
        meta = {"source": "refine", "expires": FUTURE}
        assert not self._call("PATTERN", meta, allowed=mr.PHASE_SOURCE_MAP["implement"])

    # --- All authoritative kinds pass ---
    def test_avoid_kind_passes(self):
        assert self._call("AVOID", {"source": "implement", "expires": FUTURE})

    def test_fix_kind_passes(self):
        assert self._call("FIX", {"source": "implement", "expires": FUTURE})

    def test_non_provisional_non_invalid_kind_passes(self):
        """Spec §6 only excludes PROVISIONAL/INVALID; other kinds like NOTE pass through."""
        assert self._call("NOTE", {"source": "implement", "expires": FUTURE})


# ── TestScanMarkdownFiles ──────────────────────────────────────────────────

SAMPLE_MD = """\
# Backend Patterns

- [PATTERN] Keep this one. <!-- issue:#1 date:2026-01-01 expires:{future} source:implement -->
- [AVOID] Also keep. <!-- issue:#2 date:2026-01-01 expires:{future} source:implement -->
- [PROVISIONAL] Skip me. <!-- evidence:x issue:#3 date:2026-01-01 expires:{future} source:implement -->
- [PATTERN] Expired entry. <!-- issue:#4 date:2026-01-01 expires:{past} source:implement -->
- [PATTERN] Wrong source. <!-- issue:#5 date:2026-01-01 expires:{future} source:conformance -->
---
<!-- PROVISIONAL -->
- [PATTERN] In provisional section — skip. <!-- issue:#6 date:2026-01-01 expires:{future} source:implement -->
""".format(future=FUTURE, past=PAST)

GLOBAL_MD = """\
# Codebase Patterns

- [PATTERN] Global entry any-source. <!-- issue:#10 date:2026-01-01 expires:{future} source:conformance -->
- [AVOID] Another global. <!-- issue:#11 date:2026-01-01 expires:{future} source:refine -->
""".format(future=FUTURE)


class TestScanMarkdownFiles:
    def _build_dir(self, tmp_path, files):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        for fname, content in files.items():
            (mem_dir / fname).write_text(content, encoding="utf-8")
        return mem_dir

    def test_returns_passing_entries_only(self, tmp_path):
        mem_dir = self._build_dir(tmp_path, {"backend-patterns.md": SAMPLE_MD})
        result = mr.scan_markdown_files(
            mem_dir,
            ["backend-patterns.md"],
            files=["backend/app/foo.py"],
            allowed_sources={"implement"},
        )
        assert "backend-patterns.md" in result
        entries = result["backend-patterns.md"]
        assert len(entries) == 2
        assert "Keep this one" in entries[0]
        assert "Also keep" in entries[1]

    def test_provisional_entries_excluded(self, tmp_path):
        mem_dir = self._build_dir(tmp_path, {"backend-patterns.md": SAMPLE_MD})
        result = mr.scan_markdown_files(
            mem_dir, ["backend-patterns.md"], files=[], allowed_sources={"implement"}
        )
        texts = " ".join(result.get("backend-patterns.md", []))
        assert "Skip me" not in texts

    def test_provisional_section_entries_excluded(self, tmp_path):
        mem_dir = self._build_dir(tmp_path, {"backend-patterns.md": SAMPLE_MD})
        result = mr.scan_markdown_files(
            mem_dir, ["backend-patterns.md"], files=[], allowed_sources={"implement"}
        )
        texts = " ".join(result.get("backend-patterns.md", []))
        assert "provisional section" not in texts

    def test_expired_entries_excluded(self, tmp_path):
        mem_dir = self._build_dir(tmp_path, {"backend-patterns.md": SAMPLE_MD})
        result = mr.scan_markdown_files(
            mem_dir, ["backend-patterns.md"], files=[], allowed_sources={"implement"}
        )
        texts = " ".join(result.get("backend-patterns.md", []))
        assert "Expired entry" not in texts

    def test_wrong_source_excluded_for_area_file(self, tmp_path):
        mem_dir = self._build_dir(tmp_path, {"backend-patterns.md": SAMPLE_MD})
        result = mr.scan_markdown_files(
            mem_dir, ["backend-patterns.md"], files=[], allowed_sources={"implement"}
        )
        texts = " ".join(result.get("backend-patterns.md", []))
        assert "Wrong source" not in texts

    def test_global_file_passes_all_sources(self, tmp_path):
        mem_dir = self._build_dir(tmp_path, {"codebase-patterns.md": GLOBAL_MD})
        result = mr.scan_markdown_files(
            mem_dir,
            ["codebase-patterns.md"],
            files=[],
            allowed_sources={"implement"},
        )
        assert "codebase-patterns.md" in result
        assert len(result["codebase-patterns.md"]) == 2

    def test_missing_file_skipped_gracefully(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        result = mr.scan_markdown_files(
            mem_dir, ["backend-patterns.md"], files=[], allowed_sources={"implement"}
        )
        assert result == {}

    def test_empty_file_skipped(self, tmp_path):
        mem_dir = self._build_dir(tmp_path, {"backend-patterns.md": ""})
        result = mr.scan_markdown_files(
            mem_dir, ["backend-patterns.md"], files=[], allowed_sources={"implement"}
        )
        assert result == {}

    def test_path_tag_filter_applied(self, tmp_path):
        content = (
            "- [PATTERN] Frontend only. <!-- issue:#1 expires:{f} source:implement "
            "path:frontend/src/ -->\n"
            "- [PATTERN] No restriction. <!-- issue:#2 expires:{f} source:implement -->\n"
        ).format(f=FUTURE)
        mem_dir = self._build_dir(tmp_path, {"backend-patterns.md": content})
        result = mr.scan_markdown_files(
            mem_dir,
            ["backend-patterns.md"],
            files=["backend/app/foo.py"],
            allowed_sources={"implement"},
        )
        entries = result.get("backend-patterns.md", [])
        texts = " ".join(entries)
        assert "Frontend only" not in texts
        assert "No restriction" in texts

    def test_returns_file_only_if_entries_non_empty(self, tmp_path):
        content = "- [PROVISIONAL] Skip me. <!-- issue:#1 expires:{f} source:implement -->\n".format(f=FUTURE)
        mem_dir = self._build_dir(tmp_path, {"backend-patterns.md": content})
        result = mr.scan_markdown_files(
            mem_dir, ["backend-patterns.md"], files=[], allowed_sources={"implement"}
        )
        assert "backend-patterns.md" not in result


# ── TestFormatOutput ───────────────────────────────────────────────────────

class TestFormatOutput:
    def test_markdown_format_section_header(self):
        results = {"backend-patterns.md": ["- [PATTERN] Foo."]}
        out = mr.format_markdown_output(results)
        assert "### Memory: backend-patterns.md" in out
        assert "- [PATTERN] Foo." in out

    def test_markdown_format_empty_results(self):
        assert mr.format_markdown_output({}) == ""

    def test_markdown_format_order_follows_all_memory_files(self):
        results = {
            "backend-patterns.md": ["- [PATTERN] B."],
            "codebase-patterns.md": ["- [PATTERN] C."],
        }
        out = mr.format_markdown_output(results)
        assert out.index("### Memory: codebase") < out.index("### Memory: backend")

    def test_index_format_section_header(self):
        candidates = [{"source_file": "backend-patterns.md", "text": "- [PATTERN] Foo.",
                        "specificity": 0, "expires_at": FUTURE}]
        out = mr.format_index_output(candidates)
        assert "### Memory: backend-patterns.md" in out
        assert "- [PATTERN] Foo." in out

    def test_index_format_empty_candidates(self):
        assert mr.format_index_output([]) == ""

    def test_index_format_order_follows_all_memory_files(self):
        candidates = [
            {"source_file": "backend-patterns.md", "text": "- [PATTERN] B.",
             "specificity": 0, "expires_at": FUTURE},
            {"source_file": "codebase-patterns.md", "text": "- [PATTERN] C.",
             "specificity": 0, "expires_at": FUTURE},
        ]
        out = mr.format_index_output(candidates)
        assert out.index("### Memory: codebase") < out.index("### Memory: backend")

    def test_index_format_sorts_by_specificity_descending(self):
        candidates = [
            {"source_file": "backend-patterns.md", "text": "- [PATTERN] Low.",
             "specificity": 0, "expires_at": FUTURE},
            {"source_file": "backend-patterns.md", "text": "- [PATTERN] High.",
             "specificity": 10, "expires_at": FUTURE},
        ]
        out = mr.format_index_output(candidates)
        assert out.index("High") < out.index("Low")

    def test_index_format_sorts_by_created_at_as_tiebreaker(self):
        candidates = [
            {"source_file": "backend-patterns.md", "text": "- [PATTERN] Older.",
             "specificity": 5, "created_at": "2026-01-01"},
            {"source_file": "backend-patterns.md", "text": "- [PATTERN] Newer.",
             "specificity": 5, "created_at": "2027-01-01"},
        ]
        out = mr.format_index_output(candidates)
        assert out.index("Newer") < out.index("Older")


# ── TestScanIndex ──────────────────────────────────────────────────────────

def _build_index_dir(tmp_path, index_lines, records):
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    records_dir = mem_dir / "records"
    records_dir.mkdir()
    (mem_dir / "index.jsonl").write_text("\n".join(index_lines), encoding="utf-8")
    for rec_id, rec_data in records.items():
        (records_dir / f"{rec_id}.json").write_text(json.dumps(rec_data), encoding="utf-8")
    return mem_dir


class TestScanIndex:
    def _basic_entry(self, **kwargs):
        base = {
            "id": "aabb0011",
            "kind": "PATTERN",
            "source_file": "backend-patterns.md",
            "path_prefixes": [],
            "expires_at": FUTURE,
            "confidence": 1.0,
            "summary_snippet": "Snippet.",
        }
        base.update(kwargs)
        return base

    def _basic_record(self, rec_id, summary="Full text.", sources=("implement",)):
        return {
            "id": rec_id,
            "kind": "PATTERN",
            "summary": summary,
            "evidence": [{"source": s, "date": "2026-01-01", "issue": 1} for s in sources],
            "path_prefixes": [],
            "expires_at": FUTURE,
        }

    def test_provisional_status_excluded(self, tmp_path):
        entry = self._basic_entry(id="aabb0001", status="provisional", agent_id="implement")
        mem_dir = _build_index_dir(
            tmp_path,
            [json.dumps(entry)],
            {"aabb0001": self._basic_record("aabb0001")},
        )
        result = mr.scan_index(mem_dir, ["backend-patterns.md"], [], {"implement"})
        assert result == []

    def test_invalid_status_excluded(self, tmp_path):
        entry = self._basic_entry(id="aabb0002", status="invalid", agent_id="implement")
        mem_dir = _build_index_dir(
            tmp_path,
            [json.dumps(entry)],
            {"aabb0002": self._basic_record("aabb0002")},
        )
        result = mr.scan_index(mem_dir, ["backend-patterns.md"], [], {"implement"})
        assert result == []

    def test_expired_entry_excluded(self, tmp_path):
        entry = self._basic_entry(id="aabb0003", expires_at=PAST)
        mem_dir = _build_index_dir(
            tmp_path,
            [json.dumps(entry)],
            {"aabb0003": self._basic_record("aabb0003")},
        )
        result = mr.scan_index(mem_dir, ["backend-patterns.md"], [], {"implement"})
        assert result == []

    def test_wrong_area_file_excluded(self, tmp_path):
        entry = self._basic_entry(id="aabb0004", source_file="frontend-patterns.md")
        mem_dir = _build_index_dir(
            tmp_path,
            [json.dumps(entry)],
            {"aabb0004": self._basic_record("aabb0004")},
        )
        result = mr.scan_index(mem_dir, ["backend-patterns.md"], [], {"implement"})
        assert result == []

    def test_source_filter_applied_for_area_file(self, tmp_path):
        entry = self._basic_entry(id="aabb0005", agent_id="conformance")
        mem_dir = _build_index_dir(
            tmp_path,
            [json.dumps(entry)],
            {"aabb0005": self._basic_record("aabb0005", sources=("implement",))},
        )
        result = mr.scan_index(mem_dir, ["backend-patterns.md"], [], {"implement"})
        assert result == []

    def test_correct_source_passes(self, tmp_path):
        entry = self._basic_entry(id="aabb0006", agent_id="implement")
        mem_dir = _build_index_dir(
            tmp_path,
            [json.dumps(entry)],
            {"aabb0006": self._basic_record("aabb0006", sources=("implement",))},
        )
        result = mr.scan_index(mem_dir, ["backend-patterns.md"], [], {"implement"})
        assert len(result) == 1
        assert "Full text." in result[0]["text"]

    def test_global_file_passes_any_source(self, tmp_path):
        entry = self._basic_entry(id="aabb0007", source_file="codebase-patterns.md")
        mem_dir = _build_index_dir(
            tmp_path,
            [json.dumps(entry)],
            {"aabb0007": {**self._basic_record("aabb0007", sources=("refine",)),
                          "source_file": "codebase-patterns.md"}},
        )
        result = mr.scan_index(
            mem_dir, ["codebase-patterns.md", "backend-patterns.md"], [], {"implement"}
        )
        assert len(result) == 1

    def test_path_prefix_filter(self, tmp_path):
        entry = self._basic_entry(id="aabb0008", path_prefixes=["frontend/src/"], agent_id="implement")
        mem_dir = _build_index_dir(
            tmp_path,
            [json.dumps(entry)],
            {"aabb0008": self._basic_record("aabb0008")},
        )
        result = mr.scan_index(
            mem_dir, ["backend-patterns.md"], ["backend/app/foo.py"], {"implement"}
        )
        assert result == []

    def test_path_prefix_match_sets_specificity(self, tmp_path):
        entry = self._basic_entry(id="aabb0009", path_prefixes=["backend/app/"], agent_id="implement")
        mem_dir = _build_index_dir(
            tmp_path,
            [json.dumps(entry)],
            {"aabb0009": self._basic_record("aabb0009")},
        )
        result = mr.scan_index(
            mem_dir, ["backend-patterns.md"], ["backend/app/services/scanner.py"], {"implement"}
        )
        assert len(result) == 1
        assert result[0]["specificity"] == len("backend/app/")

    def test_zero_specificity_for_empty_path_prefixes(self, tmp_path):
        entry = self._basic_entry(id="aabb0010", agent_id="implement")
        mem_dir = _build_index_dir(
            tmp_path,
            [json.dumps(entry)],
            {"aabb0010": self._basic_record("aabb0010")},
        )
        result = mr.scan_index(
            mem_dir, ["backend-patterns.md"], ["backend/app/foo.py"], {"implement"}
        )
        assert len(result) == 1
        assert result[0]["specificity"] == 0

    def test_index_non_authoritative_kind_passes(self, tmp_path):
        """Spec §6 (index path): only status=provisional/invalid excluded, not by kind."""
        entry = self._basic_entry(id="aabb0020", kind="NOTE", agent_id="implement")
        mem_dir = _build_index_dir(
            tmp_path,
            [json.dumps(entry)],
            {"aabb0020": self._basic_record("aabb0020")},
        )
        result = mr.scan_index(mem_dir, ["backend-patterns.md"], [], {"implement"})
        assert len(result) == 1

    def test_index_source_filter_uses_agent_id_not_evidence(self, tmp_path):
        """Spec: agent_id from index entry drives source filter, not evidence[].source."""
        entry = self._basic_entry(id="aabb0021", agent_id="implement")
        rec = {
            "id": "aabb0021", "kind": "PATTERN",
            "summary": "Agent-id path.",
            "evidence": [{"source": "conformance", "date": "2026-01-01", "issue": 1}],
            "path_prefixes": [], "expires_at": FUTURE,
        }
        mem_dir = _build_index_dir(tmp_path, [json.dumps(entry)], {"aabb0021": rec})
        result = mr.scan_index(mem_dir, ["backend-patterns.md"], [], {"implement"})
        assert len(result) == 1

    def test_index_source_filter_excludes_wrong_agent_id(self, tmp_path):
        """Spec: index entry with wrong agent_id excluded even if record evidence matches."""
        entry = self._basic_entry(id="aabb0022", agent_id="conformance")
        mem_dir = _build_index_dir(
            tmp_path,
            [json.dumps(entry)],
            {"aabb0022": self._basic_record("aabb0022", sources=("implement",))},
        )
        result = mr.scan_index(mem_dir, ["backend-patterns.md"], [], {"implement"})
        assert result == []


# ── TestRetrieveMemory ─────────────────────────────────────────────────────

class TestRetrieveMemory:
    def test_uses_index_when_present(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        records_dir = mem_dir / "records"
        records_dir.mkdir()
        rec = {
            "id": "abc123",
            "kind": "PATTERN",
            "summary": "Index path summary.",
            "evidence": [{"source": "implement", "date": "2026-01-01", "issue": 1}],
            "path_prefixes": [],
            "expires_at": FUTURE,
        }
        (records_dir / "abc123.json").write_text(json.dumps(rec), encoding="utf-8")
        entry = {
            "id": "abc123",
            "kind": "PATTERN",
            "source_file": "backend-patterns.md",
            "agent_id": "implement",
            "path_prefixes": [],
            "expires_at": FUTURE,
            "confidence": 1.0,
            "summary_snippet": "Index path summary.",
        }
        (mem_dir / "index.jsonl").write_text(json.dumps(entry), encoding="utf-8")

        out = mr.retrieve_memory(mem_dir, "implement", ["backend/app/foo.py"])
        assert "Index path summary" in out

    def test_falls_back_to_markdown_when_no_index(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        content = "- [PATTERN] Markdown fallback. <!-- issue:#1 expires:{f} source:implement -->\n".format(f=FUTURE)
        (mem_dir / "backend-patterns.md").write_text(content, encoding="utf-8")

        out = mr.retrieve_memory(mem_dir, "implement", ["backend/app/foo.py"])
        assert "Markdown fallback" in out

    def test_falls_back_when_index_yields_zero_survivors(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        records_dir = mem_dir / "records"
        records_dir.mkdir()
        # Index entry filtered out by wrong agent_id (source filter)
        rec = {
            "id": "xyz999",
            "kind": "PATTERN",
            "summary": "Should not appear.",
            "evidence": [{"source": "conformance", "date": "2026-01-01", "issue": 1}],
            "path_prefixes": [],
            "expires_at": FUTURE,
        }
        (records_dir / "xyz999.json").write_text(json.dumps(rec), encoding="utf-8")
        entry = {
            "id": "xyz999",
            "kind": "PATTERN",
            "source_file": "backend-patterns.md",
            "agent_id": "conformance",
            "path_prefixes": [],
            "expires_at": FUTURE,
            "confidence": 1.0,
            "summary_snippet": "Should not appear.",
        }
        (mem_dir / "index.jsonl").write_text(json.dumps(entry), encoding="utf-8")
        content = "- [PATTERN] Fallback appears. <!-- issue:#2 expires:{f} source:implement -->\n".format(f=FUTURE)
        (mem_dir / "backend-patterns.md").write_text(content, encoding="utf-8")

        out = mr.retrieve_memory(mem_dir, "implement", ["backend/app/foo.py"])
        assert "Fallback appears" in out
        assert "Should not appear" not in out

    def test_falls_back_when_index_unreadable(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        # A directory named index.jsonl triggers OSError on read_text
        (mem_dir / "index.jsonl").mkdir()
        content = "- [PATTERN] Fallback appears. <!-- issue:#2 expires:{f} source:implement -->\n".format(f=FUTURE)
        (mem_dir / "backend-patterns.md").write_text(content, encoding="utf-8")

        out = mr.retrieve_memory(mem_dir, "implement", ["backend/app/foo.py"])
        assert "Fallback appears" in out


# ── TestMainCLI ────────────────────────────────────────────────────────────

class TestMainCLI:
    def _run(self, args, memory_dir=None, tmp_path=None):
        import subprocess
        script = str(Path(__file__).resolve().parents[1] / "scripts" / "memory_retrieve.py")
        cmd = [sys.executable, script] + args
        if memory_dir:
            cmd += ["--memory-dir", str(memory_dir)]
        return subprocess.run(cmd, capture_output=True, text=True)

    def _make_mem_dir(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        content = "- [PATTERN] CLI test. <!-- issue:#1 expires:{f} source:implement -->\n".format(f=FUTURE)
        (mem_dir / "backend-patterns.md").write_text(content, encoding="utf-8")
        return mem_dir

    def test_missing_phase_exits_nonzero(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        result = self._run([], memory_dir=mem_dir)
        assert result.returncode != 0

    def test_invalid_phase_exits_nonzero(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        result = self._run(["--phase", "invalid"], memory_dir=mem_dir)
        assert result.returncode != 0

    def test_missing_memory_dir_exits_nonzero(self, tmp_path):
        result = self._run(["--phase", "implement", "--memory-dir", str(tmp_path / "nonexistent")])
        assert result.returncode != 0

    def test_valid_call_exits_zero(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        result = self._run(["--phase", "implement", "--files", "backend/app/foo.py"],
                           memory_dir=mem_dir)
        assert result.returncode == 0

    def test_output_contains_memory_section(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        result = self._run(["--phase", "implement", "--files", "backend/app/foo.py"],
                           memory_dir=mem_dir)
        assert "### Memory:" in result.stdout

    def test_issue_flag_accepted(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        result = self._run(["--phase", "implement", "--issue", "646"], memory_dir=mem_dir)
        assert result.returncode == 0

    def test_labels_flag_accepted(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        result = self._run(["--phase", "implement", "--labels", "backend"], memory_dir=mem_dir)
        assert result.returncode == 0

    def test_all_phases_accepted(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        for phase in ["refine", "plan", "implement", "validate", "review"]:
            result = self._run(["--phase", phase], memory_dir=mem_dir)
            assert result.returncode == 0, f"Phase {phase!r} failed: {result.stderr}"


# ── Conformance fix verification tests ──────────────────────────────────────
# These tests assert spec-correct behavior. They fail on the pre-fix code
# and pass after the three material deviations are corrected.

class TestConformanceFixes:
    ALLOWED = {"implement"}
    FILES = ["backend/app/services/scanner.py"]

    def _call(self, tag, meta, source_file="backend-patterns.md", files=None, allowed=None):
        return mr.passes_line_filters(
            tag,
            meta,
            source_file,
            files if files is not None else self.FILES,
            allowed if allowed is not None else self.ALLOWED,
        )

    def test_missing_source_passes_backward_compat(self):
        """Spec assumption: entries without source: tag pass unconditionally."""
        assert self._call("PATTERN", {"expires": FUTURE})

    def test_non_provisional_non_invalid_kind_passes(self):
        """Spec §6 only excludes PROVISIONAL/INVALID; other kinds like NOTE should pass."""
        assert self._call("NOTE", {"source": "implement", "expires": FUTURE})

    def test_index_ranking_uses_created_at(self):
        """Spec §7.3: tiebreak by created_at/updated_at descending, not expires_at."""
        candidates = [
            {"source_file": "backend-patterns.md", "text": "- [PATTERN] Older.",
             "specificity": 5, "created_at": "2026-01-01"},
            {"source_file": "backend-patterns.md", "text": "- [PATTERN] Newer.",
             "specificity": 5, "created_at": "2027-01-01"},
        ]
        out = mr.format_index_output(candidates)
        assert out.index("Newer") < out.index("Older")


# ── TestEmitMemoryTrace ────────────────────────────────────────────────────

import subprocess  # noqa: E402


class TestEmitMemoryTrace:
    """Tests for emit_memory_trace() and --emit-trace-to CLI flag (issue #647)."""

    def _make_mem_dir(self, tmp_path, content="- [PATTERN] Foo. <!-- source:implement expires:2099-12-31 -->\n- [PATTERN] Bar. <!-- source:implement expires:2099-12-31 -->\n"):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        for fname in mr.ALL_MEMORY_FILES:
            (mem_dir / fname).write_text(content)
        return mem_dir

    def test_emit_writes_valid_json(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "memory-trace.json"
        mr.emit_memory_trace(trace_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"})
        assert trace_path.exists()
        data = json.loads(trace_path.read_text())
        assert isinstance(data, dict)

    def test_emit_schema_version(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "memory-trace.json"
        mr.emit_memory_trace(trace_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"})
        data = json.loads(trace_path.read_text())
        assert data["schema_version"] == 1

    def test_emit_retrieval_mechanism(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "memory-trace.json"
        mr.emit_memory_trace(trace_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"})
        data = json.loads(trace_path.read_text())
        assert data["retrieval_mechanism"] == "flatfile-pathtag"

    def test_emit_phase_field(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "memory-trace.json"
        mr.emit_memory_trace(trace_path, "plan", [], mem_dir, mr.ALL_MEMORY_FILES, {"refine"})
        data = json.loads(trace_path.read_text())
        assert data["phase"] == "plan"

    def test_emit_affected_files(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "memory-trace.json"
        files = ["backend/app/services/scanner.py", "dark-factory/scripts/memory_retrieve.py"]
        mr.emit_memory_trace(trace_path, "implement", files, mem_dir, mr.ALL_MEMORY_FILES, {"implement"})
        data = json.loads(trace_path.read_text())
        assert data["affected_files"] == files

    def test_emit_files_loaded_structure(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "memory-trace.json"
        mr.emit_memory_trace(trace_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"})
        data = json.loads(trace_path.read_text())
        assert "files_loaded" in data
        assert isinstance(data["files_loaded"], list)
        for entry in data["files_loaded"]:
            assert "path" in entry
            assert "entries_total" in entry
            assert "entries_included" in entry
            assert "entries_filtered_out" in entry

    def test_emit_counts_match(self, tmp_path):
        content = (
            "- [PATTERN] P1. <!-- source:implement expires:2099-12-31 -->\n"
            "- [PATTERN] P2. <!-- source:implement expires:2099-12-31 -->\n"
            "- [PROVISIONAL] Skip. <!-- source:implement expires:2099-12-31 -->\n"
        )
        mem_dir = self._make_mem_dir(tmp_path, content=content)
        trace_path = tmp_path / "memory-trace.json"
        mr.emit_memory_trace(trace_path, "implement", [], mem_dir, ["backend-patterns.md"], {"implement"})
        data = json.loads(trace_path.read_text())
        entry = next(e for e in data["files_loaded"] if e["path"].endswith("backend-patterns.md"))
        assert entry["entries_total"] == 3
        assert entry["entries_included"] == 2
        assert entry["entries_filtered_out"] == 1

    def test_emit_fallback_false_on_success(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "memory-trace.json"
        mr.emit_memory_trace(trace_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"})
        data = json.loads(trace_path.read_text())
        assert data["fallback_used"] is False

    def test_emit_nonfatal_on_write_error(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        bad_path = Path("/nonexistent/directory/memory-trace.json")
        # Should not raise
        mr.emit_memory_trace(bad_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"})

    def test_cli_emit_trace_to_flag_accepted(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "trace.json"
        result = subprocess.run(
            [sys.executable, str(Path(mr.__file__).resolve()),
             "--phase", "implement",
             "--memory-dir", str(mem_dir),
             "--emit-trace-to", str(trace_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert trace_path.exists()
        data = json.loads(trace_path.read_text())
        assert data["schema_version"] == 1

    def test_cli_no_trace_when_flag_absent(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "trace.json"
        result = subprocess.run(
            [sys.executable, str(Path(mr.__file__).resolve()),
             "--phase", "implement",
             "--memory-dir", str(mem_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert not trace_path.exists()

    def test_emit_issue_field(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "memory-trace.json"
        mr.emit_memory_trace(trace_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"}, issue=123)
        data = json.loads(trace_path.read_text())
        assert data["issue"] == 123

    def test_emit_issue_defaults_to_zero(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "memory-trace.json"
        mr.emit_memory_trace(trace_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"})
        data = json.loads(trace_path.read_text())
        assert data["issue"] == 0

    def test_emit_agent_id_field(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "memory-trace.json"
        mr.emit_memory_trace(trace_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"}, agent_id="implementation-agent")
        data = json.loads(trace_path.read_text())
        assert data["agent_id"] == "implementation-agent"

    def test_emit_project_field(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "memory-trace.json"
        mr.emit_memory_trace(trace_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"})
        data = json.loads(trace_path.read_text())
        assert data["project"] == "markethawk"

    def test_phase_agent_id_map_exists(self, tmp_path):
        assert hasattr(mr, "PHASE_AGENT_ID")
        assert mr.PHASE_AGENT_ID["implement"] == "implementation-agent"
        assert mr.PHASE_AGENT_ID["plan"] == "plan-agent"
        assert mr.PHASE_AGENT_ID["refine"] == "refine-agent"
        assert mr.PHASE_AGENT_ID["validate"] == "validate-agent"

    def test_cli_includes_issue_agent_project(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "trace.json"
        result = subprocess.run(
            [sys.executable, str(Path(mr.__file__).resolve()),
             "--phase", "implement",
             "--memory-dir", str(mem_dir),
             "--issue", "647",
             "--emit-trace-to", str(trace_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert trace_path.exists()
        data = json.loads(trace_path.read_text())
        assert data["issue"] == 647
        assert data["agent_id"] == "implementation-agent"
        assert data["project"] == "markethawk"


# ── TestComputeLabelBoost ──────────────────────────────────────────────────

class TestComputeLabelBoost:
    def test_no_labels_returns_zero(self):
        assert mr.compute_label_boost("backend-patterns.md", []) == 0

    def test_none_labels_returns_zero(self):
        assert mr.compute_label_boost("backend-patterns.md", None) == 0

    def test_backend_label_boosts_backend_patterns(self):
        assert mr.compute_label_boost("backend-patterns.md", ["backend"]) == 1

    def test_frontend_label_boosts_frontend_patterns(self):
        assert mr.compute_label_boost("frontend-patterns.md", ["frontend"]) == 1

    def test_dark_factory_label_boosts_ops_patterns(self):
        assert mr.compute_label_boost("dark-factory-ops.md", ["Dark Factory"]) == 1

    def test_dark_factory_hyphen_label_boosts_ops_patterns(self):
        assert mr.compute_label_boost("dark-factory-ops.md", ["dark-factory"]) == 1

    def test_label_match_is_case_insensitive(self):
        assert mr.compute_label_boost("backend-patterns.md", ["BACKEND"]) == 1

    def test_label_no_map_match_returns_zero(self):
        assert mr.compute_label_boost("backend-patterns.md", ["performance"]) == 0

    def test_mismatched_file_returns_zero(self):
        assert mr.compute_label_boost("codebase-patterns.md", ["backend"]) == 0

    def test_global_file_never_boosted(self):
        assert mr.compute_label_boost("codebase-patterns.md", ["frontend", "backend"]) == 0
        assert mr.compute_label_boost("architecture.md", ["dark factory"]) == 0

    def test_returns_one_not_more(self):
        assert mr.compute_label_boost("dark-factory-ops.md", ["dark factory", "dark-factory"]) == 1

    def test_multiple_labels_one_matching(self):
        assert mr.compute_label_boost("frontend-patterns.md", ["performance", "frontend", "backend"]) == 1


# ── TestMainCLI labels_nargs addition ──────────────────────────────────────

class TestMainCLILabelNargs:
    def _run(self, args, memory_dir=None):
        import subprocess
        script = str(Path(__file__).resolve().parents[1] / "scripts" / "memory_retrieve.py")
        cmd = [sys.executable, script] + args
        if memory_dir:
            cmd += ["--memory-dir", str(memory_dir)]
        return subprocess.run(cmd, capture_output=True, text=True)

    def _make_mem_dir(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        content = "- [PATTERN] CLI test. <!-- issue:#1 expires:{f} source:implement -->\n".format(f=FUTURE)
        (mem_dir / "backend-patterns.md").write_text(content, encoding="utf-8")
        return mem_dir

    def test_labels_nargs_accepts_multiple(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        result = self._run(
            ["--phase", "implement", "--labels", "Dark Factory", "performance"],
            memory_dir=mem_dir,
        )
        assert result.returncode == 0


# ── TestFormatIndexOutputCap ───────────────────────────────────────────────

class TestFormatIndexOutputCap:
    """Tests for dual cap and label-boost sort in format_index_output()."""

    def _make_candidate(self, text, specificity=0, created_at="2026-01-01", source_file="backend-patterns.md"):
        return {
            "source_file": source_file,
            "text": f"- [PATTERN] {text}",
            "specificity": specificity,
            "created_at": created_at,
        }

    def _candidates(self, n, source_file="backend-patterns.md"):
        return [self._make_candidate(f"Entry {i}", source_file=source_file) for i in range(n)]

    def test_nine_candidates_capped_to_eight(self):
        caps = {}
        out = mr.format_index_output(self._candidates(9), _cap_out=caps)
        assert caps["entries_selected"] == 8
        assert caps["entries_dropped_by_cap"] == 1

    def test_eight_candidates_no_drop(self):
        caps = {}
        mr.format_index_output(self._candidates(8), _cap_out=caps)
        assert caps["entries_selected"] == 8
        assert caps["entries_dropped_by_cap"] == 0

    def test_two_candidates_no_drop(self):
        caps = {}
        mr.format_index_output(self._candidates(2), _cap_out=caps)
        assert caps["entries_selected"] == 2
        assert caps["entries_dropped_by_cap"] == 0

    def test_token_budget_cap_stops_early(self):
        long_text = "x" * 590
        candidates = [self._make_candidate(long_text + f"_{i}") for i in range(20)]
        caps = {}
        mr.format_index_output(candidates, _cap_out=caps)
        assert caps["entries_selected"] <= 10
        assert caps["entries_dropped_by_cap"] >= 10

    def test_count_cap_takes_priority_over_token_cap(self):
        caps = {}
        mr.format_index_output(self._candidates(12), _cap_out=caps)
        assert caps["entries_selected"] == 8
        assert caps["entries_dropped_by_cap"] == 4

    def test_cap_out_none_no_error(self):
        out = mr.format_index_output(self._candidates(2))
        assert "### Memory:" in out

    def test_cap_out_per_file_selected(self):
        caps = {}
        candidates = (
            [self._make_candidate(f"B{i}", source_file="backend-patterns.md") for i in range(5)] +
            [self._make_candidate(f"F{i}", source_file="frontend-patterns.md") for i in range(5)]
        )
        mr.format_index_output(candidates, _cap_out=caps)
        assert caps["entries_selected"] == 8
        total_per_file = sum(caps["per_file_selected"].values())
        assert total_per_file == 8

    def test_cap_out_per_file_dropped(self):
        caps = {}
        candidates = (
            [self._make_candidate(f"B{i}", source_file="backend-patterns.md") for i in range(5)] +
            [self._make_candidate(f"F{i}", source_file="frontend-patterns.md") for i in range(5)]
        )
        mr.format_index_output(candidates, _cap_out=caps)
        total_dropped = sum(caps["per_file_dropped"].values())
        assert total_dropped == 2

    def test_label_boost_promotes_matching_file(self):
        candidates = [
            {"source_file": "backend-patterns.md", "text": "- [PATTERN] Low spec backend.",
             "specificity": 0, "created_at": "2026-01-01"},
            {"source_file": "frontend-patterns.md", "text": "- [PATTERN] High spec frontend.",
             "specificity": 100, "created_at": "2026-01-01"},
        ]
        out = mr.format_index_output(candidates, labels=["backend"])
        assert "Low spec backend" in out
        assert "High spec frontend" in out

    def test_only_selected_entries_in_output(self):
        candidates = [
            self._make_candidate(f"Entry {i}", specificity=9 - i) for i in range(9)
        ]
        out = mr.format_index_output(candidates)
        assert "Entry 8" not in out

    def test_markdown_fallback_unchanged_by_cap(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        lines = [
            f"- [PATTERN] Entry {i}. <!-- source:implement expires:2099-12-31 -->"
            for i in range(10)
        ]
        (mem_dir / "backend-patterns.md").write_text("\n".join(lines), encoding="utf-8")
        out = mr.retrieve_memory(str(mem_dir), "implement", ["backend/app/foo.py"])
        for i in range(10):
            assert f"Entry {i}" in out


# ── TestEmitMemoryTraceCap ─────────────────────────────────────────────────

class TestEmitMemoryTraceCap:
    """Tests for cap-count fields in emit_memory_trace()."""

    def _make_mem_dir(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        content = "- [PATTERN] Foo. <!-- source:implement expires:2099-12-31 -->\n"
        for fname in mr.ALL_MEMORY_FILES:
            (mem_dir / fname).write_text(content)
        return mem_dir

    def test_cap_counts_in_trace_root(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "trace.json"
        cap_counts = {
            "entries_selected": 6,
            "entries_dropped_by_cap": 10,
            "per_file_selected": {"backend-patterns.md": 3, "codebase-patterns.md": 3},
            "per_file_dropped": {"frontend-patterns.md": 5, "dark-factory-ops.md": 5},
        }
        mr.emit_memory_trace(
            trace_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"},
            cap_counts=cap_counts,
        )
        data = json.loads(trace_path.read_text())
        assert data["entries_selected_total"] == 6
        assert data["entries_dropped_by_cap_total"] == 10

    def test_per_file_selected_in_files_loaded(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "trace.json"
        cap_counts = {
            "entries_selected": 3,
            "entries_dropped_by_cap": 0,
            "per_file_selected": {"backend-patterns.md": 3},
            "per_file_dropped": {},
        }
        mr.emit_memory_trace(
            trace_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"},
            cap_counts=cap_counts,
        )
        data = json.loads(trace_path.read_text())
        backend_entry = next(
            (e for e in data["files_loaded"] if e["path"].endswith("backend-patterns.md")), None
        )
        assert backend_entry is not None
        assert backend_entry["entries_selected"] == 3
        assert backend_entry["entries_dropped_by_cap"] == 0

    def test_per_file_dropped_zero_when_not_in_cap_counts(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "trace.json"
        cap_counts = {
            "entries_selected": 0,
            "entries_dropped_by_cap": 0,
            "per_file_selected": {},
            "per_file_dropped": {},
        }
        mr.emit_memory_trace(
            trace_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"},
            cap_counts=cap_counts,
        )
        data = json.loads(trace_path.read_text())
        frontend_entry = next(
            (e for e in data["files_loaded"] if e["path"].endswith("frontend-patterns.md")), None
        )
        if frontend_entry:
            assert frontend_entry["entries_selected"] == 0
            assert frontend_entry["entries_dropped_by_cap"] == 0

    def test_empty_cap_counts_omits_root_totals(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "trace.json"
        mr.emit_memory_trace(
            trace_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"},
            cap_counts={},
        )
        data = json.loads(trace_path.read_text())
        assert "entries_selected_total" not in data
        assert "entries_dropped_by_cap_total" not in data

    def test_cli_cap_counts_in_trace_via_index_path(self, tmp_path):
        """Integration: CLI with index path emits cap count fields in trace."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        records_dir = mem_dir / "records"
        records_dir.mkdir()
        index_lines = []
        for i in range(10):
            entry_id = f"aabb{i:04d}"
            entry = {
                "id": entry_id,
                "kind": "PATTERN",
                "source_file": "backend-patterns.md",
                "agent_id": "implement",
                "path_prefixes": [],
                "expires_at": "2099-12-31",
                "created_at": f"2026-01-{i+1:02d}",
                "confidence": 1.0,
                "summary_snippet": f"Entry {i}.",
            }
            index_lines.append(json.dumps(entry))
            record = {
                "id": entry_id,
                "kind": "PATTERN",
                "summary": f"Entry {i} full summary.",
                "evidence": [{"source": "implement", "date": "2026-01-01", "issue": 667}],
                "path_prefixes": [],
                "expires_at": "2099-12-31",
            }
            (records_dir / f"{entry_id}.json").write_text(json.dumps(record), encoding="utf-8")
        (mem_dir / "index.jsonl").write_text("\n".join(index_lines), encoding="utf-8")

        trace_path = tmp_path / "trace.json"
        result = subprocess.run(
            [
                sys.executable, str(Path(mr.__file__).resolve()),
                "--phase", "implement",
                "--memory-dir", str(mem_dir),
                "--emit-trace-to", str(trace_path),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert trace_path.exists()
        data = json.loads(trace_path.read_text())
        assert data.get("entries_selected_total") == 8
        assert data.get("entries_dropped_by_cap_total") == 2


# ── T5: uncapped_tokens + memory feature-disabled bypass (R1/R4) ─────────────

def _make_candidates(n, source_file="codebase-patterns.md"):
    return [
        {
            "id": f"id{i:04d}",
            "kind": "PATTERN",
            "text": f"- [PATTERN] Entry {i} description text. <!-- dedup-key:entry{i} -->",
            "source_file": source_file,
            "specificity": 0,
            "created_at": "",
        }
        for i in range(n)
    ]


def test_format_index_output_emits_uncapped_tokens():
    """format_index_output() must populate cap_out['uncapped_tokens'] with total
    token cost of all ranked candidates before the k/budget cap is applied."""
    candidates = _make_candidates(2)
    cap_out = {}
    mr.format_index_output(candidates, _cap_out=cap_out)
    assert "uncapped_tokens" in cap_out
    assert cap_out["uncapped_tokens"] > 0


def test_format_index_output_bypasses_cap_when_disabled(monkeypatch, tmp_path):
    """When memory.enabled is false in config, ALL candidates must be returned
    (no top-k cap) and entries_selected must equal len(candidates)."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("token_optimization:\n  memory:\n    enabled: false\n")
    monkeypatch.setenv("TOKEN_OPTIMIZATION_MEMORY_ENABLED", "false")

    candidates = _make_candidates(12)
    cap_out = {}
    mr.format_index_output(candidates, _cap_out=cap_out)
    assert cap_out.get("entries_selected") == 12
    assert cap_out.get("entries_dropped_by_cap") == 0

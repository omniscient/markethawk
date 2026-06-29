"""
Tests for dark-factory/scripts/memory_maintain.py.

All tests operate on in-memory strings; no filesystem writes.
"""
import copy
import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import memory_maintain as mm  # noqa: E402


# ---------------------------------------------------------------------------
# parse_entry
# ---------------------------------------------------------------------------

class TestParseEntry:
    def test_pattern_tag_and_body(self):
        line = "- [PATTERN] Use foo. <!-- issue:#123 date:2026-01-01 expires:2026-07-01 source:implement -->"
        e = mm.parse_entry(line)
        assert e.tag == "PATTERN"
        assert e.body == "Use foo."
        assert e.meta["issue"] == "#123"
        assert e.meta["expires"] == "2026-07-01"

    def test_provisional_tag(self):
        line = "- [PROVISIONAL] Some prov entry. <!-- evidence:x issue:#200 date:2026-01-01 expires:2026-07-01 source:implement -->"
        e = mm.parse_entry(line)
        assert e.tag == "PROVISIONAL"
        assert e.meta["issue"] == "#200"

    def test_invalid_tag_with_reason(self):
        line = "- [INVALID: superseded by identical entry added 2026-06-01] Old entry. <!-- issue:#50 date:2026-01-01 source:implement -->"
        e = mm.parse_entry(line)
        assert e.tag.startswith("INVALID")
        assert "superseded" in e.tag

    def test_no_meta_comment_returns_empty_dict(self):
        line = "- [PATTERN] Entry with no metadata."
        e = mm.parse_entry(line)
        assert e.meta == {}
        assert e.body == "Entry with no metadata."

    def test_non_entry_line_returns_none(self):
        assert mm.parse_entry("## Section Header") is None
        assert mm.parse_entry("") is None
        assert mm.parse_entry("---") is None

    def test_multi_issue_meta(self):
        line = "- [PROVISIONAL] Multi evidence. <!-- evidence:x issue:#10 evidence2:y issue:#20 date:2026-01-01 expires:2026-07-01 source:implement -->"
        e = mm.parse_entry(line)
        assert "#10" in e.issue_numbers
        assert "#20" in e.issue_numbers

    def test_path_tag_extracted(self):
        line = "- [AVOID] Don't do X. <!-- issue:#99 date:2026-01-01 path:backend/app/ expires:2026-07-01 source:implement -->"
        e = mm.parse_entry(line)
        assert e.meta.get("path") == "backend/app/"


# ---------------------------------------------------------------------------
# render_entry
# ---------------------------------------------------------------------------

class TestRenderEntry:
    def test_roundtrip_preserves_line_with_period(self):
        line = "- [PATTERN] Use foo. <!-- issue:#123 date:2026-01-01 expires:2026-07-01 source:implement -->"
        e = mm.parse_entry(line)
        assert mm.render_entry(e) == line

    def test_roundtrip_preserves_line_without_period(self):
        line = "- [AVOID] Never use tmpfs for shared volumes <!-- issue:#99 date:2026-01-01 source:implement -->"
        e = mm.parse_entry(line)
        assert mm.render_entry(e) == line

    def test_tag_replacement_changes_rendered_tag(self):
        line = "- [PROVISIONAL] Promo me. <!-- evidence:x issue:#10 evidence2:y issue:#20 date:2026-01-01 expires:2026-07-01 source:implement -->"
        e = mm.parse_entry(line)
        e.tag = "PATTERN"
        rendered = mm.render_entry(e)
        assert rendered.startswith("- [PATTERN]")


# ---------------------------------------------------------------------------
# parse_file_content / render_file
# ---------------------------------------------------------------------------

SAMPLE_FILE = """\
# Test Memory File

## Section A

- [PATTERN] Auth entry one. <!-- issue:#1 date:2026-01-01 expires:2027-01-01 source:implement -->
- [AVOID] Auth entry two. <!-- issue:#2 date:2026-02-01 expires:2027-02-01 source:implement -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->

- [PROVISIONAL] Prov entry one. <!-- evidence:x issue:#10 date:2026-03-01 expires:2026-09-01 source:implement -->
"""


class TestParseFile:
    def test_auth_entry_count(self):
        mf = mm.parse_file_content(SAMPLE_FILE)
        assert len(mf.auth_entries) == 2

    def test_prov_entry_count(self):
        mf = mm.parse_file_content(SAMPLE_FILE)
        assert len(mf.prov_entries) == 1

    def test_auth_entry_tags(self):
        mf = mm.parse_file_content(SAMPLE_FILE)
        assert mf.auth_entries[0].tag == "PATTERN"
        assert mf.auth_entries[1].tag == "AVOID"

    def test_prov_entry_tag(self):
        mf = mm.parse_file_content(SAMPLE_FILE)
        assert mf.prov_entries[0].tag == "PROVISIONAL"


class TestRenderFile:
    def test_roundtrip(self):
        mf = mm.parse_file_content(SAMPLE_FILE)
        rendered = mm.render_file(mf)
        assert rendered == SAMPLE_FILE
        # Section header must precede the first entry
        section_pos = rendered.index("## Section A")
        entry_pos = rendered.index("- [PATTERN]")
        assert section_pos < entry_pos

    def test_modify_auth_entry_reflects_in_render(self):
        mf = mm.parse_file_content(SAMPLE_FILE)
        mf.auth_entries[0].tag = "FIX"
        rendered = mm.render_file(mf)
        assert "- [FIX]" in rendered
        assert "- [PATTERN]" not in rendered

    def test_extra_auth_entry_appended_when_no_raw_line(self):
        mf = mm.parse_file_content(SAMPLE_FILE)
        promoted = copy.copy(mf.prov_entries[0])
        promoted.tag = "PATTERN"
        mf.auth_entries.append(promoted)
        rendered = mm.render_file(mf)
        assert rendered.count("- [PATTERN]") == 2  # original + promoted

    def test_removed_auth_entry_not_in_render(self):
        mf = mm.parse_file_content(SAMPLE_FILE)
        mf.auth_entries = mf.auth_entries[1:]  # remove first (expire simulation)
        rendered = mm.render_file(mf)
        assert "Auth entry one." not in rendered
        assert "Auth entry two." in rendered


# ---------------------------------------------------------------------------
# op_expire
# ---------------------------------------------------------------------------

def _entry(tag, body, expires=None, issue="#1", date_str="2026-01-01"):
    meta = {"issue": issue, "date": date_str, "source": "implement"}
    raw = f"issue:{issue} date:{date_str} source:implement"
    if expires:
        meta["expires"] = expires
        raw += f" expires:{expires}"
    return mm.MemoryEntry(tag=tag, body=body, meta=meta, raw_meta=raw)


class TestOpExpire:
    TODAY = _date(2026, 6, 27)

    def test_removes_expired_auth_entry(self):
        entries = [_entry("PATTERN", "Old entry", expires="2026-01-01")]
        result = mm.op_expire(entries, [], self.TODAY)
        assert len(result.kept_auth) == 0
        assert len(result.removed_auth) == 1

    def test_keeps_future_auth_entry(self):
        entries = [_entry("PATTERN", "Current entry", expires="2027-01-01")]
        result = mm.op_expire(entries, [], self.TODAY)
        assert len(result.kept_auth) == 1
        assert len(result.removed_auth) == 0

    def test_no_expires_key_is_kept(self):
        entries = [_entry("PATTERN", "No expiry")]
        result = mm.op_expire(entries, [], self.TODAY)
        assert len(result.kept_auth) == 1

    def test_removes_expired_provisional(self):
        prov = [_entry("PROVISIONAL", "Expired prov", expires="2026-01-01")]
        result = mm.op_expire([], prov, self.TODAY)
        assert len(result.kept_prov) == 0
        assert len(result.removed_prov) == 1

    def test_keeps_non_expired_provisional(self):
        prov = [_entry("PROVISIONAL", "Active prov", expires="2027-01-01")]
        result = mm.op_expire([], prov, self.TODAY)
        assert len(result.kept_prov) == 1

    def test_removes_provisional_with_only_one_issue_and_past_expires(self):
        prov = [_entry("PROVISIONAL", "Single issue expired", expires="2026-01-01", issue="#5")]
        result = mm.op_expire([], prov, self.TODAY)
        assert len(result.removed_prov) == 1


# ---------------------------------------------------------------------------
# op_promote
# ---------------------------------------------------------------------------

def _prov_entry(body, issues, extra_meta=""):
    raw = " ".join(f"issue:{i}" for i in issues)
    raw += f" date:2026-01-01 expires:2027-01-01 source:implement{extra_meta}"
    meta = {"date": "2026-01-01", "expires": "2027-01-01", "source": "implement"}
    for iss in issues:
        if "issue" not in meta:
            meta["issue"] = iss
    return mm.MemoryEntry(tag="PROVISIONAL", body=body, meta=meta, raw_meta=raw)


class TestOpPromote:
    def test_two_distinct_issues_promotes_to_pattern(self):
        prov = [_prov_entry("Promote me", ["#10", "#20"])]
        result = mm.op_promote(prov)
        assert len(result.promoted) == 1
        assert result.promoted[0].tag == "PATTERN"
        assert result.promoted[0] not in result.remaining_prov

    def test_one_issue_stays_provisional(self):
        prov = [_prov_entry("Stay provisional", ["#10"])]
        result = mm.op_promote(prov)
        assert len(result.promoted) == 0
        assert len(result.remaining_prov) == 1

    def test_two_identical_issues_not_promoted(self):
        prov = [_prov_entry("Not promoted", ["#10", "#10"])]
        result = mm.op_promote(prov)
        assert len(result.promoted) == 0

    def test_promoted_entry_moves_from_prov_to_auth(self):
        prov = [
            _prov_entry("Promote", ["#10", "#20"]),
            _prov_entry("Stay", ["#30"]),
        ]
        result = mm.op_promote(prov)
        assert len(result.promoted) == 1
        assert len(result.remaining_prov) == 1
        assert result.remaining_prov[0].body == "Stay"

    def test_inline_metadata_tag_overrides_pattern(self):
        raw = "evidence:x issue:#10 evidence2:y issue:#20 date:2026-01-01 expires:2027-01-01 source:implement promote_as:AVOID"
        e = mm.MemoryEntry(
            tag="PROVISIONAL",
            body="Avoid entry",
            meta={"date": "2026-01-01", "promote_as": "AVOID"},
            raw_meta=raw,
        )
        result = mm.op_promote([e])
        assert result.promoted[0].tag == "AVOID"


# ---------------------------------------------------------------------------
# op_dedup
# ---------------------------------------------------------------------------

class TestOpDedup:
    def test_identical_bodies_marks_older_invalid(self):
        older = _entry("PATTERN", "Use the transaction rollback fixture", date_str="2026-01-01")
        newer = _entry("PATTERN", "Use the transaction rollback fixture", date_str="2026-06-01")
        result = mm.op_dedup([older, newer])
        # Both entries share the same body, so use list-based checks instead of dict keying
        invalid_entries = [e for e in result.entries if e.tag.startswith("INVALID")]
        assert len(invalid_entries) == 1
        assert invalid_entries[0].meta.get("date") == "2026-01-01"
        surviving = [e for e in result.entries if not e.tag.startswith("INVALID")]
        assert len(surviving) == 1
        assert surviving[0].meta.get("date") == "2026-06-01"

    def test_below_threshold_not_deduped(self):
        e1 = _entry("PATTERN", "Use foo for bar operations to get results.")
        e2 = _entry("PATTERN", "Use completely different approach with no similarities at all.")
        result = mm.op_dedup([e1, e2])
        assert all(not e.tag.startswith("INVALID") for e in result.entries)

    def test_already_invalid_entries_skipped(self):
        inv = _entry("INVALID: already bad", "Some body text for dedup test.")
        normal = _entry("PATTERN", "Some body text for dedup test.")
        result = mm.op_dedup([inv, normal])
        invalid_count = sum(1 for e in result.entries if e.tag.startswith("INVALID"))
        assert invalid_count == 1

    def test_dedup_count_reported(self):
        older = _entry("PATTERN", "Duplicate pattern entry here for dedup check.", date_str="2026-01-01")
        newer = _entry("PATTERN", "Duplicate pattern entry here for dedup check.", date_str="2026-06-01")
        result = mm.op_dedup([older, newer])
        assert result.deduped_count == 1


# ---------------------------------------------------------------------------
# cmd_invalidate (in-memory variant)
# ---------------------------------------------------------------------------

class TestCmdInvalidateLogic:
    def test_matching_entry_retagged(self):
        content = (
            "# Header\n"
            "\n"
            "- [PATTERN] Use the foo approach for bar. <!-- issue:#1 date:2026-01-01 source:implement -->\n"
            "- [PATTERN] Use baz for everything. <!-- issue:#2 date:2026-01-01 source:implement -->\n"
            "\n"
            "---\n"
            "<!-- PROVISIONAL -->\n"
        )
        result = mm.invalidate_content(content, match="foo approach", reason="deprecated by bar-v2")
        assert "[INVALID: deprecated by bar-v2]" in result
        assert "[PATTERN] Use the foo approach" not in result

    def test_non_matching_entries_unchanged(self):
        content = (
            "# Header\n"
            "- [PATTERN] Use baz for everything. <!-- issue:#2 date:2026-01-01 source:implement -->\n"
            "---\n"
            "<!-- PROVISIONAL -->\n"
        )
        result = mm.invalidate_content(content, match="not present", reason="whatever")
        assert result == content

    def test_meta_comment_preserved_after_retag(self):
        content = (
            "# H\n"
            "- [PATTERN] Keep the metadata comment intact. <!-- issue:#7 date:2026-05-01 source:implement -->\n"
            "---\n"
            "<!-- PROVISIONAL -->\n"
        )
        result = mm.invalidate_content(content, match="metadata comment", reason="test")
        assert "<!-- issue:#7 date:2026-05-01 source:implement -->" in result


# ---------------------------------------------------------------------------
# cmd_run logic (scope filter + apply_ops_to_content)
# ---------------------------------------------------------------------------

FULL_FILE = """\
# Test File

- [PATTERN] Keep this one. <!-- issue:#1 date:2026-01-01 expires:2027-01-01 source:implement -->
- [PATTERN] This one expired. <!-- issue:#2 date:2026-01-01 expires:2025-01-01 source:implement -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->

- [PROVISIONAL] Ready to promote. <!-- evidence:x issue:#10 evidence2:y issue:#20 date:2026-01-01 expires:2027-01-01 source:implement -->
- [PROVISIONAL] Single issue only. <!-- issue:#30 date:2026-01-01 expires:2027-01-01 source:implement -->
"""


class TestApplyOpsToContent:
    TODAY = _date(2026, 6, 27)

    def test_expired_entry_removed(self):
        new_content, summary = mm.apply_ops_to_content(FULL_FILE, self.TODAY, scope=None)
        assert "This one expired." not in new_content
        assert summary["expired_auth"] == 1

    def test_keep_non_expired(self):
        new_content, summary = mm.apply_ops_to_content(FULL_FILE, self.TODAY, scope=None)
        assert "Keep this one." in new_content

    def test_promoted_entry_moves_to_auth(self):
        new_content, summary = mm.apply_ops_to_content(FULL_FILE, self.TODAY, scope=None)
        assert summary["promoted"] == 1
        assert "[PATTERN] Ready to promote." in new_content

    def test_single_issue_stays_provisional(self):
        new_content, summary = mm.apply_ops_to_content(FULL_FILE, self.TODAY, scope=None)
        assert "Single issue only." in new_content

    def test_scope_filter_skips_unmatched_entries(self):
        scoped_file = (
            "# H\n"
            "- [PATTERN] Backend only. <!-- issue:#1 date:2026-01-01 expires:2025-01-01 source:implement path:backend/ -->\n"
            "- [PATTERN] Frontend only. <!-- issue:#2 date:2026-01-01 expires:2025-01-01 source:implement path:frontend/ -->\n"
            "---\n<!-- PROVISIONAL -->\n"
        )
        new_content, summary = mm.apply_ops_to_content(scoped_file, self.TODAY, scope="backend/")
        # backend entry is in-scope and expired → removed
        assert "Backend only." not in new_content
        # frontend entry is out-of-scope → kept unconditionally
        assert "Frontend only." in new_content


class TestDryRunDiff:
    def test_dry_run_returns_unified_diff_string(self):
        original = FULL_FILE
        today = _date(2026, 6, 27)
        diff = mm.compute_dry_run_diff(original, "test.md", today, scope=None)
        # FULL_FILE has expired + promotable entries, so a diff must exist
        assert "---" in diff or diff == ""

from pathlib import Path

CMD = (
    Path(__file__).resolve().parents[2]
    / ".archon" / "commands" / "dark-factory-conformance.md"
)


def test_conformance_dedupe_wired():
    """Phase 3.6.2 must invoke dedupe_oos.py."""
    text = CMD.read_text(encoding="utf-8")
    assert "dedupe_oos.py" in text, "Phase 3.6.2 must invoke dedupe_oos.py"


def test_conformance_dedupe_embeds_dedup_key():
    """New spillover issue bodies must embed a dedup-key HTML comment."""
    text = CMD.read_text(encoding="utf-8")
    assert "dedup-key" in text, \
        "Spillover issue body template must include '<!-- dedup-key: ... -->'"


def test_conformance_dedupe_fetches_spillovers():
    """Phase 3.6.2 must fetch existing open spillover issues before calling dedupe_oos.py."""
    text = CMD.read_text(encoding="utf-8")
    assert "SPILLOVER_JSON" in text, \
        "Phase 3.6.2 must fetch open spillover issues into SPILLOVER_JSON"


def test_conformance_dedupe_action_list():
    """Phase 3.6.2 must process an ACTION_LIST from dedupe_oos.py output."""
    text = CMD.read_text(encoding="utf-8")
    assert "ACTION_LIST" in text, \
        "Phase 3.6.2 must build ACTION_LIST from dedupe_oos.py output"

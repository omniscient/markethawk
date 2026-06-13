import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from factory_core import board


def _items(items):
    return subprocess.CompletedProcess([], 0, stdout=json.dumps({"items": items}), stderr="")


def _ok():
    return subprocess.CompletedProcess([], 0, stdout="", stderr="")


def test_find_board_item_found(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _items([
        {"id": "ITEM42", "content": {"number": 42, "type": "Issue"}},
    ]))
    assert board.find_board_item(42) == "ITEM42"


def test_find_board_item_wrong_number(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _items([
        {"id": "ITEM99", "content": {"number": 99, "type": "Issue"}},
    ]))
    assert board.find_board_item(42) == ""


def test_find_board_item_gh_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw:
        subprocess.CompletedProcess([], 1, stdout="", stderr="error"))
    assert board.find_board_item(42) == ""


def test_set_board_status_calls_item_edit(monkeypatch):
    calls = []
    def fake(cmd, **kw):
        calls.append(cmd)
        if "item-list" in cmd:
            return _items([{"id": "ITEM42", "content": {"number": 42, "type": "Issue"}}])
        return _ok()
    monkeypatch.setattr(subprocess, "run", fake)
    board.set_board_status(42, "opt_abc")
    assert any("item-edit" in " ".join(c) for c in calls)
    edit = next(c for c in calls if "item-edit" in " ".join(c))
    assert "opt_abc" in edit
    assert "ITEM42" in edit


def test_set_board_status_no_item_skips_edit(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: (calls.append(cmd), _items([]))[1])
    board.set_board_status(42, "opt_abc")
    assert not any("item-edit" in " ".join(c) for c in calls)


def test_post_or_update_comment_new_comment(monkeypatch):
    calls = []
    def fake(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake)
    board.post_or_update_comment(42, "<!-- marker -->", "body text")
    assert any("issue" in " ".join(c) and "comment" in " ".join(c) for c in calls)


def test_post_or_update_comment_updates_existing(monkeypatch):
    calls = []
    def fake(cmd, **kw):
        calls.append(cmd)
        if "--jq" in " ".join(cmd):
            return subprocess.CompletedProcess([], 0, stdout="12345\n", stderr="")
        return _ok()
    monkeypatch.setattr(subprocess, "run", fake)
    board.post_or_update_comment(42, "<!-- marker -->", "updated body")
    assert any("PATCH" in " ".join(c) for c in calls)
    assert any("12345" in " ".join(c) for c in calls)

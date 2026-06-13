import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from factory_core.breaker import (
    get_retry_count, increment_retry, reset_retry, trip_to_blocked,
)


def test_get_retry_count_missing_file(tmp_path):
    assert get_retry_count("42:refine", tmp_path / "state.json") == 0


def test_increment_creates_key(tmp_path):
    sf = tmp_path / "state.json"
    assert increment_retry("42:refine", sf) == 1
    assert get_retry_count("42:refine", sf) == 1


def test_increment_accumulates(tmp_path):
    sf = tmp_path / "state.json"
    increment_retry("42:refine", sf)
    increment_retry("42:refine", sf)
    assert get_retry_count("42:refine", sf) == 2


def test_increment_does_not_affect_other_keys(tmp_path):
    sf = tmp_path / "state.json"
    increment_retry("42:refine", sf)
    increment_retry("42:plan", sf)
    assert get_retry_count("42:refine", sf) == 1
    assert get_retry_count("42:plan", sf) == 1


def test_reset_removes_key(tmp_path):
    sf = tmp_path / "state.json"
    increment_retry("42:refine", sf)
    reset_retry("42:refine", sf)
    assert get_retry_count("42:refine", sf) == 0


def test_reset_noop_when_missing(tmp_path):
    sf = tmp_path / "state.json"
    reset_retry("42:refine", sf)  # should not raise


def test_implement_key_is_bare_issue_number(tmp_path):
    sf = tmp_path / "state.json"
    increment_retry("42", sf)
    assert get_retry_count("42", sf) == 1
    assert get_retry_count("42:implement", sf) == 0


def test_state_file_is_valid_json(tmp_path):
    sf = tmp_path / "state.json"
    increment_retry("42:refine", sf)
    data = json.loads(sf.read_text())
    assert data == {"42:refine": 1}


def test_atomic_write_survives_existing_file(tmp_path):
    sf = tmp_path / "state.json"
    sf.write_text('{"existing": 5}')
    increment_retry("42:refine", sf)
    data = json.loads(sf.read_text())
    assert data["existing"] == 5
    assert data["42:refine"] == 1


def test_trip_to_blocked_resets_retry(tmp_path, monkeypatch):
    sf = tmp_path / "state.json"
    increment_retry("42", sf)
    monkeypatch.setattr(subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess([], 0, stdout="", stderr=""))
    with patch("factory_core.board.set_board_status"):
        trip_to_blocked(42, "implement", "test reason", sf)
    assert get_retry_count("42", sf) == 0


def test_trip_to_blocked_phase_key_naming(tmp_path, monkeypatch):
    sf = tmp_path / "state.json"
    increment_retry("42:refine", sf)
    monkeypatch.setattr(subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess([], 0, stdout="", stderr=""))
    with patch("factory_core.board.set_board_status"):
        trip_to_blocked(42, "refine", "test reason", sf)
    assert get_retry_count("42:refine", sf) == 0


def test_trip_to_blocked_posts_comment(tmp_path, monkeypatch):
    sf = tmp_path / "state.json"
    calls = []
    monkeypatch.setattr(subprocess, "run",
        lambda cmd, **kw: (calls.append(cmd),
                           subprocess.CompletedProcess([], 0, stdout="", stderr=""))[1])
    with patch("factory_core.board.set_board_status"):
        trip_to_blocked(42, "plan", "retry limit reached", sf)
    assert any("comment" in " ".join(c) for c in calls)

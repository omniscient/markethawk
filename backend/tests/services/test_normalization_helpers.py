"""
Tests for normalization module pure helper functions — no DB required.
"""
from datetime import datetime

import pytest

from app.services.normalization import _parse_date, _to_date_str


# ── _parse_date ───────────────────────────────────────────────────────────────

def test_parse_datetime_with_fractional_seconds():
    result = _parse_date("2024-01-15T09:30:00.000000")
    assert result == datetime(2024, 1, 15, 9, 30, 0)


def test_parse_datetime_without_fractional_seconds():
    result = _parse_date("2024-01-15T09:30:00")
    assert result == datetime(2024, 1, 15, 9, 30, 0)


def test_parse_date_only():
    result = _parse_date("2024-01-15")
    assert result == datetime(2024, 1, 15, 0, 0, 0)


def test_parse_none_returns_none():
    assert _parse_date(None) is None


def test_parse_empty_string_returns_none():
    assert _parse_date("") is None


def test_parse_invalid_format_returns_none():
    assert _parse_date("not-a-date") is None


# ── _to_date_str ──────────────────────────────────────────────────────────────

def test_to_date_str_formats_correctly():
    dt = datetime(2024, 1, 15, 9, 30, 0)
    assert _to_date_str(dt) == "2024-01-15"


def test_roundtrip_parse_and_format():
    original = "2024-06-01"
    parsed = _parse_date(original)
    assert _to_date_str(parsed) == original

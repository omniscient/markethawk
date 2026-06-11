"""Unit tests for app/utils/db.py — get_or_404()."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.utils.db import get_or_404


class _FakeModel:
    id = None


class TestGetOr404:
    def test_returns_object_when_found(self):
        db = MagicMock(spec=Session)
        obj = _FakeModel()
        db.query.return_value.filter.return_value.first.return_value = obj
        result = get_or_404(db, _FakeModel, 1, "FakeModel")
        assert result is obj

    def test_raises_404_when_not_found(self):
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            get_or_404(db, _FakeModel, 99, "Widget")
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Widget not found"

    def test_detail_uses_name_argument(self):
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            get_or_404(db, _FakeModel, 5, "Strategy")
        assert "Strategy" in exc_info.value.detail
        assert "not found" in exc_info.value.detail

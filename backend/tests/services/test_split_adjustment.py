"""
Tests for SplitAdjustmentService — pure math helpers that require no DB.
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.services.split_adjustment import SplitAdjustmentService


def _split(split_from, split_to):
    s = MagicMock()
    s.split_from = split_from
    s.split_to = split_to
    return s


# ── compute_price_factor ──────────────────────────────────────────────────────


def test_reverse_split_10_to_1_factor_is_10():
    factor = SplitAdjustmentService.compute_price_factor(_split(10, 1))
    assert factor == Decimal("10")


def test_forward_split_1_to_2_factor_is_half():
    factor = SplitAdjustmentService.compute_price_factor(_split(1, 2))
    assert factor == Decimal("0.5")


def test_3_for_1_split_factor_is_third():
    factor = SplitAdjustmentService.compute_price_factor(_split(1, 3))
    assert factor == pytest.approx(Decimal("0.3333"), rel=Decimal("1e-3"))


def test_no_split_1_to_1_factor_is_one():
    factor = SplitAdjustmentService.compute_price_factor(_split(1, 1))
    assert factor == Decimal("1")


def test_reverse_4_for_1_factor_is_4():
    factor = SplitAdjustmentService.compute_price_factor(_split(4, 1))
    assert factor == Decimal("4")


# ── get_unapplied_splits ──────────────────────────────────────────────────────


def test_get_unapplied_splits_returns_list(db):
    result = SplitAdjustmentService.get_unapplied_splits(db)
    assert isinstance(result, list)

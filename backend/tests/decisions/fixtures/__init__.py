"""Loader for the JSON fixture cases under ``malformed/``, ``stale/``, ``low_quality/``
and ``prompt_injected/``.

Each ``*.json`` file is ``{"target": "schema"|"request"|"result", "description": str,
"patch": {...}, ...}``. ``patch`` is deep-merged over the baseline object's
``model_dump(mode="json")``: dicts merge recursively, any other value replaces, and the
string ``"__delete__"`` removes the key. Extra top-level keys are case-specific expectations.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent
DELETE = "__delete__"


def load_cases(category: str) -> list[tuple[str, dict[str, Any]]]:
    paths = sorted((FIXTURES_DIR / category).glob("*.json"))
    if not paths:
        raise AssertionError(f"no fixtures in {category}/")
    return [(p.stem, json.loads(p.read_text())) for p in paths]


def apply_patch(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in patch.items():
        if value == DELETE:
            merged.pop(key, None)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = apply_patch(merged[key], value)
        else:
            merged[key] = value
    return merged

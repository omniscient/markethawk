"""Load the LT-1a roster migration module so tests execute its exact seed SQL."""

import importlib.util
from pathlib import Path
from types import ModuleType

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "alembic"
    / "versions"
    / "f8f6c8fc1c83_add_lt_etf_roster_static_universe.py"
)


def load_lt_etf_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "lt_etf_roster_migration", MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

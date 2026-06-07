"""Assert the coverage config no longer omits the full tasks package."""

import pathlib
import tomllib


def test_tasks_glob_not_in_coverage_omit():
    cfg = tomllib.loads(
        (pathlib.Path(__file__).parent.parent / "pyproject.toml").read_text()
    )
    omit = cfg["tool"]["coverage"]["run"]["omit"]
    assert "app/tasks/*.py" not in omit, (
        "app/tasks/*.py must be removed from [tool.coverage.run] omit — "
        "use # pragma: no cover on the two broker-bound functions instead"
    )

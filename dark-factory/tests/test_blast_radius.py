"""Tests for gate_blast_radius.py — deterministic file classifier."""
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().parents[2] / "dark-factory" / "scripts" / "gate_blast_radius.py"


def run_script(
    changed_files: list,
    hotspots_content: str = "",
    lines_changed: int = 50,
    config_extra: dict = None,
) -> dict:
    """Run the script; return parsed output header lines as a dict."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as hf:
        hf.write(hotspots_content)
        hf.flush()
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as cf:
            cfg = {
                "blast_radius": {
                    "enabled": True,
                    "hotspot_score_floor": 5.0,
                    "size_budget_lines": 400,
                    "size_budget_blocks": False,
                }
            }
            if config_extra:
                cfg["blast_radius"].update(config_extra)
            cf.write(yaml.dump(cfg))
            cf.flush()
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--changed-files-stdin",
                    "--lines-changed",
                    str(lines_changed),
                    "--hotspots",
                    hf.name,
                    "--config",
                    cf.name,
                ],
                input="\n".join(changed_files),
                capture_output=True,
                text=True,
            )
    assert proc.returncode == 0, proc.stderr
    result = {}
    for line in proc.stdout.splitlines():
        if ": " in line and not line.startswith("  "):
            k, v = line.split(": ", 1)
            result[k] = v
    return result


def test_no_triggers_produces_pass():
    out = run_script(["frontend/src/components/Foo.tsx", "docs/some-doc.md"])
    assert out["STATUS"] == "PASS"
    assert out["GATE_TYPE"] == "blast"
    assert out["SEVERITY"] == "none"


def test_migration_file_triggers_human_required():
    out = run_script(["alembic/versions/abc123_add_col.py"])
    assert out["STATUS"] == "HUMAN_REQUIRED"
    assert out["SEVERITY"] == "critical"


def test_seed_sql_triggers_human_required():
    out = run_script(["dark-factory/seed/02_scanner_data.sql"])
    assert out["STATUS"] == "HUMAN_REQUIRED"


def test_auth_router_triggers_human_required():
    out = run_script(["backend/app/routers/auth.py"])
    assert out["STATUS"] == "HUMAN_REQUIRED"


def test_hotspot_file_above_floor_triggers_human_required():
    # Space-separated format matching docs/codeindex-hotspots.md: score first, bare path second
    hotspots = "    7.2  backend/app/services/scanner.py  (2d / 10t)  200 loc\n"
    out = run_script(["backend/app/services/scanner.py"], hotspots_content=hotspots)
    assert out["STATUS"] == "HUMAN_REQUIRED"


def test_hotspot_file_below_floor_does_not_trigger():
    hotspots = "    3.1  backend/app/services/scanner.py  (1d / 5t)  200 loc\n"
    out = run_script(["backend/app/services/scanner.py"], hotspots_content=hotspots)
    assert out["STATUS"] == "PASS"


def test_size_blocking_when_enabled():
    out = run_script(
        ["frontend/src/components/Foo.tsx"],
        lines_changed=500,
        config_extra={"size_budget_lines": 400, "size_budget_blocks": True},
    )
    assert out["STATUS"] == "HUMAN_REQUIRED"


def test_size_advisory_only_by_default():
    out = run_script(["frontend/src/components/Foo.tsx"], lines_changed=500)
    assert out["STATUS"] == "PASS"


def test_lines_changed_in_artifact():
    out = run_script(["frontend/src/components/Foo.tsx"], lines_changed=123)
    assert out["LINES_CHANGED"] == "123"


def test_disabled_produces_skipped():
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as cf:
        cfg = {
            "blast_radius": {
                "enabled": False,
                "hotspot_score_floor": 5.0,
                "size_budget_lines": 400,
                "size_budget_blocks": False,
            }
        }
        cf.write(yaml.dump(cfg))
        cf.flush()
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--changed-files-stdin",
                "--lines-changed",
                "50",
                "--hotspots",
                "/dev/null",
                "--config",
                cf.name,
            ],
            input="alembic/versions/abc.py",
            capture_output=True,
            text=True,
        )
    assert proc.returncode == 0
    assert "SKIPPED" in proc.stdout

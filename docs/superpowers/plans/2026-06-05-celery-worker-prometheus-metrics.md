# Plan: Celery Worker Prometheus Metrics Fix (#194)

**Goal**: Fix `celery_tasks_total` and `celery_task_duration_seconds` never reaching Prometheus by resolving two root causes: (1) the `prometheus_multiproc` Docker volume uses `driver_opts: type: tmpfs`, giving each container a private tmpfs instance instead of a shared filesystem; and (2) stale `.db` files from dead container runs and recycled Celery child processes inflate metric aggregates.

**Architecture**: Retain the existing shared-directory model. Both `backend` and `celery-worker` write `.db` files to `/tmp/prometheus_multiproc`; the backend's `MultiProcessCollector` at `GET /metrics` aggregates them; Prometheus continues scraping only `backend:8000`. No new containers, no new scrape targets, no new ports.

**Tech Stack**: Docker Compose (volume definition + container startup commands), Python/Celery signals (`worker_process_shutdown`).

---

## File Structure

| File | Change | Purpose |
|---|---|---|
| `docker-compose.yml` | Modify | Remove `driver_opts` from volume; prefix backend + celery-worker commands with stale-file wipe |
| `docker-compose.override.yml` | Modify | Prefix dev-mode override commands with stale-file wipe (overrides replace base commands) |
| `backend/requirements.txt` | Modify | Add `PyYAML>=6.0` (needed by regression test) |
| `backend/app/core/celery_app.py` | Modify | Add `worker_process_shutdown` handler → `mark_process_dead` |
| `backend/tests/test_docker_compose_config.py` | New | Regression: volume has no `driver_opts`; commands contain the wipe prefix |
| `backend/tests/core/test_celery_prometheus_cleanup.py` | New | Unit: shutdown handler calls `mark_process_dead(pid)`; is a no-op when env var absent |

---

## Task 1 — Fix prometheus_multiproc volume (tmpfs → real named volume) + cold-start wipe

**Files**: `docker-compose.yml`, `docker-compose.override.yml`, `backend/requirements.txt`, `backend/tests/test_docker_compose_config.py`

### Step 1a — Add PyYAML to backend/requirements.txt

The regression test parses YAML files. PyYAML is not yet listed in `backend/requirements.txt`. Add it:

```
# In backend/requirements.txt — append
PyYAML>=6.0
```

Install in the running container so the tests can run immediately:

```bash
docker-compose exec backend pip install "PyYAML>=6.0"
```

Expected output:
```
Successfully installed PyYAML-6.0.2
```

### Step 1b — Write the failing regression tests

Create `backend/tests/test_docker_compose_config.py`:

```python
"""Regression tests for Prometheus multiprocess Docker Compose configuration."""
import os

import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))


def _load(filename):
    with open(os.path.join(REPO_ROOT, filename)) as f:
        return yaml.safe_load(f)


def test_prometheus_multiproc_volume_has_no_driver_opts():
    """Volume must be a plain named volume so both containers share the same filesystem.

    driver_opts: type: tmpfs gives each container a private tmpfs instance — files written
    by celery-worker are invisible to the backend's MultiProcessCollector.
    """
    compose = _load("docker-compose.yml")
    vol = (compose.get("volumes") or {}).get("prometheus_multiproc") or {}
    assert "driver_opts" not in vol


def test_backend_command_wipes_multiproc_dir_on_start():
    """backend command must clear stale .db files from prior runs on every cold start."""
    compose = _load("docker-compose.yml")
    cmd = compose["services"]["backend"]["command"]
    assert "rm -rf /tmp/prometheus_multiproc/*" in cmd


def test_celery_worker_command_wipes_multiproc_dir_on_start():
    """celery-worker command must clear stale .db files from prior runs on every cold start."""
    compose = _load("docker-compose.yml")
    cmd = compose["services"]["celery-worker"]["command"]
    assert "rm -rf /tmp/prometheus_multiproc/*" in cmd


def test_override_backend_command_wipes_multiproc_dir_on_start():
    """Dev-mode override command must also wipe stale files.

    docker-compose.override.yml replaces the base command entirely, so the rm -rf
    must be present in the override too.
    """
    compose = _load("docker-compose.override.yml")
    cmd = compose["services"]["backend"]["command"]
    assert "rm -rf /tmp/prometheus_multiproc/*" in cmd


def test_override_celery_worker_command_wipes_multiproc_dir_on_start():
    """Dev-mode override command must also wipe stale files.

    docker-compose.override.yml replaces the base command entirely, so the rm -rf
    must be present in the override too.
    """
    compose = _load("docker-compose.override.yml")
    cmd = compose["services"]["celery-worker"]["command"]
    assert "rm -rf /tmp/prometheus_multiproc/*" in cmd
```

### Step 1c — Verify the tests fail

```bash
cd /workspace/markethawk/backend && python -m pytest tests/test_docker_compose_config.py -v
```

Expected (all fail before any changes):
```
FAILED tests/test_docker_compose_config.py::test_prometheus_multiproc_volume_has_no_driver_opts
FAILED tests/test_docker_compose_config.py::test_backend_command_wipes_multiproc_dir_on_start
FAILED tests/test_docker_compose_config.py::test_celery_worker_command_wipes_multiproc_dir_on_start
FAILED tests/test_docker_compose_config.py::test_override_backend_command_wipes_multiproc_dir_on_start
FAILED tests/test_docker_compose_config.py::test_override_celery_worker_command_wipes_multiproc_dir_on_start
5 failed
```

### Step 1d — Fix 1: Remove driver_opts from the prometheus_multiproc volume definition

In `docker-compose.yml`, find the `prometheus_multiproc` volume block (~line 544):

```yaml
# BEFORE
  prometheus_multiproc:
    driver: local
    driver_opts:
      type: tmpfs
      device: tmpfs
      o: size=256m

# AFTER
  prometheus_multiproc:
```

This makes the volume a plain Docker named volume backed by the host filesystem, genuinely shared between all containers that mount it.

### Step 1e — Fix 2: Add cold-start wipe to docker-compose.yml commands

In `docker-compose.yml`, update the `backend` service `command` (~line 93):

```yaml
# BEFORE
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000

# AFTER
    command: sh -c "rm -rf /tmp/prometheus_multiproc/* 2>/dev/null; uvicorn app.main:app --host 0.0.0.0 --port 8000"
```

Update the `celery-worker` service `command` (~line 164):

```yaml
# BEFORE
    command: celery -A app.core.celery_app:celery_app worker --loglevel=info

# AFTER
    command: sh -c "rm -rf /tmp/prometheus_multiproc/* 2>/dev/null; celery -A app.core.celery_app:celery_app worker --loglevel=info"
```

The `2>/dev/null` silences the error when the directory is empty; `sh -c` is needed because glob expansion (`*`) requires a shell.

### Step 1f — Fix 2 (continued): Add cold-start wipe to docker-compose.override.yml commands

The override file replaces the base `command` fields entirely in dev mode, so the wipe must also appear there.

In `docker-compose.override.yml`, update the `backend` service `command`:

```yaml
# BEFORE
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# AFTER
    command: sh -c "rm -rf /tmp/prometheus_multiproc/* 2>/dev/null; uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
```

Update the `celery-worker` service `command`:

```yaml
# BEFORE
    command: python -m watchfiles --filter python 'celery -A app.core.celery_app:celery_app worker --loglevel=info' /app/app

# AFTER
    command: sh -c "rm -rf /tmp/prometheus_multiproc/* 2>/dev/null; python -m watchfiles --filter python 'celery -A app.core.celery_app:celery_app worker --loglevel=info' /app/app"
```

### Step 1g — Verify all regression tests pass

```bash
cd /workspace/markethawk/backend && python -m pytest tests/test_docker_compose_config.py -v
```

Expected:
```
PASSED tests/test_docker_compose_config.py::test_prometheus_multiproc_volume_has_no_driver_opts
PASSED tests/test_docker_compose_config.py::test_backend_command_wipes_multiproc_dir_on_start
PASSED tests/test_docker_compose_config.py::test_celery_worker_command_wipes_multiproc_dir_on_start
PASSED tests/test_docker_compose_config.py::test_override_backend_command_wipes_multiproc_dir_on_start
PASSED tests/test_docker_compose_config.py::test_override_celery_worker_command_wipes_multiproc_dir_on_start
5 passed
```

### Step 1h — Commit

```bash
git add docker-compose.yml docker-compose.override.yml backend/requirements.txt backend/tests/test_docker_compose_config.py
git commit -m "fix(#194): convert prometheus_multiproc to real named volume + cold-start stale-file wipe"
```

---

## Task 2 — Wire worker_process_shutdown signal for per-process cleanup

**Files**: `backend/app/core/celery_app.py`, `backend/tests/core/test_celery_prometheus_cleanup.py`

### Step 2a — Write the failing unit tests

Create `backend/tests/core/test_celery_prometheus_cleanup.py`:

```python
"""Unit tests for Prometheus per-process metric cleanup on Celery child process exit."""
import os
from unittest.mock import MagicMock, patch


def test_cleanup_calls_mark_process_dead_when_env_set():
    """Handler calls mark_process_dead(pid) when PROMETHEUS_MULTIPROC_DIR is set."""
    from app.core.celery_app import _cleanup_prometheus_on_exit

    mock_mark = MagicMock()
    with patch.dict(os.environ, {"PROMETHEUS_MULTIPROC_DIR": "/tmp/prom_test"}):
        with patch("prometheus_client.multiprocess.mark_process_dead", mock_mark):
            _cleanup_prometheus_on_exit(sender=None, pid=42, exitcode=0)

    mock_mark.assert_called_once_with(42)


def test_cleanup_no_op_when_env_not_set():
    """Handler is a no-op when PROMETHEUS_MULTIPROC_DIR is absent from the environment."""
    from app.core.celery_app import _cleanup_prometheus_on_exit

    env_without = {k: v for k, v in os.environ.items() if k != "PROMETHEUS_MULTIPROC_DIR"}
    mock_mark = MagicMock()
    with patch.dict(os.environ, env_without, clear=True):
        with patch("prometheus_client.multiprocess.mark_process_dead", mock_mark):
            _cleanup_prometheus_on_exit(sender=None, pid=99, exitcode=0)

    mock_mark.assert_not_called()
```

### Step 2b — Verify the tests fail

```bash
cd /workspace/markethawk/backend && python -m pytest tests/core/test_celery_prometheus_cleanup.py -v
```

Expected (ImportError — function does not exist yet):
```
FAILED tests/core/test_celery_prometheus_cleanup.py::test_cleanup_calls_mark_process_dead_when_env_set
FAILED tests/core/test_celery_prometheus_cleanup.py::test_cleanup_no_op_when_env_not_set
# ImportError: cannot import name '_cleanup_prometheus_on_exit' from 'app.core.celery_app'
2 failed
```

### Step 2c — Fix 3: Add worker_process_shutdown handler to celery_app.py

In `backend/app/core/celery_app.py`, make two changes:

**1.** Add `os` to the top-level imports and expand the Celery signals import:

```python
# BEFORE
from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready

# AFTER
import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_shutdown, worker_ready
```

**2.** Add the shutdown handler immediately after the `_on_worker_ready` function:

```python
@worker_process_shutdown.connect
def _cleanup_prometheus_on_exit(sender, pid, exitcode, **kwargs):
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client import multiprocess
        multiprocess.mark_process_dead(pid)
```

The full top of the file after both changes:

```python
import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_shutdown, worker_ready

from app.core.config import settings

celery_app = Celery(
    "stockscanner",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks"],
)


@worker_ready.connect
def _on_worker_ready(sender, **kwargs):
    """Run startup validation when the Celery worker finishes booting."""
    from app.tasks.scanning import validate_scheduled_scanner_configs

    validate_scheduled_scanner_configs()


@worker_process_shutdown.connect
def _cleanup_prometheus_on_exit(sender, pid, exitcode, **kwargs):
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client import multiprocess
        multiprocess.mark_process_dead(pid)


# News polling runs weekdays only (Mon-Fri).
# ... rest of file unchanged ...
```

### Step 2d — Verify the unit tests pass

```bash
cd /workspace/markethawk/backend && python -m pytest tests/core/test_celery_prometheus_cleanup.py -v
```

Expected:
```
PASSED tests/core/test_celery_prometheus_cleanup.py::test_cleanup_calls_mark_process_dead_when_env_set
PASSED tests/core/test_celery_prometheus_cleanup.py::test_cleanup_no_op_when_env_not_set
2 passed
```

### Step 2e — Run the full test suite (no regressions)

```bash
cd /workspace/markethawk/backend && python -m pytest tests/ -x -q 2>&1 | tail -10
```

Expected (no new failures):
```
... passed, ... warnings
```

### Step 2f — Confirm backend reloaded cleanly

```bash
docker-compose logs backend --tail=10
```

Expected: no `ImportError` or `AttributeError` lines; timestamps are recent.

### Step 2g — Commit

```bash
git add backend/app/core/celery_app.py backend/tests/core/test_celery_prometheus_cleanup.py
git commit -m "fix(#194): wire worker_process_shutdown → mark_process_dead for per-PID metric cleanup"
```

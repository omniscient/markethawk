"""Tests for Celery app configuration and signal handlers."""

import pytest


def test_worker_process_shutdown_calls_mark_process_dead(tmp_path, monkeypatch):
    """worker_process_shutdown signal must call mark_process_dead to clean up per-PID gauge files."""
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))

    from app.core.celery_app import _cleanup_prometheus_on_exit

    dead_pids = []
    monkeypatch.setattr(
        "prometheus_client.multiprocess.mark_process_dead",
        lambda pid: dead_pids.append(pid),
    )

    _cleanup_prometheus_on_exit(sender=None, pid=99999, exitcode=0)
    assert 99999 in dead_pids


def test_worker_process_shutdown_noop_without_multiproc_dir(monkeypatch):
    """_cleanup_prometheus_on_exit must be a no-op when PROMETHEUS_MULTIPROC_DIR is unset."""
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)

    from app.core.celery_app import _cleanup_prometheus_on_exit

    dead_pids = []
    monkeypatch.setattr(
        "prometheus_client.multiprocess.mark_process_dead",
        lambda pid: dead_pids.append(pid),
    )

    _cleanup_prometheus_on_exit(sender=None, pid=99999, exitcode=0)
    assert dead_pids == []


def test_worker_init_calls_load_extension_modules(monkeypatch):
    from app.core.celery_app import _load_extension_modules
    from app.core.config import settings

    calls = []
    monkeypatch.setattr(
        "app.core.celery_app.load_extension_modules",
        lambda names: calls.append(names),
    )

    _load_extension_modules()

    assert calls == [settings.MARKETHAWK_EXTENSION_MODULES]


def test_worker_init_raises_system_exit_on_import_error(monkeypatch):
    from app.core.celery_app import _load_extension_modules
    from app.exceptions import ExtensionImportError

    def _raise(*args, **kwargs):
        raise ExtensionImportError("boom", module_name="myedge.x", original_error="x")

    monkeypatch.setattr("app.core.celery_app.load_extension_modules", _raise)

    with pytest.raises(SystemExit):
        _load_extension_modules()

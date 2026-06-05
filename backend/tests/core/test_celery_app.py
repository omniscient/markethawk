"""Tests for Celery app configuration and signal handlers."""


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

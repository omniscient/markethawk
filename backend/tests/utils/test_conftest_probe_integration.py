"""Integration test: _testcontainers_url() must call probe unconditionally.

Spec requirement #2: conftest.py's _testcontainers_url() must continue to call
the discovery function exactly as today; no change to fixture behaviour.
"""

from unittest.mock import MagicMock, patch


def test_probe_called_without_discovery_env_var(monkeypatch):
    """probe_running_postgres() is called even when POSTGRES_DISCOVERY_ENABLED is unset."""
    monkeypatch.delenv("POSTGRES_DISCOVERY_ENABLED", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)

    probe_calls = []

    def _counting_probe():
        probe_calls.append(1)
        return None  # no postgres found — fall through to container

    mock_inner = MagicMock()
    mock_inner.get_connection_url.return_value = "postgresql://test:test@localhost/test"
    mock_container = MagicMock()
    mock_container.__enter__ = lambda s: mock_inner
    mock_container.__exit__ = lambda s, *a: False

    with (
        patch("tests.conftest.probe_running_postgres", _counting_probe),
        patch("tests.conftest.PostgresContainer", return_value=mock_container),
    ):
        import tests.conftest as conf

        with conf._testcontainers_url():
            pass

    assert len(probe_calls) == 1, (
        "probe_running_postgres() must be called unconditionally in _testcontainers_url(); "
        "spec requirement #2 forbids gating it behind POSTGRES_DISCOVERY_ENABLED"
    )

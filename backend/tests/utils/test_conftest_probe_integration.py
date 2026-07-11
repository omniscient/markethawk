"""Regression tests for PostgreSQL test database URL resolution."""

from unittest.mock import MagicMock, call, patch

from tests.conftest import POSTGRES_IMAGE, _testcontainers_url


def test_testcontainers_url_uses_container_when_postgres_probe_finds_nothing():
    """The probe runs first, then testcontainers supplies the fallback URL."""
    container = MagicMock()
    container.get_connection_url.return_value = "postgresql://container:test@db/test"
    container_context = MagicMock()
    container_context.__enter__.return_value = container
    calls = MagicMock()

    with (
        patch("tests.conftest.probe_running_postgres", return_value=None) as probe,
        patch("tests.conftest.PostgresContainer", return_value=container_context) as postgres_container,
    ):
        calls.attach_mock(probe, "probe_running_postgres")
        calls.attach_mock(postgres_container, "PostgresContainer")

        with _testcontainers_url() as url:
            assert url == "postgresql://container:test@db/test"

    calls.assert_has_calls(
        [
            call.probe_running_postgres(),
            call.PostgresContainer(POSTGRES_IMAGE),
        ]
    )
    probe.assert_called_once_with()
    postgres_container.assert_called_once_with(POSTGRES_IMAGE)

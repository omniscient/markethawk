"""Unit tests for the pg_discovery module."""

from unittest.mock import MagicMock, patch

from tests.utils.pg_discovery import probe_running_postgres


class TestProbeRunningPostgres:
    def test_explicit_env_var_returns_immediately(self, monkeypatch):
        """TEST_DATABASE_URL takes priority over all other probing."""
        monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://x:y@z/db")
        result = probe_running_postgres()
        assert result == "postgresql://x:y@z/db"

    def test_docker_api_ip_discovery(self, monkeypatch):
        """Finds a reachable postgres via the Docker API when DOCKER_HOST is set."""
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        monkeypatch.setenv("DOCKER_HOST", "tcp://docker:2375")

        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "Image": "postgres:15-alpine",
                "NetworkSettings": {
                    "Networks": {"bridge": {"IPAddress": "172.17.0.2"}}
                },
            }
        ]

        mock_conn = MagicMock()

        with (
            patch("tests.utils.pg_discovery.requests") as mock_requests,
            patch("tests.utils.pg_discovery.psycopg2") as mock_psycopg2,
        ):
            mock_requests.get.return_value = mock_response
            mock_psycopg2.connect.return_value = mock_conn

            result = probe_running_postgres()

        assert result is not None
        assert "172.17.0.2" in result

    def test_docker_api_failure_falls_through_to_hostname(self, monkeypatch):
        """When Docker API call fails, falls through to well-known hostnames."""
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        monkeypatch.setenv("DOCKER_HOST", "tcp://docker:2375")

        mock_conn = MagicMock()

        with (
            patch("tests.utils.pg_discovery.requests") as mock_requests,
            patch("tests.utils.pg_discovery.psycopg2") as mock_psycopg2,
        ):
            mock_requests.get.side_effect = Exception("connection refused")

            # Only the "postgres" hostname succeeds
            def connect_side_effect(*args, **kwargs):
                if kwargs.get("host") == "postgres":
                    return mock_conn
                raise Exception("unreachable")

            mock_psycopg2.connect.side_effect = connect_side_effect

            result = probe_running_postgres()

        assert result is not None
        assert "postgres" in result

    def test_credential_iteration_order(self, monkeypatch):
        """Iterates through common credentials; returns first working combination."""
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        monkeypatch.delenv("DOCKER_HOST", raising=False)

        mock_conn = MagicMock()

        with (
            patch("tests.utils.pg_discovery.requests"),
            patch("tests.utils.pg_discovery.psycopg2") as mock_psycopg2,
        ):
            call_count = 0

            def connect_side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                # Only the second credential set (onecli) on localhost succeeds
                if kwargs.get("user") == "onecli" and kwargs.get("host") == "localhost":
                    return mock_conn
                raise Exception("auth failed")

            mock_psycopg2.connect.side_effect = connect_side_effect
            result = probe_running_postgres()

        assert result is not None
        assert "onecli" in result
        assert call_count > 1  # verified iteration happened

    def test_docker_api_non_list_response_falls_through_to_hostname(self, monkeypatch):
        """When Docker API returns a non-list (e.g. error dict), falls through to hostname probing."""
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        monkeypatch.setenv("DOCKER_HOST", "tcp://docker:2375")

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": "authorization failed"}

        mock_conn = MagicMock()

        with (
            patch("tests.utils.pg_discovery.requests") as mock_requests,
            patch("tests.utils.pg_discovery.psycopg2") as mock_psycopg2,
        ):
            mock_requests.get.return_value = mock_response

            def connect_side_effect(*args, **kwargs):
                if kwargs.get("host") == "postgres":
                    return mock_conn
                raise Exception("unreachable")

            mock_psycopg2.connect.side_effect = connect_side_effect

            result = probe_running_postgres()

        assert result is not None
        assert "postgres" in result

    def test_all_fail_returns_none(self, monkeypatch):
        """Returns None when no postgres instance is reachable."""
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        monkeypatch.delenv("DOCKER_HOST", raising=False)

        with (
            patch("tests.utils.pg_discovery.requests"),
            patch("tests.utils.pg_discovery.psycopg2") as mock_psycopg2,
        ):
            mock_psycopg2.connect.side_effect = Exception("unreachable")
            result = probe_running_postgres()

        assert result is None

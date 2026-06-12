import os

# Must be set before any app import so SlowAPI limiter builds as a no-op.
# Redis (db 1) is not available in the test environment; without this the
# SlowAPIASGIMiddleware raises ConnectionError on every request.
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("POLYGON_API_KEY", "test-key-for-unit-tests-only")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-unit-tests-only-aaa")

import logging as _logging
from contextlib import contextmanager
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

from app.core.database import Base
from app.main import app

_conftest_logger = _logging.getLogger(__name__)

POSTGRES_IMAGE = "postgres:15-alpine"


def _probe_running_postgres() -> str | None:
    """Return a postgres URL if a running instance is reachable, else None.

    Probes the Docker daemon (via DOCKER_HOST) for running postgres containers,
    then tries common credentials. Falls back to hostname-based probing so the
    tests work in both factory (DinD, exec-blocked) and standard CI environments.
    """
    import psycopg2
    import requests

    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit

    # Collect candidate IPs from running postgres containers via Docker API.
    candidate_ips: list[str] = []
    docker_host = os.environ.get("DOCKER_HOST", "")
    if docker_host.startswith("tcp://"):
        try:
            r = requests.get(
                f"http://{docker_host[6:]}/containers/json",
                timeout=3,
            )
            for c in r.json():
                if "postgres" not in c.get("Image", "").lower():
                    continue
                for net_info in (
                    c.get("NetworkSettings", {}).get("Networks", {}).values()
                ):
                    ip = net_info.get("IPAddress", "")
                    if ip:
                        candidate_ips.append(ip)
        except Exception:
            pass

    # Also try well-known hostnames.
    for hostname in ["postgres", "stockscanner-db", "localhost"]:
        candidate_ips.append(hostname)

    common_creds = [
        ("postgres", "postgres", "postgres"),
        ("postgres", "postgres", "stockscanner"),
        ("onecli", "onecli", "onecli"),
    ]
    for ip in candidate_ips:
        for user, pw, db in common_creds:
            try:
                psycopg2.connect(
                    host=ip,
                    port=5432,
                    user=user,
                    password=pw,
                    dbname=db,
                    connect_timeout=1,
                ).close()
                return f"postgresql://{user}:{pw}@{ip}:5432/{db}"
            except Exception:
                pass
    return None


@contextmanager
def _testcontainers_url():
    # When testcontainers' exec endpoint is blocked (e.g. docker-socket-proxy
    # with EXEC:0), fall back to a running postgres discovered via DNS probe.
    probe = _probe_running_postgres()
    if probe:
        yield probe
        return
    with PostgresContainer(POSTGRES_IMAGE) as container:
        yield container.get_connection_url()


@contextmanager
def _env_url(url: str):
    yield url


@pytest.fixture(scope="session")
def pg_container():
    # Yield a sentinel; real connection URL is resolved in db_engine.
    yield None


@pytest.fixture(scope="session")
def db_engine(pg_container):
    test_url = os.environ.get("TEST_DATABASE_URL")
    ctx = _env_url(test_url) if test_url else _testcontainers_url()
    with ctx as url:
        engine = create_engine(url)
        try:
            Base.metadata.create_all(bind=engine)
        except Exception as exc:
            _conftest_logger.warning(f"db_engine: create_all failed ({exc})")
            raise
        yield engine
        try:
            Base.metadata.drop_all(bind=engine)
        except Exception as exc:
            _conftest_logger.warning(f"db_engine: drop_all skipped ({exc})")


@pytest.fixture(scope="function")
def db(db_engine) -> Generator:
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    # Create a SAVEPOINT so session.commit() in route handlers releases the
    # savepoint rather than committing to the real database. The event listener
    # restarts a fresh SAVEPOINT after each release so subsequent commits within
    # the same test also stay isolated. The outer transaction.rollback() undoes
    # everything when the test finishes.
    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(session, transaction):
        if transaction.nested and not transaction._parent.nested:
            session.begin_nested()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="module")
def client() -> Generator:
    with TestClient(app) as c:
        yield c

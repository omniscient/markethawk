import pytest
import logging as _logging
from typing import Generator
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from testcontainers.postgres import PostgresContainer

from app.core.database import Base, get_db
from app.main import app

_conftest_logger = _logging.getLogger(__name__)

POSTGRES_IMAGE = "postgres:15-alpine"


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer(POSTGRES_IMAGE) as container:
        yield container


@pytest.fixture(scope="session")
def db_engine(pg_container):
    url = pg_container.get_connection_url()
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

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="module")
def client() -> Generator:
    with TestClient(app) as c:
        yield c

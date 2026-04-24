
import pytest
import logging as _logging
from typing import Generator
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.core.config import settings

_conftest_logger = _logging.getLogger(__name__)

# Use an in-memory SQLite database for testing
# or a separate test database URL if preferred
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="session", autouse=True)
def db_engine():
    # Try to create tables, but don't fail if it doesn't work
    # (SQLite doesn't support JSONB, so skip for unit tests that mock dependencies)
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as exc:
        _conftest_logger.warning(f"db_engine: create_all skipped ({exc})")

    yield engine

    # Try to drop tables
    try:
        Base.metadata.drop_all(bind=engine)
    except Exception as exc:
        _conftest_logger.warning(f"db_engine: drop_all skipped ({exc})")

@pytest.fixture(scope="function")
def db() -> Generator:
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture(scope="module")
def client() -> Generator:
    with TestClient(app) as c:
        yield c

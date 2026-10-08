"""Shared test fixtures.

Sets up an isolated test environment:
  - In-memory SQLite database (fast, no disk I/O, auto-cleaned).
  - TestClient with dependency overrides for the DB session.
  - Temporary directory for generated certificates.

Every test gets a fresh database — no test pollution.
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.services.job_service import seed_default_templates
from app.config import settings


# Create an in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite:///./test_certificates.db"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    """Provide a test database session."""
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Create fresh tables before each test and drop them after.

    Also sets up a temp directory for generated certificates so tests
    don't pollute the real output directory.
    """
    # Monkeypatch SessionLocal so background tasks use the test database
    monkeypatch.setattr("app.services.job_service.SessionLocal", TestSessionLocal)
    monkeypatch.setattr("app.database.SessionLocal", TestSessionLocal)

    # Create tables
    Base.metadata.create_all(bind=test_engine)

    # Seed default templates
    db = TestSessionLocal()
    seed_default_templates(db)
    db.close()

    # Override certificates directory to use temp
    original_dir = settings.certificates_dir
    settings.certificates_dir = str(tmp_path / "certs")
    os.makedirs(settings.certificates_dir, exist_ok=True)

    yield

    # Cleanup
    settings.certificates_dir = original_dir
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def client():
    """Provide a FastAPI TestClient with the test DB."""
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def db_session():
    """Provide a raw database session for direct DB assertions."""
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def sample_recipients():
    """A standard list of valid recipients for testing."""
    return [
        {
            "name": "Alice Johnson",
            "email": "alice@example.com",
            "course_name": "Advanced Python",
            "date": "2024-12-15",
        },
        {
            "name": "Bob Smith",
            "email": "bob@example.com",
            "course_name": "Advanced Python",
            "date": "2024-12-15",
        },
        {
            "name": "Charlie Brown",
            "course_name": "Advanced Python",
            "date": "2024-12-15",
        },
    ]


@pytest.fixture()
def sample_job_payload(sample_recipients):
    """A complete valid job creation payload."""
    return {
        "recipients": sample_recipients,
        "template_id": "classic",
    }

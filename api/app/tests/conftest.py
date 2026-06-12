import os
from collections.abc import Generator

# Settings() runs at import time of app.core.config and requires these vars.
# CI has no .env, so seed defaults before any app.* import below.
_TEST_ENV_DEFAULTS = {
    "SECRET_KEY": "test-secret-key",
    "PROJECT_NAME": "alice-test",
    "POSTGRES_SERVER": "localhost",
    "POSTGRES_USER": "postgres",
    "HAYSTACK_INFERENCE_URL": "http://localhost:1416",
    "HAYSTACK_INGESTION_URL": "http://localhost:1416",
    "PII_FILTER_URL": "http://localhost:1417",
    "RABBITMQ_URL": "amqp://guest:guest@localhost:5672/",
    "MINIO_URL": "http://localhost:9000",
    "MINIO_ACCESS_KEY": "minioadmin",
    "MINIO_SECRET_KEY": "minioadmin",
    "MINIO_BUCKET_NAME": "test-bucket",
    "MINIO_REGION": "us-east-1",
}
for _k, _v in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_k, _v)

# No unit test should reach a real object store. Stub the Minio client before
# any storage-backed service is imported, so constructing a StorageManager
# (e.g. the module-level file_upload_manager singleton) never opens a socket.
from unittest.mock import MagicMock  # noqa: E402

import app.core.storage as _storage  # noqa: E402

_storage.Minio = MagicMock()

import pytest  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

from app.models.enums import UserRole  # noqa: E402
from app.models.tables import User  # noqa: E402


@pytest.fixture(scope="function")
def test_engine() -> Generator[Engine]:
    """Fresh in-memory database per test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db(test_engine: Engine) -> Generator[Session]:
    with Session(test_engine) as session:
        yield session


@pytest.fixture
def test_user(db: Session) -> User:
    user = User(
        email="test@example.com",
        is_active=True,
        role=UserRole.USER.value,
        name="Test User",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_user(db: Session) -> User:
    user = User(
        email="admin@example.com",
        is_active=True,
        role=UserRole.ADMIN.value,
        name="Admin User",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

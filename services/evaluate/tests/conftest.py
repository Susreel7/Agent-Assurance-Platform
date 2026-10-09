from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet

from evaluate.config import Settings, reset_settings_cache
from evaluate.migrations.runner import apply_migrations


@pytest.fixture(autouse=True)
def _reset_settings() -> None:
    reset_settings_cache()


@pytest.fixture(scope="session")
def fernet_key() -> str:
    return Fernet.generate_key().decode("ascii")


@pytest.fixture(scope="session")
def database_url() -> str:
    env = os.environ.get("EVALUATE_DATABASE_URL")
    if env:
        return env
    try:
        try:
            from testcontainers.community.postgres import PostgresContainer
        except ImportError:
            from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("set EVALUATE_DATABASE_URL or install testcontainers for integration tests")
        raise
    with PostgresContainer("postgres:16-alpine") as postgres:
        url = postgres.get_connection_url()
        yield url.replace("+psycopg2", "").replace("postgresql+psycopg2", "postgresql")


@pytest.fixture(scope="session")
def migrated_db(database_url: str) -> str:
    apply_migrations(database_url)
    return database_url


@pytest.fixture
def settings(migrated_db: str, fernet_key: str) -> Settings:
    return Settings(
        database_url=migrated_db,
        run_migrations_on_startup=False,
        internal_service_token="test-internal-token",
        encryption_keys_json=f'{{"local:default":"{fernet_key}"}}',
        default_encryption_key_ref="local:default",
        introspection_url="http://introspect.test/v1/workload-credentials/-/introspect",
        redis_enabled=False,
    )

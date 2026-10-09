"""Shared test fixtures.

The unit suite must not depend on the machine it runs on. `Settings` is a
`BaseSettings`, so it reads `AAP_*` environment variables and a `.env` file in addition
to whatever a test passes explicitly. That is right in production and wrong in a test:
exporting `AAP_DEV_AUTH_BYPASS=true` to talk to a local stack — the normal thing to do
while developing — made five config tests fail with errors that pointed at the code
rather than at the environment.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Callable, Iterator

import pytest

# Windows needs the selector loop for async Postgres: Python picks ProactorEventLoop
# there and psycopg refuses to run in async mode on it, so every database test errors
# before it starts.
#
# Defined only on Windows, and deliberately so. This was an `event_loop_policy` fixture
# that returned the default on other platforms, which reads as a harmless no-op but is
# not one: pytest-asyncio 1.4 deprecated overriding that fixture, `filterwarnings` in
# pyproject.toml turns DeprecationWarning into an error, and the override was therefore
# failing **331 unit tests** at setup on Linux — the platform every real run uses. The
# replacement hook cannot express "no opinion" either, because returning `None` from a
# registered implementation is a UsageError, so the implementation itself has to be
# absent rather than empty.
if sys.platform == "win32":

    def pytest_asyncio_loop_factories() -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
        return {"selector": asyncio.SelectorEventLoop}


@pytest.fixture(autouse=True)
def _isolate_settings_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Hide ambient deployment configuration from every test.

    Autouse and unconditional: a unit test that wants a setting should pass it, and one
    that does not should get the declared default rather than the developer's shell.
    """
    for name in list(os.environ):
        if name.startswith("AAP_") or name == "DATABASE_URL":
            monkeypatch.delenv(name, raising=False)
    yield

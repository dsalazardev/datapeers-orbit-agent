"""Shared pytest configuration.

Async tests use the anyio pytest plugin with the asyncio backend; no
pytest-asyncio dependency is needed (design D12).
"""

from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"

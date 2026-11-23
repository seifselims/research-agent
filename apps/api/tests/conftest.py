"""Shared pytest fixtures."""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.main import create_app


@pytest.fixture
def app() -> FastAPI:
    """A fresh app per test, so test-only routes added in one test don't leak into others."""
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client that calls the app in-process (no server or network needed)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

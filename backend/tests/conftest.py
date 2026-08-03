from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine

from aware_backend.config import get_settings
from aware_backend.db import get_db
from aware_backend.main import app

_settings = get_settings()
assert _settings.test_database_url, "AWARE_TEST_DATABASE_URL must be set to run tests"


@pytest.fixture
async def db_engine() -> AsyncGenerator[AsyncEngine]:
    # Created per-test (not module-level) so its pooled connections stay bound
    # to the event loop pytest-asyncio spins up for that test.
    engine = create_async_engine(_settings.test_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_connection(db_engine: AsyncEngine) -> AsyncGenerator[AsyncConnection]:
    async with db_engine.connect() as connection:
        yield connection


@pytest.fixture
async def db_session(db_connection: AsyncConnection) -> AsyncGenerator[AsyncSession]:
    transaction = await db_connection.begin()
    session = AsyncSession(
        bind=db_connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    async def _override_get_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()

from collections.abc import AsyncGenerator
from time import sleep

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.config import DATABASE_URL, DATABASE_SYNC_URL

# Async engine and session (for FastAPI request handling)
sql_async_engine = create_async_engine(DATABASE_URL, echo=False, future=True)
SqlAsyncSession = async_sessionmaker(sql_async_engine, expire_on_commit=False, class_=AsyncSession)


async def async_get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SqlAsyncSession() as session:
        yield session


# Sync engine (for Alembic migrations and startup checks)
sql_sync_engine = create_engine(
    url=DATABASE_SYNC_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SqlSyncSession = sessionmaker(bind=sql_sync_engine, expire_on_commit=False)


def wait_for_database(max_retries: int = 30, retry_delay: float = 1.0):
    """Wait for PostgreSQL database to become available."""
    for attempt in range(max_retries):
        try:
            with SqlSyncSession() as session:
                session.execute(text("SELECT 1"))
            return
        except OperationalError:
            if attempt % 10 == 0:
                print(f"[startup] Waiting for database... (attempt {attempt + 1})")
            if attempt < max_retries - 1:
                sleep(retry_delay)
            else:
                print("[startup] ERROR: Could not connect to database after retries.")
                exit(1)
        except Exception as e:
            print(f"[startup] Unexpected database error: {e}")
            exit(1)

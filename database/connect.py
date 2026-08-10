"""Модуль подключения базы данных."""
import os
from asyncio import current_task
from contextvars import ContextVar, Token
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

def _database_url() -> str:
    """Returns an async SQLAlchemy URL for SQLite (legacy) or PostgreSQL.

    DATABASE_URL takes precedence over DB_PATH. This lets the old production
    service keep running on SQLite until the final, reversible switch-over.
    """
    configured_url = os.getenv("DATABASE_URL", "").strip()
    if configured_url:
        if configured_url.startswith("postgres://"):
            return "postgresql+asyncpg://" + configured_url.removeprefix("postgres://")
        if configured_url.startswith("postgresql://"):
            return "postgresql+asyncpg://" + configured_url.removeprefix("postgresql://")
        return configured_url

    db_path = os.getenv("DB_PATH", "database/database.db")
    db_dir = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(db_dir, exist_ok=True)
    if os.path.isabs(db_path):
        return f"sqlite+aiosqlite:///{db_path}"
    return f"sqlite+aiosqlite:///./{db_path}"


DATABASE_URL = _database_url()
engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
Base = declarative_base()
SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
_request_session_scope: ContextVar[str | None] = ContextVar("request_session_scope", default=None)


def _session_scope() -> object:
    return _request_session_scope.get() or current_task()


def bind_request_session_scope() -> Token[str | None]:
    return _request_session_scope.set(uuid4().hex)


def reset_request_session_scope(token: Token[str | None]) -> None:
    _request_session_scope.reset(token)


Session = async_scoped_session(SessionFactory, scopefunc=_session_scope)
session = Session


async def rollback_session() -> None:
    """Откатывает текущую task-local сессию, если в ней есть активная транзакция."""
    try:
        if session.in_transaction():
            await session.rollback()
    except Exception:
        pass


async def remove_session() -> None:
    """Удаляет текущую task-local сессию из scoped registry."""
    try:
        await session.remove()
    except Exception:
        pass


async def close_db() -> None:
    """Закрывает глобальную сессию и engine при остановке приложения."""
    await remove_session()
    await engine.dispose()

"""Модуль подключения базы данных."""
import os
from asyncio import current_task
from contextvars import ContextVar, Token
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

def _database_url() -> str:
    """Возвращает обязательный URL рабочего PostgreSQL-подключения."""
    configured_url = os.getenv("DATABASE_URL", "").strip()
    if configured_url.startswith("postgres://"):
        configured_url = "postgresql+asyncpg://" + configured_url.removeprefix("postgres://")
    elif configured_url.startswith("postgresql://"):
        configured_url = "postgresql+asyncpg://" + configured_url.removeprefix("postgresql://")
    if not configured_url.startswith("postgresql+asyncpg://"):
        raise RuntimeError("DATABASE_URL должен содержать URL PostgreSQL с драйвером asyncpg")
    return configured_url


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

"""Модуль подключения базы данных."""
import os

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

db_path = os.getenv("DB_PATH", "database/database.db")

# Гарантируем наличие каталога для файла БД перед подключением.
db_dir = os.path.dirname(os.path.abspath(db_path))
os.makedirs(db_dir, exist_ok=True)

# Формируем корректный URL: если путь абсолютный, используем четыре слэша.
if os.path.isabs(db_path):
    __DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"
else:
    __DATABASE_URL = f"sqlite+aiosqlite:///./{db_path}"

engine = create_async_engine(__DATABASE_URL, echo=False)
Base = declarative_base()
Session = sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
session = Session()


async def close_db() -> None:
    """Закрывает глобальную сессию и engine при остановке приложения."""
    await session.close()
    await engine.dispose()

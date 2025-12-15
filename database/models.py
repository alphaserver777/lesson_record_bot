"""Модуль моделей с баз данных (основные таблицы студентов и записей)."""
from sqlalchemy import Column, ForeignKey
from sqlalchemy.types import Boolean, Date, Integer, String

from database.connect import Base


class RecordDate(Base):
    """Модель записей на даты/время."""

    __tablename__ = "record_dates"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, ForeignKey("student_profiles.telegram_id", ondelete="CASCADE"), nullable=True)
    record_date = Column(Date, nullable=False)
    hour = Column(Integer, nullable=False)
    minute = Column(Integer, nullable=False, default=0)
    duration_minutes = Column(Integer, nullable=False, default=60)
    event_id = Column(String(255), nullable=True)


class RegularLesson(Base):
    """Модель постоянных занятий (фиксированные слоты)."""

    __tablename__ = "regular_lessons"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, ForeignKey("student_profiles.telegram_id", ondelete="SET NULL"), nullable=True)
    full_name = Column(String(100), nullable=False)
    username = Column(String(100), nullable=True)
    cost = Column(Integer, nullable=True)
    # day_of_week: 0 - Monday, ... 6 - Sunday
    day_of_week = Column(Integer, nullable=True)
    lesson_date = Column(Date, nullable=True)  # legacy, можно не заполнять для еженедельных
    hour = Column(Integer, nullable=True)   # время начала
    minute = Column(Integer, nullable=True) # минуты начала
    duration_minutes = Column(Integer, nullable=False, default=60)


class StudentProfile(Base):
    """Дополнительная информация об ученике (основная таблица студентов)."""

    __tablename__ = "student_profiles"
    __table_args__ = {"extend_existing": True}

    telegram_id = Column(Integer, primary_key=True)
    full_name = Column(String(100), nullable=True)
    age = Column(Integer, nullable=True)
    price = Column(Integer, nullable=True)
    direction = Column(String(100), nullable=True)  # направление обучения
    goal = Column(String(255), nullable=True)       # цель обучения
    notes = Column(String(255), nullable=True)      # прочие заметки
    telephone = Column(String(20), nullable=True)
    blocked = Column(Boolean, default=False)
    last_visit_date = Column(String(50), nullable=True)

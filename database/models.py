"""Модели БД."""
from sqlalchemy import Column, ForeignKey
from sqlalchemy.types import Boolean, Date, Integer, String

from database.connect import Base


class RecordDate(Base):
    __tablename__ = "record_dates"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, ForeignKey("student_profiles.telegram_id", ondelete="CASCADE"), nullable=True)
    record_date = Column(Date, nullable=False)
    hour = Column(Integer, nullable=False)
    minute = Column(Integer, nullable=False, default=0)
    duration_minutes = Column(Integer, nullable=False, default=60)
    kind = Column(String(20), nullable=True, default="single")  # single/regular/block
    presence_status = Column(String(20), nullable=True)  # yes/no/pending
    presence_last_reminder = Column(String(50), nullable=True)
    presence_message_id = Column(Integer, nullable=True)
    note = Column(String(255), nullable=True)
    event_id = Column(String(255), nullable=True)
    booking_status = Column(String(20), nullable=False, default="approved")  # pending/approved/rejected
    approval_admin_id = Column(Integer, nullable=True)
    approval_updated_at = Column(String(50), nullable=True)


class RegularLesson(Base):
    __tablename__ = "regular_lessons"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, ForeignKey("student_profiles.telegram_id", ondelete="SET NULL"), nullable=True)
    full_name = Column(String(100), nullable=False)
    username = Column(String(100), nullable=True)
    cost = Column(Integer, nullable=True)
    day_of_week = Column(Integer, nullable=True)
    lesson_date = Column(Date, nullable=True)
    hour = Column(Integer, nullable=True)
    minute = Column(Integer, nullable=True)
    duration_minutes = Column(Integer, nullable=False, default=60)


class StudentProfile(Base):
    __tablename__ = "student_profiles"
    __table_args__ = {"extend_existing": True}

    telegram_id = Column(Integer, primary_key=True)
    full_name = Column(String(100), nullable=True)
    telegram_username = Column(String(100), nullable=True)
    age = Column(Integer, nullable=True)
    price = Column(Integer, nullable=True)
    direction = Column(String(100), nullable=True)
    goal = Column(String(255), nullable=True)
    notes = Column(String(255), nullable=True)
    telephone = Column(String(20), nullable=True)
    blocked = Column(Boolean, default=False)
    last_visit_date = Column(String(50), nullable=True)
    balance_lessons = Column(Integer, nullable=False, default=0)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, ForeignKey("student_profiles.telegram_id", ondelete="SET NULL"), nullable=True)
    full_name = Column(String(100), nullable=True)
    lesson_date = Column(Date, nullable=False)
    hour = Column(Integer, nullable=False)
    minute = Column(Integer, nullable=False, default=0)
    duration_minutes = Column(Integer, nullable=False, default=60)
    amount = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="paid")  # paid/unpaid
    created_at = Column(String(50), nullable=True)
    source = Column(String(50), nullable=True)  # balance/manual

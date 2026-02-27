"""Pydantic schemas for web API."""
from __future__ import annotations

from datetime import date
from pydantic import BaseModel, Field


class AuthIn(BaseModel):
    initData: str


class BookIn(BaseModel):
    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    duration: int = 60
    mode: str = "preset"


class CancelIn(BaseModel):
    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")


class SingleLessonIn(BaseModel):
    telegram_id: int
    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    duration: int = 60


class RegularLessonIn(BaseModel):
    telegram_id: int
    day_of_week: int = Field(ge=0, le=6)
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    duration: int = 60


class ManualPaymentIn(BaseModel):
    telegram_id: int
    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    amount: int = Field(ge=0)
    duration: int = 60


class BroadcastIn(BaseModel):
    message: str
    only_unpaid: bool = False


class AdminUserPatchIn(BaseModel):
    full_name: str | None = None
    telephone: str | None = None
    price: int | None = None
    balance_lessons_set: int | None = None
    balance_lessons_add: int | None = None
    blocked: bool | None = None

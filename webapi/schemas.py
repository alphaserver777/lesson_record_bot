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


class LessonCloseIn(BaseModel):
    telegram_id: int
    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    decision: str = Field(pattern=r"^(paid|unpaid|canceled)$")
    amount: int | None = Field(default=None, ge=0)
    duration: int = 60
    source: str = Field(default="manual", pattern=r"^(manual|balance)$")


class LessonCloseBulkItemIn(BaseModel):
    telegram_id: int
    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    duration: int = 60
    amount: int | None = Field(default=None, ge=0)


class LessonCloseBulkIn(BaseModel):
    items: list[LessonCloseBulkItemIn]
    decision: str = Field(pattern=r"^(paid|unpaid|canceled)$")


class BroadcastIn(BaseModel):
    message: str
    only_unpaid: bool = False


class AdminUserPatchIn(BaseModel):
    telegram_id_new: int | None = None
    merge_if_exists: bool = False
    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    telephone: str | None = None
    price: int | None = None
    balance_lessons_set: int | None = None
    balance_lessons_add: int | None = None
    blocked: bool | None = None


class UserProfileIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    telephone: str = Field(min_length=5, max_length=20)


class WorkIntervalIn(BaseModel):
    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{2}:\d{2}$")


class WorkDayIn(BaseModel):
    weekday: int = Field(ge=0, le=6)
    enabled: bool = True
    intervals: list[WorkIntervalIn] = Field(default_factory=list)


class WorkScheduleApplyPolicyIn(BaseModel):
    cancel_affected: bool = False
    date_from: date | None = None
    date_to: date | None = None


class WorkScheduleIn(BaseModel):
    days: list[WorkDayIn]
    apply_policy: WorkScheduleApplyPolicyIn | None = None


class WorkSchedulePreviewIn(BaseModel):
    days: list[WorkDayIn]
    date_from: date | None = None
    date_to: date | None = None


class WorkScheduleApplyIn(BaseModel):
    affected_ids: list[int]
    notify_users: bool = True
    reason: str | None = None

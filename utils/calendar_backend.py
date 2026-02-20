"""Локальный календарный backend (только БД, без внешних интеграций)."""
import datetime
import os
import uuid
from typing import Iterable, List, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from database.connect import session
from database.models import RecordDate, RegularLesson


class CalendarBackendError(Exception):
    """Ошибка локального календарного backend."""


def _local_event_id(kind: str) -> str:
    return f"local-{kind}-{uuid.uuid4().hex}"


def get_calendar_tz():
    tz_name = os.getenv("CALENDAR_TIMEZONE") or "UTC"
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


async def list_events(time_min: str, time_max: str) -> List[dict]:
    # В локальном backend внешнего календаря нет.
    _ = (time_min, time_max)
    return []


async def get_busy_intervals(target_date: datetime.date) -> List[Tuple[datetime.datetime, datetime.datetime]]:
    tz = get_calendar_tz()
    busy: list[tuple[datetime.datetime, datetime.datetime]] = []

    rows = await session.execute(
        select(RecordDate.hour, RecordDate.minute, RecordDate.duration_minutes, RecordDate.kind).where(
            RecordDate.record_date == target_date,
            RecordDate.kind != "allow",
        )
    )
    for row in rows:
        hour = int(row.hour or 0)
        minute = int(row.minute or 0)
        duration = int(row.duration_minutes or 60)
        kind = (row.kind or "").lower()
        if kind == "block" and hour == 0 and minute == 0:
            start = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=tz)
            end = start + datetime.timedelta(days=1)
            busy.append((start, end))
            continue
        start = datetime.datetime.combine(target_date, datetime.time(hour, minute), tzinfo=tz)
        end = start + datetime.timedelta(minutes=max(1, duration))
        busy.append((start, end))

    weekday = target_date.weekday()
    regulars = await session.execute(
        select(RegularLesson.hour, RegularLesson.minute, RegularLesson.duration_minutes).where(
            RegularLesson.day_of_week == weekday,
            RegularLesson.telegram_id.is_not(None),
        )
    )
    for row in regulars:
        hour = int(row.hour or 0)
        minute = int(row.minute or 0)
        duration = int(row.duration_minutes or 60)
        start = datetime.datetime.combine(target_date, datetime.time(hour, minute), tzinfo=tz)
        end = start + datetime.timedelta(minutes=max(1, duration))
        busy.append((start, end))

    uniq = {(s, e) for s, e in busy}
    return sorted(list(uniq), key=lambda x: x[0])


async def create_booking(
    contact,
    date: datetime.date,
    hour: int,
    minute: int = 0,
    duration_minutes: int = 60,
    record_id: int | None = None,
) -> str:
    _ = (contact, date, hour, minute, duration_minutes, record_id)
    return _local_event_id("single")


async def create_simple_event(
    date: datetime.date,
    hour: int,
    minute: int = 0,
    duration_minutes: int = 60,
    summary: str = "Запись",
    description: str | None = None,
    telegram_id: int | None = None,
    record_id: int | None = None,
    kind: str | None = None,
) -> str:
    _ = (date, hour, minute, duration_minutes, summary, description, telegram_id, record_id)
    return _local_event_id(kind or "single")


async def create_block_event(
    date: datetime.date,
    hour: int,
    minute: int,
    duration_minutes: int,
    note: str = "Зарезервировано",
) -> str:
    _ = (date, hour, minute, duration_minutes, note)
    return _local_event_id("block")


async def create_full_day_block_event(date: datetime.date, note: str = "Резерв администратора") -> str:
    _ = (date, note)
    return _local_event_id("full-day")


async def delete_events(event_ids: Iterable[str]) -> None:
    _ = event_ids
    return


async def delete_events_in_range(
    date: datetime.date,
    hour: int,
    minute: int,
    duration_minutes: int,
) -> None:
    _ = (date, hour, minute, duration_minutes)
    return

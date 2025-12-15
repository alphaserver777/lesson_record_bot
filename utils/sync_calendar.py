"""Синхронизация событий Google Calendar в БД."""
import asyncio
import datetime
from datetime import timezone
import logging
from typing import Tuple

from sqlalchemy import select, delete

from utils.google_calendar import list_events
from utils.misc.region_datetime import region_current_datetime
from database.models import RecordDate, RegularLesson
from database.connect import session
from utils.schedule import SLOT_DURATION_MINUTES

logger = logging.getLogger(__name__)


def _parse_dt(event_time: dict) -> datetime.datetime | None:
    dt_str = event_time.get("dateTime")
    if not dt_str:
        return None
    try:
        return datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except ValueError:
        return None


async def sync_calendar(days_ahead: int = 30) -> Tuple[int, int]:
    """
    Загружает события за ближайшие days_ahead дней.
    Повторяющиеся добавляем в regular_lessons (по дню недели/времени),
    одиночные — в record_dates (telegram_id пустой).
    Возвращает кортеж (count_regular, count_single).
    """
    utc_now = datetime.datetime.now(timezone.utc)
    time_min = utc_now.isoformat()
    time_max = (utc_now + datetime.timedelta(days=days_ahead)).isoformat()

    events = await list_events(time_min, time_max)
    reg_added = 0
    single_added = 0

    for event in events:
        start = _parse_dt(event.get("start", {}))
        end = _parse_dt(event.get("end", {}))
        if not start or not end:
            continue
        duration = int((end - start).total_seconds() // 60)
        duration = duration if duration > 0 else SLOT_DURATION_MINUTES

        if event.get("recurringEventId") or event.get("recurrence"):
            # регулярное событие
            day_of_week = start.weekday()
            hour = start.hour
            minute = start.minute
            summary = event.get("summary") or "Регулярное занятие"

            # ищем, есть ли такое же по времени; если нет — добавляем
            exists = await session.execute(
                select(RegularLesson).where(
                    RegularLesson.day_of_week == day_of_week,
                    RegularLesson.hour == hour,
                    RegularLesson.minute == minute,
                    RegularLesson.duration_minutes == duration,
                )
            )
            if exists.first():
                continue

            lesson = RegularLesson(
                telegram_id=None,
                full_name=summary,
                username=None,
                cost=None,
                day_of_week=day_of_week,
                lesson_date=None,
                hour=hour,
                minute=minute,
                duration_minutes=duration,
            )
            session.add(lesson)
            reg_added += 1
        else:
            # одиночное событие
            await session.execute(
                delete(RecordDate).where(RecordDate.event_id == event.get("id"))
            )
            record = RecordDate(
                telegram_id=None,
                record_date=start.date(),
                hour=start.hour,
                minute=start.minute,
                duration_minutes=duration,
                event_id=event.get("id"),
            )
            session.add(record)
            single_added += 1

    await session.commit()
    return reg_added, single_added

"""Синхронизация событий Google Calendar и БД."""
import datetime
import logging
from typing import Tuple

from sqlalchemy import delete, select

from utils.google_calendar import create_simple_event, get_calendar_tz, list_events
from database.models import RecordDate, RegularLesson
from database.connect import session
from utils.schedule import SLOT_DURATION_MINUTES

logger = logging.getLogger(__name__)


def _parse_dt(event_time: dict) -> datetime.datetime | None:
    dt_str = event_time.get("dateTime")
    date_only = event_time.get("date")
    if dt_str:
        try:
            return datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except ValueError:
            return None
    if date_only:
        try:
            return datetime.datetime.fromisoformat(date_only + "T00:00:00").replace(tzinfo=get_calendar_tz())
        except ValueError:
            return None
    return None


async def sync_calendar(days_ahead: int = 30) -> Tuple[int, int]:
    """
    Загружает события за ближайшие days_ahead дней.
    Повторяющиеся добавляем в regular_lessons (по дню недели/времени),
    одиночные — в record_dates (telegram_id пустой).
    Возвращает кортеж (count_regular, count_single).
    """
    now_tz = datetime.datetime.now(get_calendar_tz())
    time_min = now_tz.isoformat()
    time_max = (now_tz + datetime.timedelta(days=days_ahead)).isoformat()

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

        status = event.get("status")
        if status == "cancelled":
            continue

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


async def push_db_events_to_calendar(days_ahead: int = 30) -> int:
    """
    Создаёт в Google Calendar отсутствующие события на ближайшие days_ahead дней
    для записей без event_id (разовые и развёрнутые регулярные).
    Возвращает количество созданных событий.
    """
    created = 0
    today = datetime.datetime.now(get_calendar_tz()).date()
    max_date = today + datetime.timedelta(days=days_ahead)

    singles = await session.execute(
        select(RecordDate).where(
            RecordDate.event_id.is_(None),
            RecordDate.record_date >= today,
            RecordDate.record_date <= max_date,
        )
    )
    for rec in singles.scalars():
        try:
            event_id = await create_simple_event(
                rec.record_date,
                rec.hour,
                rec.minute,
                rec.duration_minutes,
                summary="Запись (ручная)",
            )
            rec.event_id = event_id
            created += 1
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Не удалось создать событие для записи %s: %s", rec.id, exc)

    regulars = await session.execute(select(RegularLesson))
    regulars = regulars.scalars().all()
    if regulars:
        day_iter = today
        while day_iter <= max_date:
            weekday = day_iter.weekday()
            for lesson in regulars:
                if lesson.day_of_week == weekday:
                    exists = await session.execute(
                        select(RecordDate).where(
                            RecordDate.record_date == day_iter,
                            RecordDate.hour == lesson.hour,
                            RecordDate.minute == lesson.minute,
                        )
                    )
                    if exists.first():
                        continue
                    try:
                        event_id = await create_simple_event(
                            day_iter,
                            lesson.hour or 0,
                            lesson.minute or 0,
                            lesson.duration_minutes or SLOT_DURATION_MINUTES,
                            summary=lesson.full_name or "Регулярное занятие",
                        )
                        rec = RecordDate(
                            telegram_id=lesson.telegram_id,
                            record_date=day_iter,
                            hour=lesson.hour or 0,
                            minute=lesson.minute or 0,
                            duration_minutes=lesson.duration_minutes or SLOT_DURATION_MINUTES,
                            event_id=event_id,
                        )
                        session.add(rec)
                        created += 1
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.warning("Не удалось создать событие для регулярки %s: %s", lesson.id, exc)
            day_iter += datetime.timedelta(days=1)

    await session.commit()
    return created

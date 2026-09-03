"""Генерация слотов по расписанию из PostgreSQL."""
import datetime
import threading
from typing import List, Tuple

from sqlalchemy import text

from database.connect import session

# День недели: 0 - Пн ... 6 - Вс
WEEK_SCHEDULE = {
    0: [("18:30", "23:00")],
    1: [("18:30", "23:00")],
    2: [("18:30", "23:00")],
    3: [("18:30", "23:00")],
    4: [("18:30", "23:00")],
    5: [("13:00", "22:00")],
    6: [("14:00", "21:00")],
}

# Длительность встречи и шаг выбора времени
SLOT_DURATION_MINUTES = 60
SLOT_STEP_MINUTES = 5

_CACHE_LOCK = threading.Lock()
_CACHE_MAP: dict[int, list[tuple[str, str]]] | None = None
_EXTRA_INTERVALS_CACHE: dict[datetime.date, list[tuple[str, str]]] = {}


def _parse_time(value: str) -> datetime.time:
    hour, minute = value.split(":")
    return datetime.time(int(hour), int(minute))


def _minutes_to_hhmm(total_minutes: int) -> str:
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


async def refresh_schedule_cache() -> None:
    """Refreshes synchronous slot-generator caches from the application DB.

    Slot generation is used by synchronous bot helpers. The in-process cache
    is refreshed at startup and after every admin change to availability.
    """
    global _CACHE_MAP, _EXTRA_INTERVALS_CACHE
    rows = await session.execute(
        text(
            "SELECT weekday, start_minute, end_minute FROM working_intervals "
            "WHERE is_active = :active ORDER BY weekday, start_minute, end_minute"
        ),
        {"active": True},
    )
    schedule_map: dict[int, list[tuple[str, str]]] = {}
    for row in rows:
        schedule_map.setdefault(int(row.weekday), []).append(
            (_minutes_to_hhmm(int(row.start_minute)), _minutes_to_hhmm(int(row.end_minute)))
        )

    override_rows = await session.execute(
        text(
            "SELECT target_date, start_minute, end_minute FROM date_availability_overrides "
            "WHERE mode = :mode ORDER BY target_date, start_minute, end_minute"
        ),
        {"mode": "extra_open"},
    )
    extras: dict[datetime.date, list[tuple[str, str]]] = {}
    for row in override_rows:
        target_date = row.target_date
        if isinstance(target_date, str):
            target_date = datetime.date.fromisoformat(target_date)
        extras.setdefault(target_date, []).append(
            (_minutes_to_hhmm(int(row.start_minute)), _minutes_to_hhmm(int(row.end_minute)))
        )

    with _CACHE_LOCK:
        _CACHE_MAP = schedule_map
        _EXTRA_INTERVALS_CACHE = extras


def _load_extra_open_intervals_for_date(target_date: datetime.date) -> list[tuple[str, str]]:
    return list(_EXTRA_INTERVALS_CACHE.get(target_date, []))


def _working_schedule_map() -> dict[int, list[tuple[str, str]]]:
    global _CACHE_MAP
    with _CACHE_LOCK:
        return _CACHE_MAP or {}


def get_working_intervals_for_weekday(weekday: int) -> list[tuple[str, str]]:
    dynamic = _working_schedule_map().get(weekday)
    if dynamic is not None:
        return dynamic
    return WEEK_SCHEDULE.get(weekday, [])


def get_working_intervals_for_date(target_date: datetime.date) -> list[tuple[str, str]]:
    base = list(get_working_intervals_for_weekday(target_date.weekday()))
    extra = _load_extra_open_intervals_for_date(target_date)
    merged = [*base, *extra]
    return sorted(merged, key=lambda item: item[0])


def slots_for_date(target_date: datetime.date, now_dt: datetime.datetime | None = None) -> List[Tuple[int, int]]:
    """Возвращает список доступных стартов слотов (hour, minute) на дату по расписанию."""
    day_schedule = get_working_intervals_for_date(target_date)
    if not day_schedule:
        return []

    slots: List[Tuple[int, int]] = []
    for start_str, end_str in day_schedule:
        start_time = _parse_time(start_str)
        end_time = _parse_time(end_str)
        start_dt = datetime.datetime.combine(target_date, start_time)
        end_dt = datetime.datetime.combine(target_date, end_time)

        current = start_dt
        while current + datetime.timedelta(minutes=SLOT_DURATION_MINUTES) <= end_dt:
            slots.append((current.hour, current.minute))
            current += datetime.timedelta(minutes=SLOT_STEP_MINUTES)

    if now_dt and now_dt.date() == target_date:
        slots = [(h, m) for h, m in slots if datetime.datetime.combine(target_date, datetime.time(h, m)) > now_dt]

    return sorted(set(slots), key=lambda item: (item[0], item[1]))


def format_slot(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def is_time_in_schedule(
    target_date: datetime.date,
    hour: int,
    minute: int,
    duration_minutes: int = SLOT_DURATION_MINUTES,
) -> bool:
    """Проверяет, попадает ли слот в доступные интервалы дня."""
    day_schedule = get_working_intervals_for_date(target_date)
    if not day_schedule:
        return False

    start_candidate = datetime.datetime.combine(target_date, datetime.time(hour, minute))
    end_candidate = start_candidate + datetime.timedelta(minutes=duration_minutes)

    for start_str, end_str in day_schedule:
        interval_start = datetime.datetime.combine(target_date, _parse_time(start_str))
        interval_end = datetime.datetime.combine(target_date, _parse_time(end_str))
        if interval_start <= start_candidate and end_candidate <= interval_end:
            return True
    return False

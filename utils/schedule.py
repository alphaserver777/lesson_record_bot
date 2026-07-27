"""Генерация слотов по недельному расписанию (динамически из БД + fallback)."""
import datetime
import logging
import os
import sqlite3
import threading
import time
from typing import List, Tuple

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

_CACHE_TTL_SEC = 45
_CACHE_LOCK = threading.Lock()
_CACHE_TS = 0.0
_CACHE_MAP: dict[int, list[tuple[str, str]]] | None = None
logger = logging.getLogger(__name__)


def _parse_time(value: str) -> datetime.time:
    hour, minute = value.split(":")
    return datetime.time(int(hour), int(minute))


def _minutes_to_hhmm(total_minutes: int) -> str:
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _resolve_db_path() -> str:
    db_path = os.getenv("DB_PATH", "database/database.db")
    if os.path.isabs(db_path):
        return db_path
    return os.path.abspath(db_path)


def _load_schedule_from_db() -> dict[int, list[tuple[str, str]]]:
    path = _resolve_db_path()
    if not os.path.exists(path):
        return {}
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='working_intervals'"
        )
        if not cur.fetchone():
            return {}

        cur.execute(
            "SELECT weekday, start_minute, end_minute "
            "FROM working_intervals "
            "WHERE is_active = 1 "
            "ORDER BY weekday, start_minute, end_minute"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    schedule_map: dict[int, list[tuple[str, str]]] = {}
    for weekday, start_minute, end_minute in rows:
        day = int(weekday)
        start = _minutes_to_hhmm(int(start_minute))
        end = _minutes_to_hhmm(int(end_minute))
        schedule_map.setdefault(day, []).append((start, end))
    return schedule_map


def _load_extra_open_intervals_for_date(target_date: datetime.date) -> list[tuple[str, str]]:
    path = _resolve_db_path()
    if not os.path.exists(path):
        return []
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='date_availability_overrides'"
        )
        if not cur.fetchone():
            return []

        cur.execute(
            "SELECT start_minute, end_minute "
            "FROM date_availability_overrides "
            "WHERE target_date = ? AND mode = 'extra_open' "
            "ORDER BY start_minute, end_minute",
            (target_date.isoformat(),),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    return [(_minutes_to_hhmm(int(start_minute)), _minutes_to_hhmm(int(end_minute))) for start_minute, end_minute in rows]


def _working_schedule_map() -> dict[int, list[tuple[str, str]]]:
    global _CACHE_TS, _CACHE_MAP
    now = time.time()
    with _CACHE_LOCK:
        if _CACHE_MAP is not None and (now - _CACHE_TS) < _CACHE_TTL_SEC:
            return _CACHE_MAP
        try:
            loaded = _load_schedule_from_db()
            _CACHE_MAP = loaded if loaded else {}
            _CACHE_TS = now
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("failed to load working schedule from db, fallback to static: %s", exc)
            _CACHE_MAP = {}
            _CACHE_TS = now
        return _CACHE_MAP


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

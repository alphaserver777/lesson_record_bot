"""Генерация слотов по недельному расписанию."""
import datetime
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
SLOT_STEP_MINUTES = 10


def _parse_time(value: str) -> datetime.time:
    hour, minute = value.split(":")
    return datetime.time(int(hour), int(minute))


def slots_for_date(target_date: datetime.date, now_dt: datetime.datetime | None = None) -> List[Tuple[int, int]]:
    """Возвращает список доступных стартов слотов (hour, minute) на дату по расписанию."""
    day_schedule = WEEK_SCHEDULE.get(target_date.weekday(), [])
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

    return slots


def format_slot(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"

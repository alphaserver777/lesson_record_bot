"""Утилита для названия дня недели (рус)."""
from datetime import date


def weekday_name(value):
    """
    Принимает date или номер дня недели (0=Пн ... 6=Вс).
    Возвращает строку с названием на русском.
    """
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    if isinstance(value, int):
        idx = value
    elif isinstance(value, date):
        idx = value.weekday()
    else:
        return "День"
    try:
        return days[idx]
    except Exception:
        return "День"

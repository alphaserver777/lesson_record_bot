"""Модуль создания клавиатуры календаря."""
import calendar
import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import transactions

from utils.calendar_backend import CalendarBackendError, get_busy_intervals, get_calendar_tz
from utils.misc.weekend_reservations import ListWeekends
from utils.schedule import SLOT_DURATION_MINUTES, slots_for_date

NAMES_DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Суб", "Вск")
NAMES_MONTH = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}


def _slot_is_busy(busy_intervals, date_obj: datetime.date, hour: int, minute: int) -> bool:
    slot_start = datetime.datetime.combine(date_obj, datetime.time(hour, minute), tzinfo=get_calendar_tz())
    slot_end = slot_start + datetime.timedelta(minutes=SLOT_DURATION_MINUTES)
    for start, end in busy_intervals:
        if slot_start < end and slot_end > start:
            return True
    return False


def _strike(text: str) -> str:
    """Возвращает строку с перечеркиванием символов."""
    return "".join(ch + "\u0336" for ch in text)


def _underline(text: str) -> str:
    """Возвращает строку с подчёркиванием символов."""
    return "".join(ch + "\u0332" for ch in text)


async def _day_marker(date_obj: datetime.date) -> tuple[str, str]:
    """Возвращает (текст_кнопки, callback_data) с пометкой занятости."""
    slots = slots_for_date(date_obj)
    if not slots:
        return _strike(str(date_obj.day)), "ignore"

    if await transactions.is_day_reserved(date_obj):
        return _strike(str(date_obj.day)), "ignore"

    try:
        busy_intervals = await get_busy_intervals(date_obj)
    except CalendarBackendError:
        return _strike(str(date_obj.day)), "ignore"

    free_slots = 0
    for hour, minute in slots:
        if not _slot_is_busy(busy_intervals, date_obj, hour, minute):
            free_slots += 1

    if free_slots == 0:
        return _strike(str(date_obj.day)), "ignore"
    if free_slots <= 2:
        text = _underline(str(date_obj.day))
        return text, f"calendar_day_{date_obj}"
    return str(date_obj.day), f"calendar_day_{date_obj}"


async def calendar_buttons(date: datetime, action: str) -> InlineKeyboardBuilder:
    """
    Функция создания клавиатуры календаря.
    :return: InlineKeyboardMarkup
    """
    keyboard_builder = InlineKeyboardBuilder()

    if action == "del_all_record_day_2":
        action += "="

    current_datetime = datetime.datetime.now()
    year_month = f"{date.year} {NAMES_MONTH[date.month]}"

    text_btn = (
        ("🎉🎁🎉", "ignore")
        if date.month == current_datetime.month and date.year == current_datetime.year
        else ("<--", f"calendar_change_month=down={date}={action}"),

        (year_month, "ignore"),
        ("-->", f"calendar_change_month=up={date}={action}"),
    )

    for text in text_btn:
        keyboard_builder.button(text=text[0], callback_data=text[1])

    for day in NAMES_DAYS:
        keyboard_builder.button(text=day, callback_data="ignore")

    obj = calendar.Calendar()

    weekends_obj = ListWeekends()
    list_weekends = await weekends_obj.get_list_weekends()

    btns = []

    today = datetime.date.today()
    for week in obj.monthdayscalendar(date.year, date.month):
        for day_num in week:
            if day_num == 0:
                btns.append(InlineKeyboardButton(text="-", callback_data="ignore"))
                continue

            current_date = date.replace(day=day_num)
            if current_date < today:
                btns.append(InlineKeyboardButton(text="-", callback_data="ignore"))
                continue

            if action == "calendar_day":
                text, callback_data = await _day_marker(current_date)
                btns.append(InlineKeyboardButton(text=text, callback_data=callback_data))
            else:
                callback_data = f"{action}_{current_date}"
                if current_date.weekday() in list_weekends and action == "calendar_day":
                    btns.append(InlineKeyboardButton(text="вых", callback_data="weekend"))
                else:
                    btns.append(InlineKeyboardButton(text=str(day_num), callback_data=callback_data))

    keyboard_builder.row(*btns, width=7)

    add_count_btn = 7 - len(keyboard_builder.__dict__["_markup"][-1])
    for _ in range(add_count_btn):
        keyboard_builder.button(text="-", callback_data="ignore")

    return keyboard_builder

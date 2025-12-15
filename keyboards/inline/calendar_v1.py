"""Модуль создания клавиатуры календаря."""
import calendar
import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.google_calendar import GoogleCalendarError, get_busy_intervals, get_calendar_tz
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


async def _day_marker(date_obj: datetime.date) -> tuple[str, str]:
    """Возвращает (текст_кнопки, callback_data) с пометкой занятости."""
    slots = slots_for_date(date_obj)
    if not slots:
        return f"⛔{date_obj.day}", "ignore"

    try:
        busy_intervals = await get_busy_intervals(date_obj)
    except GoogleCalendarError:
        return f"❓{date_obj.day}", "ignore"

    free_slots = 0
    for hour, minute in slots:
        if not _slot_is_busy(busy_intervals, date_obj, hour, minute):
            free_slots += 1

    if free_slots == 0:
        mark = "❌"
        callback = "ignore"
    elif free_slots <= 2:
        mark = "⚠️"
        callback = None
    else:
        mark = "✅"
        callback = None

    text = f"{mark}{date_obj.day}"
    if callback is None:
        callback = f"calendar_day_{date_obj}"
    return text, callback


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

    btns = [InlineKeyboardButton(text="-", callback_data="ignore") for _ in range(date.weekday())]

    day_ind = 1
    for day_num in obj.itermonthdays(date.year, date.month):
        if day_num >= date.day:
            current_date = date.replace(day=day_num)
            if action == "calendar_day":
                text, callback_data = await _day_marker(current_date)
                btns.append(InlineKeyboardButton(text=text, callback_data=callback_data))
            else:
                callback_data = f"{action}_{current_date}"
                # старое поведение пометки выходных для админских действий
                if day_ind in list_weekends and action == "calendar_day":
                    btns.append(InlineKeyboardButton(text="вых", callback_data="weekend"))
                else:
                    btns.append(InlineKeyboardButton(text=str(day_num), callback_data=callback_data))

        if day_ind == 7:
            day_ind = 0
        day_ind += 1

    keyboard_builder.row(*btns, width=7)

    add_count_btn = 7 - len(keyboard_builder.__dict__["_markup"][-1])
    for _ in range(add_count_btn):
        keyboard_builder.button(text="-", callback_data="ignore")

    return keyboard_builder

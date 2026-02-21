"""Новый namespaced календарь и выбор слотов для админских сценариев."""
import calendar
import datetime

from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.calendar_backend import get_busy_intervals, get_calendar_tz
from utils.schedule import SLOT_DURATION_MINUTES, slots_for_date


def _slot_busy(intervals, date_obj: datetime.date, hour: int, minute: int) -> bool:
    start = datetime.datetime.combine(date_obj, datetime.time(hour, minute), tzinfo=get_calendar_tz())
    end = start + datetime.timedelta(minutes=SLOT_DURATION_MINUTES)
    return any(start < busy_end and end > busy_start for busy_start, busy_end in intervals)


async def namespaced_month_calendar(context: str, view_date: datetime.date) -> types.InlineKeyboardMarkup:
    month_start = view_date.replace(day=1)
    prev_month = (month_start - datetime.timedelta(days=1)).replace(day=1)
    next_month = (month_start + datetime.timedelta(days=32)).replace(day=1)
    today = datetime.date.today()

    kb = InlineKeyboardBuilder()
    kb.row(
        types.InlineKeyboardButton(
            text="⬅️",
            callback_data=f"calendar:month:prev:{context}:{prev_month.strftime('%Y-%m')}",
        ),
        types.InlineKeyboardButton(text=month_start.strftime("%m.%Y"), callback_data="ignore"),
        types.InlineKeyboardButton(
            text="➡️",
            callback_data=f"calendar:month:next:{context}:{next_month.strftime('%Y-%m')}",
        ),
    )
    for w in ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"):
        kb.button(text=w, callback_data="ignore")
    kb.adjust(3, 7)

    cal = calendar.Calendar(firstweekday=0)
    for week in cal.monthdayscalendar(month_start.year, month_start.month):
        row = []
        for day in week:
            if day == 0:
                row.append(types.InlineKeyboardButton(text=" ", callback_data="ignore"))
                continue
            d = month_start.replace(day=day)
            if d < today:
                row.append(types.InlineKeyboardButton(text=f"·{day}", callback_data="ignore"))
            else:
                row.append(
                    types.InlineKeyboardButton(
                        text=str(day),
                        callback_data=f"calendar:day:{context}:{d.isoformat()}",
                    )
                )
        kb.row(*row)

    kb.row(types.InlineKeyboardButton(text="⬅️ В dashboard", callback_data="admin:menu"))
    return kb.as_markup()


async def slot_picker(date_obj: datetime.date, context: str) -> types.InlineKeyboardMarkup:
    now_local = datetime.datetime.now(get_calendar_tz()).replace(tzinfo=None)
    slots = slots_for_date(date_obj, now_local)
    busy = await get_busy_intervals(date_obj)

    kb = InlineKeyboardBuilder()
    for hour, minute in slots:
        text = f"{hour:02d}:{minute:02d}"
        if _slot_busy(busy, date_obj, hour, minute):
            kb.button(text=f"⛔ {text}", callback_data="ignore")
        else:
            kb.button(text=f"✅ {text}", callback_data=f"slot:pick:{context}:{date_obj.isoformat()}:{hour:02d}:{minute:02d}")
    kb.adjust(3)
    kb.row(types.InlineKeyboardButton(text="⬅️ В dashboard", callback_data="admin:menu"))
    return kb.as_markup()


def regular_weekday_kb(telegram_id: int) -> types.InlineKeyboardMarkup:
    days = [
        ("Пн", 0),
        ("Вт", 1),
        ("Ср", 2),
        ("Чт", 3),
        ("Пт", 4),
        ("Сб", 5),
        ("Вс", 6),
    ]
    kb = InlineKeyboardBuilder()
    for name, idx in days:
        kb.button(text=name, callback_data=f"admin:lesson:add_regular_day:{telegram_id}:{idx}")
    kb.adjust(4)
    kb.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin:user:{telegram_id}:1"))
    return kb.as_markup()


def regular_time_kb(telegram_id: int, day_of_week: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for h in range(9, 21):
        kb.button(text=f"{h:02d}:00", callback_data=f"admin:lesson:add_regular_time:{telegram_id}:{day_of_week}:{h:02d}:00")
    kb.adjust(4)
    kb.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin:lesson:add_regular:{telegram_id}"))
    return kb.as_markup()


def regular_duration_kb(telegram_id: int, day_of_week: int, hh: int, mm: int) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="60 мин",
                    callback_data=f"admin:lesson:add_regular_save:{telegram_id}:{day_of_week}:{hh:02d}:{mm:02d}:60",
                ),
                types.InlineKeyboardButton(
                    text="90 мин",
                    callback_data=f"admin:lesson:add_regular_save:{telegram_id}:{day_of_week}:{hh:02d}:{mm:02d}:90",
                ),
            ],
            [types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin:lesson:add_regular_day:{telegram_id}:{day_of_week}")],
        ]
    )

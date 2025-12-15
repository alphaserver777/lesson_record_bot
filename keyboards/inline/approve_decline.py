"""Клавиатура для согласования/аннулирования записи админом."""
import datetime

from aiogram.utils.keyboard import InlineKeyboardBuilder


def approve_decline_kb(user_id: int, date: datetime.date, hour: int, minute: int):
    builder = InlineKeyboardBuilder()
    date_str = date.isoformat()
    time_str = f"{hour:02d}_{minute:02d}"
    builder.button(
        text="✅ Согласовать",
        callback_data=f"approve_rec={user_id}={date_str}={time_str}",
    )
    builder.button(
        text="❌ Аннулировать",
        callback_data=f"cancel_rec={user_id}={date_str}={time_str}",
    )
    builder.adjust(2)
    return builder.as_markup()

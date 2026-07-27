"""Клавиатура подтверждения присутствия."""
from aiogram.utils.keyboard import InlineKeyboardBuilder


def presence_confirm_kb(date_str: str, time_str: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтверждаю", callback_data=f"presence_yes={date_str}={time_str}")
    builder.button(text="❌ Не смогу прийти", callback_data=f"presence_no={date_str}={time_str}")
    builder.adjust(1)
    return builder.as_markup()


def presence_cancel_confirm_kb(date_str: str, time_str: str):
    """Кнопки окончательного подтверждения отмены занятия."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, отменить занятие", callback_data=f"presence_cancel_yes={date_str}={time_str}")
    builder.button(text="Нет, оставить занятие", callback_data=f"presence_cancel_no={date_str}={time_str}")
    builder.adjust(1)
    return builder.as_markup()

"""Модуль создания клавиатуры."""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_buttons() -> InlineKeyboardMarkup:
    """
    Функция создания клавиатуры для главного админ меню.
    :return: InlineKeyboardMarkup
    """
    keyboard_builder = InlineKeyboardBuilder()
    keyboard_builder.button(text="👥 Пользователи", callback_data="admin:users:list:1")
    keyboard_builder.button(text="📚 Занятия", callback_data="admin:lessons:menu")
    keyboard_builder.button(text="🗓️ Расписание", callback_data="admin:schedule:menu")
    keyboard_builder.button(text="Вернуться к календарю", callback_data="start_command=calendar_day")
    keyboard_builder.adjust(1)
    return keyboard_builder.as_markup()

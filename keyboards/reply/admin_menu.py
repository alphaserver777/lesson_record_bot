"""Постоянная кнопка для быстрого входа в админ-меню."""
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def admin_reply_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="Админ меню")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

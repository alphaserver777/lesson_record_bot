"""Запуск синхронизации календаря (двусторонней)."""
from aiogram import types
from aiogram.exceptions import TelegramBadRequest

from keyboards.inline.back_admin_menu import back_admin_menu_button
from utils.sync_calendar import push_db_events_to_calendar, sync_calendar


async def sync_calendar_handler(callback: types.CallbackQuery):
    # Односторонняя синхронизация: из БД в календарь
    created = await push_db_events_to_calendar(days_ahead=30)
    kb = back_admin_menu_button()
    await callback.message.answer(
        f"Выгрузка завершена.\n"
        f"Выгружено из БД в календарь: создано {created} событий.",
        reply_markup=kb,
    )
    try:
        await callback.answer()
    except TelegramBadRequest:
        # Игнорируем, если callback устарел
        pass

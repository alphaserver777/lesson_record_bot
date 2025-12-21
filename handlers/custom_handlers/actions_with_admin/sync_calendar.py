"""Запуск синхронизации календаря (двусторонней)."""
from aiogram import types

from keyboards.inline.back_admin_menu import back_admin_menu_button
from utils.sync_calendar import push_db_events_to_calendar, sync_calendar


async def sync_calendar_handler(callback: types.CallbackQuery):
    reg, single = await sync_calendar(days_ahead=30)
    created = await push_db_events_to_calendar(days_ahead=30)
    kb = back_admin_menu_button()
    await callback.message.answer(
        f"Синхронизация завершена.\n"
        f"Импортировано из календаря: регулярных {reg}, разовых {single}.\n"
        f"Выгружено из БД в календарь: создано {created} событий.",
        reply_markup=kb,
    )
    await callback.answer()

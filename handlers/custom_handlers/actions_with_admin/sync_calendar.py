"""Запуск синхронизации календаря."""
from aiogram import types

from keyboards.inline.back_admin_menu import back_admin_menu_button
from utils.sync_calendar import sync_calendar


async def sync_calendar_handler(callback: types.CallbackQuery):
    reg, single = await sync_calendar(days_ahead=30)
    kb = back_admin_menu_button()
    await callback.message.answer(
        f"Синхронизация завершена.\nРегулярных добавлено: {reg}\nРазовых добавлено: {single}",
        reply_markup=kb,
    )
    await callback.answer()

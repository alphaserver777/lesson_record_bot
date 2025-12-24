"""Модуль админ меню."""
from aiogram import types
from aiogram.fsm.context import FSMContext

from config_data.config import ADMINS_TELEGRAM_ID
from keyboards.inline.admin_buttons import admin_buttons


async def admin_menu(
    message: [types.CallbackQuery, types.Message], state: FSMContext
) -> None:
    """
    Выводит клавиатуру админ меню (доступно только администраторам).
    """
    user_id = message.from_user.id if isinstance(message, types.Message) else message.from_user.id
    if user_id not in ADMINS_TELEGRAM_ID:
        if isinstance(message, types.CallbackQuery):
            await message.answer("Нет доступа", show_alert=True)
        else:
            await message.answer("Нет доступа")
        return

    kb = admin_buttons()
    target = message.message if isinstance(message, types.CallbackQuery) else message
    await target.answer("Выберите действие:", reply_markup=kb)
    await state.clear()
    if isinstance(message, types.CallbackQuery):
        await message.message.delete()

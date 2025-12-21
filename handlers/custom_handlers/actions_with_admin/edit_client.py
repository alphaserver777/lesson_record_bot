"""Редактирование данных студента администратором."""
from aiogram import types
from aiogram.fsm.context import FSMContext

from database import transactions
from keyboards.inline.back_admin_menu import back_admin_menu_button
from states.states import AdminEditState


async def edit_client_menu(callback: types.CallbackQuery, state: FSMContext):
    telegram_id = int(callback.data.split("=")[1])
    await state.update_data(edit_telegram_id=telegram_id)
    kb = back_admin_menu_button()
    text = (
        "Что изменить?\n"
        "1) Цена за занятие — отправьте число.\n"
        "2) Баланс занятий — отправьте целое число (установить).\n\n"
        "Выберите действие:"
    )
    await callback.message.answer(
        text,
        reply_markup=kb
    )
    await callback.message.answer(
        "Изменить цену?", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Изменить цену", callback_data=f"edit_price={telegram_id}")],
            [types.InlineKeyboardButton(text="Изменить баланс", callback_data=f"edit_balance={telegram_id}")]
        ])
    )
    await callback.answer()


async def edit_price_start(callback: types.CallbackQuery, state: FSMContext):
    telegram_id = int(callback.data.split("=")[1])
    await state.update_data(edit_telegram_id=telegram_id)
    await callback.message.answer("Введите новую цену за занятие (число):")
    await state.set_state(AdminEditState.edit_price)
    await callback.answer()


async def edit_price_set(message: types.Message, state: FSMContext):
    try:
        price = int(message.text.strip())
        if price < 0:
            raise ValueError
    except Exception:
        await message.answer("Нужно число (>=0). Попробуйте ещё раз.")
        return
    data = await state.get_data()
    telegram_id = data.get("edit_telegram_id")
    await transactions.upsert_student_profile(telegram_id=telegram_id, price=price)
    await message.answer(f"Цена обновлена: {price} ₽")
    await state.clear()


async def edit_balance_start(callback: types.CallbackQuery, state: FSMContext):
    telegram_id = int(callback.data.split("=")[1])
    await state.update_data(edit_telegram_id=telegram_id)
    await callback.message.answer("Введите новый баланс уроков (целое число):")
    await state.set_state(AdminEditState.edit_balance)
    await callback.answer()


async def edit_balance_set(message: types.Message, state: FSMContext):
    try:
        balance = int(message.text.strip())
    except Exception:
        await message.answer("Нужно целое число. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    telegram_id = data.get("edit_telegram_id")
    await transactions.set_balance(telegram_id, balance)
    await message.answer(f"Баланс обновлён: {balance}")
    await state.clear()

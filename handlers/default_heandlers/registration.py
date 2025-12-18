"""Регистрация нового пользователя."""
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove
from aiogram.filters import CommandStart
from aiogram import F

from database import transactions
from keyboards.reply.phone_request import contact_button
from states.states import RegistrationState
from handlers.default_heandlers.start import start_command
from handlers.custom_handlers.actions_with_admin.set_price import request_price_for_student
from config_data.config import ADMINS_TELEGRAM_ID


async def registration_full_name(message: types.Message, state: FSMContext):
    full_name = message.text.strip()
    if not full_name:
        await message.answer("Введите фамилию и имя.")
        return
    await state.update_data(full_name=full_name)
    await message.answer("Укажите ваш возраст (числом).")
    await state.set_state(RegistrationState.age)


async def registration_age(message: types.Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if age <= 0 or age > 120:
            raise ValueError
    except ValueError:
        await message.answer("Введите возраст числом.")
        return

    await state.update_data(age=age)
    kb = await contact_button()
    await message.answer("Отправьте свой номер, нажав на кнопку ниже.", reply_markup=kb)
    await state.set_state(RegistrationState.phone)


async def registration_phone(message: types.Message, state: FSMContext):
    contact = message.contact
    if not contact or not contact.phone_number:
        await message.answer("Нужно отправить контакт через кнопку ниже.")
        kb = await contact_button()
        await message.answer("Отправьте свой номер, нажав на кнопку ниже.", reply_markup=kb)
        return

    data = await state.get_data()
    full_name = data.get("full_name")
    age = data.get("age")
    telegram_id = contact.user_id
    username = message.from_user.username

    # Создаём пользователя и профиль
    await transactions.add_user(telegram_id, full_name)
    await transactions.update_phone(telegram_id, contact.phone_number)
    await transactions.upsert_student_profile(
        telegram_id=telegram_id,
        full_name=full_name,
        age=age,
    )
    await transactions.update_visit_date(telegram_id)

    # Уведомляем администраторов и просим указать стоимость
    if ADMINS_TELEGRAM_ID:
        await request_price_for_student(full_name, telegram_id, username)

    await state.clear()
    await message.answer("Спасибо, регистрация завершена. Можно выбирать время записи.", reply_markup=ReplyKeyboardRemove())
    await start_command(message, state)

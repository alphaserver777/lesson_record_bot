"""Модуль обработки удаление записи."""
import datetime

from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove

from database import transactions
from handlers.default_heandlers.start import start_command
from keyboards.reply.list_button import list_button
from states.states import ServiceDateState


async def delete_recordings_1(
    message: [types.CallbackQuery, types.Message], state: FSMContext
):
    """Функция delete_recordings_1. Ожидает подтверждения на удаление записи."""
    input_text = message.text
    if "Вернуться" in input_text or "Записей ещё нет" in input_text:
        await state.clear()
        await start_command(message, state)
    else:
        split_text = input_text.split()
        time_parts = split_text[2].split(":")
        hour = int(time_parts[0])
        minute = int(time_parts[1]) if len(time_parts) > 1 else 0
        date = split_text[0].split("-")
        date = date[::-1]
        date = "-".join(date)
        date = datetime.datetime.strptime(date, '%Y-%m-%d')
        date = date.date()

        await state.update_data(
            {
                "date": date,
                "hour": hour,
                "minute": minute,
            }
        )

        for_btn = [(0, "Удалить"), (0, "Вернуться")]
        kb = list_button(for_btn)
        await message.answer("Точно удаляю?", reply_markup=kb)
        await state.set_state(ServiceDateState.service_delete_conf)


async def delete_recordings_2(
    message: [types.CallbackQuery, types.Message], state: FSMContext
):
    """Функция delete_recordings_2. Удаляет запись."""
    input_text = message.text

    if "Вернуться" in input_text:
        await state.clear()
        await start_command(message, state)
    else:
        context_data = await state.get_data()
        date, hour, minute = context_data.get("date"), context_data.get("hour"), context_data.get("minute")
        await transactions.del_record(date, hour, minute)

        await message.answer("Запись удалена.", reply_markup=ReplyKeyboardRemove())
        await state.clear()
        await start_command(message, state)

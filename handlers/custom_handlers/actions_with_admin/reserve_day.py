"""Модуль резервирования дня."""
import datetime

from aiogram import types
from aiogram.fsm.context import FSMContext

from config_data import config
from database import transactions
from keyboards.inline.back_admin_menu import back_admin_menu_button
from keyboards.inline.calendar_v1 import calendar_buttons
from loader import bot
from states.states import AdminReserve


async def reserve_day_1(message: [types.CallbackQuery, types.Message]):
    """
    Функция reserve_day_1. Коллбэк с датой reserve_day запускает данную функцию.
    выводит календарь.
    """
    current_date = datetime.date.today()
    callback_data = "reserve_day_2"
    telegram_id = message.from_user.id

    kb = await calendar_buttons(current_date, callback_data)
    kb.button(text="Мои записи", callback_data=f"view_recordings={telegram_id}")
    kb.button(text="Админ меню", callback_data="admin_menu")
    kb.adjust(3, 7)
    kb = kb.as_markup()
    await message.message.answer("Выберите дату:", reply_markup=kb)


async def reserve_day_2(message: [types.CallbackQuery, types.Message], state: FSMContext):
    """
    Функция reserve_day_2. Коллбэк с датой reserve_day_2 запускает данную функцию.
    Ждёт подтверждения на резерв дня.
    """
    date = datetime.datetime.strptime(
        message.data.split("_")[3], "%Y-%m-%d"
    )
    date = date.date()

    await state.update_data({"date": date})

    await state.update_data(reserve_day=date)
    await message.message.answer(
        "Введите время начала и конца рабочего дня через пробел (например, 9 18):"
    )
    await state.set_state(AdminReserve.reserve_times)


async def reserve_day_3(message: [types.CallbackQuery, types.Message], state: FSMContext):
    """
    Ввод времени рабочего дня.
    """
    data = await state.get_data()
    date = data.get("reserve_day")
    if not date:
        await message.message.answer("Не удалось получить дату, начните заново.")
        await state.clear()
        return
    try:
        beginning, end = message.text.split()
        beginning = int(beginning)
        end = int(end)
    except Exception:
        await message.message.answer("Неверный формат. Введите два числа, например: 9 18")
        return
    await state.update_data(reserve_begin=beginning, reserve_end=end)
    await state.set_state(AdminReserve.note)
    await message.message.answer("Введите причину/комментарий резерва:")


async def reserve_day_4(message: types.Message, state: FSMContext):
    """
    Финальное бронирование дня с указанием причины.
    """
    data = await state.get_data()
    date = data.get("reserve_day")
    beginning = data.get("reserve_begin", config.BEGINNING_WORKING_DAY)
    end = data.get("reserve_end", config.END_WORKING_DAY)
    note = message.text.strip() if message.text else "Резерв администратора"

    telegram_id = message.from_user.id

    created_count = await transactions.reserve_day(
        telegram_id, date, beginning, end, note=note
    )

    kb = back_admin_menu_button()
    if created_count:
        await message.message.answer(
            f"День зарезервирован блокировкой на весь день. Причина: {note}\n"
            "Существующие записи не отменены.",
            reply_markup=kb
        )
    else:
        await message.message.answer(
            "Не удалось создать блокировки в календаре. Проверьте настройки и попробуйте снова.",
            reply_markup=kb
        )
    await state.clear()

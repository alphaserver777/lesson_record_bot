"""Модуль удаления определённой записи на день."""
import datetime

from aiogram import types

from database import transactions
from keyboards.inline.back_admin_menu import back_admin_menu_button
from keyboards.inline.confirm_yes_no import conf_yes_no_button
from loader import bot


async def del_record_day_1(message: [types.CallbackQuery, types.Message]):
    """
    Функция del_all_record_day_1. Коллбэк с датой del_record_day_1 запускает данную функцию.
    Удаляет определённую запись на день.
    """
    data_split = message.data.split("=")
    date = datetime.datetime.strptime(
            data_split[1], "%Y-%m-%d"
        )
    date = date.date()
    time_parts = data_split[2].split("_")
    hour = int(time_parts[0])
    minute = int(time_parts[1]) if len(time_parts) > 1 else 0

    info_user = await transactions.get_info_user(date, hour, minute)

    sending_text = f"Ваша запись на {date.day}-{date.month}-{date.year} в {hour:02d}:{minute:02d} аннулирована"
    await bot.send_message(chat_id=info_user[0], text=sending_text, parse_mode="HTML")

    await transactions.del_record(date, hour, minute)

    kb = back_admin_menu_button()
    await message.message.answer("Запись удалена", reply_markup=kb)

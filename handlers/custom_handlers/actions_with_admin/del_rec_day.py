"""Модуль удаления определённой записи на день."""
import datetime
import logging

from aiogram import types

from database import transactions
from keyboards.inline.back_admin_menu import back_admin_menu_button
from keyboards.inline.confirm_yes_no import conf_yes_no_button
from loader import bot
from utils.schedule import SLOT_DURATION_MINUTES

logger = logging.getLogger(__name__)


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
    if not info_user:
        kb = back_admin_menu_button()
        await message.message.answer("Запись не найдена.", reply_markup=kb)
        await message.answer()
        return

    telegram_id, kind = info_user if len(info_user) > 1 else (info_user[0], "single")
    sending_text = f"Ваша запись на {date.day}-{date.month}-{date.year} в {hour:02d}:{minute:02d} аннулирована"
    if telegram_id and kind != "block":
        try:
            await bot.send_message(chat_id=telegram_id, text=sending_text, parse_mode="HTML")
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Не удалось отправить уведомление об удалении %s: %s", telegram_id, exc)

    try:
        if kind == "regular":
            # Разовая отмена регулярки: удаляем запись (если есть) и ставим allow, чтобы не показывать блок
            await transactions.cancel_regular_slot_with_allow(
                date, hour, minute, note="Отмена регулярного занятия"
            )
        else:
            await transactions.del_record(date, hour, minute)
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Ошибка при удалении записи %s %s:%s: %s", date, hour, minute, exc)
        await message.message.answer("Не удалось удалить запись, попробуйте позже.")
        await message.answer()
        return

    kb = back_admin_menu_button()
    await message.message.answer("Запись удалена/заблокирована на этот день.", reply_markup=kb)
    await message.answer()

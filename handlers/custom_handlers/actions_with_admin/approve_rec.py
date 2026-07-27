"""Согласование или аннулирование записи админом."""
import datetime
import logging

from aiogram import types

from database import transactions
from loader import bot

logger = logging.getLogger(__name__)


async def approve_record(callback: types.CallbackQuery):
    """
    Подтвердить запись: уведомляет пользователя.
    """
    _, user_id, date_str, time_str = callback.data.split("=")
    user_id = int(user_id)
    date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    hour, minute = map(int, time_str.split("_"))

    await bot.send_message(
        chat_id=user_id,
        text=f"Ваша запись на {date.day}-{date.month}-{date.year} в {hour:02d}:{minute:02d} подтверждена ✅",
    )
    await callback.message.answer("Запись подтверждена.")
    await callback.answer()


async def cancel_record(callback: types.CallbackQuery):
    """
    Аннулировать запись: удаляет запись и уведомляет пользователя.
    """
    try:
        _, user_id, date_str, time_str = callback.data.split("=")
        user_id = int(user_id)
        date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        hour, minute = map(int, time_str.split("_"))

        try:
            await transactions.delete_single_slot(
                user_id,
                date,
                hour,
                minute,
                cancel_event_type="canceled_by_admin",
                source_context="admin",
                note="Аннулировано администратором",
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Не удалось удалить запись %s %s:%s: %s", date, hour, minute, exc)

        await bot.send_message(
            chat_id=user_id,
            text=(
                f"Ваша запись на {date.day}-{date.month}-{date.year} в {hour:02d}:{minute:02d} аннулирована. "
                "Можете написать админу в ЛС: @proffessor_it"
            ),
        )
        await callback.message.answer("Запись аннулирована.")
        await callback.answer()
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Ошибка в cancel_record: %s", exc)
        try:
            await callback.answer("Ошибка при аннулировании", show_alert=True)
        except Exception:
            pass

"""Ответы на подтверждение присутствия."""
import datetime
import logging

from aiogram import types

from config_data.config import ADMINS_TELEGRAM_ID
from database import transactions
from loader import bot

logger = logging.getLogger(__name__)


async def presence_yes(callback: types.CallbackQuery):
    await _handle_presence(callback, "подтвердил присутствие ✅")


async def presence_no(callback: types.CallbackQuery):
    await _handle_presence(callback, "не сможет прийти ❌")


async def _handle_presence(callback: types.CallbackQuery, status_text: str):
    try:
        _, date_str, time_str = callback.data.split("=")
        date = datetime.datetime.fromisoformat(date_str).date()
        hour, minute = map(int, time_str.split("_"))
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Некорректные данные presence: %s", exc)
        await callback.answer("Ошибка данных", show_alert=True)
        return

    user = callback.from_user
    username = f"@{user.username}" if user.username else f"tg://user?id={user.id}"
    profile = await transactions.get_student_profile(user.id)
    display_name = profile.full_name if profile and profile.full_name else user.full_name or username
    time_text = f"{hour:02d}:{minute:02d}"

    await callback.message.answer(f"Спасибо! Отметили, что вы {status_text} на {time_text} ({date.day:02d}-{date.month:02d}).")
    await callback.answer()

    try:
        status_value = "yes" if "подтвердил" in status_text else "no"
        await transactions.mark_presence_status(callback.from_user.id, date, hour, minute, status_value)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Не удалось записать статус присутствия: %s", exc)

    admin_msg = (
        f"Ответ по занятию {date.day:02d}-{date.month:02d} в {time_text}:\n"
        f"{display_name} ({username}) {status_text}"
    )
    for admin_id in ADMINS_TELEGRAM_ID:
        try:
            await bot.send_message(chat_id=admin_id, text=admin_msg, parse_mode="HTML")
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Не удалось отправить уведомление админу %s: %s", admin_id, exc)

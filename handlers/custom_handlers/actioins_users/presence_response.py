"""Ответы на подтверждение присутствия."""
import datetime
import logging

from aiogram import types

from config_data.config import ADMINS_TELEGRAM_ID
from database import transactions
from keyboards.inline.presence_confirm import presence_cancel_confirm_kb
from loader import bot

logger = logging.getLogger(__name__)


async def presence_yes(callback: types.CallbackQuery):
    await _handle_presence(callback, "подтвердил присутствие ✅")


async def presence_no(callback: types.CallbackQuery):
    parsed = _parse_presence_callback(callback.data)
    if parsed is None:
        await callback.answer("Ошибка данных", show_alert=True)
        return
    date, hour, minute = parsed
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"Вы не сможете прийти {date.day:02d}-{date.month:02d} в {hour:02d}:{minute:02d}. "
        "Отменить занятие и освободить это время?",
        reply_markup=presence_cancel_confirm_kb(date.isoformat(), f"{hour:02d}_{minute:02d}"),
    )
    await callback.answer()


async def presence_cancel_yes(callback: types.CallbackQuery):
    parsed = _parse_presence_callback(callback.data)
    if parsed is None:
        await callback.answer("Ошибка данных", show_alert=True)
        return
    date, hour, minute = parsed
    canceled = await transactions.cancel_lesson_after_presence_decline(
        callback.from_user.id, date, hour, minute
    )
    await callback.message.edit_reply_markup(reply_markup=None)
    if not canceled:
        await callback.message.answer("Это занятие уже отменено или недоступно.")
        await callback.answer()
        return

    time_text = f"{hour:02d}:{minute:02d}"
    await callback.message.answer(
        f"Занятие {date.day:02d}-{date.month:02d} в {time_text} отменено. Время освобождено."
    )
    await callback.answer("Занятие отменено")
    await _notify_admins_about_cancellation(callback, date, hour, minute)


async def presence_cancel_no(callback: types.CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Хорошо, занятие оставлено в расписании.")
    await callback.answer()


def _parse_presence_callback(data: str | None) -> tuple[datetime.date, int, int] | None:
    try:
        _, date_str, time_str = (data or "").split("=")
        date = datetime.datetime.fromisoformat(date_str).date()
        hour, minute = map(int, time_str.split("_"))
        return date, hour, minute
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Некорректные данные presence: %s", exc)
        return None


async def _handle_presence(callback: types.CallbackQuery, status_text: str):
    parsed = _parse_presence_callback(callback.data)
    if parsed is None:
        await callback.answer("Ошибка данных", show_alert=True)
        return
    date, hour, minute = parsed

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


async def _notify_admins_about_cancellation(
    callback: types.CallbackQuery,
    date: datetime.date,
    hour: int,
    minute: int,
) -> None:
    user = callback.from_user
    username = f"@{user.username}" if user.username else f"tg://user?id={user.id}"
    profile = await transactions.get_student_profile(user.id)
    display_name = profile.full_name if profile and profile.full_name else user.full_name or username
    admin_msg = (
        f"Занятие отменено учеником: {date.day:02d}-{date.month:02d} в {hour:02d}:{minute:02d}\n"
        f"{display_name} ({username}). Время освобождено."
    )
    for admin_id in ADMINS_TELEGRAM_ID:
        try:
            await bot.send_message(chat_id=admin_id, text=admin_msg, parse_mode="HTML")
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Не удалось отправить уведомление админу %s: %s", admin_id, exc)

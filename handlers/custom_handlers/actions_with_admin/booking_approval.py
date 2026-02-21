"""Approve/reject booking requests from Telegram admin callbacks."""
import datetime
import logging

from aiogram import types

from config_data.config import ADMINS_TELEGRAM_ID
from database import transactions
from loader import bot

logger = logging.getLogger(__name__)


def _fmt_date(d: datetime.date, h: int, m: int) -> str:
    return f"{d.day:02d}.{d.month:02d}.{d.year} {h:02d}:{m:02d}"


async def booking_approve(callback: types.CallbackQuery) -> None:
    if callback.from_user.id not in ADMINS_TELEGRAM_ID:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    try:
        record_id = int(callback.data.split(":")[1])
    except Exception:  # pylint: disable=broad-except
        await callback.answer("Ошибка данных", show_alert=True)
        return

    status, rec = await transactions.approve_pending_booking(record_id, callback.from_user.id)
    if not rec:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    if status == "approved":
        try:
            await bot.send_message(
                chat_id=rec.telegram_id,
                text=f"✅ Ваша запись согласована: {_fmt_date(rec.record_date, rec.hour, rec.minute)}",
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to notify user about approved booking id=%s: %s", record_id, exc)
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(f"Заявка #{record_id} согласована ✅")
        await callback.answer("Согласовано")
        return

    if status == "slot_busy":
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(f"Заявка #{record_id} отклонена: слот уже занят.")
        await callback.answer("Слот занят", show_alert=True)
        return

    if status == "calendar_error":
        await callback.answer("Ошибка календаря при согласовании", show_alert=True)
        return

    await callback.answer("Эта заявка уже обработана")


async def booking_reject(callback: types.CallbackQuery) -> None:
    if callback.from_user.id not in ADMINS_TELEGRAM_ID:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    try:
        record_id = int(callback.data.split(":")[1])
    except Exception:  # pylint: disable=broad-except
        await callback.answer("Ошибка данных", show_alert=True)
        return

    status, rec = await transactions.reject_pending_booking(record_id, callback.from_user.id)
    if not rec:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    if status == "rejected":
        try:
            await bot.send_message(
                chat_id=rec.telegram_id,
                text=f"❌ Ваша запись отклонена: {_fmt_date(rec.record_date, rec.hour, rec.minute)}",
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to notify user about rejected booking id=%s: %s", record_id, exc)
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(f"Заявка #{record_id} отклонена ❌")
        await callback.answer("Отклонено")
        return

    await callback.answer("Эта заявка уже обработана")

"""Обработчики подтверждения оплаты."""
import datetime
import logging

from aiogram import types

from database import transactions
from loader import bot

logger = logging.getLogger(__name__)


async def payment_yes(callback: types.CallbackQuery):
    await _handle_payment(callback, status="paid")


async def payment_no(callback: types.CallbackQuery):
    await _handle_payment(callback, status="unpaid")


async def _handle_payment(callback: types.CallbackQuery, status: str):
    try:
        _, pay_id_str, date_str, time_str, duration_str = callback.data.split("=")
        pay_id = int(pay_id_str)
        date = datetime.datetime.fromisoformat(date_str).date()
        hour, minute = map(int, time_str.split("_"))
        duration = int(duration_str)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Ошибка данных оплаты: %s", exc)
        await callback.answer("Ошибка данных", show_alert=True)
        return

    if pay_id:
        await transactions.mark_payment_status(pay_id, status)
    else:
        # Создаём запись
        admin = callback.from_user
        full_name = admin.full_name
        await transactions.add_payment(
            telegram_id=None,
            full_name=full_name,
            lesson_date=date,
            hour=hour,
            minute=minute,
            duration_minutes=duration,
            amount=None,
            status=status,
            source="manual",
        )

    await callback.message.answer(
        f"Отметка оплаты: {('получена ✅' if status=='paid' else 'не получена ❌')}"
    )
    await callback.answer()

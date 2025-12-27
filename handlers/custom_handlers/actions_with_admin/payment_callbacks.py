"""Обработчики подтверждения оплаты."""
import datetime
import logging

from aiogram import types

from database import transactions
from loader import bot
from states.states import PaymentState
from aiogram.fsm.context import FSMContext

logger = logging.getLogger(__name__)


async def payment_yes(callback: types.CallbackQuery):
    await _handle_payment(callback, status="paid")


async def payment_no(callback: types.CallbackQuery):
    await _handle_payment(callback, status="unpaid")


async def payment_cancel(callback: types.CallbackQuery):
    await _handle_payment(callback, status="canceled")


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

    if status == "paid":
        text = "Отметка оплаты: получена ✅"
    elif status == "unpaid":
        text = "Отметка оплаты: не получена ❌"
    else:
        text = "Отметка: занятие отменено 🚫"

    await callback.message.answer(text)
    await callback.answer()


async def payment_amount(callback: types.CallbackQuery, state: FSMContext):
    """
    Запрашиваем сумму оплаты для ручного ввода.
    """
    try:
        _, pay_id_str, date_str, time_str, duration_str = callback.data.split("=")
        pay_id = int(pay_id_str)
        date = datetime.datetime.fromisoformat(date_str).date()
        hour, minute = map(int, time_str.split("_"))
        duration = int(duration_str)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Ошибка данных payment_amount: %s", exc)
        await callback.answer("Ошибка данных", show_alert=True)
        return

    await state.update_data(pay_id=pay_id, pay_date=date, pay_hour=hour, pay_minute=minute, pay_duration=duration)
    await callback.message.answer("Введите фактическую сумму оплаты (число, ₽):")
    await state.set_state(PaymentState.amount)
    await callback.answer()


async def payment_amount_entered(message: types.Message, state: FSMContext):
    """
    Обработка введённой суммы: отмечаем платеж, при переплате зачисляем на баланс.
    """
    try:
        amount_val = int(message.text.strip())
        if amount_val < 0:
            raise ValueError
    except Exception:
        await message.answer("Нужно указать сумму числом (₽). Попробуйте ещё раз.")
        return

    data = await state.get_data()
    pay_id = data.get("pay_id", 0)
    date = data.get("pay_date")
    hour = data.get("pay_hour")
    minute = data.get("pay_minute")
    duration = data.get("pay_duration")

    pay = await transactions.get_payment(pay_id) if pay_id else None
    telegram_id = pay.telegram_id if pay else None
    profile = await transactions.get_student_profile(telegram_id) if telegram_id else None
    base_price = pay.amount if (pay and pay.amount is not None) else (profile.price if profile else None)

    price_value = base_price or amount_val
    paid_from_amount = min(amount_val, price_value)
    extra = max(0, amount_val - price_value)
    unpaid = max(0, price_value - amount_val)

    # Обновляем/создаём платеж
    if pay is None:
        pay = await transactions.add_payment(
            telegram_id=telegram_id,
            full_name=profile.full_name if profile else None,
            lesson_date=date,
            hour=hour,
            minute=minute,
            duration_minutes=duration or 60,
            amount=paid_from_amount,
            status="paid" if unpaid == 0 else "partial",
            source="manual",
        )
    else:
        await transactions.update_payment(
            pay_id=pay_id,
            amount=paid_from_amount,
            status="paid" if unpaid == 0 else "partial",
            source="manual",
        )

    # Зачисление переплаты на баланс
    new_balance = None
    if telegram_id and extra > 0:
        await transactions.change_balance(telegram_id, extra)
        profile = await transactions.get_student_profile(telegram_id)
        new_balance = profile.balance_lessons if profile else None

    # Ответ админу
    msg_parts = [
        f"Оплата за занятие {date} {hour:02d}:{minute:02d}: {paid_from_amount} ₽ — статус {'оплачено' if unpaid == 0 else 'частично оплачено'}."
    ]
    if unpaid > 0:
        msg_parts.append(f"Долг: {unpaid} ₽.")
    if extra > 0:
        msg_parts.append(f"На баланс зачислено: {extra} ₽.")
        if new_balance is not None:
            msg_parts.append(f"Баланс: {new_balance} ₽.")

    await message.answer(" ".join(msg_parts))
    await state.clear()

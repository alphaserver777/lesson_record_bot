"""Обработчики подтверждения оплаты."""
import datetime
import logging

from aiogram import types

from database import transactions
from loader import bot
from utils.schedule import SLOT_DURATION_MINUTES
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

    paid_from_balance = 0
    if pay_id:
        pay = await transactions.get_payment(pay_id)
        if not pay:
            await callback.answer("Платеж не найден", show_alert=True)
            return

        if status == "paid" and pay.status == "paid":
            await callback.answer("Оплата уже подтверждена")
            return

        if status == "paid":
            source = "manual"
            if pay.telegram_id and (pay.amount or 0) > 0:
                profile = await transactions.get_student_profile(pay.telegram_id)
                balance_amount = (profile.balance_lessons or 0) if profile else 0
                paid_from_balance = min(balance_amount, pay.amount or 0)
                if paid_from_balance > 0:
                    await transactions.change_balance(pay.telegram_id, -paid_from_balance)

                if paid_from_balance >= (pay.amount or 0):
                    source = "balance"
                elif paid_from_balance > 0:
                    source = "balance+manual"

            await transactions.update_payment(pay_id=pay_id, source=source)

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
        if paid_from_balance > 0:
            text = f"Отметка оплаты: получена ✅\nСписано с баланса: {paid_from_balance} ₽."
        else:
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
        if not message.text:
            raise ValueError
        amount_raw = message.text.strip().replace(" ", "").replace("₽", "").replace("р", "").replace("Р", "")
        amount_val = int(amount_raw)
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
    if pay:
        # Надёжно берём привязку из платежа (на случай потери части FSM-данных).
        date = pay.lesson_date
        hour = pay.hour
        minute = pay.minute
        duration = pay.duration_minutes or duration or SLOT_DURATION_MINUTES
    if date is None or hour is None or minute is None:
        await message.answer("Сессия ввода устарела. Нажмите кнопку «Ввести сумму» ещё раз.")
        await state.clear()
        return

    telegram_id = pay.telegram_id if pay else None
    profile = await transactions.get_student_profile(telegram_id) if telegram_id else None
    base_price = pay.amount if (pay and pay.amount is not None) else (profile.price if profile else None)
    pay_duration = duration or SLOT_DURATION_MINUTES

    factor = 1
    if pay is None and base_price is not None and pay_duration:
        factor = max(1, (pay_duration + SLOT_DURATION_MINUTES - 1) // SLOT_DURATION_MINUTES)
    price_value = (base_price * factor) if base_price is not None else amount_val
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

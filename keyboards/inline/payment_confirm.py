"""Клавиатура подтверждения оплаты."""
from aiogram.utils.keyboard import InlineKeyboardBuilder


def payment_confirm_kb(payment_id: int | None, date_str: str, time_str: str, duration: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Оплата получена", callback_data=f"pay_yes={payment_id or 0}={date_str}={time_str}={duration}")
    builder.button(text="❌ Не оплатили", callback_data=f"pay_no={payment_id or 0}={date_str}={time_str}={duration}")
    builder.button(text="🚫 Занятие отменено", callback_data=f"pay_cancel={payment_id or 0}={date_str}={time_str}={duration}")
    builder.button(text="💳 Ввести сумму", callback_data=f"pay_amount={payment_id or 0}={date_str}={time_str}={duration}")
    builder.adjust(1)
    return builder.as_markup()

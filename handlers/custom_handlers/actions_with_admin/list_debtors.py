"""Вывод неоплаченных занятий."""
from aiogram import types

from database import transactions
from keyboards.inline.payment_confirm import payment_confirm_kb
from keyboards.inline.back_admin_menu import back_admin_menu_button


async def list_debtors(callback: types.CallbackQuery):
    unpaid = await transactions.list_unpaid_payments()
    if not unpaid:
        await callback.message.answer("Нет неоплаченных занятий.")
    else:
        for row in unpaid:
            pay = row[0]
            date = pay.lesson_date
            time_text = f"{pay.hour:02d}:{pay.minute:02d}"
            dur = pay.duration_minutes or 60
            kb = payment_confirm_kb(pay.id, date.isoformat(), f"{pay.hour:02d}_{pay.minute:02d}", dur)
            await callback.message.answer(
                f"""Ученик: {pay.full_name or 'не указан'}
Дата: {date.day:02d}-{date.month:02d}-{date.year}
Время: {time_text}
Длительность: {dur} мин
Статус: {pay.status}
""",
                reply_markup=kb
            )
    kb_back = back_admin_menu_button()
    await callback.message.answer("Вернуться в админ меню?", reply_markup=kb_back)
    await callback.answer()

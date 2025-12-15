"""Модуль обработки просмотра записей."""
from aiogram import types
from aiogram.fsm.context import FSMContext

from database import transactions
from keyboards.reply.list_button import list_button
from states.states import ServiceDateState


async def view_recordings(message: types.Message, state: FSMContext):
    """Функция view_recordings. Запрашивает в базе записи и выводит их пользователю."""
    telegram_id = message.data.split("=")[1]
    res = await transactions.view_record(telegram_id)
    reg = await transactions.view_regular_lessons(int(telegram_id))

    parts = []
    if reg:
        days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        parts.append("<b>Регулярные занятия:</b>")
        for lesson in reg:
            day_name = days[lesson.day_of_week] if lesson.day_of_week is not None else "День"
            time_text = f"{lesson.hour:02d}:{lesson.minute:02d}"
            dur = lesson.duration_minutes or 60
            parts.append(f"• {day_name} в {time_text}, {dur} мин")
        parts.append("")  # пустая строка

    if res:
        parts.append("<b>Разовые записи:</b>")
        for obj in res:
            date = obj.record_date
            time_text = f"{obj.hour:02d}:{obj.minute:02d}"
            parts.append(f"• {date.day:02d}-{date.month:02d}-{date.year} в {time_text}")

    if not res and not reg:
        parts.append("Записей ещё нет")

    text = "\n".join(parts)
    await message.message.answer(text, parse_mode="HTML")
    await state.clear()

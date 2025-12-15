"""Модуль напоминая о записи"""
import datetime

from loader import bot

from database import transactions
from config_data.config import ADMINS_TELEGRAM_ID
from utils.schedule import SLOT_DURATION_MINUTES
from keyboards.inline.presence_confirm import presence_confirm_kb


async def reminder(date: datetime) -> None:
    """
    Функция reminder. Напоминания о записи. Запрашивает всех пользователей на сегодня.
    """
    lessons = await transactions.lessons_for_date(date)
    seen = set()
    for user_id, hour, minute, duration in lessons:
        if not user_id:
            continue
        key = (user_id, hour, minute)
        if key in seen:
            continue
        seen.add(key)
        time_text = f"{hour:02d}:{minute:02d}"
        kb = presence_confirm_kb(date.isoformat(), f"{hour:02d}_{minute:02d}")
        await bot.send_message(
            chat_id=user_id,
            text=f"Напоминаю: сегодня занятие в {time_text}. Пожалуйста, подтвердите присутствие.",
            reply_markup=kb,
        )


async def reminder_before_start(target_datetime: datetime.datetime) -> None:
    """
    Напоминание за 10 минут до начала слота: клиенту и админам.
    """
    res = await transactions.records_starting_at(
        target_datetime.date(), target_datetime.hour, target_datetime.minute
    )
    if not res:
        return

    time_text = target_datetime.strftime("%H:%M")
    for user in res:
        telegram_id, full_name, telephone, hour, minute = user
        await bot.send_message(
            chat_id=telegram_id,
            text=f"Через 10 минут ваша запись в {time_text}.",
        )

        admin_text = (
            f"Скоро встреча: {full_name or telegram_id} в {time_text}."
            f" Телефон: {telephone or 'не указан'}."
            f" <a href=\"tg://user?id={telegram_id}\">Написать клиенту</a>"
        )
        for admin_id in ADMINS_TELEGRAM_ID:
            await bot.send_message(chat_id=admin_id, text=admin_text, parse_mode="HTML")

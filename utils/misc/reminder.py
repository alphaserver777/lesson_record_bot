"""Модуль напоминая о записи"""
import datetime

from loader import bot

from database import transactions
from config_data.config import ADMINS_TELEGRAM_ID
from keyboards.inline.presence_confirm import presence_confirm_kb
from utils.schedule import SLOT_DURATION_MINUTES


async def reminder(date: datetime) -> None:
    """
    Функция reminder. Напоминания о записи. Запрашивает всех пользователей на сегодня.
    """
    await send_presence_prompts(date, force_pending=True)


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


async def reminder_before_delta(target_datetime: datetime.datetime, delta_minutes: int) -> None:
    """
    Универсальное напоминание за delta_minutes до начала слота.
    """
    res = await transactions.records_starting_at(
        target_datetime.date(), target_datetime.hour, target_datetime.minute
    )
    if not res:
        return

    time_text = target_datetime.strftime("%H:%M")
    lead_text = f"Через {delta_minutes} минут" if delta_minutes < 60 else f"Через {delta_minutes // 60} час(а)"
    for user in res:
        telegram_id, full_name, telephone, hour, minute = user
        await bot.send_message(
            chat_id=telegram_id,
            text=f"{lead_text} ваша запись в {time_text}.",
        )

        admin_text = (
            f"{lead_text}: {full_name or telegram_id} в {time_text}."
            f" Телефон: {telephone or 'не указан'}."
            f" <a href=\"tg://user?id={telegram_id}\">Написать клиенту</a>"
        )
        for admin_id in ADMINS_TELEGRAM_ID:
            await bot.send_message(chat_id=admin_id, text=admin_text, parse_mode="HTML")


async def send_presence_prompts(date: datetime.date, force_pending: bool = False) -> None:
    """
    Рассылает напоминания о подтверждении присутствия за день.
    Если force_pending=True — всем без ответа ставим статус pending и шлём.
    Иначе шлём только тем, у кого статус не yes/no.
    """
    lessons = await transactions.pending_presence_for_date(date)
    seen = set()
    for rec in lessons:
        _, user_id, _, hour, minute, _, presence_status, _ = rec
        if not user_id:
            continue
        if presence_status in ("yes", "no"):
            continue
        if not force_pending and presence_status == "pending":
            # Уже ожидание — напомним повторно
            pass
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
        await transactions.mark_presence_status(user_id, date, hour, minute, "pending")

"""Модуль напоминая о записи"""
import datetime

from loader import bot

from database import transactions
from config_data.config import ADMINS_TELEGRAM_ID
from keyboards.inline.presence_confirm import presence_confirm_kb
from utils.schedule import SLOT_DURATION_MINUTES
from utils.google_calendar import get_calendar_tz


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
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=f"Через 10 минут ваша запись в {time_text}.",
            )
        except Exception:
            # Пользователь может быть недоступен/заблокировал бота — не останавливаем цикл.
            pass

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
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=f"{lead_text} ваша запись в {time_text}.",
            )
        except Exception:
            pass

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
    Если force_pending=True — сбрасываем статус на pending и шлём.
    Иначе шлём только тем, у кого статус не yes/no, или status is NULL (не отправлялось).
    """
    lessons = await transactions.pending_presence_for_date(date)
    seen = set()
    now_dt = datetime.datetime.now(get_calendar_tz())
    for rec in lessons:
        # rec может содержать 8 или 9 полей (с kind). Берём по позиции.
        if len(rec) >= 8:
            _, user_id, _, hour, minute, duration, presence_status, last_reminder = rec[:8]
            rec_kind = rec[8] if len(rec) > 8 else None
        else:
            continue
        if not user_id:
            continue
        start_dt = datetime.datetime.combine(date, datetime.time(hour, minute), tzinfo=get_calendar_tz())
        # Не шлём напоминания для уже начавшихся/прошедших слотов
        if start_dt <= now_dt:
            continue
        if presence_status in ("yes", "no"):
            continue
        key = (user_id, hour, minute)
        if key in seen:
            continue
        seen.add(key)
        time_text = f"{hour:02d}:{minute:02d}"
        kb = presence_confirm_kb(date.isoformat(), f"{hour:02d}_{minute:02d}")
        try:
            await bot.send_message(
                chat_id=user_id,
                text=f"Напоминаю: сегодня занятие в {time_text}. Пожалуйста, подтвердите присутствие.",
                reply_markup=kb,
            )
            logger.info("Отправлено напоминание о присутствии user=%s date=%s time=%s", user_id, date, time_text)
        except Exception:
            pass
        await transactions.mark_presence_status(user_id, date, hour, minute, "pending")

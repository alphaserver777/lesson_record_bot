"""Модуль напоминая о записи"""
import datetime
import logging

from loader import bot

from database import transactions
from config_data.config import ADMINS_TELEGRAM_ID
from keyboards.inline.presence_confirm import presence_confirm_kb
from utils.schedule import SLOT_DURATION_MINUTES
from utils.calendar_backend import get_calendar_tz

logger = logging.getLogger(__name__)


def _format_last_lesson(last_lesson: tuple[datetime.date, int, int] | None) -> str:
    if not last_lesson:
        return "неизвестно"
    lesson_date, hour, minute = last_lesson
    return f"{lesson_date.strftime('%d-%m-%Y')} {hour:02d}:{minute:02d}"


def _admin_reminder_text(item: dict, target_datetime: datetime.datetime, lead_text: str) -> str:
    telegram_id = int(item["telegram_id"])
    full_name = item.get("full_name") or str(telegram_id)
    duration = int(item.get("duration_minutes") or SLOT_DURATION_MINUTES)
    kind = "Регулярное" if item.get("kind") == "regular" else "Разовое"
    price_60 = int(item.get("price_60") or 0)
    amount = int(item.get("amount") or 0)
    phone = item.get("telephone") or "не указан"
    last_lesson = _format_last_lesson(item.get("last_lesson"))
    return (
        f"{lead_text}: {full_name} в {target_datetime.strftime('%H:%M')}\n"
        f"Тип: {kind}\n"
        f"Длительность: {duration} мин\n"
        f"Цена: {amount} ₽"
        + (f" ({price_60} ₽ / 60 мин)" if price_60 else "")
        + "\n"
        f"Телефон: {phone}\n"
        f"Крайнее занятие: {last_lesson}\n"
        f"<a href=\"tg://user?id={telegram_id}\">Написать клиенту</a>"
    )

async def reminder(date: datetime) -> None:
    """
    Функция reminder. Напоминания о записи. Запрашивает всех пользователей на сегодня.
    """
    await send_presence_prompts(date, force_pending=True)


async def reminder_before_start(target_datetime: datetime.datetime) -> None:
    """
    Напоминание за 10 минут до начала слота: клиенту и админам.
    """
    res = await transactions.records_starting_at_details(
        target_datetime.date(), target_datetime.hour, target_datetime.minute
    )
    if not res:
        return

    time_text = target_datetime.strftime("%H:%M")
    for item in res:
        telegram_id = int(item["telegram_id"])
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=f"Через 10 минут ваша запись в {time_text}.",
            )
        except Exception:
            # Пользователь может быть недоступен/заблокировал бота — не останавливаем цикл.
            pass

        admin_text = _admin_reminder_text(item, target_datetime, "Через 10 минут")
        for admin_id in ADMINS_TELEGRAM_ID:
            await bot.send_message(chat_id=admin_id, text=admin_text, parse_mode="HTML")


async def reminder_before_delta(target_datetime: datetime.datetime, delta_minutes: int) -> None:
    """
    Универсальное напоминание за delta_minutes до начала слота.
    """
    res = await transactions.records_starting_at_details(
        target_datetime.date(), target_datetime.hour, target_datetime.minute
    )
    if not res:
        return

    time_text = target_datetime.strftime("%H:%M")
    lead_text = f"Через {delta_minutes} минут" if delta_minutes < 60 else f"Через {delta_minutes // 60} час(а)"
    for item in res:
        telegram_id = int(item["telegram_id"])
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=f"{lead_text} ваша запись в {time_text}.",
            )
            logger.info("Напоминание пользователю отправлено user=%s date=%s time=%s", telegram_id, target_datetime.date(), time_text)
        except Exception as exc:
            logger.warning("Не удалось отправить напоминание пользователю %s: %s", telegram_id, exc)

        admin_text = _admin_reminder_text(item, target_datetime, lead_text)
        for admin_id in ADMINS_TELEGRAM_ID:
            try:
                await bot.send_message(chat_id=admin_id, text=admin_text, parse_mode="HTML")
                logger.info("Напоминание админу отправлено admin=%s user=%s date=%s time=%s", admin_id, telegram_id, target_datetime.date(), time_text)
            except Exception as exc:
                logger.warning("Не удалось отправить напоминание админу %s: %s", admin_id, exc)


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
        # rec содержит поля из pending_presence_for_date().
        if len(rec) >= 9:
            _, user_id, _, hour, minute, _, presence_status, _, presence_message_id = rec[:9]
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
        reminder_text = f"Напоминаю: сегодня занятие в {time_text}. Пожалуйста, подтвердите присутствие."
        try:
            if presence_message_id:
                try:
                    await bot.delete_message(chat_id=user_id, message_id=presence_message_id)
                except Exception as del_exc:
                    logger.warning(
                        "Не удалось удалить предыдущее presence-сообщение user=%s msg=%s: %s",
                        user_id,
                        presence_message_id,
                        del_exc,
                    )
            sent_message = await bot.send_message(
                chat_id=user_id,
                text=reminder_text,
                reply_markup=kb,
            )
            logger.info("Напоминание о присутствии отправлено user=%s date=%s time=%s", user_id, date, time_text)
        except Exception as exc:
            logger.warning("Не удалось отправить напоминание о присутствии пользователю %s: %s", user_id, exc)
            continue
        await transactions.mark_presence_status(
            user_id, date, hour, minute, "pending", presence_message_id=sent_message.message_id
        )

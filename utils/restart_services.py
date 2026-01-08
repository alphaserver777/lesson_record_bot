"""Модуль перезапуска сервисов."""
import asyncio
import datetime
import logging

from config_data.config import LOCAL_UTC, REMINDER_TIME
from database import transactions
from utils.google_calendar import get_calendar_tz
from utils.misc.reminder import reminder, reminder_before_delta, send_presence_prompts
from keyboards.inline.payment_confirm import payment_confirm_kb
from config_data.config import ADMINS_TELEGRAM_ID
from aiogram.types import BufferedInputFile
from loader import bot
from database.transactions import (
    add_payment,
    change_balance,
    get_student_profile,
    get_lesson_kind,
    find_payment,
    payments_summary_for_range,
    payments_daily_breakdown,
)
from utils.misc.reporting import build_weekly_report_chart
from utils.schedule import SLOT_DURATION_MINUTES

logger = logging.getLogger(__name__)


async def restarting_services() -> None:
    """
    Функция restarting_services. Каждый день в 8:30 утра перезапускает функции:
    удаляет записи (старше 7 дней), удаляет пользователей
    (которые заходили более полгода назад),
    резервирует выходные дни на 2 месяца и отправляет напоминания о записи.
    """
    await transactions.deleting_records_older_7_days()
    await transactions.deletes_old_users()

    reminder_hour = 10
    reminder_minute = 0
    try:
        if REMINDER_TIME:
            reminder_time = REMINDER_TIME.split(":")
            reminder_hour = int(reminder_time[0])
            reminder_minute = int(reminder_time[1])
    except (IndexError, ValueError):
        reminder_hour = 10
        reminder_minute = 0

    initial_presence_sent = False
    daily_report_sent: datetime.date | None = None
    weekly_report_sent: datetime.date | None = None

    while True:
        region_time = datetime.datetime.now(get_calendar_tz())

        # При старте отправляем запросы на подтверждение на сегодня, даже если пропустили утреннее время
        if not initial_presence_sent:
            await send_presence_prompts(region_time.date(), force_pending=False)
            initial_presence_sent = True

        if region_time.hour == reminder_hour and region_time.minute == reminder_minute:
            await transactions.deleting_records_older_7_days()
            await transactions.deletes_old_users()

            await reminder(region_time.date())

        # Ежечасные пинги, если нет ответа по присутствию
        if region_time.minute == 0:
            await send_presence_prompts(region_time.date(), force_pending=False)

        # Напоминания за 60 и 10 минут до начала слота
        target_time_10 = region_time + datetime.timedelta(minutes=10)
        target_time_60 = region_time + datetime.timedelta(minutes=60)
        try:
            await reminder_before_delta(target_time_60, 60)
            await reminder_before_delta(target_time_10, 10)
        except Exception:
            # Не блокируем цикл, если пользователю нельзя отправить сообщение
            pass

        # Уведомление об оплате по окончании слота
        lessons_today = await transactions.lessons_for_date(region_time.date())
        for user_id, hour, minute, duration, kind_flag in lessons_today:
            if not user_id:
                continue
            duration = duration or SLOT_DURATION_MINUTES
            end_time = datetime.datetime.combine(
                region_time.date(),
                datetime.time(hour, minute),
                tzinfo=get_calendar_tz(),
            ) + datetime.timedelta(minutes=duration)
            delta_seconds = (region_time - end_time).total_seconds()
            if delta_seconds < 0 or delta_seconds >= 6 * 3600:
                continue
            # Не дублируем платеж, если уже есть
            existing_payment = await find_payment(user_id, region_time.date(), hour, minute)
            if existing_payment:
                continue
            date_str = region_time.date().isoformat()
            time_str = f"{hour:02d}_{minute:02d}"
            profile = await get_student_profile(user_id) if user_id else None
            student_name = profile.full_name if profile else "Ученик"

            kind = kind_flag or await get_lesson_kind(region_time.date(), hour, minute, user_id)
            kind_text = "регулярное" if kind == "regular" else "разовое" if kind == "single" else "неизвестно"
            price_value = profile.price if profile else None
            # Корректируем стоимость по длительности занятия (множитель от базового слота)
            factor = 1
            if price_value is not None and duration:
                factor = max(1, (duration + SLOT_DURATION_MINUTES - 1) // SLOT_DURATION_MINUTES)
                price_value = price_value * factor
            price_text = f"{price_value} ₽" if price_value is not None else "не указана"
            profile_link = f'<a href="tg://user?id={user_id}">профиль</a>' if user_id else ""
            username_note = f" (@{profile.notes.split('@',1)[1].strip()})" if profile and profile.notes and '@' in profile.notes else ""
            logger.info("Запрос оплаты: user=%s date=%s time=%s duration=%s", user_id, region_time.date(), time_str, duration)

            balance_amount = profile.balance_lessons if profile else 0
            if profile and balance_amount > 0 and price_value and price_value > 0:
                paid_from_balance = min(balance_amount, price_value)
                await change_balance(user_id, -paid_from_balance)
                new_balance = balance_amount - paid_from_balance
                remaining_amount = price_value - paid_from_balance

                if remaining_amount <= 0:
                    await add_payment(
                        telegram_id=user_id,
                        full_name=student_name,
                        lesson_date=region_time.date(),
                        hour=hour,
                        minute=minute,
                        duration_minutes=duration,
                        amount=price_value,
                        status="paid",
                        source="balance",
                    )
                    for admin_id in ADMINS_TELEGRAM_ID:
                        try:
                            await bot.send_message(
                                chat_id=admin_id,
                                text=(
                                    f"{student_name}{username_note} {profile_link}\n"
                                    f"Тип: {kind_text}\n"
                                    f"Дата/время: {region_time.date().isoformat()} {hour:02d}:{minute:02d} ({duration} мин)\n"
                                    f"Оплачено с баланса: {paid_from_balance} ₽. Остаток: {new_balance} ₽."
                                ),
                            )
                            logger.info("Отправлено уведомление об оплате admin=%s user=%s date=%s time=%s", admin_id, user_id, region_time.date(), time_str)
                        except Exception as exc:
                            logger.warning("Не удалось отправить уведомление об оплате админу %s: %s", admin_id, exc)
                else:
                    pay = await add_payment(
                        telegram_id=user_id,
                        full_name=student_name,
                        lesson_date=region_time.date(),
                        hour=hour,
                        minute=minute,
                        duration_minutes=duration,
                        amount=remaining_amount,
                        status="unpaid",
                        source="balance+manual",
                    )
                    kb = payment_confirm_kb(payment_id=pay.id, date_str=date_str, time_str=time_str, duration=duration)
                    for admin_id in ADMINS_TELEGRAM_ID:
                        try:
                            await bot.send_message(
                                chat_id=admin_id,
                                text=(
                                    f"{student_name}{username_note} {profile_link}\n"
                                    f"Тип: {kind_text}\n"
                                    f"Дата/время: {region_time.date().isoformat()} {hour:02d}:{minute:02d} ({duration} мин)\n"
                                    f"Часть оплачено с баланса: {paid_from_balance} ₽. К доплате: {remaining_amount} ₽.\n"
                                    f"Баланс после списания: {new_balance} ₽."
                                ),
                                reply_markup=kb
                            )
                            logger.info("Отправлен запрос доплаты admin=%s user=%s date=%s time=%s", admin_id, user_id, region_time.date(), time_str)
                        except Exception as exc:
                            logger.warning("Не удалось отправить запрос доплаты админу %s: %s", admin_id, exc)
            else:
                current_balance = balance_amount
                pay = await add_payment(
                    telegram_id=user_id,
                    full_name=student_name,
                    lesson_date=region_time.date(),
                    hour=hour,
                    minute=minute,
                    duration_minutes=duration,
                    amount=price_value if price_value is not None else None,
                    status="unpaid",
                    source="manual",
                )
                kb = payment_confirm_kb(payment_id=pay.id, date_str=date_str, time_str=time_str, duration=duration)
                for admin_id in ADMINS_TELEGRAM_ID:
                    try:
                        await bot.send_message(
                            chat_id=admin_id,
                            text=(
                                f"{student_name}{username_note} {profile_link}\n"
                                f"Тип: {kind_text}\n"
                                f"Дата/время: {region_time.date().isoformat()} {hour:02d}:{minute:02d} ({duration} мин)\n"
                                f"Сумма к оплате: {price_text}\n"
                                f"Баланс: {current_balance} ₽\n"
                                "Оплата получена?"
                            ),
                            reply_markup=kb
                        )
                        logger.info("Отправлен запрос оплаты admin=%s user=%s date=%s time=%s", admin_id, user_id, region_time.date(), time_str)
                    except Exception as exc:
                        logger.warning("Не удалось отправить запрос оплаты админу %s: %s", admin_id, exc)

        # Ежедневный и недельный финансовый отчёт в 23:00
        if region_time.hour == 23 and region_time.minute == 0:
            today = region_time.date()
            if daily_report_sent != today:
                summary = await payments_summary_for_range(today, today)
                unpaid_total = summary["billed_total"] - summary["earned_total"]
                report_text = (
                    f"Финансовый отчет за {today.isoformat()}:\n"
                    f"Занятий проведено: {summary['lessons_total']}\n"
                    f"Оплачено: {summary['lessons_paid']}\n"
                    f"Заработано: {summary['earned_total']} ₽\n"
                    f"К оплате: {unpaid_total} ₽"
                )
                for admin_id in ADMINS_TELEGRAM_ID:
                    try:
                        await bot.send_message(chat_id=admin_id, text=report_text)
                        logger.info("Отправлен дневной отчет admin=%s date=%s", admin_id, today)
                    except Exception as exc:
                        logger.warning("Не удалось отправить дневной отчет админу %s: %s", admin_id, exc)
                daily_report_sent = today

            if today.weekday() == 6 and weekly_report_sent != today:
                week_start = today - datetime.timedelta(days=today.weekday())
                week_end = today
                summary = await payments_summary_for_range(week_start, week_end)
                daily = await payments_daily_breakdown(week_start, week_end)
                daily_map = {row[0]: row for row in daily}
                dates = [week_start + datetime.timedelta(days=i) for i in range(7)]
                amounts = [daily_map.get(d, (d, 0, 0, 0, 0))[2] for d in dates]
                unpaid_total = summary["billed_total"] - summary["earned_total"]
                chart_title = f"Week {week_start.isoformat()}..{week_end.isoformat()}"
                chart_buf = build_weekly_report_chart(dates, amounts, title=chart_title)
                chart_file = BufferedInputFile(chart_buf.getvalue(), filename="weekly.png")
                report_text = (
                    f"Финансовый отчет за неделю {week_start.isoformat()}–{week_end.isoformat()}:\n"
                    f"Занятий проведено: {summary['lessons_total']}\n"
                    f"Оплачено: {summary['lessons_paid']}\n"
                    f"Заработано: {summary['earned_total']} ₽\n"
                    f"К оплате: {unpaid_total} ₽"
                )
                for admin_id in ADMINS_TELEGRAM_ID:
                    try:
                        await bot.send_photo(chat_id=admin_id, photo=chart_file, caption=report_text)
                        logger.info("Отправлен недельный отчет admin=%s date=%s", admin_id, today)
                    except Exception as exc:
                        logger.warning("Не удалось отправить недельный отчет админу %s: %s", admin_id, exc)
                weekly_report_sent = today

        await asyncio.sleep(60)

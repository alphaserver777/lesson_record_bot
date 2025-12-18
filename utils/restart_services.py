"""Модуль перезапуска сервисов."""
import asyncio
import datetime

from config_data.config import LOCAL_UTC, REMINDER_TIME
from database import transactions
from utils.misc.region_datetime import region_current_datetime
from utils.misc.reminder import reminder, reminder_before_start
from keyboards.inline.payment_confirm import payment_confirm_kb
from config_data.config import ADMINS_TELEGRAM_ID
from loader import bot
from database.transactions import add_payment, change_balance, get_student_profile


async def restarting_services() -> None:
    """
    Функция restarting_services. Каждый день в 8:30 утра перезапускает функции:
    удаляет записи (старше 7 дней), удаляет пользователей
    (которые заходили более полгода назад),
    резервирует выходные дни на 2 месяца и отправляет напоминания о записи.
    """
    await transactions.deleting_records_older_7_days()
    await transactions.deletes_old_users()

    try:
        reminder_time = REMINDER_TIME.split(":")
        reminder_hour = int(reminder_time[0])
        reminder_minute = int(reminder_time[1])

    except (IndexError, ValueError):
        reminder_hour = 8
        reminder_minute = 30

    while True:
        region_time = await region_current_datetime()

        if region_time.hour == reminder_hour and region_time.minute == reminder_minute:
            await transactions.deleting_records_older_7_days()
            await transactions.deletes_old_users()

            await reminder(region_time.date())

        # Напоминания за 10 минут до начала слота
        target_time = region_time + datetime.timedelta(minutes=10)
        await reminder_before_start(target_time)

        # Уведомление об оплате по окончании слота
        lessons_today = await transactions.lessons_for_date(region_time.date())
        for user_id, hour, minute, duration in lessons_today:
            end_time = datetime.datetime.combine(region_time.date(), datetime.time(hour, minute)) + datetime.timedelta(minutes=duration)
            if end_time.hour == region_time.hour and end_time.minute == region_time.minute:
                date_str = region_time.date().isoformat()
                time_str = f"{hour:02d}_{minute:02d}"
                profile = await get_student_profile(user_id) if user_id else None
                student_name = profile.full_name if profile else "Ученик"

                if profile and (profile.balance_lessons or 0) > 0:
                    new_balance = (profile.balance_lessons or 0) - 1
                    await change_balance(user_id, -1)
                    await add_payment(
                        telegram_id=user_id,
                        full_name=student_name,
                        lesson_date=region_time.date(),
                        hour=hour,
                        minute=minute,
                        duration_minutes=duration,
                        amount=None,
                        status="paid",
                        source="balance",
                    )
                    for admin_id in ADMINS_TELEGRAM_ID:
                        await bot.send_message(
                            chat_id=admin_id,
                            text=f"{student_name}: занятие {hour:02d}:{minute:02d} оплачено с баланса (осталось {new_balance}).",
                        )
                else:
                    pay = await add_payment(
                        telegram_id=user_id,
                        full_name=student_name,
                        lesson_date=region_time.date(),
                        hour=hour,
                        minute=minute,
                        duration_minutes=duration,
                        amount=None,
                        status="unpaid",
                        source="manual",
                    )
                    kb = payment_confirm_kb(payment_id=pay.id, date_str=date_str, time_str=time_str, duration=duration)
                    for admin_id in ADMINS_TELEGRAM_ID:
                        await bot.send_message(
                            chat_id=admin_id,
                            text=f"{student_name}: занятие {hour:02d}:{minute:02d} завершилось. Оплата получена?",
                            reply_markup=kb
                        )

        await asyncio.sleep(60)

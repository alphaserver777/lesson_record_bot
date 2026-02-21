"""Background scheduler in notification-only bot mode."""
import asyncio
import datetime
import logging

from config_data.config import REMINDER_TIME
from database import transactions
from utils.calendar_backend import get_calendar_tz
from utils.misc.reminder import reminder, reminder_before_delta, send_presence_prompts

logger = logging.getLogger(__name__)


async def restarting_services() -> None:
    """
    Notification-only scheduler:
    - daily cleanup,
    - daily presence prompts,
    - hourly pending presence pings,
    - reminders before lesson start.

    No admin UX/business flows (payments/stats/broadcasts) are executed here.
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

    reminder_total_minutes = reminder_hour * 60 + reminder_minute
    last_daily_presence_date: datetime.date | None = None

    while True:
        region_time = datetime.datetime.now(get_calendar_tz())
        current_date = region_time.date()
        current_total_minutes = region_time.hour * 60 + region_time.minute

        if last_daily_presence_date != current_date and current_total_minutes >= reminder_total_minutes:
            await transactions.deleting_records_older_7_days()
            await transactions.deletes_old_users()
            await reminder(current_date)
            last_daily_presence_date = current_date

        if region_time.minute == 0 and current_total_minutes > reminder_total_minutes:
            await send_presence_prompts(current_date, force_pending=False)

        target_time_10 = region_time + datetime.timedelta(minutes=10)
        target_time_60 = region_time + datetime.timedelta(minutes=60)
        try:
            await reminder_before_delta(target_time_60, 60)
            await reminder_before_delta(target_time_10, 10)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Reminder loop warning: %s", exc)

        await asyncio.sleep(60)

"""Интеграция с Google Calendar: свободные часы, создание и удаление событий."""
import asyncio
import datetime
import logging
from typing import Iterable, List, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config_data.config import (
    GOOGLE_CALENDAR_ID,
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_TIMEZONE,
)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendarError(Exception):
    """Исключения, связанные с работой Google Calendar."""


logger = logging.getLogger(__name__)
try:
    _tz = ZoneInfo(GOOGLE_TIMEZONE) if GOOGLE_TIMEZONE else ZoneInfo("UTC")
except ZoneInfoNotFoundError:
    _tz = ZoneInfo("UTC")


def _ensure_settings():
    if not GOOGLE_CREDENTIALS_FILE or not GOOGLE_CALENDAR_ID:
        raise GoogleCalendarError("Не заданы GOOGLE_CREDENTIALS_FILE или GOOGLE_CALENDAR_ID в .env")


def _get_service():
    _ensure_settings()
    creds = service_account.Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_FILE, scopes=SCOPES
    )
    # Создаем новый экземпляр клиента на каждый вызов, чтобы избежать проблем с потокобезопасностью httplib2.
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _parse_iso(dt_str: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00")).astimezone(_tz)


def get_calendar_tz():
    return _tz


async def list_events(time_min: str, time_max: str) -> List[dict]:
    """Возвращает список событий в заданном диапазоне (разворачивает повторяющиеся)."""
    def _call():
        return (
            _get_service()
            .events()
            .list(
                calendarId=GOOGLE_CALENDAR_ID,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

    try:
        resp = await asyncio.to_thread(_call)
        return resp.get("items", [])
    except HttpError as exc:
        raise GoogleCalendarError(f"Не удалось загрузить события: {exc}") from exc
    except Exception as exc:  # pylint: disable=broad-except
        raise GoogleCalendarError(f"Не удалось загрузить события: {exc}") from exc


async def get_busy_intervals(target_date: datetime.date) -> List[Tuple[datetime.datetime, datetime.datetime]]:
    """Возвращает занятые интервалы (start, end) в выбранный день из Google Calendar."""
    start_dt = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=_tz)
    end_dt = start_dt + datetime.timedelta(days=1)

    def _call():
        body = {
            "timeMin": start_dt.isoformat(),
            "timeMax": end_dt.isoformat(),
            "items": [{"id": GOOGLE_CALENDAR_ID}],
        }
        return _get_service().freebusy().query(body=body).execute()

    try:
        response = await asyncio.to_thread(_call)
    except HttpError as exc:
        raise GoogleCalendarError(f"Не удалось запросить занятость: {exc}") from exc
    except Exception as exc:  # pylint: disable=broad-except
        raise GoogleCalendarError(f"Не удалось запросить занятость: {exc}") from exc

    busy = response["calendars"][GOOGLE_CALENDAR_ID]["busy"]
    busy_intervals: List[Tuple[datetime.datetime, datetime.datetime]] = []

    for interval in busy:
        start = _parse_iso(interval["start"])
        end = _parse_iso(interval["end"])
        busy_intervals.append((start, end))

    return busy_intervals


async def create_booking(contact, date: datetime.date, hour: int, minute: int = 0, duration_minutes: int = 60) -> str:
    """
    Создаёт событие записи на час и возвращает event_id.
    contact ожидает объект Message.contact (aiogram).
    """
    start = datetime.datetime.combine(date, datetime.time(hour=hour, minute=minute), tzinfo=_tz)
    end = start + datetime.timedelta(minutes=duration_minutes)

    # Универсальный доступ к полям контакта (объект или словарь)
    first_name = getattr(contact, "first_name", None) or (contact.get("first_name") if isinstance(contact, dict) else "")
    last_name = getattr(contact, "last_name", None) or (contact.get("last_name") if isinstance(contact, dict) else "")
    phone_number = getattr(contact, "phone_number", None) or (contact.get("phone_number") if isinstance(contact, dict) else "")
    summary_parts = [
        "Запись",
        first_name or "",
        last_name or "",
    ]
    summary = " ".join(part for part in summary_parts if part).strip() or "Запись"
    description = f"Телефон: {phone_number}" if phone_number else ""

    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": str(_tz)},
        "end": {"dateTime": end.isoformat(), "timeZone": str(_tz)},
        "extendedProperties": {"private": {"source": "bot_service"}},
    }

    def _call():
        return _get_service().events().insert(calendarId=GOOGLE_CALENDAR_ID, body=body).execute()

    try:
        event = await asyncio.to_thread(_call)
        return event["id"]
    except HttpError as exc:
        raise GoogleCalendarError(f"Не удалось создать событие: {exc}") from exc
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Ошибка при создании события в календаре: %s", exc)
        raise GoogleCalendarError(f"Не удалось создать событие: {exc}") from exc


async def create_block_event(date: datetime.date, hour: int, minute: int, duration_minutes: int, note: str = "Зарезервировано") -> str:
    """
    Создаёт блокирующее событие на указанный слот (для резервирования дня админом).
    """
    start = datetime.datetime.combine(date, datetime.time(hour=hour, minute=minute), tzinfo=_tz)
    end = start + datetime.timedelta(minutes=duration_minutes)

    body = {
        "summary": note,
        "start": {"dateTime": start.isoformat(), "timeZone": str(_tz)},
        "end": {"dateTime": end.isoformat(), "timeZone": str(_tz)},
        "extendedProperties": {"private": {"source": "bot_service"}},
    }

    def _call():
        return _get_service().events().insert(calendarId=GOOGLE_CALENDAR_ID, body=body).execute()

    try:
        event = await asyncio.to_thread(_call)
        return event["id"]
    except HttpError as exc:
        raise GoogleCalendarError(f"Не удалось зарезервировать слот: {exc}") from exc
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Ошибка при создании блокирующего события: %s", exc)
        raise GoogleCalendarError(f"Не удалось зарезервировать слот: {exc}") from exc


async def create_full_day_block_event(date: datetime.date, note: str = "Резерв администратора") -> str:
    """
    Создаёт блокирующее событие на весь день.
    """
    start_date_str = date.isoformat()
    end_date_str = (date + datetime.timedelta(days=1)).isoformat()
    body = {
        "summary": note,
        "start": {"date": start_date_str, "timeZone": str(_tz)},
        "end": {"date": end_date_str, "timeZone": str(_tz)},
        "extendedProperties": {"private": {"source": "bot_service", "type": "full_day_block"}},
    }

    def _call():
        return _get_service().events().insert(calendarId=GOOGLE_CALENDAR_ID, body=body).execute()

    try:
        event = await asyncio.to_thread(_call)
        return event["id"]
    except HttpError as exc:
        raise GoogleCalendarError(f"Не удалось создать дневной резерв: {exc}") from exc
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Ошибка при создании дневного резерва: %s", exc)
        raise GoogleCalendarError(f"Не удалось создать дневной резерв: {exc}") from exc


async def delete_events(event_ids: Iterable[str]) -> None:
    """
    Удаляет события по списку event_id (тихо пропуская пустые).
    Делаем последовательно, чтобы избежать сбоев SSL при большом числе параллельных запросов.
    """
    ids = [event_id for event_id in event_ids if event_id]
    if not ids:
        return

    try:
        _ensure_settings()
    except GoogleCalendarError:
        # Если Google не сконфигурирован, просто выходим.
        return

    async def _delete_one(event_id: str) -> None:
        def _call():
            try:
                _get_service().events().delete(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
            except HttpError:
                # Игнорируем, если событие уже удалено или нет прав.
                return

        # Запускаем в отдельном потоке без массовой конкуренции
        try:
            await asyncio.to_thread(_call)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Ошибка при удалении события %s: %s", event_id, exc)

    for ev_id in ids:
        await _delete_one(ev_id)


async def delete_events_in_range(
    date: datetime.date, hour: int, minute: int, duration_minutes: int
) -> None:
    """
    Удаляет события в указанном промежутке времени, созданные ботом (extendedProperties.source=bot_service).
    Полезно для удаления одиночных вхождений даже у повторяющихся событий.
    """
    start = datetime.datetime.combine(date, datetime.time(hour=hour, minute=minute), tzinfo=_tz)
    end = start + datetime.timedelta(minutes=duration_minutes)

    def _list_events():
        return (
            _get_service()
            .events()
            .list(
                calendarId=GOOGLE_CALENDAR_ID,
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                showDeleted=False,
                privateExtendedProperty="source=bot_service",
            )
            .execute()
        )

    try:
        events_resp = await asyncio.to_thread(_list_events)
    except HttpError as exc:
        logger.warning("Не удалось получить события для удаления: %s", exc)
        return
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Ошибка при запросе событий для удаления: %s", exc)
        return

    items = events_resp.get("items", [])
    if not items:
        return

    async def _delete(event_id: str):
        def _call():
            try:
                _get_service().events().delete(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
            except HttpError:
                return

        try:
            await asyncio.to_thread(_call)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Ошибка при удалении события %s: %s", event_id, exc)

    for ev in items:
        await _delete(ev["id"])

"""Модуль работы с базой данных."""
import datetime
from typing import Any

from sqlalchemy import func, select, text

from database.connect import Base, engine, session
from database.models import RecordDate, RegularLesson, StudentProfile
from utils.google_calendar import (
    GoogleCalendarError,
    create_block_event,
    create_full_day_block_event,
    create_booking,
    delete_events,
    delete_events_in_range,
    get_busy_intervals,
    get_calendar_tz,
)
from utils.schedule import SLOT_DURATION_MINUTES, slots_for_date


async def init_db() -> None:
    """Функция init_db. При отсутствии базы донных создаёт их."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_event_id_column()
    await _ensure_minute_column()
    await _ensure_regular_lessons_columns()
    await _ensure_student_profiles_columns()


async def _ensure_event_id_column() -> None:
    """Добавляет колонку event_id в record_dates, если её нет (для синхронизации с Google)."""
    columns = await session.execute(text("PRAGMA table_info('record_dates')"))
    column_names = {row[1] for row in columns}
    if "event_id" not in column_names:
        await session.execute(text("ALTER TABLE record_dates ADD COLUMN event_id VARCHAR(255)"))
        await session.commit()


async def _ensure_minute_column() -> None:
    """Добавляет колонку minute/duration, если их нет."""
    columns = await session.execute(text("PRAGMA table_info('record_dates')"))
    column_names = {row[1] for row in columns}
    if "minute" not in column_names:
        await session.execute(text("ALTER TABLE record_dates ADD COLUMN minute INTEGER DEFAULT 0 NOT NULL"))
        await session.commit()
    if "duration_minutes" not in column_names:
        await session.execute(text("ALTER TABLE record_dates ADD COLUMN duration_minutes INTEGER DEFAULT 60 NOT NULL"))
        await session.commit()
    # Предполагаем, что колонка telegram_id может быть NULL в новой схеме; если нет — потребуется пересоздание таблицы


async def _ensure_regular_lessons_columns() -> None:
    """Добавляет недостающие колонки для regular_lessons."""
    columns = await session.execute(text("PRAGMA table_info('regular_lessons')"))
    column_names = {row[1] for row in columns}
    if "day_of_week" not in column_names:
        await session.execute(text("ALTER TABLE regular_lessons ADD COLUMN day_of_week INTEGER"))
        await session.commit()
    if "lesson_date" not in column_names:
        await session.execute(text("ALTER TABLE regular_lessons ADD COLUMN lesson_date DATE"))
        await session.commit()
    if "duration_minutes" not in column_names:
        await session.execute(text("ALTER TABLE regular_lessons ADD COLUMN duration_minutes INTEGER DEFAULT 60"))
        await session.commit()


async def _ensure_student_profiles_columns() -> None:
    """Добавляет недостающие колонки в student_profiles (telephone и др.)."""
    columns = await session.execute(text("PRAGMA table_info('student_profiles')"))
    column_names = {row[1] for row in columns}
    if "telephone" not in column_names:
        await session.execute(text("ALTER TABLE student_profiles ADD COLUMN telephone VARCHAR(20)"))
        await session.commit()
    if "blocked" not in column_names:
        await session.execute(text("ALTER TABLE student_profiles ADD COLUMN blocked BOOLEAN DEFAULT 0"))
        await session.commit()
    if "last_visit_date" not in column_names:
        await session.execute(text("ALTER TABLE student_profiles ADD COLUMN last_visit_date VARCHAR(50)"))
        await session.commit()


async def deleting_records_older_7_days() -> None:
    """Функция deleting_records_older_7_days. Удаляет записи старее 7 дней."""
    sql = text(
        """
        DELETE FROM record_dates WHERE record_date < datetime('now', '-7 days')
        """
    )
    await session.execute(sql)
    await session.commit()


async def deletes_old_users() -> None:
    """Функция deletes_old_users. Удаляет пользователей, которые не заходили полгода."""
    sql = text(
        """
        DELETE FROM student_profiles WHERE last_visit_date < datetime('now', '-6 month')
        """
    )
    await session.execute(sql)
    await session.commit()


async def user_check(telegram_id: int) -> tuple[Any]:
    """Функция user_check. Проверяет создан ли пользователь и возвращает статус его блокировки."""
    res = await session.execute(select(StudentProfile.blocked).where(StudentProfile.telegram_id == telegram_id))
    return res.one_or_none()


async def add_user(telegram_id: int, full_name: str) -> None:
    """Функция add_user. Добавляет новый профиль (идемпотентно)."""
    profile = await session.get(StudentProfile, telegram_id)
    if profile is None:
        profile = StudentProfile(telegram_id=telegram_id, full_name=full_name)
        session.add(profile)
    else:
        if full_name and full_name != profile.full_name:
            profile.full_name = full_name
    await session.commit()


async def update_visit_date(telegram_id: int) -> None:
    """Функция update_visit_date. Обновляет время посещения пользователя."""
    now = datetime.datetime.now()
    profile = await session.get(StudentProfile, telegram_id)
    if profile:
        profile.last_visit_date = now.isoformat()
    await session.commit()


async def update_phone(telegram_id: int, phone_number: str) -> None:
    """Обновляет телефон пользователя."""
    profile = await session.get(StudentProfile, telegram_id)
    if profile:
        profile.telephone = phone_number
    await session.commit()


async def get_student_profile(telegram_id: int) -> StudentProfile | None:
    """Возвращает профиль ученика по telegram_id."""
    return await session.get(StudentProfile, telegram_id)


async def count_date_rec(telegram_id: int) -> int:
    """Функция count_date_rec. Возвращает количество записей пользователя."""
    res = await session.execute(select(func.count()).where(RecordDate.telegram_id == telegram_id))
    return res.one_or_none()


async def get_date_time_appointment(date: datetime) -> list[Any]:
    """Функция get_date_time_appointment. Возвращает дату и время записи пользователя."""
    # date = datetime_trans_str(date)
    res = await session.execute(
        select(RecordDate.hour, RecordDate.minute, RecordDate.telegram_id).where(RecordDate.record_date == date)
    )
    return res.all()


async def check_date_time_appointment(date: datetime, hour: int, minute: int) -> list[Any]:
    """Функция check_date_time_appointment. Проверяет занята дата и время записи (по Google)."""
    busy_intervals = await get_busy_intervals(date)
    slot_start = datetime.datetime.combine(
        date, datetime.time(hour, minute), tzinfo=get_calendar_tz()
    )
    slot_end = slot_start + datetime.timedelta(minutes=SLOT_DURATION_MINUTES)
    for start, end in busy_intervals:
        if slot_start < end and slot_end > start:
            return [(hour, minute)]
    return []


async def is_slot_busy(date: datetime.date, hour: int, minute: int) -> bool:
    """True если слот занят в Google Calendar."""
    busy_intervals = await get_busy_intervals(date)
    slot_start = datetime.datetime.combine(
        date, datetime.time(hour, minute), tzinfo=get_calendar_tz()
    )
    slot_end = slot_start + datetime.timedelta(minutes=SLOT_DURATION_MINUTES)
    for start, end in busy_intervals:
        if slot_start < end and slot_end > start:
            return True
    return False


async def set_date_time_appointment(contact, date: datetime, hour: int, minute: int) -> bool:
    """Функция set_date_time_appointment. Обновляет номер телефона пользователя
    и записает на его на приём. Возвращает True если запись успешно создана в Google."""
    if hasattr(contact, "phone_number"):
        phone_number = contact.phone_number
        telegram_id = contact.user_id
        first_name = contact.first_name if hasattr(contact, "first_name") else ""
        last_name = contact.last_name if hasattr(contact, "last_name") else ""
    else:
        phone_number = contact.get("phone_number")
        telegram_id = contact.get("user_id")
        first_name = contact.get("first_name", "")
        last_name = contact.get("last_name", "")

    res = await user_check(telegram_id)
    if not res:
        full_name = [last_name if last_name else "", first_name if first_name else ""]
        full_name = " ".join(full_name).strip()
        await add_user(telegram_id, full_name)

    await update_phone(telegram_id, phone_number)

    try:
        event_id = await create_booking(contact, date, hour, minute, SLOT_DURATION_MINUTES)
    except GoogleCalendarError:
        return False

    record = RecordDate(
        telegram_id=telegram_id,
        record_date=date,
        hour=hour,
        minute=minute,
        event_id=event_id,
    )

    session.add(record)
    await session.commit()
    return True


async def del_record(date: datetime, hour: int, minute: int) -> None:
    """Функция del_record. Удаляет запись."""
    record = await session.execute(
        select(RecordDate).where(
            RecordDate.record_date == date, RecordDate.hour == hour, RecordDate.minute == minute
        )
    )
    record = record.scalar()

    if record:
        await delete_events([record.event_id])
        try:
            await delete_events_in_range(date, hour, minute, SLOT_DURATION_MINUTES)
        except Exception:
            # игнорируем сетевые ошибки при удалении события
            pass
        await session.delete(record)
        await session.commit()


async def del_record_all_day(date: datetime) -> None:
    """Функция del_record. Удаляет все записи на день."""
    res = await session.execute(select(RecordDate).where(RecordDate.record_date == date))
    res = res.all()

    if res:
        try:
            await delete_events(obj[0].event_id for obj in res)
        except Exception:  # calendar errors игнорируются, чтобы очистить локально
            pass
        # Дополнительно пытаемся удалить события, помеченные ботом, в каждом слоте дня
        for obj in res:
            try:
                await delete_events_in_range(date, obj[0].hour, obj[0].minute, SLOT_DURATION_MINUTES)
            except Exception:
                # игнорируем сетевые ошибки при удалении, локально чистим
                pass
        for obj in res:
            await session.delete(obj[0])
        await session.commit()


async def view_clients() -> list[Any]:
    """Функция view_clients. Возвращает всех клиентов из профилей."""
    res = await session.execute(select(StudentProfile))
    return res.all()


async def view_record(telegram_id: int) -> list[Any]:
    """Функция view_record. Возвращает все записи пользователя."""
    res = await session.execute(
        select(RecordDate.record_date, RecordDate.hour, RecordDate.minute).where(RecordDate.telegram_id == telegram_id).order_by(
            RecordDate.record_date, RecordDate.hour, RecordDate.minute))
    return res.all()


async def view_regular_lessons(telegram_id: int) -> list[Any]:
    """Возвращает регулярные занятия пользователя."""
    res = await session.execute(
        select(
            RegularLesson.day_of_week,
            RegularLesson.hour,
            RegularLesson.minute,
            RegularLesson.duration_minutes,
        ).where(RegularLesson.telegram_id == telegram_id).order_by(
            RegularLesson.day_of_week, RegularLesson.hour, RegularLesson.minute
        )
    )
    return res.all()


async def block_unblock_user(telegram_id: int, action: str) -> None:
    """Функция block_unblock_user. Блокирует и разблокирует пользователя."""
    profile = await session.get(StudentProfile, telegram_id)
    if profile:
        profile.blocked = 1 if action == "bl" else 0
    await session.commit()


async def del_user(telegram_id: int) -> None:
    """Функция del_user. Удаляет пользователя."""
    profile = await session.get(StudentProfile, telegram_id)
    if profile:
        await session.delete(profile)
    await session.commit()


async def search_client(search_text: str) -> list[Any]:
    """Функция search_client. Ищет пользователей по имени и номеру телефона."""
    res = await session.execute(select(StudentProfile).where(StudentProfile.telephone.ilike(f'%{search_text}%')))
    res = res.all()

    if not res:
        res = await session.execute(select(StudentProfile).where(StudentProfile.full_name.ilike(f'%{search_text}%')))
        res = res.all()
    return res


async def reserve_day(
        telegram_id: int, date: datetime, beginning_working_day: int, end_working_day: int
) -> int:
    """Функция reserve_day. Резервирует день одним событием."""
    try:
        event_id = await create_full_day_block_event(date, "Резерв администратора")
    except GoogleCalendarError:
        return 0

    record = RecordDate(
        telegram_id=telegram_id,
        record_date=date,
        hour=0,
        minute=0,
        event_id=event_id,
    )
    session.add(record)
    await session.commit()
    return 1


async def mailing_for_day(date: datetime) -> list[Any]:
    """Функция mailing_for_day. Возвращает всех пользователя кто записан на день."""
    res = await session.execute(
        select(RecordDate.telegram_id, RecordDate.hour, RecordDate.minute).where(RecordDate.record_date == date).group_by(RecordDate.telegram_id, RecordDate.hour, RecordDate.minute))
    return res.all()


async def viewing_recordings_day_db(date: datetime) -> list[Any]:
    """Функция viewing_recordings_day_db. Возвращает все записи на день."""
    res = await (session.execute(select(StudentProfile.full_name, StudentProfile.telephone, RecordDate.hour, RecordDate.minute).
                                 join(StudentProfile, StudentProfile.telegram_id == RecordDate.telegram_id).
                                 where(RecordDate.record_date == date).order_by(RecordDate.hour, RecordDate.minute)))
    return res.all()


async def get_info_user(date: datetime, hour: int, minute: int) -> Any:
    """Функция get_info_user. Возвращает ид пользователя."""
    res = await (session.execute(select(RecordDate.telegram_id).
                                 where(RecordDate.record_date == date, RecordDate.hour == hour, RecordDate.minute == minute)))
    return res.one_or_none()


async def records_starting_at(date: datetime.date, hour: int, minute: int) -> list[Any]:
    """Возвращает записи, начинающиеся в заданное время (для напоминаний)."""
    res = await session.execute(
        select(
            StudentProfile.telegram_id,
            StudentProfile.full_name,
            StudentProfile.telephone,
            RecordDate.hour,
            RecordDate.minute,
        )
        .join(StudentProfile, StudentProfile.telegram_id == RecordDate.telegram_id)
        .where(
            RecordDate.record_date == date,
            RecordDate.hour == hour,
            RecordDate.minute == minute,
        )
    )
    return res.all()


# --- Постоянные занятия ---
async def add_regular_lesson(
        full_name: str,
        username: str | None,
        cost: int | None,
        day_of_week: int,
        hour: int,
        minute: int = 0,
        duration_minutes: int = 60,
        telegram_id: int | None = None,
) -> None:
    """Добавляет запись о постоянном занятии (еженедельный слот). day_of_week: 0=Пн ... 6=Вс."""
    lesson = RegularLesson(
        telegram_id=telegram_id,
        full_name=full_name,
        username=username,
        cost=cost,
        day_of_week=day_of_week,
        hour=hour,
        minute=minute,
        duration_minutes=duration_minutes,
    )
    session.add(lesson)
    await session.commit()


async def list_regular_lessons() -> list[Any]:
    """Возвращает все постоянные занятия."""
    res = await session.execute(
        select(RegularLesson).order_by(RegularLesson.day_of_week, RegularLesson.hour, RegularLesson.minute)
    )
    return res.all()


# --- Профили учеников ---
async def upsert_student_profile(
        telegram_id: int,
        full_name: str | None = None,
        age: int | None = None,
        price: int | None = None,
        direction: str | None = None,
        goal: str | None = None,
        notes: str | None = None,
) -> None:
    """
    Создаёт или обновляет профиль ученика.
    """
    profile = await session.get(StudentProfile, telegram_id)
    if profile is None:
        profile = StudentProfile(telegram_id=telegram_id)
        session.add(profile)

    if full_name is not None:
        profile.full_name = full_name
    if age is not None:
        profile.age = age
    if price is not None:
        profile.price = price
    if direction is not None:
        profile.direction = direction
    if goal is not None:
        profile.goal = goal
    if notes is not None:
        profile.notes = notes

    await session.commit()


async def get_student_profile(telegram_id: int) -> StudentProfile | None:
    """Возвращает профиль ученика по telegram_id."""
    return await session.get(StudentProfile, telegram_id)


async def list_student_profiles() -> list[Any]:
    """Возвращает все профили учеников."""
    res = await session.execute(select(StudentProfile))
    return res.all()


async def lessons_for_date(date: datetime.date) -> list[Any]:
    """Возвращает все занятия (разовые + регулярные) на дату."""
    # разовые
    single = await session.execute(
        select(
            RecordDate.telegram_id,
            RecordDate.hour,
            RecordDate.minute,
            RecordDate.duration_minutes,
        ).where(RecordDate.record_date == date)
    )
    result = [(row.telegram_id, row.hour, row.minute, row.duration_minutes) for row in single]

    # регулярные по дню недели
    weekday = date.weekday()
    regular = await session.execute(
        select(
            RegularLesson.telegram_id,
            RegularLesson.hour,
            RegularLesson.minute,
            RegularLesson.duration_minutes,
        ).where(RegularLesson.day_of_week == weekday)
    )
    result.extend((row.telegram_id, row.hour, row.minute, row.duration_minutes) for row in regular)
    return result

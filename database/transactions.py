"""Модуль работы с базой данных."""
import datetime
import logging
from typing import Any

from sqlalchemy import case, delete, func, select, text

from database.connect import Base, engine, session
from database.models import Payment, RecordDate, RegularLesson, StudentProfile
from utils.calendar_backend import (
    CalendarBackendError,
    create_block_event,
    create_booking,
    create_simple_event,
    create_full_day_block_event,
    delete_events,
    delete_events_in_range,
    get_busy_intervals,
    get_calendar_tz,
)
from utils.sync_calendar import push_db_events_to_calendar
from utils.schedule import SLOT_DURATION_MINUTES, slots_for_date

logger = logging.getLogger(__name__)


def _build_event_summary(full_name: str | None, kind: str) -> str:
    """Формирует заголовок события с именем ученика и типом записи."""
    kind_label = "Регулярное" if kind == "regular" else "Разовое"
    name = (full_name or "").strip() or "Запись"
    return f"{name} ({kind_label})"


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_event_id_column()
    await _ensure_minute_column()
    await _ensure_record_kind_column()
    await _ensure_record_note_column()
    await _ensure_presence_columns()
    await _ensure_regular_lessons_columns()
    await _ensure_student_profiles_columns()
    await _ensure_payments_columns()
    await _normalize_record_kinds()


async def _ensure_event_id_column() -> None:
    columns = await session.execute(text("PRAGMA table_info('record_dates')"))
    column_names = {row[1] for row in columns}
    if "event_id" not in column_names:
        await session.execute(text("ALTER TABLE record_dates ADD COLUMN event_id VARCHAR(255)"))
        await session.commit()


async def _ensure_minute_column() -> None:
    columns = await session.execute(text("PRAGMA table_info('record_dates')"))
    column_names = {row[1] for row in columns}
    if "minute" not in column_names:
        await session.execute(text("ALTER TABLE record_dates ADD COLUMN minute INTEGER DEFAULT 0 NOT NULL"))
        await session.commit()
    if "duration_minutes" not in column_names:
        await session.execute(text("ALTER TABLE record_dates ADD COLUMN duration_minutes INTEGER DEFAULT 60 NOT NULL"))
        await session.commit()


async def _ensure_record_kind_column() -> None:
    columns = await session.execute(text("PRAGMA table_info('record_dates')"))
    column_names = {row[1] for row in columns}
    if "kind" not in column_names:
        await session.execute(text("ALTER TABLE record_dates ADD COLUMN kind VARCHAR(20) DEFAULT 'single'"))
        await session.commit()


async def _ensure_presence_columns() -> None:
    columns = await session.execute(text("PRAGMA table_info('record_dates')"))
    column_names = {row[1] for row in columns}
    if "presence_status" not in column_names:
        await session.execute(text("ALTER TABLE record_dates ADD COLUMN presence_status VARCHAR(20)"))
        await session.commit()
    if "presence_last_reminder" not in column_names:
        await session.execute(text("ALTER TABLE record_dates ADD COLUMN presence_last_reminder VARCHAR(50)"))
        await session.commit()
    if "presence_message_id" not in column_names:
        await session.execute(text("ALTER TABLE record_dates ADD COLUMN presence_message_id INTEGER"))
        await session.commit()


async def _ensure_record_note_column() -> None:
    columns = await session.execute(text("PRAGMA table_info('record_dates')"))
    column_names = {row[1] for row in columns}
    if "note" not in column_names:
        await session.execute(text("ALTER TABLE record_dates ADD COLUMN note VARCHAR(255)"))
        await session.commit()


async def _normalize_record_kinds() -> None:
    # Блокеры без владельца помечаем как block (кроме allow)
    await session.execute(
        text(
            "UPDATE record_dates SET kind='block' "
            "WHERE telegram_id IS NULL "
            "AND (kind IS NULL OR (kind NOT IN ('block','allow')))"
        )
    )
    # Записи, совпадающие с регулярками по дню недели/времени, помечаем как regular
    await session.execute(
        text(
            """
            UPDATE record_dates
            SET kind='regular'
            WHERE telegram_id IS NOT NULL
              AND (kind IS NULL OR kind != 'regular')
              AND EXISTS (
                SELECT 1 FROM regular_lessons rl
                WHERE rl.telegram_id = record_dates.telegram_id
                  AND rl.day_of_week = ((CAST(strftime('%w', record_dates.record_date) AS INTEGER) + 6) % 7)
                  AND rl.hour = record_dates.hour
                  AND rl.minute = record_dates.minute
              )
            """
        )
    )
    await session.commit()


# --- Presence confirmation ---
async def pending_presence_for_date(date: datetime.date) -> list[Any]:
    target_date = date

    # Блоки/allow на день — не шлём напоминания для таких слотов
    block_allow = await session.execute(
        select(RecordDate.hour, RecordDate.minute).where(
            RecordDate.record_date == target_date,
            RecordDate.kind.in_(["block", "allow"]),
        )
    )
    blocked_times = {(row.hour, row.minute) for row in block_allow}

    # Существующие записи
    res = await session.execute(
        select(
            RecordDate.id,
            RecordDate.telegram_id,
            RecordDate.record_date,
            RecordDate.hour,
            RecordDate.minute,
            RecordDate.duration_minutes,
            RecordDate.presence_status,
            RecordDate.presence_last_reminder,
            RecordDate.presence_message_id,
            RecordDate.kind,
        ).where(
            RecordDate.record_date == target_date,
            RecordDate.telegram_id.is_not(None),
            RecordDate.kind.not_in(["block", "allow"]),
        )
    )
    records = res.all()
    seen_slots = {(row[1], row[3], row[4]) for row in records}

    # Добавляем регулярки на этот день, если слота нет в record_dates, и создаём запись для хранения статуса
    weekday = target_date.weekday()
    regulars = await session.execute(
        select(
            RegularLesson.telegram_id,
            RegularLesson.hour,
            RegularLesson.minute,
            RegularLesson.duration_minutes,
        ).where(
            RegularLesson.day_of_week == weekday,
            RegularLesson.telegram_id.is_not(None),
        )
    )
    new_records: list[tuple] = []
    for lesson in regulars:
        key = (lesson.telegram_id, lesson.hour, lesson.minute)
        if key in seen_slots:
            continue
        if (lesson.hour, lesson.minute) in blocked_times:
            continue
        try:
            rec = RecordDate(
                telegram_id=lesson.telegram_id,
                record_date=target_date,
                hour=lesson.hour or 0,
                minute=lesson.minute or 0,
                duration_minutes=lesson.duration_minutes or SLOT_DURATION_MINUTES,
                kind="regular",
                presence_status=None,
                event_id=None,
            )
            session.add(rec)
            await session.commit()
            new_records.append(
                (
                    rec.id,
                    rec.telegram_id,
                    rec.record_date,
                    rec.hour,
                    rec.minute,
                    rec.duration_minutes,
                    rec.presence_status,
                    rec.presence_last_reminder,
                    rec.presence_message_id,
                    rec.kind,
                )
            )
        except Exception:
            continue

    return records + new_records


async def mark_presence_status(
    telegram_id: int,
    date: datetime.date,
    hour: int,
    minute: int,
    status: str,
    presence_message_id: int | None = None,
) -> None:
    rec = await session.execute(
        select(RecordDate).where(
            RecordDate.telegram_id == telegram_id,
            RecordDate.record_date == date,
            RecordDate.hour == hour,
            RecordDate.minute == minute,
        ).order_by(RecordDate.id.asc())
    )
    rec_obj = rec.scalars().first()
    if rec_obj:
        rec_obj.presence_status = status
        rec_obj.presence_last_reminder = datetime.datetime.now().isoformat()
        rec_obj.presence_message_id = presence_message_id
        # Чистим дубликаты, если есть
        dupes = await session.execute(
            select(RecordDate).where(
                RecordDate.telegram_id == telegram_id,
                RecordDate.record_date == date,
                RecordDate.hour == hour,
                RecordDate.minute == minute,
                RecordDate.id != rec_obj.id,
            )
        )
        for dup in dupes.scalars():
            await session.delete(dup)
        await session.commit()


async def _ensure_regular_lessons_columns() -> None:
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
    if "balance_lessons" not in column_names:
        await session.execute(text("ALTER TABLE student_profiles ADD COLUMN balance_lessons INTEGER DEFAULT 0"))
        await session.commit()
    if "telegram_username" not in column_names:
        await session.execute(text("ALTER TABLE student_profiles ADD COLUMN telegram_username VARCHAR(100)"))
        await session.commit()


async def _ensure_payments_columns() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Payment.__table__.create, checkfirst=True)
    columns = await session.execute(text("PRAGMA table_info('payments')"))
    column_names = {row[1] for row in columns}
    if "source" not in column_names:
        await session.execute(text("ALTER TABLE payments ADD COLUMN source VARCHAR(50)"))
        await session.commit()


async def deleting_records_older_7_days() -> None:
    sql = text("DELETE FROM record_dates WHERE record_date < datetime('now', '-7 days')")
    await session.execute(sql)
    await session.commit()


async def deletes_old_users() -> None:
    sql = text("DELETE FROM student_profiles WHERE last_visit_date < datetime('now', '-6 month')")
    await session.execute(sql)
    await session.commit()


async def user_check(telegram_id: int) -> tuple[Any]:
    res = await session.execute(select(StudentProfile.blocked).where(StudentProfile.telegram_id == telegram_id))
    return res.one_or_none()


async def add_user(telegram_id: int, full_name: str) -> None:
    profile = await session.get(StudentProfile, telegram_id)
    if profile is None:
        profile = StudentProfile(telegram_id=telegram_id, full_name=full_name)
        session.add(profile)
    else:
        if full_name and full_name != profile.full_name:
            profile.full_name = full_name
    await session.commit()


async def upsert_student_profile(
    telegram_id: int,
    full_name: str | None = None,
    age: int | None = None,
    username: str | None = None,
    price: int | None = None,
    direction: str | None = None,
    goal: str | None = None,
    notes: str | None = None,
    telephone: str | None = None,
    balance_lessons: int | None = None,
) -> StudentProfile:
    """
    Создает профиль студента, если его нет, или обновляет переданные поля.
    Незаполненные поля (None) не затирают существующие значения.
    """
    profile = await session.get(StudentProfile, telegram_id)
    if profile is None:
        profile = StudentProfile(telegram_id=telegram_id)
        session.add(profile)

    if full_name is not None:
        profile.full_name = full_name
    if age is not None:
        profile.age = age
    if username is not None:
        profile.telegram_username = username
    if price is not None:
        profile.price = price
    if direction is not None:
        profile.direction = direction
    if goal is not None:
        profile.goal = goal
    if notes is not None:
        profile.notes = notes
    if telephone is not None:
        profile.telephone = telephone
    if balance_lessons is not None:
        profile.balance_lessons = balance_lessons

    await session.commit()
    return profile


async def update_visit_date(telegram_id: int) -> None:
    now = datetime.datetime.now()
    profile = await session.get(StudentProfile, telegram_id)
    if profile:
        profile.last_visit_date = now.isoformat()
    await session.commit()


async def update_phone(telegram_id: int, phone_number: str) -> None:
    profile = await session.get(StudentProfile, telegram_id)
    if profile:
        profile.telephone = phone_number
    await session.commit()


async def get_student_profile(telegram_id: int) -> StudentProfile | None:
    return await session.get(StudentProfile, telegram_id)


async def list_student_profiles() -> list[Any]:
    res = await session.execute(select(StudentProfile))
    return res.all()


async def change_balance(telegram_id: int, delta: int) -> None:
    profile = await session.get(StudentProfile, telegram_id)
    if profile:
        profile.balance_lessons = (profile.balance_lessons or 0) + delta
        await session.commit()


async def count_date_rec(telegram_id: int) -> int:
    res = await session.execute(select(func.count()).where(RecordDate.telegram_id == telegram_id))
    return res.one_or_none()


async def set_balance(telegram_id: int, balance: int) -> None:
    profile = await session.get(StudentProfile, telegram_id)
    if profile:
        profile.balance_lessons = balance
        await session.commit()


async def get_date_time_appointment(date: datetime) -> list[Any]:
    res = await session.execute(
        select(RecordDate.hour, RecordDate.minute, RecordDate.telegram_id).where(RecordDate.record_date == date)
    )
    return res.all()


async def check_date_time_appointment(date: datetime, hour: int, minute: int) -> list[Any]:
    busy_intervals = await get_busy_intervals(date)
    slot_start = datetime.datetime.combine(date, datetime.time(hour, minute), tzinfo=get_calendar_tz())
    slot_end = slot_start + datetime.timedelta(minutes=SLOT_DURATION_MINUTES)
    for start, end in busy_intervals:
        if slot_start < end and slot_end > start:
            return [(hour, minute)]
    return []


async def is_slot_busy(date: datetime.date, hour: int, minute: int) -> bool:
    busy_intervals = await get_busy_intervals(date)
    slot_start = datetime.datetime.combine(date, datetime.time(hour, minute), tzinfo=get_calendar_tz())
    slot_end = slot_start + datetime.timedelta(minutes=SLOT_DURATION_MINUTES)
    for start, end in busy_intervals:
        if slot_start < end and slot_end > start:
            return True
    return False


async def set_date_time_appointment(contact, date: datetime, hour: int, minute: int) -> bool:
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
        full_name = " ".join([last_name or "", first_name or ""]).strip()
        await add_user(telegram_id, full_name)

    await update_phone(telegram_id, phone_number)

    try:
        event_id = await create_booking(contact, date, hour, minute, SLOT_DURATION_MINUTES)
    except CalendarBackendError:
        return False

    record = RecordDate(
        telegram_id=telegram_id,
        record_date=date,
        hour=hour,
        minute=minute,
        duration_minutes=SLOT_DURATION_MINUTES,
        kind="single",
        event_id=event_id,
    )
    session.add(record)
    await session.commit()
    return True


async def add_single_slot(
    telegram_id: int,
    date: datetime.date,
    hour: int,
    minute: int,
    duration_minutes: int = SLOT_DURATION_MINUTES,
    summary: str | None = None,
) -> bool:
    """
    Добавляет разовое занятие от имени администратора: создаёт событие в календаре и запись в БД.
    """
    profile = await session.get(StudentProfile, telegram_id)
    summary_text = summary or _build_event_summary(profile.full_name if profile else None, "single")

    try:
        event_id = await create_simple_event(
            date,
            hour,
            minute,
            duration_minutes,
            summary=summary_text,
            telegram_id=telegram_id,
            kind="single",
        )
    except CalendarBackendError:
        return False

    record = RecordDate(
        telegram_id=telegram_id,
        record_date=date,
        hour=hour,
        minute=minute,
        duration_minutes=duration_minutes,
        kind="single",
        event_id=event_id,
    )
    session.add(record)
    await session.commit()
    return True


async def add_regular_slot(
    telegram_id: int,
    day_of_week: int,
    hour: int,
    minute: int,
    duration_minutes: int = SLOT_DURATION_MINUTES,
    full_name: str | None = None,
) -> None:
    profile = await session.get(StudentProfile, telegram_id) if telegram_id else None
    lesson_title = full_name or (profile.full_name if profile else None) or "Регулярное занятие"
    lesson = RegularLesson(
        telegram_id=telegram_id,
        full_name=lesson_title,
        username=None,
        cost=None,
        day_of_week=day_of_week,
        lesson_date=None,
        hour=hour,
        minute=minute,
        duration_minutes=duration_minutes,
    )
    session.add(lesson)
    await session.commit()

    # Выгружаем новые регулярки в календарь сразу, чтобы слоты были забронированы
    try:
        await push_db_events_to_calendar(days_ahead=30)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Не удалось синхронизировать регулярку в календарь: %s", exc)


async def delete_single_slot(
    telegram_id: int,
    date: datetime.date,
    hour: int,
    minute: int,
) -> None:
    rec = await session.execute(
        select(RecordDate).where(
            RecordDate.telegram_id == telegram_id,
            RecordDate.record_date == date,
            RecordDate.hour == hour,
            RecordDate.minute == minute,
        )
    )
    rec = rec.scalar()
    if rec:
        await delete_events([rec.event_id])
        try:
            await delete_events_in_range(date, hour, minute, rec.duration_minutes or SLOT_DURATION_MINUTES)
        except Exception:
            pass
        await session.delete(rec)
        await session.commit()


async def delete_regular_slot(
    telegram_id: int,
    day_of_week: int,
    hour: int,
    minute: int,
    delete_future_single: bool = True,
) -> None:
    lessons = await session.execute(
        select(RegularLesson).where(
            RegularLesson.telegram_id == telegram_id,
            RegularLesson.day_of_week == day_of_week,
            RegularLesson.hour == hour,
            RegularLesson.minute == minute,
        )
    )
    for lesson in lessons.scalars():
        await session.delete(lesson)

    if delete_future_single:
        today = datetime.date.today()
        records = await session.execute(
            select(RecordDate).where(
                RecordDate.telegram_id == telegram_id,
                RecordDate.record_date >= today,
                RecordDate.hour == hour,
                RecordDate.minute == minute,
            )
        )
        for rec in records.scalars():
            await delete_events([rec.event_id])
            try:
                await delete_events_in_range(rec.record_date, rec.hour, rec.minute, rec.duration_minutes or SLOT_DURATION_MINUTES)
            except Exception:
                pass
            await session.delete(rec)

    await session.commit()


async def del_record(date: datetime, hour: int, minute: int) -> None:
    records_res = await session.execute(
        select(RecordDate)
        .where(RecordDate.record_date == date, RecordDate.hour == hour, RecordDate.minute == minute)
        .order_by(RecordDate.id.asc())
    )
    records = records_res.scalars().all()
    if not records:
        return

    if len(records) > 1:
        logger.warning(
            "del_record: найдено несколько записей на слот date=%s time=%02d:%02d count=%s",
            date,
            hour,
            minute,
            len(records),
        )

    has_non_block = any((rec.kind or "single") not in ("block", "allow") for rec in records)
    duration = next(
        (rec.duration_minutes for rec in records if rec.duration_minutes),
        SLOT_DURATION_MINUTES,
    )

    for rec in records:
        await delete_events([rec.event_id])
        await session.delete(rec)
    await session.commit()

    try:
        await delete_events_in_range(date, hour, minute, duration)
    except Exception:
        pass

    # Блокируем слот только если удалили пользовательскую запись
    if has_non_block:
        await ensure_block_slot(date, hour, minute, duration)


async def cancel_regular_slot_with_allow(date: datetime.date, hour: int, minute: int, note: str | None = None) -> None:
    """
    Удаляет запись (если есть) и ставит allow, чтобы регулярка не восстановилась,
    но слот не отображался как блок.
    """
    records_res = await session.execute(
        select(RecordDate)
        .where(RecordDate.record_date == date, RecordDate.hour == hour, RecordDate.minute == minute)
        .order_by(RecordDate.id.asc())
    )
    records = records_res.scalars().all()
    if records:
        if len(records) > 1:
            logger.warning(
                "cancel_regular_slot_with_allow: найдено несколько записей на слот date=%s time=%02d:%02d count=%s",
                date,
                hour,
                minute,
                len(records),
            )
        duration = next(
            (rec.duration_minutes for rec in records if rec.duration_minutes),
            SLOT_DURATION_MINUTES,
        )
        for rec in records:
            await delete_events([rec.event_id])
            await session.delete(rec)
        await session.commit()
        try:
            await delete_events_in_range(date, hour, minute, duration)
        except Exception:
            pass
        await ensure_allow_slot(date, hour, minute, duration, note=note)
    else:
        await ensure_allow_slot(date, hour, minute, SLOT_DURATION_MINUTES, note=note)


async def del_record_all_day(date: datetime) -> None:
    res = await session.execute(select(RecordDate).where(RecordDate.record_date == date))
    res = res.all()

    if res:
        try:
            await delete_events(obj[0].event_id for obj in res)
        except Exception:
            pass
        for obj in res:
            try:
                await delete_events_in_range(date, obj[0].hour, obj[0].minute, SLOT_DURATION_MINUTES)
            except Exception:
                pass
        for obj in res:
            await session.delete(obj[0])
        await session.commit()


async def ensure_block_slot(
    date: datetime.date,
    hour: int,
    minute: int,
    duration_minutes: int = SLOT_DURATION_MINUTES,
    note: str | None = None,
) -> None:
    """
    Создаёт блокирующую запись (telegram_id=None) для слота,
    чтобы регулярка/синхронизация не восстанавливала удалённое занятие.
    """
    # Не ставим блок, если есть allow на этот слот
    allow = await session.execute(
        select(RecordDate.id).where(
            RecordDate.record_date == date,
            RecordDate.hour == hour,
            RecordDate.minute == minute,
            RecordDate.kind == "allow",
        )
    )
    if allow.first():
        return

    exists_block = await session.execute(
        select(RecordDate.id).where(
            RecordDate.record_date == date,
            RecordDate.hour == hour,
            RecordDate.minute == minute,
            RecordDate.telegram_id.is_(None),
            RecordDate.kind == "block",
        )
    )
    if exists_block.first():
        return

    try:
        await delete_events_in_range(date, hour, minute, duration_minutes)
    except Exception:
        pass

    block = RecordDate(
        telegram_id=None,
        record_date=date,
        hour=hour,
        minute=minute,
        duration_minutes=duration_minutes,
        kind="block",
        note=note,
        event_id=None,
    )
    session.add(block)
    await session.commit()


async def ensure_allow_slot(
    date: datetime.date,
    hour: int,
    minute: int,
    duration_minutes: int = SLOT_DURATION_MINUTES,
    note: str | None = None,
) -> None:
    """
    Создаёт отметку allow (не показывается как блок), чтобы отменённая регулярка не восстанавливалась,
    но админ не видел её как блок.
    """
    exists_allow = await session.execute(
        select(RecordDate.id).where(
            RecordDate.record_date == date,
            RecordDate.hour == hour,
            RecordDate.minute == minute,
            RecordDate.kind == "allow",
        )
    )
    if exists_allow.first():
        return

    # Удаляем возможные блоки для этого слота
    await session.execute(
        delete(RecordDate).where(
            RecordDate.record_date == date,
            RecordDate.hour == hour,
            RecordDate.minute == minute,
            RecordDate.kind == "block",
        )
    )
    allow = RecordDate(
        telegram_id=None,
        record_date=date,
        hour=hour,
        minute=minute,
        duration_minutes=duration_minutes,
        kind="allow",
        note=note,
        event_id=None,
    )
    session.add(allow)
    await session.commit()


async def view_clients() -> list[Any]:
    res = await session.execute(select(StudentProfile))
    return res.all()


async def view_record(telegram_id: int) -> list[Any]:
    res = await session.execute(
        select(RecordDate.record_date, RecordDate.hour, RecordDate.minute).where(
            RecordDate.telegram_id == telegram_id,
            (RecordDate.kind.is_(None) | (RecordDate.kind == "single")),
        ).order_by(
            RecordDate.record_date, RecordDate.hour, RecordDate.minute)
    )
    return res.all()


async def view_regular_lessons(telegram_id: int) -> list[Any]:
    res = await session.execute(
        select(RegularLesson).where(RegularLesson.telegram_id == telegram_id).order_by(
            RegularLesson.day_of_week, RegularLesson.hour, RegularLesson.minute
        )
    )
    return res.scalars().all()


async def block_unblock_user(telegram_id: int, action: str) -> None:
    profile = await session.get(StudentProfile, telegram_id)
    if profile:
        profile.blocked = 1 if action == "bl" else 0
    await session.commit()


async def del_user(telegram_id: int) -> None:
    profile = await session.get(StudentProfile, telegram_id)
    if profile:
        await session.delete(profile)
    await session.commit()


async def search_client(search_text: str) -> list[Any]:
    res = await session.execute(select(StudentProfile).where(StudentProfile.telephone.ilike(f'%{search_text}%')))
    res = res.all()

    if not res:
        res = await session.execute(select(StudentProfile).where(StudentProfile.full_name.ilike(f'%{search_text}%')))
        res = res.all()
    return res


async def reserve_day(
        telegram_id: int, date: datetime, beginning_working_day: int, end_working_day: int, note: str = "Резерв администратора"
) -> int:
    # Проверяем, не создан ли уже блок на этот день
    exists = await session.execute(
        select(RecordDate.id).where(
            RecordDate.record_date == date,
            RecordDate.kind == "block",
            RecordDate.hour == 0,
            RecordDate.minute == 0,
        )
    )
    if exists.first():
        return 1

    try:
        event_id = await create_full_day_block_event(date, note)
    except CalendarBackendError:
        return 0

    record = RecordDate(
        telegram_id=telegram_id,
        record_date=date,
        hour=0,
        minute=0,
        duration_minutes=SLOT_DURATION_MINUTES,
        kind="block",
        note=note,
        event_id=event_id,
    )
    session.add(record)
    await session.commit()
    return 1


async def mailing_for_day(date: datetime) -> list[Any]:
    res = await session.execute(
        select(RecordDate.telegram_id, RecordDate.hour, RecordDate.minute).where(
            RecordDate.record_date == date,
            RecordDate.telegram_id.is_not(None),
            RecordDate.kind != "block",
        ).group_by(
            RecordDate.telegram_id, RecordDate.hour, RecordDate.minute)
    )
    return res.all()


async def viewing_recordings_day_db(date: datetime, show_blocks: bool = False) -> list[Any]:
    """
    Возвращает список записей на день, включая разовые и регулярные.
    Приоритет: если для регулярки уже есть разовая запись на этот слот, дубликат не показываем.
    show_blocks=True — вернуть информацию о блоках (для админов).
    """
    target_date = date.date() if isinstance(date, datetime.datetime) else date

    blocks = await session.execute(
        select(RecordDate.hour, RecordDate.minute, RecordDate.note).where(
            RecordDate.record_date == target_date,
            RecordDate.telegram_id.is_(None),
            (
                (RecordDate.kind.in_(["block", "allow"]))
                | ((RecordDate.kind.is_(None)) & (RecordDate.event_id.is_(None)))
            ),
        )
    )
    blocked_times = {(row.hour, row.minute): row.note for row in blocks}

    singles = await session.execute(
        select(
            StudentProfile.full_name,
            StudentProfile.telephone,
            StudentProfile.telegram_username,
            RecordDate.hour,
            RecordDate.minute,
            RecordDate.telegram_id,
            RecordDate.event_id,
            RecordDate.kind,
            RecordDate.duration_minutes,
        )
        .join(StudentProfile, StudentProfile.telegram_id == RecordDate.telegram_id)
        .where(RecordDate.record_date == target_date)
    )

    result = []
    seen_slots: set[tuple[int | None, int, int]] = set()
    for row in singles:
        if getattr(row, "kind", None) == "block":
            continue
        key = (row.telegram_id, row.hour, row.minute)
        if key in seen_slots:
            continue
        seen_slots.add(key)
        kind_raw = getattr(row, "kind", None)
        kind = "Регулярное" if kind_raw == "regular" else "Разовое"
        result.append((
            row.full_name,
            row.telephone,
            row.hour,
            row.minute,
            kind,
            row.telegram_id,
            row.duration_minutes or SLOT_DURATION_MINUTES,
            row.telegram_username,
        ))

    weekday = target_date.weekday()
    regulars = await session.execute(
        select(
            StudentProfile.full_name,
            StudentProfile.telephone,
            StudentProfile.telegram_username,
            RegularLesson.hour,
            RegularLesson.minute,
            RegularLesson.telegram_id,
            RegularLesson.duration_minutes,
        )
        .join(StudentProfile, StudentProfile.telegram_id == RegularLesson.telegram_id, isouter=True)
        .where(RegularLesson.day_of_week == weekday)
    )

    seen_reg_slots: set[tuple[int | None, int, int]] = set()
    for row in regulars:
        if (row.hour, row.minute) in blocked_times:
            continue
        key = (row.telegram_id, row.hour, row.minute)
        if key in seen_reg_slots:
            continue
        seen_reg_slots.add(key)
        if key in seen_slots:
            continue
        result.append((
            row.full_name or "Регулярное занятие",
            row.telephone,
            row.hour,
            row.minute,
            "Регулярное",
            row.telegram_id,
            row.duration_minutes or SLOT_DURATION_MINUTES,
            row.telegram_username,
        ))

    # Добавляем информацию о блоках (для админов) с реальным временем
    if show_blocks and blocked_times:
        for (bh, bm), note in sorted(blocked_times.items(), key=lambda x: (x[0][0], x[0][1])):
            result.append(("Резерв администратора", "", bh, bm, "Блок", note or "День недоступен", None, None))

    return sorted(result, key=lambda r: (r[2], r[3]))


async def get_info_user(date: datetime, hour: int, minute: int) -> Any:
    """
    Возвращает (telegram_id, kind) для записи или регулярки на указанный слот.
    kind: single/regular/block.
    """
    res = await session.execute(
        select(RecordDate.id, RecordDate.telegram_id, RecordDate.kind).where(
            RecordDate.record_date == date,
            RecordDate.hour == hour,
            RecordDate.minute == minute,
        ).order_by(RecordDate.id.asc())
    )
    rows = res.all()
    if rows:
        if len(rows) > 1:
            logger.warning(
                "get_info_user: найдено несколько записей на слот date=%s time=%02d:%02d count=%s",
                date,
                hour,
                minute,
                len(rows),
            )
        # Предпочитаем пользовательскую запись, затем block/allow.
        rows_sorted = sorted(rows, key=lambda row: 1 if (row[2] or "single") in ("block", "allow") else 0)
        picked = rows_sorted[0]
        return (picked[1], picked[2] or "single")

    # Если нет записи, ищем регулярку на этот день/время
    weekday = date.weekday() if isinstance(date, datetime.date) else date
    reg = await session.execute(
        select(RegularLesson.telegram_id, RegularLesson.day_of_week).where(
            RegularLesson.day_of_week == weekday,
            RegularLesson.hour == hour,
            RegularLesson.minute == minute,
        )
    )
    reg_row = reg.one_or_none()
    if reg_row:
        return (reg_row[0], "regular")
    return None


async def get_record_slot_info(
    telegram_id: int,
    date: datetime.date,
    hour: int,
    minute: int,
) -> tuple[str, int] | None:
    """
    Возвращает тип слота (single/regular) и длительность.
    """
    res = await session.execute(
        select(RecordDate).where(
            RecordDate.telegram_id == telegram_id,
            RecordDate.record_date == date,
            RecordDate.hour == hour,
            RecordDate.minute == minute,
        )
    )
    rec = res.scalar_one_or_none()
    if rec:
        kind = rec.kind or "single"
        duration = rec.duration_minutes or SLOT_DURATION_MINUTES
        if kind in ("block", "allow"):
            return None
        return (kind, duration)

    weekday = date.weekday()
    reg = await session.execute(
        select(RegularLesson.duration_minutes).where(
            RegularLesson.telegram_id == telegram_id,
            RegularLesson.day_of_week == weekday,
            RegularLesson.hour == hour,
            RegularLesson.minute == minute,
        )
    )
    reg_row = reg.scalar_one_or_none()
    if reg_row is not None:
        return ("regular", reg_row or SLOT_DURATION_MINUTES)
    return None


async def reschedule_single_slot(
    telegram_id: int,
    old_date: datetime.date,
    old_hour: int,
    old_minute: int,
    new_date: datetime.date,
    new_hour: int,
    new_minute: int,
    duration_minutes: int | None = None,
) -> bool:
    """
    Перенос разовой записи на новый слот.
    """
    res = await session.execute(
        select(RecordDate).where(
            RecordDate.telegram_id == telegram_id,
            RecordDate.record_date == old_date,
            RecordDate.hour == old_hour,
            RecordDate.minute == old_minute,
        )
    )
    record = res.scalar_one_or_none()
    if not record:
        return False

    duration = duration_minutes or record.duration_minutes or SLOT_DURATION_MINUTES
    profile = await session.get(StudentProfile, telegram_id)
    summary_text = _build_event_summary(profile.full_name if profile else None, "single")

    await delete_events([record.event_id])
    try:
        await delete_events_in_range(old_date, old_hour, old_minute, duration)
    except Exception:
        pass

    try:
        event_id = await create_simple_event(
            new_date,
            new_hour,
            new_minute,
            duration,
            summary=summary_text,
            telegram_id=telegram_id,
            kind="single",
        )
    except CalendarBackendError:
        return False

    record.record_date = new_date
    record.hour = new_hour
    record.minute = new_minute
    record.kind = "single"
    record.event_id = event_id
    record.duration_minutes = duration
    record.presence_status = None
    record.presence_last_reminder = None
    record.presence_message_id = None
    await session.commit()
    return True


async def records_starting_at(date: datetime.date, hour: int, minute: int) -> list[Any]:
    # Сначала берём записи из record_dates (разовые и развёрнутые регулярки)
    res = await session.execute(
        select(
            StudentProfile.telegram_id,
            StudentProfile.full_name,
            StudentProfile.telephone,
            RecordDate.hour,
            RecordDate.minute,
            RecordDate.duration_minutes,
            RecordDate.kind,
        )
        .join(StudentProfile, StudentProfile.telegram_id == RecordDate.telegram_id)
        .where(
            RecordDate.record_date == date,
            RecordDate.hour == hour,
            RecordDate.minute == minute,
            RecordDate.kind != "block",
        )
    )
    result = res.all()
    seen = {(row.telegram_id, row.hour, row.minute) for row in result}

    # Добавляем регулярки, если для слота нет записи
    weekday = date.weekday()
    regs = await session.execute(
        select(
            RegularLesson.telegram_id,
            RegularLesson.hour,
            RegularLesson.minute,
            RegularLesson.duration_minutes,
            StudentProfile.full_name,
            StudentProfile.telephone,
        )
        .join(StudentProfile, StudentProfile.telegram_id == RegularLesson.telegram_id, isouter=True)
        .where(
            RegularLesson.day_of_week == weekday,
            RegularLesson.hour == hour,
            RegularLesson.minute == minute,
        )
    )
    for row in regs:
        key = (row.telegram_id, row.hour, row.minute)
        if key in seen:
            continue
        result.append(
            (
                row.telegram_id,
                row.full_name,
                row.telephone,
                row.hour,
                row.minute,
                row.duration_minutes or SLOT_DURATION_MINUTES,
                "regular",
            )
        )

    return result


async def lessons_for_date(date: datetime.date) -> list[Any]:
    single = await session.execute(
        select(
            RecordDate.telegram_id,
            RecordDate.hour,
            RecordDate.minute,
            RecordDate.duration_minutes,
            RecordDate.kind,
        ).where(
            RecordDate.record_date == date,
            RecordDate.kind != "block",
        )
    )
    result = []
    seen_slots: set[tuple[int | None, int, int]] = set()
    for row in single:
        key = (row.telegram_id, row.hour, row.minute)
        seen_slots.add(key)
        result.append((
            row.telegram_id,
            row.hour,
            row.minute,
            row.duration_minutes or SLOT_DURATION_MINUTES,
            row.kind or "single",
        ))

    weekday = date.weekday()
    regular = await session.execute(
        select(
            RegularLesson.telegram_id,
            RegularLesson.hour,
            RegularLesson.minute,
            RegularLesson.duration_minutes,
        ).where(RegularLesson.day_of_week == weekday)
    )
    for row in regular:
        key = (row.telegram_id, row.hour, row.minute)
        if key in seen_slots:
            continue
        result.append((
            row.telegram_id,
            row.hour,
            row.minute,
            row.duration_minutes or SLOT_DURATION_MINUTES,
            "regular",
        ))

    return result


async def get_lesson_kind(date: datetime.date, hour: int, minute: int, telegram_id: int | None) -> str | None:
    """
    Возвращает тип занятия для указанного слота:
    - "single" если найдено в record_dates
    - "regular" если найдено в regular_lessons
    - None если не найдено.
    """
    if telegram_id is None:
        return None

    rec = await session.execute(
        select(RecordDate.kind).where(
            RecordDate.record_date == date,
            RecordDate.hour == hour,
            RecordDate.minute == minute,
            RecordDate.telegram_id == telegram_id,
        )
    )
    rec_row = rec.first()
    if rec_row:
        kind_val = rec_row[0]
        if kind_val == "regular":
            return "regular"
        return "single"

    weekday = date.weekday()
    reg = await session.execute(
        select(RegularLesson.id).where(
            RegularLesson.day_of_week == weekday,
            RegularLesson.hour == hour,
            RegularLesson.minute == minute,
            RegularLesson.telegram_id == telegram_id,
        )
    )
    if reg.first():
        return "regular"
    return None


async def payments_summary_for_range(
    start_date: datetime.date,
    end_date: datetime.date,
) -> dict[str, int]:
    """
    Возвращает сводку по платежам за период.
    lessons_total — количество занятий (по записям оплат),
    lessons_paid — количество оплаченных,
    earned_total — сумма оплаченного,
    billed_total — сумма начислений (включая неоплаченное).
    """
    res = await session.execute(
        select(
            func.count(Payment.id),
            func.sum(
                case(
                    (Payment.status == "paid", func.coalesce(Payment.amount, 0)),
                    else_=0,
                )
            ),
            func.sum(func.coalesce(Payment.amount, 0)),
            func.sum(case((Payment.status == "paid", 1), else_=0)),
        ).where(
            Payment.lesson_date >= start_date,
            Payment.lesson_date <= end_date,
            Payment.status != "canceled",
        )
    )
    row = res.one()
    lessons_total = int(row[0] or 0)
    earned_total = int(row[1] or 0)
    billed_total = int(row[2] or 0)
    lessons_paid = int(row[3] or 0)
    return {
        "lessons_total": lessons_total,
        "lessons_paid": lessons_paid,
        "earned_total": earned_total,
        "billed_total": billed_total,
    }


async def payments_daily_breakdown(
    start_date: datetime.date,
    end_date: datetime.date,
) -> list[tuple[datetime.date, int, int, int, int]]:
    """
    Возвращает список (дата, всего занятий, заработано, начислено, оплачено).
    """
    res = await session.execute(
        select(
            Payment.lesson_date,
            func.count(Payment.id),
            func.sum(
                case(
                    (Payment.status == "paid", func.coalesce(Payment.amount, 0)),
                    else_=0,
                )
            ),
            func.sum(func.coalesce(Payment.amount, 0)),
            func.sum(case((Payment.status == "paid", 1), else_=0)),
        )
        .where(
            Payment.lesson_date >= start_date,
            Payment.lesson_date <= end_date,
            Payment.status != "canceled",
        )
        .group_by(Payment.lesson_date)
        .order_by(Payment.lesson_date)
    )
    rows = res.all()
    result: list[tuple[datetime.date, int, int, int, int]] = []
    for row in rows:
        result.append(
            (
                row[0],
                int(row[1] or 0),
                int(row[2] or 0),
                int(row[3] or 0),
                int(row[4] or 0),
            )
        )
    return result


# --- Оплаты ---
async def add_payment(
        telegram_id: int | None,
        full_name: str | None,
        lesson_date: datetime.date,
        hour: int,
        minute: int,
        duration_minutes: int,
        amount: int | None,
        status: str,
        source: str | None = None,
) -> Payment:
    pay = Payment(
        telegram_id=telegram_id,
        full_name=full_name,
        lesson_date=lesson_date,
        hour=hour,
        minute=minute,
        duration_minutes=duration_minutes,
        amount=amount,
        status=status,
        created_at=datetime.datetime.now().isoformat(),
        source=source or "",
    )
    session.add(pay)
    await session.commit()
    return pay


async def find_payment(
    telegram_id: int | None,
    lesson_date: datetime.date,
    hour: int,
    minute: int,
) -> Payment | None:
    res = await session.execute(
        select(Payment).where(
            Payment.telegram_id == telegram_id,
            Payment.lesson_date == lesson_date,
            Payment.hour == hour,
            Payment.minute == minute,
        )
    )
    return res.scalars().first()


async def get_payment(payment_id: int) -> Payment | None:
    return await session.get(Payment, payment_id)


async def update_payment(
    payment_id: int | None = None,
    *,
    pay_id: int | None = None,
    amount: int | None = None,
    status: str | None = None,
    source: str | None = None,
) -> None:
    # Backward compatibility: some callers still pass pay_id.
    resolved_payment_id = payment_id if payment_id is not None else pay_id
    if resolved_payment_id is None:
        return

    pay = await session.get(Payment, resolved_payment_id)
    if not pay:
        return
    if amount is not None:
        pay.amount = amount
    if status is not None:
        pay.status = status
    if source is not None:
        pay.source = source
    await session.commit()


async def list_unpaid_payments() -> list[Any]:
    res = await session.execute(
        select(Payment).where(Payment.status == "unpaid").order_by(Payment.lesson_date, Payment.hour, Payment.minute)
    )
    return res.all()


async def mark_payment_paid(payment_id: int) -> None:
    pay = await session.get(Payment, payment_id)
    if pay:
        pay.status = "paid"
        await session.commit()


async def mark_payment_status(payment_id: int, status: str) -> None:
    pay = await session.get(Payment, payment_id)
    if pay:
        pay.status = status
        await session.commit()

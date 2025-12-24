"""Модуль работы с базой данных."""
import datetime
import logging
from typing import Any

from sqlalchemy import delete, func, select, text

from database.connect import Base, engine, session
from database.models import Payment, RecordDate, RegularLesson, StudentProfile
from utils.google_calendar import (
    GoogleCalendarError,
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


async def _normalize_record_kinds() -> None:
    # Блокеры без владельца помечаем как block
    await session.execute(
        text(
            "UPDATE record_dates SET kind='block' "
            "WHERE telegram_id IS NULL AND (kind IS NULL OR kind != 'block')"
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
    except GoogleCalendarError:
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
    except GoogleCalendarError:
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
    lesson_title = _build_event_summary(full_name or (profile.full_name if profile else None), "regular")
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
    record = await session.execute(
        select(RecordDate).where(RecordDate.record_date == date, RecordDate.hour == hour, RecordDate.minute == minute)
    )
    record = record.scalar()

    if record:
        duration = record.duration_minutes or SLOT_DURATION_MINUTES
        await delete_events([record.event_id])
        try:
            await delete_events_in_range(date, hour, minute, SLOT_DURATION_MINUTES)
        except Exception:
            pass
        await session.delete(record)
        await session.commit()

        await ensure_block_slot(date, hour, minute, duration)


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
) -> None:
    """
    Создаёт блокирующую запись (telegram_id=None) для слота,
    чтобы регулярка/синхронизация не восстанавливала удалённое занятие.
    """
    exists_block = await session.execute(
        select(RecordDate.id).where(
            RecordDate.record_date == date,
            RecordDate.hour == hour,
            RecordDate.minute == minute,
            RecordDate.telegram_id.is_(None),
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
        event_id=None,
    )
    session.add(block)
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
        telegram_id: int, date: datetime, beginning_working_day: int, end_working_day: int
) -> int:
    try:
        event_id = await create_full_day_block_event(date, "Резерв администратора")
    except GoogleCalendarError:
        return 0

    record = RecordDate(
        telegram_id=telegram_id,
        record_date=date,
        hour=0,
        minute=0,
        duration_minutes=SLOT_DURATION_MINUTES,
        kind="block",
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


async def viewing_recordings_day_db(date: datetime) -> list[Any]:
    """
    Возвращает список записей на день, включая разовые и регулярные.
    Приоритет: если для регулярки уже есть разовая запись на этот слот, дубликат не показываем.
    """
    target_date = date.date() if isinstance(date, datetime.datetime) else date

    blocks = await session.execute(
        select(RecordDate.hour, RecordDate.minute).where(
            RecordDate.record_date == target_date,
            RecordDate.telegram_id.is_(None),
        )
    )
    blocked_times = {(row.hour, row.minute) for row in blocks}

    singles = await session.execute(
        select(
            StudentProfile.full_name,
            StudentProfile.telephone,
            RecordDate.hour,
            RecordDate.minute,
            RecordDate.telegram_id,
            RecordDate.event_id,
            RecordDate.kind,
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
        seen_slots.add(key)
        kind_raw = getattr(row, "kind", None)
        kind = "Регулярное" if kind_raw == "regular" else "Разовое"
        result.append((row.full_name, row.telephone, row.hour, row.minute, kind))

    weekday = target_date.weekday()
    regulars = await session.execute(
        select(
            StudentProfile.full_name,
            StudentProfile.telephone,
            RegularLesson.hour,
            RegularLesson.minute,
            RegularLesson.telegram_id,
            RegularLesson.duration_minutes,
        )
        .join(StudentProfile, StudentProfile.telegram_id == RegularLesson.telegram_id, isouter=True)
        .where(RegularLesson.day_of_week == weekday)
    )

    for row in regulars:
        if (row.hour, row.minute) in blocked_times:
            continue
        key = (row.telegram_id, row.hour, row.minute)
        if key in seen_slots:
            continue
        result.append((row.full_name or "Регулярное занятие", row.telephone, row.hour, row.minute, "Регулярное"))

    return sorted(result, key=lambda r: (r[2], r[3]))


async def get_info_user(date: datetime, hour: int, minute: int) -> Any:
    res = await session.execute(
        select(RecordDate.telegram_id).where(RecordDate.record_date == date, RecordDate.hour == hour, RecordDate.minute == minute)
    )
    return res.one_or_none()


async def records_starting_at(date: datetime.date, hour: int, minute: int) -> list[Any]:
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


async def lessons_for_date(date: datetime.date) -> list[Any]:
    single = await session.execute(
        select(
            RecordDate.telegram_id,
            RecordDate.hour,
            RecordDate.minute,
            RecordDate.duration_minutes,
        ).where(
            RecordDate.record_date == date,
            RecordDate.kind != "block",
        )
    )
    result = [(row.telegram_id, row.hour, row.minute, row.duration_minutes) for row in single]

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
        select(RecordDate.id).where(
            RecordDate.record_date == date,
            RecordDate.hour == hour,
            RecordDate.minute == minute,
            RecordDate.telegram_id == telegram_id,
        )
    )
    if rec.first():
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

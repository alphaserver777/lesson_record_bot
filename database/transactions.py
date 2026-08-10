"""Модуль работы с базой данных."""
from collections import defaultdict
import datetime
import json
import logging
from typing import Any

from sqlalchemy import case, delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from database.connect import Base, engine, session
from database.models import AdminAuditLog, AnalyticsEvent, DateAvailabilityOverride, Lead, Payment, RecordDate, RegularLesson, RegularLessonException, StudentProfile, WorkingInterval
from utils.calendar_backend import (
    CalendarBackendError,
    create_booking,
    create_simple_event,
    delete_events,
    delete_events_in_range,
    get_busy_intervals,
    get_calendar_tz,
)
from utils.sync_calendar import push_db_events_to_calendar
from utils.schedule import SLOT_DURATION_MINUTES, SLOT_STEP_MINUTES, get_working_intervals_for_weekday, refresh_schedule_cache, slots_for_date

logger = logging.getLogger(__name__)


def _build_event_summary(full_name: str | None, kind: str) -> str:
    """Формирует заголовок события с именем ученика и типом записи."""
    kind_label = "Регулярное" if kind == "regular" else "Разовое"
    name = (full_name or "").strip() or "Запись"
    return f"{name} ({kind_label})"


def _split_full_name(full_name: str | None) -> tuple[str | None, str | None]:
    raw = (full_name or "").strip()
    if not raw:
        return None, None
    parts = [p for p in raw.split() if p]
    if len(parts) == 1:
        return parts[0], None
    # Стандартизируем: Фамилия + Имя(+Отчество) в first_name
    return " ".join(parts[1:]), parts[0]


def _compose_full_name(first_name: str | None, last_name: str | None) -> str | None:
    first = (first_name or "").strip()
    last = (last_name or "").strip()
    if not first and not last:
        return None
    return " ".join([last, first]).strip()


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # SQLite installations before PostgreSQL used additive runtime migrations.
    # PostgreSQL is created from the complete SQLAlchemy schema, so those
    # SQLite-only PRAGMA/ALTER statements must never run there.
    if engine.dialect.name != "sqlite":
        await _ensure_indexes()
        await refresh_schedule_cache()
        return
    await _ensure_event_id_column()
    await _ensure_minute_column()
    await _ensure_record_kind_column()
    await _ensure_record_note_column()
    await _ensure_presence_columns()
    await _ensure_regular_lessons_columns()
    await _ensure_regular_lesson_exceptions_table()
    await _ensure_date_availability_overrides_table()
    await _ensure_student_profiles_columns()
    await _ensure_payments_columns()
    await _ensure_analytics_events_table()
    await _ensure_booking_status_columns()
    await _normalize_record_kinds()
    await _ensure_indexes()
    await refresh_schedule_cache()


async def _ensure_indexes() -> None:
    statements = (
        "CREATE INDEX IF NOT EXISTS idx_date_availability_overrides_target_date ON date_availability_overrides(target_date, mode, start_minute, end_minute)",
        "CREATE INDEX IF NOT EXISTS idx_analytics_events_record_date ON analytics_events(record_date, event_type, telegram_id)",
        "CREATE INDEX IF NOT EXISTS idx_analytics_events_created_at ON analytics_events(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_record_dates_date_time ON record_dates(record_date, hour, minute)",
        "CREATE INDEX IF NOT EXISTS idx_record_dates_telegram_id ON record_dates(telegram_id)",
        "CREATE INDEX IF NOT EXISTS idx_profiles_name ON student_profiles(full_name)",
        "CREATE INDEX IF NOT EXISTS idx_profiles_deleted ON student_profiles(is_deleted)",
        "CREATE INDEX IF NOT EXISTS idx_payments_lesson_date_status ON payments(lesson_date, status)",
        "CREATE INDEX IF NOT EXISTS idx_payments_tg_date ON payments(telegram_id, lesson_date)",
        "CREATE INDEX IF NOT EXISTS idx_working_intervals_weekday_active ON working_intervals(weekday, is_active)",
        "CREATE INDEX IF NOT EXISTS idx_working_intervals_weekday_start_end ON working_intervals(weekday, start_minute, end_minute)",
    )
    for statement in statements:
        await session.execute(text(statement))
    await session.commit()


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


async def _ensure_booking_status_columns() -> None:
    columns = await session.execute(text("PRAGMA table_info('record_dates')"))
    column_names = {row[1] for row in columns}
    if "booking_status" not in column_names:
        await session.execute(text("ALTER TABLE record_dates ADD COLUMN booking_status VARCHAR(20) DEFAULT 'approved' NOT NULL"))
        await session.commit()
    if "approval_admin_id" not in column_names:
        await session.execute(text("ALTER TABLE record_dates ADD COLUMN approval_admin_id INTEGER"))
        await session.commit()
    if "approval_updated_at" not in column_names:
        await session.execute(text("ALTER TABLE record_dates ADD COLUMN approval_updated_at VARCHAR(50)"))
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
            ((RecordDate.booking_status.is_(None)) | (RecordDate.booking_status == "approved")),
        )
    )
    records = res.all()
    seen_slots = {(row[1], row[3], row[4]) for row in records}
    skipped_ids = await skipped_regular_lesson_ids_for_date(target_date)

    # Добавляем регулярки на этот день, если слота нет в record_dates, и создаём запись для хранения статуса
    weekday = target_date.weekday()
    regulars = await session.execute(
        select(
            RegularLesson.id,
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
        if int(lesson.id) in skipped_ids:
            continue
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
        await log_analytics_event(
            "presence_yes" if status == "yes" else "presence_no",
            telegram_id=rec_obj.telegram_id,
            record_date=rec_obj.record_date,
            hour=rec_obj.hour,
            minute=rec_obj.minute,
            duration_minutes=rec_obj.duration_minutes or SLOT_DURATION_MINUTES,
            lesson_kind=rec_obj.kind or "single",
            source_context="bot",
            commit=False,
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


async def _ensure_regular_lesson_exceptions_table() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(RegularLessonException.__table__.create, checkfirst=True)


async def _ensure_date_availability_overrides_table() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(DateAvailabilityOverride.__table__.create, checkfirst=True)
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_date_availability_overrides_target_date "
            "ON date_availability_overrides(target_date, mode, start_minute, end_minute)"
        )
    )
    await session.commit()


async def _ensure_student_profiles_columns() -> None:
    columns = await session.execute(text("PRAGMA table_info('student_profiles')"))
    column_names = {row[1] for row in columns}
    if "telephone" not in column_names:
        await session.execute(text("ALTER TABLE student_profiles ADD COLUMN telephone VARCHAR(20)"))
        await session.commit()
    if "miniapp_entry_chat_id" not in column_names:
        await session.execute(text("ALTER TABLE student_profiles ADD COLUMN miniapp_entry_chat_id INTEGER"))
        await session.commit()
    if "miniapp_entry_message_id" not in column_names:
        await session.execute(text("ALTER TABLE student_profiles ADD COLUMN miniapp_entry_message_id INTEGER"))
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
    if "is_deleted" not in column_names:
        await session.execute(text("ALTER TABLE student_profiles ADD COLUMN is_deleted BOOLEAN DEFAULT 0"))
        await session.commit()
    if "first_name" not in column_names:
        await session.execute(text("ALTER TABLE student_profiles ADD COLUMN first_name VARCHAR(100)"))
        await session.commit()
    if "last_name" not in column_names:
        await session.execute(text("ALTER TABLE student_profiles ADD COLUMN last_name VARCHAR(100)"))
        await session.commit()

    # Мягкий backfill для старых профилей: заполняем first/last из full_name, если поля пустые.
    rows = await session.execute(
        select(StudentProfile).where(
            StudentProfile.full_name.is_not(None),
            (StudentProfile.first_name.is_(None)) | (StudentProfile.first_name == ""),
            (StudentProfile.last_name.is_(None)) | (StudentProfile.last_name == ""),
        )
    )
    changed = False
    for (profile,) in rows.all():
        first_name, last_name = _split_full_name(profile.full_name)
        if first_name and not profile.first_name:
            profile.first_name = first_name
            changed = True
        if last_name and not profile.last_name:
            profile.last_name = last_name
            changed = True
    if changed:
        await session.commit()

    await _normalize_student_profile_full_names()


async def _normalize_student_profile_full_names() -> None:
    """Делает full_name производным полем от first_name/last_name для legacy-профилей."""
    rows = await session.execute(
        select(StudentProfile).where(
            ((StudentProfile.first_name.is_not(None)) & (StudentProfile.first_name != ""))
            | ((StudentProfile.last_name.is_not(None)) & (StudentProfile.last_name != ""))
        )
    )
    changed = False
    for (profile,) in rows.all():
        canonical = _compose_full_name(profile.first_name, profile.last_name)
        if canonical and (profile.full_name or "").strip() != canonical:
            profile.full_name = canonical
            changed = True
    if changed:
        await session.commit()


async def _ensure_payments_columns() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Payment.__table__.create, checkfirst=True)
    columns = await session.execute(text("PRAGMA table_info('payments')"))
    column_names = {row[1] for row in columns}
    if "source" not in column_names:
        await session.execute(text("ALTER TABLE payments ADD COLUMN source VARCHAR(50)"))
        await session.commit()


async def _ensure_analytics_events_table() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(AnalyticsEvent.__table__.create, checkfirst=True)
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_analytics_events_record_date "
            "ON analytics_events(record_date, event_type, telegram_id)"
        )
    )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_analytics_events_created_at "
            "ON analytics_events(created_at)"
        )
    )
    await session.commit()


def _analytics_meta_dump(meta: dict[str, Any] | None) -> str | None:
    if not meta:
        return None
    try:
        return json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return None


async def log_analytics_event(
    event_type: str,
    *,
    telegram_id: int | None = None,
    record_date: datetime.date | None = None,
    hour: int | None = None,
    minute: int | None = None,
    duration_minutes: int | None = None,
    lesson_kind: str | None = None,
    source_context: str | None = None,
    related_slot_date: datetime.date | None = None,
    related_slot_hour: int | None = None,
    related_slot_minute: int | None = None,
    meta: dict[str, Any] | None = None,
    commit: bool = True,
) -> AnalyticsEvent:
    item = AnalyticsEvent(
        event_type=event_type,
        telegram_id=telegram_id,
        record_date=record_date,
        hour=hour,
        minute=minute or 0,
        duration_minutes=duration_minutes or SLOT_DURATION_MINUTES,
        lesson_kind=lesson_kind,
        source_context=source_context,
        related_slot_date=related_slot_date,
        related_slot_hour=related_slot_hour,
        related_slot_minute=related_slot_minute or 0,
        meta_json=_analytics_meta_dump(meta),
        created_at=datetime.datetime.now().isoformat(),
    )
    session.add(item)
    if commit:
        await session.commit()
    else:
        await session.flush()
    return item


async def legacy_allow_times_for_date(date: datetime.date) -> set[tuple[int, int]]:
    res = await session.execute(
        select(RecordDate.hour, RecordDate.minute).where(
            RecordDate.record_date == date,
            RecordDate.kind == "allow",
        )
    )
    return {(int(row.hour), int(row.minute)) for row in res}


async def skipped_regular_lesson_ids_for_date(date: datetime.date) -> set[int]:
    res = await session.execute(
        select(RegularLessonException.regular_lesson_id).where(
            RegularLessonException.exception_date == date,
            RegularLessonException.action == "skip",
        )
    )
    return {int(row[0]) for row in res.all() if row[0] is not None}


async def is_regular_lesson_skipped(lesson_id: int, date: datetime.date) -> bool:
    res = await session.execute(
        select(RegularLessonException.id).where(
            RegularLessonException.regular_lesson_id == lesson_id,
            RegularLessonException.exception_date == date,
            RegularLessonException.action == "skip",
        )
    )
    return res.first() is not None


async def create_regular_skip_exception(
    regular_lesson_id: int,
    exception_date: datetime.date,
    note: str | None = None,
) -> RegularLessonException:
    exists = await session.execute(
        select(RegularLessonException).where(
            RegularLessonException.regular_lesson_id == regular_lesson_id,
            RegularLessonException.exception_date == exception_date,
            RegularLessonException.action == "skip",
        )
    )
    item = exists.scalars().first()
    if item:
        if note is not None:
            item.note = note
        await session.commit()
        return item

    item = RegularLessonException(
        regular_lesson_id=regular_lesson_id,
        exception_date=exception_date,
        action="skip",
        note=note,
        created_at=datetime.datetime.now().isoformat(),
    )
    session.add(item)
    await session.commit()
    return item


async def find_regular_lesson_for_occurrence(
    telegram_id: int,
    date: datetime.date,
    hour: int,
    minute: int,
) -> RegularLesson | None:
    weekday = date.weekday()
    res = await session.execute(
        select(RegularLesson).where(
            RegularLesson.telegram_id == telegram_id,
            RegularLesson.day_of_week == weekday,
            RegularLesson.hour == hour,
            RegularLesson.minute == minute,
        )
    )
    return res.scalars().first()


async def deleting_records_older_7_days() -> None:
    cutoff = datetime.date.today() - datetime.timedelta(days=7)
    await session.execute(delete(RecordDate).where(RecordDate.record_date < cutoff))
    await session.commit()


async def deletes_old_users() -> None:
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=182)).isoformat()
    # A Telegram account may be inactive while the student still has a
    # recurring lesson.  Removing that profile detaches the lesson from the
    # client and makes it disappear from the schedule.
    active_regular_students = select(RegularLesson.telegram_id).where(
        RegularLesson.telegram_id.is_not(None)
    )
    await session.execute(
        delete(StudentProfile).where(
            StudentProfile.last_visit_date < cutoff,
            StudentProfile.telegram_id.not_in(active_regular_students),
        )
    )
    await session.commit()


async def user_check(telegram_id: int) -> tuple[Any]:
    res = await session.execute(select(StudentProfile.blocked).where(StudentProfile.telegram_id == telegram_id))
    return res.one_or_none()


async def add_user(telegram_id: int, full_name: str) -> None:
    profile = await session.get(StudentProfile, telegram_id)
    first_name, last_name = _split_full_name(full_name)
    if profile is None:
        profile = StudentProfile(
            telegram_id=telegram_id,
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
        )
        session.add(profile)
    else:
        if full_name and full_name != profile.full_name:
            profile.full_name = full_name
        if first_name and not profile.first_name:
            profile.first_name = first_name
        if last_name and not profile.last_name:
            profile.last_name = last_name
    await session.commit()


async def upsert_student_profile(
    telegram_id: int,
    full_name: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
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
        if first_name is None and last_name is None:
            parsed_first, parsed_last = _split_full_name(full_name)
            if parsed_first:
                profile.first_name = parsed_first
            if parsed_last:
                profile.last_name = parsed_last
    if first_name is not None:
        profile.first_name = first_name.strip() or None
    if last_name is not None:
        profile.last_name = last_name.strip() or None
    if first_name is not None or last_name is not None:
        profile.full_name = _compose_full_name(profile.first_name, profile.last_name)
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


async def register_lead_source(telegram_id: int, source: str) -> Lead | None:
    """Create a single funnel entry from a validated Telegram deep-link source."""
    source = (source or "").strip().lower()
    if not source:
        return None
    existing = await session.execute(
        select(Lead).where(Lead.telegram_id == telegram_id).order_by(Lead.id.asc()).limit(1)
    )
    lead = existing.scalars().first()
    if lead:
        return lead
    profile = await session.get(StudentProfile, telegram_id)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    lead = Lead(
        telegram_id=telegram_id,
        full_name=profile.full_name if profile else None,
        telephone=profile.telephone if profile else None,
        source=source,
        stage="new",
        created_at=now,
        updated_at=now,
    )
    session.add(lead)
    await session.commit()
    return lead


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


async def get_miniapp_entry_message(telegram_id: int) -> tuple[int | None, int | None]:
    profile = await session.get(StudentProfile, telegram_id)
    if not profile:
        return None, None
    chat_id = int(profile.miniapp_entry_chat_id) if profile.miniapp_entry_chat_id is not None else None
    message_id = int(profile.miniapp_entry_message_id) if profile.miniapp_entry_message_id is not None else None
    return chat_id, message_id


async def set_miniapp_entry_message(telegram_id: int, chat_id: int | None, message_id: int | None) -> None:
    profile = await session.get(StudentProfile, telegram_id)
    if profile is None:
        profile = StudentProfile(telegram_id=telegram_id)
        session.add(profile)
    profile.miniapp_entry_chat_id = chat_id
    profile.miniapp_entry_message_id = message_id
    await session.commit()


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


async def is_slot_busy(
    date: datetime.date,
    hour: int,
    minute: int,
    duration_minutes: int = SLOT_DURATION_MINUTES,
    exclude_record_id: int | None = None,
) -> bool:
    busy_intervals = await get_busy_intervals(date, exclude_record_id=exclude_record_id)
    slot_start = datetime.datetime.combine(date, datetime.time(hour, minute), tzinfo=get_calendar_tz())
    slot_end = slot_start + datetime.timedelta(minutes=duration_minutes)
    for start, end in busy_intervals:
        if slot_start < end and slot_end > start:
            return True
    return False


def _overlaps(
    start_a: datetime.datetime,
    end_a: datetime.datetime,
    start_b: datetime.datetime,
    end_b: datetime.datetime,
) -> bool:
    return start_a < end_b and end_a > start_b


async def is_slot_overlapping_local(
    date: datetime.date,
    hour: int,
    minute: int,
    duration_minutes: int,
    exclude_record_id: int | None = None,
) -> bool:
    start = datetime.datetime.combine(date, datetime.time(hour, minute))
    end = start + datetime.timedelta(minutes=duration_minutes)
    skipped_ids = await skipped_regular_lesson_ids_for_date(date)
    allow_times = await legacy_allow_times_for_date(date)

    recs = await session.execute(
        select(RecordDate.id, RecordDate.hour, RecordDate.minute, RecordDate.duration_minutes).where(
            RecordDate.record_date == date,
            RecordDate.kind.not_in(["block", "allow"]),
            ((RecordDate.booking_status.is_(None)) | (RecordDate.booking_status.in_(["pending", "approved"]))),
        )
    )
    for rec in recs:
        if exclude_record_id is not None and rec.id == exclude_record_id:
            continue
        rec_start = datetime.datetime.combine(date, datetime.time(rec.hour, rec.minute))
        rec_end = rec_start + datetime.timedelta(minutes=rec.duration_minutes or SLOT_DURATION_MINUTES)
        if _overlaps(start, end, rec_start, rec_end):
            return True

    weekday = date.weekday()
    regs = await session.execute(
        select(RegularLesson.id, RegularLesson.hour, RegularLesson.minute, RegularLesson.duration_minutes).where(
            RegularLesson.day_of_week == weekday,
            RegularLesson.telegram_id.is_not(None),
        )
    )
    for reg in regs:
        if int(reg.id) in skipped_ids:
            continue
        if (int(reg.hour or 0), int(reg.minute or 0)) in allow_times:
            continue
        reg_start = datetime.datetime.combine(date, datetime.time(reg.hour or 0, reg.minute or 0))
        reg_end = reg_start + datetime.timedelta(minutes=reg.duration_minutes or SLOT_DURATION_MINUTES)
        if _overlaps(start, end, reg_start, reg_end):
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
        booking_status="approved",
    )
    session.add(record)
    await session.flush()
    await log_analytics_event(
        "booked",
        telegram_id=telegram_id,
        record_date=date,
        hour=hour,
        minute=minute,
        duration_minutes=duration_minutes,
        lesson_kind="single",
        source_context="admin",
        meta={"booking_status": "approved"},
        commit=False,
    )
    await log_analytics_event(
        "approved",
        telegram_id=telegram_id,
        record_date=date,
        hour=hour,
        minute=minute,
        duration_minutes=duration_minutes,
        lesson_kind="single",
        source_context="admin",
        commit=False,
    )
    await session.commit()
    return True


async def add_pending_single_slot(
    telegram_id: int,
    date: datetime.date,
    hour: int,
    minute: int,
    duration_minutes: int = SLOT_DURATION_MINUTES,
    kind: str = "single",
) -> int:
    record = RecordDate(
        telegram_id=telegram_id,
        record_date=date,
        hour=hour,
        minute=minute,
        duration_minutes=duration_minutes,
        kind=kind,
        event_id=None,
        booking_status="pending",
        approval_updated_at=datetime.datetime.now().isoformat(),
    )
    session.add(record)
    await session.flush()
    await log_analytics_event(
        "booked",
        telegram_id=telegram_id,
        record_date=date,
        hour=hour,
        minute=minute,
        duration_minutes=duration_minutes,
        lesson_kind=kind,
        source_context="miniapp",
        meta={"booking_status": "pending"},
        commit=False,
    )
    await session.commit()
    return int(record.id)


async def _reset_transaction_snapshot() -> None:
    """Reset shared session transaction to avoid stale snapshot reads in long-lived process."""
    try:
        if session.in_transaction():
            await session.rollback()
    except Exception:
        # Best-effort reset; keep existing flow if rollback is not available in current context.
        pass


async def get_record_by_id(record_id: int) -> RecordDate | None:
    await _reset_transaction_snapshot()
    return await session.get(RecordDate, record_id)


async def approve_pending_booking(record_id: int, admin_id: int) -> tuple[str, RecordDate | None]:
    await _reset_transaction_snapshot()
    rec = await session.get(RecordDate, record_id)
    if not rec:
        return ("not_found", None)
    if rec.booking_status == "approved":
        return ("already_approved", rec)
    if rec.booking_status == "rejected":
        return ("already_rejected", rec)
    if rec.booking_status not in (None, "pending"):
        return ("invalid_status", rec)

    is_busy_calendar = await is_slot_busy(
        rec.record_date,
        rec.hour,
        rec.minute,
        rec.duration_minutes or SLOT_DURATION_MINUTES,
        exclude_record_id=rec.id,
    )
    is_busy_local = await is_slot_overlapping_local(
        rec.record_date,
        rec.hour,
        rec.minute,
        rec.duration_minutes or SLOT_DURATION_MINUTES,
        exclude_record_id=rec.id,
    )
    if is_busy_calendar or is_busy_local:
        return ("slot_busy", rec)

    profile = await session.get(StudentProfile, rec.telegram_id) if rec.telegram_id else None
    summary_text = _build_event_summary(
        profile.full_name if profile else None,
        "regular" if rec.kind == "regular" else "single",
    )
    try:
        rec.event_id = await create_simple_event(
            rec.record_date,
            rec.hour,
            rec.minute,
            rec.duration_minutes or SLOT_DURATION_MINUTES,
            summary=summary_text,
            telegram_id=rec.telegram_id,
            kind=rec.kind or "single",
        )
    except CalendarBackendError:
        return ("calendar_error", rec)

    if rec.kind == "regular":
        await ensure_regular_lesson_template(
            telegram_id=rec.telegram_id,
            date=rec.record_date,
            hour=rec.hour,
            minute=rec.minute,
            duration_minutes=rec.duration_minutes or SLOT_DURATION_MINUTES,
            full_name=profile.full_name if profile else None,
            commit=False,
        )

    rec.booking_status = "approved"
    rec.approval_admin_id = admin_id
    rec.approval_updated_at = datetime.datetime.now().isoformat()
    await log_analytics_event(
        "approved",
        telegram_id=rec.telegram_id,
        record_date=rec.record_date,
        hour=rec.hour,
        minute=rec.minute,
        duration_minutes=rec.duration_minutes or SLOT_DURATION_MINUTES,
        lesson_kind=rec.kind or "single",
        source_context="admin",
        meta={"admin_id": admin_id, "record_id": rec.id},
        commit=False,
    )
    await session.commit()
    return ("approved", rec)


async def reject_pending_booking(record_id: int, admin_id: int) -> tuple[str, RecordDate | None]:
    await _reset_transaction_snapshot()
    rec = await session.get(RecordDate, record_id)
    if not rec:
        return ("not_found", None)
    if rec.booking_status == "approved":
        return ("already_approved", rec)
    if rec.booking_status == "rejected":
        return ("already_rejected", rec)

    rec.booking_status = "rejected"
    rec.approval_admin_id = admin_id
    rec.approval_updated_at = datetime.datetime.now().isoformat()
    await log_analytics_event(
        "rejected",
        telegram_id=rec.telegram_id,
        record_date=rec.record_date,
        hour=rec.hour,
        minute=rec.minute,
        duration_minutes=rec.duration_minutes or SLOT_DURATION_MINUTES,
        lesson_kind=rec.kind or "single",
        source_context="admin",
        meta={"admin_id": admin_id, "record_id": rec.id},
        commit=False,
    )
    await session.commit()
    return ("rejected", rec)


async def add_regular_slot(
    telegram_id: int,
    day_of_week: int,
    hour: int,
    minute: int,
    duration_minutes: int = SLOT_DURATION_MINUTES,
    full_name: str | None = None,
) -> None:
    await ensure_regular_lesson_template(
        telegram_id=telegram_id,
        weekday=day_of_week,
        hour=hour,
        minute=minute,
        duration_minutes=duration_minutes,
        full_name=full_name,
    )

    # Выгружаем новые регулярки в календарь сразу, чтобы слоты были забронированы
    try:
        await push_db_events_to_calendar(days_ahead=30)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Не удалось синхронизировать регулярку в календарь: %s", exc)


async def find_regular_lesson_template(
    telegram_id: int | None,
    weekday: int,
    hour: int,
    minute: int,
    duration_minutes: int = SLOT_DURATION_MINUTES,
) -> RegularLesson | None:
    if telegram_id is None:
        return None
    result = await session.execute(
        select(RegularLesson).where(
            RegularLesson.telegram_id == telegram_id,
            RegularLesson.day_of_week == weekday,
            RegularLesson.hour == hour,
            RegularLesson.minute == minute,
            RegularLesson.duration_minutes == duration_minutes,
        )
    )
    return result.scalars().first()


async def ensure_regular_lesson_template(
    telegram_id: int | None,
    hour: int,
    minute: int,
    duration_minutes: int = SLOT_DURATION_MINUTES,
    weekday: int | None = None,
    date: datetime.date | None = None,
    full_name: str | None = None,
    commit: bool = True,
) -> RegularLesson | None:
    if telegram_id is None:
        return None

    if weekday is None:
        if date is None:
            raise ValueError("weekday or date is required to materialize regular lesson template")
        weekday = date.weekday()

    existing = await find_regular_lesson_template(
        telegram_id=telegram_id,
        weekday=weekday,
        hour=hour,
        minute=minute,
        duration_minutes=duration_minutes,
    )
    if existing:
        return existing

    profile = await session.get(StudentProfile, telegram_id)
    lesson_title = full_name or (profile.full_name if profile else None) or "Регулярное занятие"
    lesson = RegularLesson(
        telegram_id=telegram_id,
        full_name=lesson_title,
        username=None,
        cost=profile.price if profile else None,
        day_of_week=weekday,
        lesson_date=None,
        hour=hour,
        minute=minute,
        duration_minutes=duration_minutes,
    )
    session.add(lesson)
    if commit:
        await session.commit()
    else:
        await session.flush()
    return lesson


async def backfill_missing_regular_templates() -> int:
    await _reset_transaction_snapshot()
    rows = await session.execute(
        select(RecordDate).where(
            RecordDate.telegram_id.is_not(None),
            RecordDate.kind == "regular",
            ((RecordDate.booking_status.is_(None)) | (RecordDate.booking_status == "approved")),
        ).order_by(RecordDate.record_date, RecordDate.hour, RecordDate.minute)
    )
    created = 0
    for rec in rows.scalars().all():
        existing = await find_regular_lesson_template(
            telegram_id=rec.telegram_id,
            weekday=rec.record_date.weekday(),
            hour=rec.hour,
            minute=rec.minute,
            duration_minutes=rec.duration_minutes or SLOT_DURATION_MINUTES,
        )
        if existing:
            continue
        lesson = await ensure_regular_lesson_template(
            telegram_id=rec.telegram_id,
            date=rec.record_date,
            hour=rec.hour,
            minute=rec.minute,
            duration_minutes=rec.duration_minutes or SLOT_DURATION_MINUTES,
        )
        if lesson:
            created += 1
    return created


async def delete_single_slot(
    telegram_id: int,
    date: datetime.date,
    hour: int,
    minute: int,
    cancel_event_type: str | None = None,
    source_context: str | None = None,
    note: str | None = None,
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
        if cancel_event_type:
            await log_analytics_event(
                cancel_event_type,
                telegram_id=telegram_id,
                record_date=date,
                hour=hour,
                minute=minute,
                duration_minutes=rec.duration_minutes or SLOT_DURATION_MINUTES,
                lesson_kind=rec.kind or "single",
                source_context=source_context,
                meta={"note": note} if note else None,
                commit=False,
            )
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
    cancel_event_type: str | None = None,
    source_context: str | None = None,
    note: str | None = None,
) -> None:
    lessons = await session.execute(
        select(RegularLesson).where(
            RegularLesson.telegram_id == telegram_id,
            RegularLesson.day_of_week == day_of_week,
            RegularLesson.hour == hour,
            RegularLesson.minute == minute,
        )
    )
    lesson_ids: list[int] = []
    for lesson in lessons.scalars():
        lesson_ids.append(int(lesson.id))
        await session.delete(lesson)

    if lesson_ids:
        await session.execute(
            delete(RegularLessonException).where(
                RegularLessonException.regular_lesson_id.in_(lesson_ids)
            )
        )

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
            if cancel_event_type:
                await log_analytics_event(
                    cancel_event_type,
                    telegram_id=telegram_id,
                    record_date=rec.record_date,
                    hour=rec.hour,
                    minute=rec.minute,
                    duration_minutes=rec.duration_minutes or SLOT_DURATION_MINUTES,
                    lesson_kind=rec.kind or "regular",
                    source_context=source_context,
                    meta={"note": note or "", "series": True},
                    commit=False,
                )
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


async def cancel_regular_occurrence(
    telegram_id: int,
    date: datetime.date,
    hour: int,
    minute: int,
    note: str | None = None,
    cancel_event_type: str | None = None,
    source_context: str | None = None,
) -> bool:
    lesson = await find_regular_lesson_for_occurrence(telegram_id, date, hour, minute)
    if lesson is None:
        return False

    await create_regular_skip_exception(int(lesson.id), date, note=note)
    await delete_single_slot(
        telegram_id,
        date,
        hour,
        minute,
        cancel_event_type=cancel_event_type,
        source_context=source_context,
        note=note,
    )
    return True


async def cancel_lesson_after_presence_decline(
    telegram_id: int,
    date: datetime.date,
    hour: int,
    minute: int,
) -> bool:
    """Отменяет занятие ученика после подтверждённого отказа.

    Регулярное занятие отменяется только на указанную дату, разовое удаляется.
    Возвращает ``False``, если активного занятия уже нет.
    """
    regular = await find_regular_lesson_for_occurrence(telegram_id, date, hour, minute)
    if regular is not None:
        if await is_regular_lesson_skipped(int(regular.id), date):
            return False
        await cancel_regular_occurrence(
            telegram_id,
            date,
            hour,
            minute,
            note="Отменено учеником после подтверждения отсутствия",
            cancel_event_type="canceled_by_client",
            source_context="bot_presence",
        )
        return True

    rec = await session.execute(
        select(RecordDate.id).where(
            RecordDate.telegram_id == telegram_id,
            RecordDate.record_date == date,
            RecordDate.hour == hour,
            RecordDate.minute == minute,
            RecordDate.kind.not_in(["block", "allow"]),
            ((RecordDate.booking_status.is_(None)) | (RecordDate.booking_status == "approved")),
        )
    )
    if rec.first() is None:
        return False
    await delete_single_slot(
        telegram_id,
        date,
        hour,
        minute,
        cancel_event_type="canceled_by_client",
        source_context="bot_presence",
        note="Отменено учеником после подтверждения отсутствия",
    )
    return True


async def last_lesson_before_slot(
    telegram_id: int,
    date: datetime.date,
    hour: int,
    minute: int,
) -> tuple[datetime.date, int, int] | None:
    result = await session.execute(
        select(
            RecordDate.record_date,
            RecordDate.hour,
            RecordDate.minute,
        ).where(
            RecordDate.telegram_id == telegram_id,
            RecordDate.kind.not_in(["block", "allow"]),
            ((RecordDate.booking_status.is_(None)) | (RecordDate.booking_status == "approved")),
            (
                (RecordDate.record_date < date)
                | (
                    (RecordDate.record_date == date)
                    & (
                        (RecordDate.hour < hour)
                        | ((RecordDate.hour == hour) & (RecordDate.minute < minute))
                    )
                )
            ),
        ).order_by(
            RecordDate.record_date.desc(),
            RecordDate.hour.desc(),
            RecordDate.minute.desc(),
        )
    )
    row = result.first()
    if row is None:
        return None
    return (row.record_date, int(row.hour), int(row.minute))


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


def _hhmm_to_minutes(value: str) -> int:
    hour_s, minute_s = value.split(":")
    return int(hour_s) * 60 + int(minute_s)


def _minutes_to_hhmm(total_minutes: int) -> str:
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def working_minute_ranges_for_date(date: datetime.date) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for start, end in get_working_intervals_for_weekday(date.weekday()):
        start_min = _hhmm_to_minutes(start)
        end_min = _hhmm_to_minutes(end)
        if end_min > start_min:
            ranges.append((start_min, end_min))
    return ranges


def block_segments_for_date(
    date: datetime.date,
    all_day: bool,
    start_minute: int | None = None,
    end_minute: int | None = None,
) -> list[tuple[int, int]]:
    working_ranges = working_minute_ranges_for_date(date)
    if not working_ranges:
        return []
    if all_day:
        return working_ranges
    if start_minute is None or end_minute is None or end_minute <= start_minute:
        return []

    segments: list[tuple[int, int]] = []
    for work_start, work_end in working_ranges:
        seg_start = max(work_start, start_minute)
        seg_end = min(work_end, end_minute)
        if seg_end > seg_start:
            segments.append((seg_start, seg_end))
    return segments


async def migrate_legacy_full_day_block(date: datetime.date) -> int:
    legacy_rows = await session.execute(
        select(RecordDate).where(
            RecordDate.record_date == date,
            RecordDate.kind == "block",
            RecordDate.hour == 0,
            RecordDate.minute == 0,
            RecordDate.telegram_id.is_not(None),
        )
    )
    legacy_blocks = legacy_rows.scalars().all()
    if not legacy_blocks:
        return 0

    segments = block_segments_for_date(date, all_day=True)
    if not segments:
        return 0

    created = 0
    note = next(((row.note or "").strip() for row in legacy_blocks if (row.note or "").strip()), "Резерв администратора")
    for row in legacy_blocks:
        await session.delete(row)
    await session.commit()
    created = await create_block_slots(date, segments, note=note)
    return created


async def create_block_slots(
    date: datetime.date,
    segments: list[tuple[int, int]],
    note: str = "Резерв администратора",
) -> int:
    created = 0
    changed = False
    normalized_note = (note or "Резерв администратора").strip() or "Резерв администратора"
    for seg_start, seg_end in segments:
        minute_cursor = seg_start
        while minute_cursor < seg_end:
            hh = minute_cursor // 60
            mm = minute_cursor % 60
            exists_block = await session.execute(
                select(RecordDate).where(
                    RecordDate.record_date == date,
                    RecordDate.hour == hh,
                    RecordDate.minute == mm,
                    RecordDate.kind == "block",
                    RecordDate.telegram_id.is_(None),
                )
            )
            block = exists_block.scalar_one_or_none()
            if block:
                if normalized_note and not (block.note or "").strip():
                    block.note = normalized_note
                    changed = True
                minute_cursor += SLOT_STEP_MINUTES
                continue

            allow = await session.execute(
                select(RecordDate.id).where(
                    RecordDate.record_date == date,
                    RecordDate.hour == hh,
                    RecordDate.minute == mm,
                    RecordDate.kind == "allow",
                )
            )
            if allow.first():
                minute_cursor += SLOT_STEP_MINUTES
                continue

            session.add(
                RecordDate(
                    telegram_id=None,
                    record_date=date,
                    hour=hh,
                    minute=mm,
                    duration_minutes=SLOT_STEP_MINUTES,
                    kind="block",
                    note=normalized_note,
                    event_id=None,
                )
            )
            created += 1
            changed = True
            minute_cursor += SLOT_STEP_MINUTES
    if changed:
        await session.commit()
    return created


async def list_blocks_for_date(date: datetime.date) -> list[dict[str, Any]]:
    await migrate_legacy_full_day_block(date)
    rows = await session.execute(
        select(RecordDate).where(
            RecordDate.record_date == date,
            RecordDate.kind == "block",
            RecordDate.telegram_id.is_(None),
        ).order_by(RecordDate.hour.asc(), RecordDate.minute.asc(), RecordDate.id.asc())
    )
    items = []
    for row in rows.scalars():
        start_min = int(row.hour) * 60 + int(row.minute)
        end_min = start_min + max(SLOT_STEP_MINUTES, int(row.duration_minutes or SLOT_STEP_MINUTES))
        items.append(
            {
                "record_id": int(row.id),
                "start_minute": start_min,
                "end_minute": end_min,
                "note": (row.note or "").strip() or None,
            }
        )
    return items


def merge_block_items(block_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for item in sorted(block_items, key=lambda x: (int(x["start_minute"]), int(x["end_minute"]))):
        start_min = int(item["start_minute"])
        end_min = int(item["end_minute"])
        if current is None:
            current = {
                "start_minute": start_min,
                "end_minute": end_min,
                "note": item.get("note"),
            }
            continue
        if start_min <= int(current["end_minute"]):
            current["end_minute"] = max(int(current["end_minute"]), end_min)
            if not current.get("note") and item.get("note"):
                current["note"] = item["note"]
            continue
        merged.append(current)
        current = {
            "start_minute": start_min,
            "end_minute": end_min,
            "note": item.get("note"),
        }
    if current is not None:
        merged.append(current)

    result: list[dict[str, Any]] = []
    for idx, item in enumerate(merged, start=1):
        start_min = int(item["start_minute"])
        end_min = int(item["end_minute"])
        result.append(
            {
                "block_id": idx,
                "start_time": _minutes_to_hhmm(start_min),
                "end_time": _minutes_to_hhmm(end_min),
                "start_minute": start_min,
                "end_minute": end_min,
                "duration": max(SLOT_STEP_MINUTES, end_min - start_min),
                "note": item.get("note"),
            }
        )
    return result


async def list_block_ranges_for_date(date: datetime.date) -> list[dict[str, Any]]:
    items = await list_blocks_for_date(date)
    return merge_block_items(items)


async def delete_blocks_in_segments(date: datetime.date, segments: list[tuple[int, int]]) -> int:
    if not segments:
        return 0
    await migrate_legacy_full_day_block(date)
    rows = await session.execute(
        select(RecordDate).where(
            RecordDate.record_date == date,
            RecordDate.kind == "block",
            RecordDate.telegram_id.is_(None),
        )
    )
    to_delete = []
    for row in rows.scalars():
        start_min = int(row.hour) * 60 + int(row.minute)
        end_min = start_min + max(SLOT_STEP_MINUTES, int(row.duration_minutes or SLOT_STEP_MINUTES))
        for seg_start, seg_end in segments:
            if start_min < seg_end and end_min > seg_start:
                to_delete.append(row)
                break
    for row in to_delete:
        await session.delete(row)
    if to_delete:
        await session.commit()
    return len(to_delete)


async def find_conflicting_lessons(
    date: datetime.date,
    segments: list[tuple[int, int]],
) -> list[dict[str, Any]]:
    if not segments:
        return []

    def _intersects(start_min: int, end_min: int) -> bool:
        for seg_start, seg_end in segments:
            if start_min < seg_end and end_min > seg_start:
                return True
        return False

    records_rows = await session.execute(
        select(
            RecordDate.id,
            RecordDate.telegram_id,
            RecordDate.record_date,
            RecordDate.hour,
            RecordDate.minute,
            RecordDate.duration_minutes,
            RecordDate.kind,
            RecordDate.booking_status,
            StudentProfile.full_name,
            StudentProfile.telephone,
        )
        .join(StudentProfile, StudentProfile.telegram_id == RecordDate.telegram_id, isouter=True)
        .where(
            RecordDate.record_date == date,
            RecordDate.telegram_id.is_not(None),
            RecordDate.kind.not_in(["block", "allow"]),
            ((RecordDate.booking_status.is_(None)) | (RecordDate.booking_status.in_(["pending", "approved"]))),
        )
    )

    conflicts: list[dict[str, Any]] = []
    seen_slots: set[tuple[int | None, int, int]] = set()
    blocked_or_allowed_rows = await session.execute(
        select(RecordDate.hour, RecordDate.minute).where(
            RecordDate.record_date == date,
            RecordDate.kind.in_(["block", "allow"]),
        )
    )
    suppressed_times = {(int(row.hour), int(row.minute)) for row in blocked_or_allowed_rows}

    for row in records_rows:
        start_min = int(row.hour) * 60 + int(row.minute)
        end_min = start_min + int(row.duration_minutes or SLOT_DURATION_MINUTES)
        if not _intersects(start_min, end_min):
            continue
        seen_slots.add((int(row.telegram_id), int(row.hour), int(row.minute)))
        kind_value = (row.kind or "single").lower()
        conflicts.append(
            {
                "source": "record",
                "record_id": int(row.id),
                "telegram_id": int(row.telegram_id),
                "date": row.record_date.isoformat(),
                "time": f"{int(row.hour):02d}:{int(row.minute):02d}",
                "end_time": _minutes_to_hhmm(end_min),
                "duration": int(row.duration_minutes or SLOT_DURATION_MINUTES),
                "kind": "regular" if kind_value == "regular" else "single",
                "full_name": row.full_name,
                "phone": row.telephone,
                "booking_status": row.booking_status or "approved",
            }
        )

    weekday = date.weekday()
    skipped_ids = await skipped_regular_lesson_ids_for_date(date)
    regular_rows = await session.execute(
        select(
            RegularLesson.id,
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
            RegularLesson.telegram_id.is_not(None),
        )
    )
    for row in regular_rows:
        if int(row.id) in skipped_ids:
            continue
        slot_key = (int(row.telegram_id), int(row.hour or 0), int(row.minute or 0))
        time_key = (int(row.hour or 0), int(row.minute or 0))
        if slot_key in seen_slots or time_key in suppressed_times:
            continue
        start_min = int(row.hour or 0) * 60 + int(row.minute or 0)
        end_min = start_min + int(row.duration_minutes or SLOT_DURATION_MINUTES)
        if not _intersects(start_min, end_min):
            continue
        conflicts.append(
            {
                "source": "regular_template",
                "record_id": None,
                "telegram_id": int(row.telegram_id),
                "date": date.isoformat(),
                "time": f"{int(row.hour or 0):02d}:{int(row.minute or 0):02d}",
                "end_time": _minutes_to_hhmm(end_min),
                "duration": int(row.duration_minutes or SLOT_DURATION_MINUTES),
                "kind": "regular",
                "full_name": row.full_name,
                "phone": row.telephone,
                "booking_status": "approved",
            }
        )

    return sorted(conflicts, key=lambda item: (item["time"], item["telegram_id"]))


async def view_clients() -> list[Any]:
    res = await session.execute(
        select(StudentProfile).where((StudentProfile.is_deleted.is_(None)) | (StudentProfile.is_deleted.is_(False)))
    )
    return res.all()


async def view_record(telegram_id: int) -> list[Any]:
    res = await session.execute(
        select(RecordDate.record_date, RecordDate.hour, RecordDate.minute).where(
            RecordDate.telegram_id == telegram_id,
            (RecordDate.kind.is_(None) | (RecordDate.kind == "single")),
            ((RecordDate.booking_status.is_(None)) | (RecordDate.booking_status != "rejected")),
        ).order_by(
            RecordDate.record_date, RecordDate.hour, RecordDate.minute)
    )
    return res.all()


async def view_record_with_status(telegram_id: int) -> list[Any]:
    await _reset_transaction_snapshot()
    res = await session.execute(
        select(
            RecordDate.record_date,
            RecordDate.hour,
            RecordDate.minute,
            RecordDate.duration_minutes,
            RecordDate.booking_status,
            RecordDate.kind,
        ).where(
            RecordDate.telegram_id == telegram_id,
            RecordDate.kind.not_in(["block", "allow"]),
            ((RecordDate.booking_status.is_(None)) | (RecordDate.booking_status != "rejected")),
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
    base_filter = ((StudentProfile.is_deleted.is_(None)) | (StudentProfile.is_deleted.is_(False)))
    res = await session.execute(
        select(StudentProfile).where(base_filter, StudentProfile.telephone.ilike(f'%{search_text}%'))
    )
    res = res.all()

    if not res:
        res = await session.execute(
            select(StudentProfile).where(base_filter, StudentProfile.full_name.ilike(f'%{search_text}%'))
        )
        res = res.all()
    return res


async def rebind_student_telegram_id(old_telegram_id: int, new_telegram_id: int) -> None:
    if old_telegram_id == new_telegram_id:
        return

    profile = await session.get(StudentProfile, old_telegram_id)
    if not profile:
        raise LookupError("PROFILE_NOT_FOUND")

    existing = await session.get(StudentProfile, new_telegram_id)
    if existing:
        raise ValueError("TELEGRAM_ID_ALREADY_EXISTS")

    replacement = StudentProfile(
        telegram_id=new_telegram_id,
        full_name=profile.full_name,
        telegram_username=profile.telegram_username,
        age=profile.age,
        price=profile.price,
        direction=profile.direction,
        goal=profile.goal,
        notes=profile.notes,
        telephone=profile.telephone,
        blocked=profile.blocked,
        is_deleted=profile.is_deleted,
        last_visit_date=profile.last_visit_date,
        balance_lessons=profile.balance_lessons,
    )
    session.add(replacement)
    await session.flush()

    await session.execute(
        update(RecordDate).where(RecordDate.telegram_id == old_telegram_id).values(telegram_id=new_telegram_id)
    )
    await session.execute(
        update(RegularLesson).where(RegularLesson.telegram_id == old_telegram_id).values(telegram_id=new_telegram_id)
    )
    await session.execute(
        update(Payment).where(Payment.telegram_id == old_telegram_id).values(telegram_id=new_telegram_id)
    )

    await session.delete(profile)
    await session.commit()


async def merge_student_into_existing(old_telegram_id: int, new_telegram_id: int) -> None:
    if old_telegram_id == new_telegram_id:
        return

    source = await session.get(StudentProfile, old_telegram_id)
    target = await session.get(StudentProfile, new_telegram_id)
    if not source:
        raise LookupError("PROFILE_NOT_FOUND")
    if not target:
        raise LookupError("TARGET_PROFILE_NOT_FOUND")

    # Переносим все связанные сущности на новый telegram_id.
    await session.execute(
        update(RecordDate).where(RecordDate.telegram_id == old_telegram_id).values(telegram_id=new_telegram_id)
    )
    await session.execute(
        update(RegularLesson).where(RegularLesson.telegram_id == old_telegram_id).values(telegram_id=new_telegram_id)
    )
    await session.execute(
        update(Payment).where(Payment.telegram_id == old_telegram_id).values(telegram_id=new_telegram_id)
    )

    # Объединяем профиль: берем значимые поля из старого, если они заполнены.
    if source.full_name:
        target.full_name = source.full_name
    if source.first_name:
        target.first_name = source.first_name
    if source.last_name:
        target.last_name = source.last_name
    if source.telegram_username:
        target.telegram_username = source.telegram_username
    if source.age is not None:
        target.age = source.age
    if source.price is not None:
        target.price = source.price
    if source.direction:
        target.direction = source.direction
    if source.goal:
        target.goal = source.goal
    if source.notes:
        target.notes = source.notes
    if source.telephone:
        target.telephone = source.telephone
    target.full_name = _compose_full_name(target.first_name, target.last_name) or target.full_name
    target.balance_lessons = int(target.balance_lessons or 0) + int(source.balance_lessons or 0)
    target.blocked = bool(target.blocked and source.blocked)
    target.is_deleted = 0

    await session.delete(source)
    await session.commit()


async def soft_delete_user(telegram_id: int) -> bool:
    profile = await session.get(StudentProfile, telegram_id)
    if not profile:
        return False
    profile.is_deleted = 1
    profile.blocked = 1
    await session.commit()
    return True


async def reserve_day(
        telegram_id: int, date: datetime, beginning_working_day: int, end_working_day: int, note: str = "Резерв администратора"
) -> int:
    _ = (telegram_id, beginning_working_day, end_working_day)
    segments = block_segments_for_date(date, all_day=True)
    if not segments:
        return 0
    await migrate_legacy_full_day_block(date)
    created = await create_block_slots(date, segments, note=note)
    return 1 if created >= 0 else 0


async def list_date_availability_overrides(target_date: datetime.date) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(DateAvailabilityOverride).where(
            DateAvailabilityOverride.target_date == target_date,
            DateAvailabilityOverride.mode == "extra_open",
        ).order_by(DateAvailabilityOverride.start_minute, DateAvailabilityOverride.end_minute)
    )
    items: list[dict[str, Any]] = []
    for row in rows.scalars().all():
        items.append(
            {
                "id": int(row.id),
                "date": target_date.isoformat(),
                "start_time": f"{int(row.start_minute) // 60:02d}:{int(row.start_minute) % 60:02d}",
                "end_time": f"{int(row.end_minute) // 60:02d}:{int(row.end_minute) % 60:02d}",
                "note": row.note or "",
                "mode": row.mode,
            }
        )
    return items


async def create_date_availability_override(
    target_date: datetime.date,
    start_minute: int,
    end_minute: int,
    note: str | None = None,
) -> dict[str, Any]:
    item = DateAvailabilityOverride(
        target_date=target_date,
        start_minute=start_minute,
        end_minute=end_minute,
        mode="extra_open",
        note=(note or "").strip() or None,
        created_at=datetime.datetime.now().isoformat(),
    )
    session.add(item)
    await session.commit()
    await refresh_schedule_cache()
    return {
        "id": int(item.id),
        "date": target_date.isoformat(),
        "start_time": f"{start_minute // 60:02d}:{start_minute % 60:02d}",
        "end_time": f"{end_minute // 60:02d}:{end_minute % 60:02d}",
        "note": item.note or "",
        "mode": item.mode,
    }


async def delete_date_availability_override(item_id: int) -> bool:
    item = await session.get(DateAvailabilityOverride, item_id)
    if not item:
        return False
    await session.delete(item)
    await session.commit()
    await refresh_schedule_cache()
    return True


async def mailing_for_day(date: datetime) -> list[Any]:
    res = await session.execute(
        select(RecordDate.telegram_id, RecordDate.hour, RecordDate.minute).where(
            RecordDate.record_date == date,
            RecordDate.telegram_id.is_not(None),
            RecordDate.kind != "block",
            ((RecordDate.booking_status.is_(None)) | (RecordDate.booking_status == "approved")),
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
    skipped_ids = await skipped_regular_lesson_ids_for_date(target_date)

    singles = await session.execute(
        select(
            StudentProfile.full_name,
            StudentProfile.telephone,
            StudentProfile.telegram_username,
            StudentProfile.price,
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
            row.price if row.price is not None else 0,
        ))

    weekday = target_date.weekday()
    regulars = await session.execute(
        select(
            RegularLesson.id,
            StudentProfile.full_name,
            StudentProfile.telephone,
            StudentProfile.telegram_username,
            StudentProfile.price,
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
        if int(row.id) in skipped_ids:
            continue
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
            row.price if row.price is not None else 0,
        ))

    # Добавляем информацию о блоках (для админов) с реальным временем
    if show_blocks and blocked_times:
        for (bh, bm), note in sorted(blocked_times.items(), key=lambda x: (x[0][0], x[0][1])):
            result.append(("Резерв администратора", "", bh, bm, "Блок", note or "День недоступен", None, None, 0))

    return sorted(result, key=lambda r: (r[2], r[3]))


async def admin_schedule_month_summary(
    start_date: datetime.date,
    end_date: datetime.date,
    duration_minutes: int = SLOT_DURATION_MINUTES,
) -> list[dict[str, Any]]:
    month_dates = [
        start_date + datetime.timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1)
    ]
    if not month_dates:
        return []

    today = datetime.date.today()
    now_local = datetime.datetime.now(get_calendar_tz()).replace(tzinfo=None)
    weekdays = sorted({target_date.weekday() for target_date in month_dates})

    record_rows = (
        await session.execute(
            select(
                RecordDate.record_date,
                RecordDate.telegram_id,
                RecordDate.hour,
                RecordDate.minute,
                RecordDate.duration_minutes,
                RecordDate.kind,
                RecordDate.booking_status,
                RecordDate.event_id,
            ).where(
                RecordDate.record_date >= start_date,
                RecordDate.record_date <= end_date,
            )
        )
    ).all()

    skipped_rows = (
        await session.execute(
            select(
                RegularLessonException.exception_date,
                RegularLessonException.regular_lesson_id,
            ).where(
                RegularLessonException.exception_date >= start_date,
                RegularLessonException.exception_date <= end_date,
                RegularLessonException.action == "skip",
            )
        )
    ).all()

    regular_rows = (
        await session.execute(
            select(
                RegularLesson.id,
                RegularLesson.day_of_week,
                RegularLesson.telegram_id,
                RegularLesson.hour,
                RegularLesson.minute,
                RegularLesson.duration_minutes,
            ).where(
                RegularLesson.day_of_week.in_(weekdays),
                RegularLesson.telegram_id.is_not(None),
            )
        )
    ).all()

    records_by_date: dict[datetime.date, list[Any]] = defaultdict(list)
    for row in record_rows:
        records_by_date[row.record_date].append(row)

    skipped_by_date: dict[datetime.date, set[int]] = defaultdict(set)
    for row in skipped_rows:
        if row.exception_date is not None and row.regular_lesson_id is not None:
            skipped_by_date[row.exception_date].add(int(row.regular_lesson_id))

    regulars_by_weekday: dict[int, list[Any]] = defaultdict(list)
    for row in regular_rows:
        regulars_by_weekday[int(row.day_of_week or 0)].append(row)

    days: list[dict[str, Any]] = []
    for target_date in month_dates:
        rows = records_by_date.get(target_date, [])
        blocked_times: set[tuple[int, int]] = set()
        allow_times: set[tuple[int, int]] = set()
        seen_slots: set[tuple[int | None, int, int]] = set()
        busy_intervals: list[tuple[datetime.datetime, datetime.datetime]] = []
        seen_intervals: set[tuple[datetime.datetime, datetime.datetime]] = set()
        booked_count = 0

        for row in rows:
            hour = int(row.hour or 0)
            minute = int(row.minute or 0)
            duration = int(row.duration_minutes or SLOT_DURATION_MINUTES)
            kind = (row.kind or "").lower()
            status = (row.booking_status or "").lower()

            if row.telegram_id is None and (
                kind in {"block", "allow"} or (row.kind is None and row.event_id is None)
            ):
                blocked_times.add((hour, minute))

            if kind == "allow":
                allow_times.add((hour, minute))

            if kind != "allow" and status != "rejected":
                if kind == "block" and hour == 0 and minute == 0:
                    start_dt = datetime.datetime.combine(target_date, datetime.time.min)
                    end_dt = start_dt + datetime.timedelta(days=1)
                else:
                    start_dt = datetime.datetime.combine(target_date, datetime.time(hour, minute))
                    end_dt = start_dt + datetime.timedelta(minutes=max(1, duration))
                interval = (start_dt, end_dt)
                if interval not in seen_intervals:
                    seen_intervals.add(interval)
                    busy_intervals.append(interval)

            if row.telegram_id is not None and kind != "block":
                slot_key = (int(row.telegram_id), hour, minute)
                if slot_key not in seen_slots:
                    seen_slots.add(slot_key)
                    booked_count += 1

        for reg in regulars_by_weekday.get(target_date.weekday(), []):
            reg_id = int(reg.id)
            hour = int(reg.hour or 0)
            minute = int(reg.minute or 0)
            duration = int(reg.duration_minutes or SLOT_DURATION_MINUTES)

            if reg_id in skipped_by_date.get(target_date, set()):
                continue
            if (hour, minute) in blocked_times:
                continue

            slot_key = (int(reg.telegram_id), hour, minute)
            if slot_key not in seen_slots:
                seen_slots.add(slot_key)
                booked_count += 1

            if (hour, minute) in allow_times:
                continue

            start_dt = datetime.datetime.combine(target_date, datetime.time(hour, minute))
            end_dt = start_dt + datetime.timedelta(minutes=max(1, duration))
            interval = (start_dt, end_dt)
            if interval not in seen_intervals:
                seen_intervals.add(interval)
                busy_intervals.append(interval)

        busy_intervals.sort(key=lambda item: item[0])

        if target_date < today:
            free_count = 0
        else:
            free_count = 0
            for hour, minute in slots_for_date(target_date, now_local):
                start_dt = datetime.datetime.combine(target_date, datetime.time(hour, minute))
                end_dt = start_dt + datetime.timedelta(minutes=duration_minutes)
                overlaps_busy = False
                for busy_start, busy_end in busy_intervals:
                    if busy_start >= end_dt:
                        break
                    if _overlaps(start_dt, end_dt, busy_start, busy_end):
                        overlaps_busy = True
                        break
                if not overlaps_busy:
                    free_count += 1

        days.append(
            {
                "date": target_date.isoformat(),
                "booked_count": booked_count,
                "free_count": free_count,
                "has_booked": booked_count > 0,
                "has_free": free_count > 0,
                "past": target_date < today,
            }
        )

    return days


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
    target_date = date if isinstance(date, datetime.date) else None
    weekday = date.weekday() if isinstance(date, datetime.date) else date
    allow_times = await legacy_allow_times_for_date(target_date) if target_date else set()
    if target_date and (hour, minute) in allow_times:
        return None
    skipped_ids = await skipped_regular_lesson_ids_for_date(target_date) if target_date else set()
    reg = await session.execute(
        select(RegularLesson.id, RegularLesson.telegram_id, RegularLesson.day_of_week).where(
            RegularLesson.day_of_week == weekday,
            RegularLesson.hour == hour,
            RegularLesson.minute == minute,
        )
    )
    reg_row = next((row for row in reg.all() if int(row[0]) not in skipped_ids), None)
    if reg_row:
        return (reg_row[1], "regular")
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
    allow_times = await legacy_allow_times_for_date(date)
    if (hour, minute) in allow_times:
        return None
    skipped_ids = await skipped_regular_lesson_ids_for_date(date)
    reg = await session.execute(
        select(RegularLesson.id, RegularLesson.duration_minutes).where(
            RegularLesson.telegram_id == telegram_id,
            RegularLesson.day_of_week == weekday,
            RegularLesson.hour == hour,
            RegularLesson.minute == minute,
        )
    )
    reg_row = next((row for row in reg.all() if int(row[0]) not in skipped_ids), None)
    if reg_row is not None:
        return ("regular", reg_row[1] or SLOT_DURATION_MINUTES)
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
    source_context: str | None = "admin",
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
    await log_analytics_event(
        "rescheduled_from",
        telegram_id=telegram_id,
        record_date=old_date,
        hour=old_hour,
        minute=old_minute,
        duration_minutes=duration,
        lesson_kind=record.kind or "single",
        source_context=source_context,
        related_slot_date=new_date,
        related_slot_hour=new_hour,
        related_slot_minute=new_minute,
        commit=False,
    )
    await log_analytics_event(
        "rescheduled_to",
        telegram_id=telegram_id,
        record_date=new_date,
        hour=new_hour,
        minute=new_minute,
        duration_minutes=duration,
        lesson_kind="single",
        source_context=source_context,
        related_slot_date=old_date,
        related_slot_hour=old_hour,
        related_slot_minute=old_minute,
        commit=False,
    )
    await session.commit()
    return True


async def records_starting_at_details(date: datetime.date, hour: int, minute: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    blocked_rows = await session.execute(
        select(RecordDate.hour, RecordDate.minute).where(
            RecordDate.record_date == date,
            RecordDate.kind == "block",
        )
    )
    blocked_times = {(int(row.hour), int(row.minute)) for row in blocked_rows}

    res = await session.execute(
        select(
            StudentProfile.telegram_id,
            StudentProfile.full_name,
            StudentProfile.telephone,
            StudentProfile.price,
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
            RecordDate.kind.not_in(["block", "allow"]),
            ((RecordDate.booking_status.is_(None)) | (RecordDate.booking_status == "approved")),
        )
    )
    seen = set()
    for row in res.all():
        tg_id = int(row.telegram_id)
        key = (tg_id, int(row.hour), int(row.minute))
        seen.add(key)
        last_lesson = await last_lesson_before_slot(tg_id, date, hour, minute)
        duration_val = int(row.duration_minutes or SLOT_DURATION_MINUTES)
        price_60 = int(row.price or 0)
        result.append(
            {
                "telegram_id": tg_id,
                "full_name": row.full_name,
                "telephone": row.telephone,
                "hour": int(row.hour),
                "minute": int(row.minute),
                "duration_minutes": duration_val,
                "kind": "regular" if (row.kind or "single") == "regular" else "single",
                "price_60": price_60,
                "amount": max(0, int(round(price_60 * (duration_val / 60.0)))),
                "last_lesson": last_lesson,
            }
        )

    weekday = date.weekday()
    skipped_ids = await skipped_regular_lesson_ids_for_date(date)
    allow_times = await legacy_allow_times_for_date(date)
    regs = await session.execute(
        select(
            RegularLesson.id,
            RegularLesson.telegram_id,
            RegularLesson.hour,
            RegularLesson.minute,
            RegularLesson.duration_minutes,
            StudentProfile.full_name,
            StudentProfile.telephone,
            StudentProfile.price,
        )
        .join(StudentProfile, StudentProfile.telegram_id == RegularLesson.telegram_id, isouter=True)
        .where(
            RegularLesson.day_of_week == weekday,
            RegularLesson.telegram_id.is_not(None),
            RegularLesson.hour == hour,
            RegularLesson.minute == minute,
        )
    )
    for row in regs:
        if int(row.id) in skipped_ids:
            continue
        time_key = (int(row.hour or 0), int(row.minute or 0))
        if time_key in allow_times or time_key in blocked_times:
            continue
        tg_id = int(row.telegram_id)
        key = (tg_id, int(row.hour or 0), int(row.minute or 0))
        if key in seen:
            continue
        last_lesson = await last_lesson_before_slot(tg_id, date, hour, minute)
        duration_val = int(row.duration_minutes or SLOT_DURATION_MINUTES)
        price_60 = int(row.price or 0)
        result.append(
            {
                "telegram_id": tg_id,
                "full_name": row.full_name,
                "telephone": row.telephone,
                "hour": int(row.hour or 0),
                "minute": int(row.minute or 0),
                "duration_minutes": duration_val,
                "kind": "regular",
                "price_60": price_60,
                "amount": max(0, int(round(price_60 * (duration_val / 60.0)))),
                "last_lesson": last_lesson,
            }
        )
    return result


async def records_starting_at(date: datetime.date, hour: int, minute: int) -> list[Any]:
    details = await records_starting_at_details(date, hour, minute)
    return [
        (
            item["telegram_id"],
            item["full_name"],
            item["telephone"],
            item["hour"],
            item["minute"],
            item["duration_minutes"],
            item["kind"],
        )
        for item in details
    ]


async def lessons_for_date_details(date: datetime.date) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    blocked_rows = await session.execute(
        select(RecordDate.hour, RecordDate.minute).where(
            RecordDate.record_date == date,
            RecordDate.kind == "block",
        )
    )
    blocked_times = {(int(row.hour), int(row.minute)) for row in blocked_rows}

    res = await session.execute(
        select(
            StudentProfile.telegram_id,
            StudentProfile.full_name,
            StudentProfile.telephone,
            StudentProfile.price,
            RecordDate.hour,
            RecordDate.minute,
            RecordDate.duration_minutes,
            RecordDate.kind,
        )
        .join(StudentProfile, StudentProfile.telegram_id == RecordDate.telegram_id)
        .where(
            RecordDate.record_date == date,
            ((RecordDate.kind.is_(None)) | (RecordDate.kind.not_in(["block", "allow"]))),
            ((RecordDate.booking_status.is_(None)) | (RecordDate.booking_status == "approved")),
        )
    )
    seen = set()
    for row in res.all():
        tg_id = int(row.telegram_id)
        hour = int(row.hour or 0)
        minute = int(row.minute or 0)
        key = (tg_id, hour, minute)
        seen.add(key)
        duration_val = int(row.duration_minutes or SLOT_DURATION_MINUTES)
        price_60 = int(row.price or 0)
        result.append(
            {
                "telegram_id": tg_id,
                "full_name": row.full_name,
                "telephone": row.telephone,
                "hour": hour,
                "minute": minute,
                "duration_minutes": duration_val,
                "kind": "regular" if (row.kind or "single") == "regular" else "single",
                "price_60": price_60,
                "amount": max(0, int(round(price_60 * (duration_val / 60.0)))),
            }
        )

    weekday = date.weekday()
    skipped_ids = await skipped_regular_lesson_ids_for_date(date)
    allow_times = await legacy_allow_times_for_date(date)
    regs = await session.execute(
        select(
            RegularLesson.id,
            RegularLesson.telegram_id,
            RegularLesson.hour,
            RegularLesson.minute,
            RegularLesson.duration_minutes,
            StudentProfile.full_name,
            StudentProfile.telephone,
            StudentProfile.price,
        )
        .join(StudentProfile, StudentProfile.telegram_id == RegularLesson.telegram_id, isouter=True)
        .where(
            RegularLesson.day_of_week == weekday,
            RegularLesson.telegram_id.is_not(None),
        )
    )
    for row in regs:
        if int(row.id) in skipped_ids:
            continue
        hour = int(row.hour or 0)
        minute = int(row.minute or 0)
        time_key = (hour, minute)
        if time_key in allow_times or time_key in blocked_times:
            continue
        tg_id = int(row.telegram_id)
        key = (tg_id, hour, minute)
        if key in seen:
            continue
        duration_val = int(row.duration_minutes or SLOT_DURATION_MINUTES)
        price_60 = int(row.price or 0)
        result.append(
            {
                "telegram_id": tg_id,
                "full_name": row.full_name,
                "telephone": row.telephone,
                "hour": hour,
                "minute": minute,
                "duration_minutes": duration_val,
                "kind": "regular",
                "price_60": price_60,
                "amount": max(0, int(round(price_60 * (duration_val / 60.0)))),
            }
        )

    return sorted(result, key=lambda item: (item["hour"], item["minute"], item["full_name"] or ""))


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
    skipped_ids = await skipped_regular_lesson_ids_for_date(date)
    allow_times = await legacy_allow_times_for_date(date)
    block_rows = await session.execute(
        select(RecordDate.hour, RecordDate.minute).where(
            RecordDate.record_date == date,
            RecordDate.telegram_id.is_(None),
            (
                (RecordDate.kind.in_(["block", "allow"]))
                | ((RecordDate.kind.is_(None)) & (RecordDate.event_id.is_(None)))
            ),
        )
    )
    blocked_times = {(int(row.hour or 0), int(row.minute or 0)) for row in block_rows}
    regular = await session.execute(
        select(
            RegularLesson.id,
            RegularLesson.telegram_id,
            RegularLesson.hour,
            RegularLesson.minute,
            RegularLesson.duration_minutes,
        ).where(RegularLesson.day_of_week == weekday)
    )
    for row in regular:
        if int(row.id) in skipped_ids:
            continue
        if (int(row.hour or 0), int(row.minute or 0)) in blocked_times:
            continue
        if (int(row.hour or 0), int(row.minute or 0)) in allow_times:
            continue
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
    if (hour, minute) in await legacy_allow_times_for_date(date):
        return None
    skipped_ids = await skipped_regular_lesson_ids_for_date(date)
    reg = await session.execute(
        select(RegularLesson.id).where(
            RegularLesson.day_of_week == weekday,
            RegularLesson.hour == hour,
            RegularLesson.minute == minute,
            RegularLesson.telegram_id == telegram_id,
        )
    )
    if next((row for row in reg.all() if int(row[0]) not in skipped_ids), None):
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


async def client_activity_for_range(
    start_date: datetime.date,
    end_date: datetime.date,
) -> list[dict[str, Any]]:
    """
    Активность клиентов за период по проведенным занятиям (paid/unpaid, без canceled).
    """
    res = await session.execute(
        select(
            Payment.telegram_id,
            func.coalesce(StudentProfile.full_name, Payment.full_name),
            func.count(Payment.id),
            func.sum(
                case(
                    (Payment.status == "paid", func.coalesce(Payment.amount, 0)),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (Payment.status == "unpaid", func.coalesce(Payment.amount, 0)),
                    else_=0,
                )
            ),
            func.max(Payment.lesson_date),
            func.max(Payment.hour),
            func.max(Payment.minute),
        )
        .join(StudentProfile, StudentProfile.telegram_id == Payment.telegram_id, isouter=True)
        .where(
            Payment.lesson_date >= start_date,
            Payment.lesson_date <= end_date,
            Payment.status != "canceled",
            Payment.telegram_id.is_not(None),
            ((StudentProfile.is_deleted.is_(None)) | (StudentProfile.is_deleted.is_(False)) | (StudentProfile.telegram_id.is_(None))),
        )
        .group_by(Payment.telegram_id, func.coalesce(StudentProfile.full_name, Payment.full_name))
        .order_by(func.count(Payment.id).desc())
    )
    items = []
    for row in res.all():
        items.append(
            {
                "telegram_id": int(row[0]) if row[0] is not None else None,
                "full_name": row[1] or (str(row[0]) if row[0] is not None else "—"),
                "lessons_count": int(row[2] or 0),
                "paid_amount": int(row[3] or 0),
                "unpaid_amount": int(row[4] or 0),
                "last_lesson_date": row[5].isoformat() if row[5] and hasattr(row[5], "isoformat") else (str(row[5]) if row[5] else None),
                "last_lesson_time": (
                    f"{int(row[6] or 0):02d}:{int(row[7] or 0):02d}" if row[6] is not None and row[7] is not None else None
                ),
            }
        )
    return items


async def first_lesson_dates_for_clients(client_ids: list[int]) -> dict[int, datetime.date]:
    """
    Первая дата проведенного занятия по каждому клиенту.
    """
    if not client_ids:
        return {}
    res = await session.execute(
        select(
            Payment.telegram_id,
            func.min(Payment.lesson_date),
        )
        .where(
            Payment.telegram_id.in_(client_ids),
            Payment.status != "canceled",
        )
        .group_by(Payment.telegram_id)
    )
    out: dict[int, datetime.date] = {}
    for tg_id, first_date in res.all():
        if tg_id is None or first_date is None:
            continue
        out[int(tg_id)] = first_date
    return out


async def payments_timeseries_for_range(
    start_date: datetime.date,
    end_date: datetime.date,
) -> list[dict[str, Any]]:
    """
    Дневной timeseries: оплачено, проведено занятий, активные клиенты.
    """
    res = await session.execute(
        select(
            Payment.lesson_date,
            func.sum(case((Payment.status == "paid", func.coalesce(Payment.amount, 0)), else_=0)),
            func.count(Payment.id),
            func.count(func.distinct(Payment.telegram_id)),
        )
        .where(
            Payment.lesson_date >= start_date,
            Payment.lesson_date <= end_date,
            Payment.status != "canceled",
        )
        .group_by(Payment.lesson_date)
        .order_by(Payment.lesson_date)
    )
    by_date: dict[str, tuple[int, int, int]] = {}
    for d, paid_amount, lessons_done, active_clients in res.all():
        key = d.isoformat() if hasattr(d, "isoformat") else str(d)
        by_date[key] = (int(paid_amount or 0), int(lessons_done or 0), int(active_clients or 0))

    items: list[dict[str, Any]] = []
    cursor = start_date
    while cursor <= end_date:
        key = cursor.isoformat()
        paid_amount, lessons_done, active_clients = by_date.get(key, (0, 0, 0))
        items.append(
            {
                "date": key,
                "paid_amount": paid_amount,
                "lessons_done": lessons_done,
                "active_clients": active_clients,
            }
        )
        cursor += datetime.timedelta(days=1)
    return items


async def client_revenue_share_for_range(
    start_date: datetime.date,
    end_date: datetime.date,
    limit: int = 6,
) -> dict[str, Any]:
    res = await session.execute(
        select(
            Payment.telegram_id,
            func.coalesce(StudentProfile.full_name, Payment.full_name),
            func.sum(
                case(
                    (Payment.status == "paid", func.coalesce(Payment.amount, 0)),
                    else_=0,
                )
            ),
            func.count(Payment.id),
        )
        .join(StudentProfile, StudentProfile.telegram_id == Payment.telegram_id, isouter=True)
        .where(
            Payment.lesson_date >= start_date,
            Payment.lesson_date <= end_date,
            Payment.status != "canceled",
            Payment.telegram_id.is_not(None),
            ((StudentProfile.is_deleted.is_(None)) | (StudentProfile.is_deleted.is_(False)) | (StudentProfile.telegram_id.is_(None))),
        )
        .group_by(Payment.telegram_id, func.coalesce(StudentProfile.full_name, Payment.full_name))
        .order_by(
            func.sum(
                case(
                    (Payment.status == "paid", func.coalesce(Payment.amount, 0)),
                    else_=0,
                )
            ).desc(),
            func.count(Payment.id).desc(),
        )
    )

    rows = res.all()
    total_paid = sum(int(row[2] or 0) for row in rows)
    if total_paid <= 0:
        return {"total_paid": 0, "items": []}

    top_rows = rows[:max(1, limit)]
    items: list[dict[str, Any]] = []
    for row in top_rows:
        paid_amount = int(row[2] or 0)
        if paid_amount <= 0:
            continue
        items.append(
            {
                "telegram_id": int(row[0]) if row[0] is not None else None,
                "full_name": row[1] or (str(row[0]) if row[0] is not None else "—"),
                "paid_amount": paid_amount,
                "lessons_count": int(row[3] or 0),
                "share_pct": round((paid_amount / total_paid) * 100.0, 2),
            }
        )

    others_amount = max(0, total_paid - sum(int(item["paid_amount"]) for item in items))
    if others_amount > 0:
        items.append(
            {
                "telegram_id": None,
                "full_name": "Остальные",
                "paid_amount": others_amount,
                "lessons_count": sum(int(row[3] or 0) for row in rows[len(top_rows):]),
                "share_pct": round((others_amount / total_paid) * 100.0, 2),
            }
        )

    return {
        "total_paid": total_paid,
        "items": items,
    }


def _safe_ratio(part: int | float, total: int | float) -> float:
    total_num = float(total or 0)
    if total_num <= 0:
        return 0.0
    return round((float(part or 0) / total_num) * 100.0, 2)


def _client_display_name(row_name: str | None, tg_id: int | None) -> str:
    return row_name or (str(tg_id) if tg_id is not None else "—")


async def client_ltv_leaderboard(limit: int = 8) -> list[dict[str, Any]]:
    res = await session.execute(
        select(
            Payment.telegram_id,
            func.coalesce(StudentProfile.full_name, Payment.full_name),
            func.sum(case((Payment.status == "paid", func.coalesce(Payment.amount, 0)), else_=0)),
            func.count(Payment.id),
            func.min(Payment.lesson_date),
            func.max(Payment.lesson_date),
        )
        .join(StudentProfile, StudentProfile.telegram_id == Payment.telegram_id, isouter=True)
        .where(
            Payment.status != "canceled",
            Payment.telegram_id.is_not(None),
        )
        .group_by(Payment.telegram_id, func.coalesce(StudentProfile.full_name, Payment.full_name))
        .order_by(
            func.sum(case((Payment.status == "paid", func.coalesce(Payment.amount, 0)), else_=0)).desc(),
            func.count(Payment.id).desc(),
        )
    )
    items: list[dict[str, Any]] = []
    for row in res.all()[:max(1, limit)]:
        total_revenue = int(row[2] or 0)
        total_lessons = int(row[3] or 0)
        items.append(
            {
                "telegram_id": int(row[0]) if row[0] is not None else None,
                "full_name": _client_display_name(row[1], int(row[0]) if row[0] is not None else None),
                "total_revenue": total_revenue,
                "total_lessons": total_lessons,
                "avg_revenue_per_lesson": int(round(total_revenue / total_lessons)) if total_lessons > 0 else 0,
                "first_lesson": row[4].isoformat() if row[4] else None,
                "last_lesson": row[5].isoformat() if row[5] else None,
            }
        )
    return items


async def retention_overview(max_cohorts: int = 6) -> dict[str, Any]:
    res = await session.execute(
        select(
            Payment.telegram_id,
            Payment.lesson_date,
        )
        .where(
            Payment.status != "canceled",
            Payment.telegram_id.is_not(None),
        )
        .order_by(Payment.telegram_id.asc(), Payment.lesson_date.asc(), Payment.hour.asc(), Payment.minute.asc(), Payment.id.asc())
    )
    lessons_by_client: dict[int, list[datetime.date]] = defaultdict(list)
    for tg_id, lesson_date in res.all():
        if tg_id is None or lesson_date is None:
            continue
        lessons_by_client[int(tg_id)].append(lesson_date)

    checkpoints = (2, 4, 8)
    totals = {weeks: 0 for weeks in checkpoints}
    retained = {weeks: 0 for weeks in checkpoints}
    cohorts: dict[str, dict[str, Any]] = {}

    for tg_id, lesson_dates in lessons_by_client.items():
        if not lesson_dates:
            continue
        first_date = lesson_dates[0]
        month_key = first_date.strftime("%Y-%m")
        cohort = cohorts.setdefault(
            month_key,
            {
                "cohort": month_key,
                "clients": 0,
                "retained_2w": 0,
                "retained_4w": 0,
                "retained_8w": 0,
            },
        )
        cohort["clients"] += 1
        for weeks in checkpoints:
            totals[weeks] += 1
            retained_flag = any(date_value >= (first_date + datetime.timedelta(weeks=weeks)) for date_value in lesson_dates[1:])
            if retained_flag:
                retained[weeks] += 1
                cohort[f"retained_{weeks}w"] += 1

    cohort_items = sorted(cohorts.values(), key=lambda item: item["cohort"], reverse=True)[:max_cohorts]
    for item in cohort_items:
        clients = int(item.get("clients") or 0)
        for weeks in checkpoints:
            item[f"retention_{weeks}w_pct"] = _safe_ratio(int(item.get(f"retained_{weeks}w") or 0), clients)

    return {
        "summary": {
            f"retention_{weeks}w_pct": _safe_ratio(retained[weeks], totals[weeks])
            for weeks in checkpoints
        },
        "cohorts": cohort_items,
        "clients_total": sum(int(item.get("clients") or 0) for item in cohorts.values()),
    }


async def revenue_drivers_for_ranges(
    current_from: datetime.date,
    current_to: datetime.date,
    previous_from: datetime.date,
    previous_to: datetime.date,
    limit: int = 5,
) -> dict[str, Any]:
    cur_clients = await client_activity_for_range(current_from, current_to)
    prev_clients = await client_activity_for_range(previous_from, previous_to)
    cur_map = {int(item["telegram_id"]): item for item in cur_clients if item.get("telegram_id") is not None}
    prev_map = {int(item["telegram_id"]): item for item in prev_clients if item.get("telegram_id") is not None}
    all_ids = sorted(set(cur_map) | set(prev_map))

    gainers: list[dict[str, Any]] = []
    decliners: list[dict[str, Any]] = []
    groups = {"new": 0, "churned": 0, "grew": 0, "declined": 0}

    for tg_id in all_ids:
        cur_item = cur_map.get(tg_id)
        prev_item = prev_map.get(tg_id)
        cur_paid = int((cur_item or {}).get("paid_amount") or 0)
        prev_paid = int((prev_item or {}).get("paid_amount") or 0)
        delta = cur_paid - prev_paid
        label = _client_display_name(
            (cur_item or prev_item or {}).get("full_name"),
            tg_id,
        )
        row = {
            "telegram_id": tg_id,
            "full_name": label,
            "paid_now": cur_paid,
            "paid_prev": prev_paid,
            "delta_abs": delta,
        }
        if prev_paid == 0 and cur_paid > 0:
            row["group"] = "new"
            groups["new"] += 1
            gainers.append(row)
        elif cur_paid == 0 and prev_paid > 0:
            row["group"] = "churned"
            groups["churned"] += 1
            decliners.append(row)
        elif delta > 0:
            row["group"] = "grew"
            groups["grew"] += 1
            gainers.append(row)
        elif delta < 0:
            row["group"] = "declined"
            groups["declined"] += 1
            decliners.append(row)

    gainers.sort(key=lambda item: (item["delta_abs"], item["paid_now"]), reverse=True)
    decliners.sort(key=lambda item: (item["delta_abs"], item["paid_prev"]))
    return {
        "summary": groups,
        "gainers": gainers[:max(1, limit)],
        "decliners": decliners[:max(1, limit)],
    }


async def _schedule_state_for_range(
    start_date: datetime.date,
    end_date: datetime.date,
) -> dict[datetime.date, dict[str, Any]]:
    all_dates = [start_date + datetime.timedelta(days=offset) for offset in range((end_date - start_date).days + 1)]
    if not all_dates:
        return {}
    weekdays = sorted({item.weekday() for item in all_dates})

    record_rows = (
        await session.execute(
            select(
                RecordDate.record_date,
                RecordDate.telegram_id,
                RecordDate.hour,
                RecordDate.minute,
                RecordDate.duration_minutes,
                RecordDate.kind,
                RecordDate.booking_status,
                RecordDate.event_id,
            ).where(
                RecordDate.record_date >= start_date,
                RecordDate.record_date <= end_date,
            )
        )
    ).all()
    skipped_rows = (
        await session.execute(
            select(
                RegularLessonException.exception_date,
                RegularLessonException.regular_lesson_id,
            ).where(
                RegularLessonException.exception_date >= start_date,
                RegularLessonException.exception_date <= end_date,
                RegularLessonException.action == "skip",
            )
        )
    ).all()
    regular_rows = (
        await session.execute(
            select(
                RegularLesson.id,
                RegularLesson.day_of_week,
                RegularLesson.telegram_id,
                RegularLesson.hour,
                RegularLesson.minute,
                RegularLesson.duration_minutes,
            ).where(
                RegularLesson.day_of_week.in_(weekdays),
                RegularLesson.telegram_id.is_not(None),
            )
        )
    ).all()

    records_by_date: dict[datetime.date, list[Any]] = defaultdict(list)
    for row in record_rows:
        records_by_date[row.record_date].append(row)

    skipped_by_date: dict[datetime.date, set[int]] = defaultdict(set)
    for row in skipped_rows:
        if row.exception_date is not None and row.regular_lesson_id is not None:
            skipped_by_date[row.exception_date].add(int(row.regular_lesson_id))

    regulars_by_weekday: dict[int, list[Any]] = defaultdict(list)
    for row in regular_rows:
        regulars_by_weekday[int(row.day_of_week or 0)].append(row)

    state: dict[datetime.date, dict[str, Any]] = {}
    for target_date in all_dates:
        rows = records_by_date.get(target_date, [])
        blocked_times: set[tuple[int, int]] = set()
        allow_times: set[tuple[int, int]] = set()
        busy_intervals: list[tuple[datetime.datetime, datetime.datetime]] = []
        seen_intervals: set[tuple[datetime.datetime, datetime.datetime]] = set()

        for row in rows:
            hour = int(row.hour or 0)
            minute = int(row.minute or 0)
            duration = int(row.duration_minutes or SLOT_DURATION_MINUTES)
            kind = (row.kind or "").lower()
            status = (row.booking_status or "").lower()

            if row.telegram_id is None and (
                kind in {"block", "allow"} or (row.kind is None and row.event_id is None)
            ):
                blocked_times.add((hour, minute))
            if kind == "allow":
                allow_times.add((hour, minute))
            if kind != "allow" and status != "rejected":
                start_dt = datetime.datetime.combine(target_date, datetime.time(hour, minute))
                end_dt = start_dt + datetime.timedelta(minutes=max(1, duration))
                interval = (start_dt, end_dt)
                if interval not in seen_intervals:
                    seen_intervals.add(interval)
                    busy_intervals.append(interval)

        for reg in regulars_by_weekday.get(target_date.weekday(), []):
            reg_id = int(reg.id)
            hour = int(reg.hour or 0)
            minute = int(reg.minute or 0)
            duration = int(reg.duration_minutes or SLOT_DURATION_MINUTES)
            if reg_id in skipped_by_date.get(target_date, set()):
                continue
            if (hour, minute) in blocked_times or (hour, minute) in allow_times:
                continue
            start_dt = datetime.datetime.combine(target_date, datetime.time(hour, minute))
            end_dt = start_dt + datetime.timedelta(minutes=max(1, duration))
            interval = (start_dt, end_dt)
            if interval not in seen_intervals:
                seen_intervals.add(interval)
                busy_intervals.append(interval)

        busy_intervals.sort(key=lambda item: item[0])
        state[target_date] = {
            "busy_intervals": busy_intervals,
            "blocked_times": blocked_times,
            "allow_times": allow_times,
        }
    return state


async def occupancy_snapshot(
    start_date: datetime.date,
    end_date: datetime.date,
) -> dict[str, Any]:
    state = await _schedule_state_for_range(start_date, end_date)
    weekday_buckets = {
        idx: {"weekday": idx, "available": 0, "occupied": 0}
        for idx in range(7)
    }
    hour_buckets: dict[int, dict[str, Any]] = {}
    heatmap: list[dict[str, Any]] = []

    for target_date, date_state in state.items():
        day_slots = slots_for_date(target_date, None)
        busy_intervals = date_state["busy_intervals"]
        for hour, minute in day_slots:
            weekday_idx = target_date.weekday()
            hour_bucket = hour_buckets.setdefault(hour, {"hour": hour, "available": 0, "occupied": 0})
            weekday_buckets[weekday_idx]["available"] += 1
            hour_bucket["available"] += 1
            start_dt = datetime.datetime.combine(target_date, datetime.time(hour, minute))
            end_dt = start_dt + datetime.timedelta(minutes=SLOT_DURATION_MINUTES)
            occupied = any(_overlaps(start_dt, end_dt, busy_start, busy_end) for busy_start, busy_end in busy_intervals)
            if occupied:
                weekday_buckets[weekday_idx]["occupied"] += 1
                hour_bucket["occupied"] += 1

    weekday_items = []
    for idx in range(7):
        item = weekday_buckets[idx]
        occupancy_pct = _safe_ratio(item["occupied"], item["available"])
        weekday_items.append({**item, "occupancy_pct": occupancy_pct})

    hour_items = []
    for hour in sorted(hour_buckets):
        item = hour_buckets[hour]
        occupancy_pct = _safe_ratio(item["occupied"], item["available"])
        hour_items.append({**item, "occupancy_pct": occupancy_pct})

    for weekday_item in weekday_items:
        for hour_item in hour_items:
            available = 0
            occupied = 0
            for target_date, date_state in state.items():
                if target_date.weekday() != weekday_item["weekday"]:
                    continue
                for slot_hour, slot_minute in slots_for_date(target_date, None):
                    if slot_hour != hour_item["hour"]:
                        continue
                    available += 1
                    start_dt = datetime.datetime.combine(target_date, datetime.time(slot_hour, slot_minute))
                    end_dt = start_dt + datetime.timedelta(minutes=SLOT_DURATION_MINUTES)
                    if any(_overlaps(start_dt, end_dt, busy_start, busy_end) for busy_start, busy_end in date_state["busy_intervals"]):
                        occupied += 1
            occupancy_pct = _safe_ratio(occupied, available)
            if occupancy_pct < 35:
                level = "underloaded"
            elif occupancy_pct > 75:
                level = "overloaded"
            else:
                level = "normal"
            heatmap.append(
                {
                    "weekday": weekday_item["weekday"],
                    "hour": hour_item["hour"],
                    "available": available,
                    "occupied": occupied,
                    "occupancy_pct": occupancy_pct,
                    "level": level,
                }
            )

    return {
        "weekday": weekday_items,
        "hour": hour_items,
        "heatmap": heatmap,
    }


async def analytics_event_breakdown(
    start_date: datetime.date,
    end_date: datetime.date,
) -> dict[str, Any]:
    res = await session.execute(
        select(AnalyticsEvent.event_type, func.count(AnalyticsEvent.id))
        .where(
            AnalyticsEvent.record_date >= start_date,
            AnalyticsEvent.record_date <= end_date,
        )
        .group_by(AnalyticsEvent.event_type)
    )
    counts = {str(event_type): int(count or 0) for event_type, count in res.all()}
    booked_base = max(1, int(counts.get("booked", 0)) + int(counts.get("approved", 0)))
    canceled_client = int(counts.get("canceled_by_client", 0))
    canceled_admin = int(counts.get("canceled_by_admin", 0))
    rescheduled = int(counts.get("rescheduled_from", 0))
    no_show = int(counts.get("presence_no", 0))
    return {
        "counts": {
            "canceled_by_client": canceled_client,
            "canceled_by_admin": canceled_admin,
            "rescheduled": rescheduled,
            "no_show": no_show,
            "presence_yes": int(counts.get("presence_yes", 0)),
            "presence_no": no_show,
        },
        "rates": {
            "cancel_client_pct": _safe_ratio(canceled_client, booked_base),
            "cancel_admin_pct": _safe_ratio(canceled_admin, booked_base),
            "reschedule_pct": _safe_ratio(rescheduled, booked_base),
            "no_show_pct": _safe_ratio(no_show, booked_base),
        },
        "coverage_note": "Полная cancel/no-show аналитика собирается с момента внедрения analytics_events без исторического backfill.",
    }


async def repeat_booking_summary() -> dict[str, Any]:
    res = await session.execute(
        select(Payment.telegram_id, func.count(Payment.id))
        .where(
            Payment.status != "canceled",
            Payment.telegram_id.is_not(None),
        )
        .group_by(Payment.telegram_id)
    )
    total_clients = 0
    returned_clients = 0
    for tg_id, lessons_count in res.all():
        if tg_id is None:
            continue
        total_clients += 1
        if int(lessons_count or 0) >= 2:
            returned_clients += 1
    return {
        "clients_total": total_clients,
        "returned_clients": returned_clients,
        "second_lesson_conversion_pct": _safe_ratio(returned_clients, total_clients),
    }


async def regular_vs_single_summary(
    start_date: datetime.date,
    end_date: datetime.date,
) -> dict[str, Any]:
    payments_res = await session.execute(
        select(
            Payment.telegram_id,
            Payment.lesson_date,
            Payment.hour,
            Payment.minute,
            Payment.amount,
            Payment.status,
        ).where(
            Payment.lesson_date >= start_date,
            Payment.lesson_date <= end_date,
            Payment.status != "canceled",
        )
    )
    payment_rows = payments_res.all()
    if not payment_rows:
        return {
            "single": {"revenue": 0, "lessons": 0, "paid_lessons": 0, "debt_ratio_pct": 0},
            "regular": {"revenue": 0, "lessons": 0, "paid_lessons": 0, "debt_ratio_pct": 0},
        }

    dates = sorted({row.lesson_date for row in payment_rows if row.lesson_date is not None})
    weekdays = sorted({item.weekday() for item in dates})
    records = (
        await session.execute(
            select(
                RecordDate.record_date,
                RecordDate.telegram_id,
                RecordDate.hour,
                RecordDate.minute,
                RecordDate.kind,
            ).where(
                RecordDate.record_date >= start_date,
                RecordDate.record_date <= end_date,
            )
        )
    ).all()
    record_kinds = {
        (row.record_date, int(row.telegram_id), int(row.hour or 0), int(row.minute or 0)): (row.kind or "single")
        for row in records
        if row.telegram_id is not None
    }
    regulars = (
        await session.execute(
            select(
                RegularLesson.telegram_id,
                RegularLesson.day_of_week,
                RegularLesson.hour,
                RegularLesson.minute,
            ).where(
                RegularLesson.day_of_week.in_(weekdays),
                RegularLesson.telegram_id.is_not(None),
            )
        )
    ).all()
    regular_keys = {
        (int(row.telegram_id), int(row.day_of_week or 0), int(row.hour or 0), int(row.minute or 0))
        for row in regulars
        if row.telegram_id is not None
    }

    summary = {
        "single": {"revenue": 0, "lessons": 0, "paid_lessons": 0},
        "regular": {"revenue": 0, "lessons": 0, "paid_lessons": 0},
    }
    for row in payment_rows:
        tg_id = int(row.telegram_id) if row.telegram_id is not None else None
        hour = int(row.hour or 0)
        minute = int(row.minute or 0)
        if tg_id is not None and record_kinds.get((row.lesson_date, tg_id, hour, minute)) == "regular":
            kind = "regular"
        elif tg_id is not None and (tg_id, row.lesson_date.weekday(), hour, minute) in regular_keys:
            kind = "regular"
        else:
            kind = "single"
        summary[kind]["lessons"] += 1
        if str(row.status) == "paid":
            summary[kind]["paid_lessons"] += 1
            summary[kind]["revenue"] += int(row.amount or 0)

    for item in summary.values():
        lessons = int(item["lessons"] or 0)
        paid_lessons = int(item["paid_lessons"] or 0)
        item["debt_ratio_pct"] = _safe_ratio(max(0, lessons - paid_lessons), lessons)
        item["revenue_share_pct"] = 0.0
        item["lessons_share_pct"] = 0.0

    total_revenue = sum(int(item["revenue"] or 0) for item in summary.values())
    total_lessons = sum(int(item["lessons"] or 0) for item in summary.values())
    for item in summary.values():
        item["revenue_share_pct"] = _safe_ratio(int(item["revenue"] or 0), total_revenue)
        item["lessons_share_pct"] = _safe_ratio(int(item["lessons"] or 0), total_lessons)
    return summary


async def analytics_event_log_coverage() -> dict[str, Any]:
    res = await session.execute(
        select(func.min(AnalyticsEvent.created_at), func.count(AnalyticsEvent.id))
    )
    first_created_at, total = res.one()
    return {
        "tracked_from": first_created_at,
        "events_total": int(total or 0),
    }


async def last_lessons_for_clients(client_ids: list[int]) -> dict[int, dict[str, Any]]:
    """
    Последнее проведенное занятие (по payments, без canceled) для списка клиентов.
    """
    if not client_ids:
        return {}
    res = await session.execute(
        select(
            Payment.telegram_id,
            Payment.lesson_date,
            Payment.hour,
            Payment.minute,
        )
        .where(
            Payment.telegram_id.in_(client_ids),
            Payment.status != "canceled",
        )
        .order_by(Payment.telegram_id.asc(), Payment.lesson_date.desc(), Payment.hour.desc(), Payment.minute.desc(), Payment.id.desc())
    )
    out: dict[int, dict[str, Any]] = {}
    for row in res.all():
        tg = int(row[0]) if row[0] is not None else None
        if tg is None or tg in out:
            continue
        lesson_date = row[1]
        out[tg] = {
            "date": lesson_date.isoformat() if lesson_date and hasattr(lesson_date, "isoformat") else (str(lesson_date) if lesson_date else None),
            "time": f"{int(row[2] or 0):02d}:{int(row[3] or 0):02d}",
        }
    return out


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
    for attempt in range(3):
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
        try:
            lesson_kind = await get_lesson_kind(lesson_date, hour, minute, telegram_id) if telegram_id is not None else None
            close_event = {
                "paid": "lesson_closed_paid",
                "unpaid": "lesson_closed_unpaid",
                "canceled": "lesson_closed_canceled",
            }.get(status)
            if close_event:
                await log_analytics_event(
                    close_event,
                    telegram_id=telegram_id,
                    record_date=lesson_date,
                    hour=hour,
                    minute=minute,
                    duration_minutes=duration_minutes,
                    lesson_kind=lesson_kind,
                    source_context="admin" if (source or "").startswith("lesson_close") or source == "balance" else "bot",
                    meta={"amount": amount, "source": source or ""},
                    commit=False,
                )
            await session.commit()
            return pay
        except IntegrityError as exc:
            await session.rollback()
            if "payments.id" in str(exc).lower() and attempt < 2:
                logger.warning(
                    "retrying payment insert after payments.id conflict: tg=%s date=%s time=%02d:%02d attempt=%s",
                    telegram_id,
                    lesson_date,
                    hour,
                    minute,
                    attempt + 1,
                )
                continue
            raise

    raise RuntimeError("unreachable")


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
    if status is not None:
        lesson_kind = await get_lesson_kind(pay.lesson_date, pay.hour, pay.minute, pay.telegram_id) if pay.telegram_id is not None else None
        close_event = {
            "paid": "lesson_closed_paid",
            "unpaid": "lesson_closed_unpaid",
            "canceled": "lesson_closed_canceled",
        }.get(status)
        if close_event:
            await log_analytics_event(
                close_event,
                telegram_id=pay.telegram_id,
                record_date=pay.lesson_date,
                hour=pay.hour,
                minute=pay.minute,
                duration_minutes=pay.duration_minutes or SLOT_DURATION_MINUTES,
                lesson_kind=lesson_kind,
                source_context="admin",
                meta={"payment_id": pay.id, "amount": pay.amount, "source": pay.source or ""},
                commit=False,
            )
    await session.commit()


async def list_unpaid_payments() -> list[Any]:
    res = await session.execute(
        select(Payment).where(Payment.status == "unpaid").order_by(Payment.lesson_date, Payment.hour, Payment.minute)
    )
    return res.all()


async def mark_payment_paid(payment_id: int) -> bool:
    pay = await session.get(Payment, payment_id)
    if pay:
        pay.status = "paid"
        lesson_kind = await get_lesson_kind(pay.lesson_date, pay.hour, pay.minute, pay.telegram_id) if pay.telegram_id is not None else None
        await log_analytics_event(
            "lesson_closed_paid",
            telegram_id=pay.telegram_id,
            record_date=pay.lesson_date,
            hour=pay.hour,
            minute=pay.minute,
            duration_minutes=pay.duration_minutes or SLOT_DURATION_MINUTES,
            lesson_kind=lesson_kind,
            source_context="admin",
            meta={"payment_id": pay.id, "amount": pay.amount, "source": pay.source or ""},
            commit=False,
        )
        await session.commit()
        return True
    return False


async def mark_payment_status(payment_id: int, status: str) -> None:
    pay = await session.get(Payment, payment_id)
    if pay:
        pay.status = status
        lesson_kind = await get_lesson_kind(pay.lesson_date, pay.hour, pay.minute, pay.telegram_id) if pay.telegram_id is not None else None
        close_event = {
            "paid": "lesson_closed_paid",
            "unpaid": "lesson_closed_unpaid",
            "canceled": "lesson_closed_canceled",
        }.get(status)
        if close_event:
            await log_analytics_event(
                close_event,
                telegram_id=pay.telegram_id,
                record_date=pay.lesson_date,
                hour=pay.hour,
                minute=pay.minute,
                duration_minutes=pay.duration_minutes or SLOT_DURATION_MINUTES,
                lesson_kind=lesson_kind,
                source_context="admin",
                meta={"payment_id": pay.id, "amount": pay.amount, "source": pay.source or ""},
                commit=False,
            )
        await session.commit()

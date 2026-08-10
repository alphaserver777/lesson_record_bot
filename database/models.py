"""Модели БД."""
from sqlalchemy import Column, ForeignKey
from sqlalchemy.types import BigInteger, Boolean, Date, Integer, String

from database.connect import Base


class RecordDate(Base):
    __tablename__ = "record_dates"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    telegram_id = Column(BigInteger, ForeignKey("student_profiles.telegram_id", ondelete="CASCADE"), nullable=True)
    record_date = Column(Date, nullable=False)
    hour = Column(Integer, nullable=False)
    minute = Column(Integer, nullable=False, default=0)
    duration_minutes = Column(Integer, nullable=False, default=60)
    kind = Column(String(20), nullable=True, default="single")  # single/regular/block
    presence_status = Column(String(20), nullable=True)  # yes/no/pending
    presence_last_reminder = Column(String(50), nullable=True)
    presence_message_id = Column(Integer, nullable=True)
    note = Column(String(255), nullable=True)
    event_id = Column(String(255), nullable=True)
    booking_status = Column(String(20), nullable=False, default="approved")  # pending/approved/rejected
    approval_admin_id = Column(Integer, nullable=True)
    approval_updated_at = Column(String(50), nullable=True)


class RegularLesson(Base):
    __tablename__ = "regular_lessons"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    telegram_id = Column(BigInteger, ForeignKey("student_profiles.telegram_id", ondelete="SET NULL"), nullable=True)
    full_name = Column(String(100), nullable=False)
    username = Column(String(100), nullable=True)
    cost = Column(Integer, nullable=True)
    day_of_week = Column(Integer, nullable=True)
    lesson_date = Column(Date, nullable=True)
    hour = Column(Integer, nullable=True)
    minute = Column(Integer, nullable=True)
    duration_minutes = Column(Integer, nullable=False, default=60)


class RegularLessonException(Base):
    __tablename__ = "regular_lesson_exceptions"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    regular_lesson_id = Column(Integer, ForeignKey("regular_lessons.id", ondelete="CASCADE"), nullable=False)
    exception_date = Column(Date, nullable=False)
    action = Column(String(20), nullable=False, default="skip")
    note = Column(String(255), nullable=True)
    created_at = Column(String(50), nullable=True)


class DateAvailabilityOverride(Base):
    __tablename__ = "date_availability_overrides"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    target_date = Column(Date, nullable=False)
    start_minute = Column(Integer, nullable=False)
    end_minute = Column(Integer, nullable=False)
    mode = Column(String(20), nullable=False, default="extra_open")
    note = Column(String(255), nullable=True)
    created_at = Column(String(50), nullable=True)


class StudentProfile(Base):
    __tablename__ = "student_profiles"
    __table_args__ = {"extend_existing": True}

    telegram_id = Column(BigInteger, primary_key=True)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, unique=True, index=True)
    full_name = Column(String(100), nullable=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    telegram_username = Column(String(100), nullable=True)
    age = Column(Integer, nullable=True)
    price = Column(Integer, nullable=True)
    direction = Column(String(100), nullable=True)
    goal = Column(String(255), nullable=True)
    notes = Column(String(255), nullable=True)
    telephone = Column(String(20), nullable=True)
    miniapp_entry_chat_id = Column(BigInteger, nullable=True)
    miniapp_entry_message_id = Column(Integer, nullable=True)
    blocked = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    last_visit_date = Column(String(50), nullable=True)
    balance_lessons = Column(Integer, nullable=False, default=0)


class Account(Base):
    """Web credentials kept separately from the Telegram profile data."""

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)
    phone = Column(String(16), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    student_telegram_id = Column(
        BigInteger,
        ForeignKey("student_profiles.telegram_id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    role = Column(String(20), nullable=False, default="user")
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)


class Lead(Base):
    """Commercial funnel record linked to a Telegram profile when available."""

    __tablename__ = "leads"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, ForeignKey("student_profiles.telegram_id", ondelete="SET NULL"), nullable=True, index=True)
    full_name = Column(String(100), nullable=True)
    telephone = Column(String(20), nullable=True)
    source = Column(String(80), nullable=False, default="direct", index=True)
    utm_medium = Column(String(80), nullable=True)
    utm_campaign = Column(String(120), nullable=True)
    utm_content = Column(String(120), nullable=True)
    direction = Column(String(80), nullable=True)
    goal = Column(String(500), nullable=True)
    stage = Column(String(32), nullable=False, default="new", index=True)
    diagnostic_at = Column(String(50), nullable=True)
    offer_amount = Column(Integer, nullable=True)
    paid_amount = Column(Integer, nullable=True)
    lost_reason = Column(String(255), nullable=True)
    next_contact_at = Column(String(50), nullable=True)
    notes = Column(String(1000), nullable=True)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)


class Contact(Base):
    """Canonical person record independent from authentication and lifecycle."""

    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    telephone = Column(String(20), nullable=True, index=True)
    preferred_channel = Column(String(20), nullable=False, default="telegram")
    status = Column(String(24), nullable=False, default="active", index=True)
    is_archived = Column(Boolean, nullable=False, default=False, index=True)
    acquisition_source = Column(String(80), nullable=False, default="unknown", index=True)
    acquisition_campaign = Column(String(120), nullable=True, index=True)
    acquired_at = Column(Date, nullable=True, index=True)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)


class TelegramIdentity(Base):
    """Telegram authentication and delivery identity for a contact."""

    __tablename__ = "telegram_identities"

    id = Column(Integer, primary_key=True)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    telegram_id = Column(BigInteger, nullable=False, unique=True, index=True)
    username = Column(String(100), nullable=True)
    last_login_at = Column(String(50), nullable=True)
    entry_chat_id = Column(BigInteger, nullable=True)
    entry_message_id = Column(Integer, nullable=True)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)


class Opportunity(Base):
    """Commercial request linked to one canonical contact."""

    __tablename__ = "opportunities"

    id = Column(Integer, primary_key=True)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    legacy_lead_id = Column(Integer, nullable=True, unique=True, index=True)
    source = Column(String(80), nullable=False, default="direct", index=True)
    utm_medium = Column(String(80), nullable=True)
    utm_campaign = Column(String(120), nullable=True)
    utm_content = Column(String(120), nullable=True)
    direction = Column(String(80), nullable=True)
    goal = Column(String(500), nullable=True)
    stage = Column(String(32), nullable=False, default="new", index=True)
    diagnostic_at = Column(String(50), nullable=True)
    diagnostic_scheduled_at = Column(String(50), nullable=True)
    diagnostic_held_at = Column(String(50), nullable=True)
    offer_amount = Column(Integer, nullable=True)
    paid_amount = Column(Integer, nullable=True)
    lost_reason = Column(String(255), nullable=True)
    next_contact_at = Column(String(50), nullable=True, index=True)
    notes = Column(String(1000), nullable=True)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)


class FunnelStage(Base):
    """Administrator-configurable columns of the commercial kanban."""

    __tablename__ = "funnel_stages"

    key = Column(String(48), primary_key=True)
    name = Column(String(100), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0, index=True)
    metric_role = Column(String(32), nullable=False, default="new", index=True)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)


class OpportunityStageEvent(Base):
    __tablename__ = "opportunity_stage_events"

    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True)
    from_stage = Column(String(48), nullable=True)
    to_stage = Column(String(48), nullable=False, index=True)
    occurred_at = Column(String(50), nullable=False, index=True)
    actor_id = Column(BigInteger, nullable=True)
    source = Column(String(32), nullable=False, default="admin")


class MarketingSource(Base):
    __tablename__ = "marketing_sources"

    key = Column(String(80), primary_key=True)
    name = Column(String(100), nullable=False)
    channel = Column(String(40), nullable=False, default="other")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)


class MarketingCampaign(Base):
    __tablename__ = "marketing_campaigns"

    id = Column(Integer, primary_key=True)
    source_key = Column(String(80), ForeignKey("marketing_sources.key", ondelete="RESTRICT"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)


class MarketingExpense(Base):
    __tablename__ = "marketing_expenses"

    id = Column(Integer, primary_key=True)
    spent_at = Column(Date, nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    source_key = Column(String(80), ForeignKey("marketing_sources.key", ondelete="RESTRICT"), nullable=False, index=True)
    campaign_id = Column(Integer, ForeignKey("marketing_campaigns.id", ondelete="SET NULL"), nullable=True, index=True)
    category = Column(String(32), nullable=False)
    note = Column(String(500), nullable=True)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    telegram_id = Column(BigInteger, ForeignKey("student_profiles.telegram_id", ondelete="SET NULL"), nullable=True)
    full_name = Column(String(100), nullable=True)
    lesson_date = Column(Date, nullable=False)
    hour = Column(Integer, nullable=False)
    minute = Column(Integer, nullable=False, default=0)
    duration_minutes = Column(Integer, nullable=False, default=60)
    amount = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="paid")  # paid/unpaid
    created_at = Column(String(50), nullable=True)
    source = Column(String(50), nullable=True)  # balance/manual


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type = Column(String(40), nullable=False)
    telegram_id = Column(BigInteger, ForeignKey("student_profiles.telegram_id", ondelete="SET NULL"), nullable=True)
    record_date = Column(Date, nullable=True)
    hour = Column(Integer, nullable=True)
    minute = Column(Integer, nullable=True, default=0)
    duration_minutes = Column(Integer, nullable=True, default=60)
    lesson_kind = Column(String(20), nullable=True)  # single/regular
    source_context = Column(String(20), nullable=True)  # miniapp/bot/admin
    related_slot_date = Column(Date, nullable=True)
    related_slot_hour = Column(Integer, nullable=True)
    related_slot_minute = Column(Integer, nullable=True, default=0)
    meta_json = Column(String(2000), nullable=True)
    created_at = Column(String(50), nullable=True)


class WorkingInterval(Base):
    __tablename__ = "working_intervals"

    id = Column(Integer, primary_key=True)
    weekday = Column(Integer, nullable=False)
    start_minute = Column(Integer, nullable=False)
    end_minute = Column(Integer, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(String(50), nullable=True)
    updated_at = Column(String(50), nullable=True)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"

    id = Column(Integer, primary_key=True)
    admin_id = Column(BigInteger, nullable=False)
    action = Column(String(100), nullable=False)
    entity = Column(String(100), nullable=False)
    payload_json = Column(String, nullable=True)
    created_at = Column(String(50), nullable=False)

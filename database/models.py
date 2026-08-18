"""Модели БД."""
from sqlalchemy import Column, ForeignKey, UniqueConstraint
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
    campaign_id = Column(Integer, ForeignKey("marketing_campaigns.id", ondelete="SET NULL"), nullable=True, index=True)
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
    # Immutable attribution link.  The legacy name remains only for historical
    # compatibility and is kept in sync with the selected campaign.
    acquisition_campaign_id = Column(Integer, ForeignKey("marketing_campaigns.id", ondelete="SET NULL"), nullable=True, index=True)
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
    student_level = Column(String(32), nullable=True)
    qualification_status = Column(String(24), nullable=False, default="new", index=True)
    desired_format = Column(String(80), nullable=True)
    desired_budget = Column(Integer, nullable=True)
    first_response_at = Column(String(50), nullable=True)
    stage = Column(String(32), nullable=False, default="new", index=True)
    diagnostic_at = Column(String(50), nullable=True)
    diagnostic_scheduled_at = Column(String(50), nullable=True)
    diagnostic_held_at = Column(String(50), nullable=True)
    offer_amount = Column(Integer, nullable=True)
    paid_amount = Column(Integer, nullable=True)
    lost_reason = Column(String(255), nullable=True)
    next_contact_at = Column(String(50), nullable=True, index=True)
    notes = Column(String(1000), nullable=True)
    landing_page = Column(String(500), nullable=True)
    referrer = Column(String(500), nullable=True)
    visitor_id = Column(String(64), nullable=True, index=True)
    metrica_client_id = Column(String(64), nullable=True, index=True)
    telegram_username_hint = Column(String(100), nullable=True)
    brief_json = Column(String(4000), nullable=True)
    consent_at = Column(String(50), nullable=True)
    public_token = Column(String(64), nullable=True, unique=True, index=True)
    idempotency_key = Column(String(80), nullable=True, unique=True, index=True)
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


class TestDriveEnrollment(Base):
    """Paid low-ticket product connecting cold traffic to mentorship."""

    __tablename__ = "test_drive_enrollments"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_test_drive_enrollment_idempotency"),
    )

    id = Column(Integer, primary_key=True)
    public_token = Column(String(64), nullable=False, unique=True, index=True)
    idempotency_key = Column(String(80), nullable=False, unique=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True)
    persona = Column(String(32), nullable=False, index=True)
    price_amount = Column(Integer, nullable=False, default=1000)
    status = Column(String(32), nullable=False, default="awaiting_payment", index=True)
    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="SET NULL"), nullable=True, index=True)
    quest_url = Column(String(500), nullable=True)
    quest_opened_at = Column(String(50), nullable=True)
    submission_url = Column(String(500), nullable=True)
    submission_note = Column(String(1000), nullable=True)
    submitted_at = Column(String(50), nullable=True)
    reviewed_at = Column(String(50), nullable=True)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)


class ReviewBookingRequest(Base):
    """Thirty-minute review unlocked after the test-drive quest is submitted."""

    __tablename__ = "review_booking_requests"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_review_booking_idempotency"),
    )

    id = Column(Integer, primary_key=True)
    public_token = Column(String(64), nullable=False, unique=True, index=True)
    idempotency_key = Column(String(80), nullable=False, unique=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True)
    enrollment_id = Column(Integer, ForeignKey("test_drive_enrollments.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_date = Column(Date, nullable=False, index=True)
    requested_hour = Column(Integer, nullable=False)
    requested_minute = Column(Integer, nullable=False)
    duration_minutes = Column(Integer, nullable=False, default=30)
    hold_key = Column(String(80), nullable=True, unique=True, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    expires_at = Column(String(50), nullable=False, index=True)
    admin_id = Column(BigInteger, nullable=True)
    decided_at = Column(String(50), nullable=True)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)


class WebAnalyticsEvent(Base):
    """First-party website events that can later be joined to a canonical contact."""

    __tablename__ = "web_analytics_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_web_analytics_event_id"),
    )

    id = Column(Integer, primary_key=True)
    event_id = Column(String(80), nullable=False, unique=True, index=True)
    event_type = Column(String(40), nullable=False, index=True)
    visitor_id = Column(String(64), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True, index=True)
    path = Column(String(500), nullable=True)
    utm_source = Column(String(80), nullable=True)
    utm_medium = Column(String(80), nullable=True)
    utm_campaign = Column(String(120), nullable=True)
    utm_content = Column(String(120), nullable=True)
    campaign_id = Column(Integer, ForeignKey("marketing_campaigns.id", ondelete="SET NULL"), nullable=True, index=True)
    tracking_link_id = Column(Integer, ForeignKey("marketing_tracking_links.id", ondelete="SET NULL"), nullable=True, index=True)
    metrica_client_id = Column(String(64), nullable=True)
    meta_json = Column(String(2000), nullable=True)
    created_at = Column(String(50), nullable=False, index=True)


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
    active_from = Column(Date, nullable=True, index=True)
    active_to = Column(Date, nullable=True, index=True)
    target_action_label = Column(String(100), nullable=False, default="Целевое действие")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)


class MarketingTrackingLink(Base):
    """Opaque public link for one concrete traffic placement."""

    __tablename__ = "marketing_tracking_links"

    id = Column(Integer, primary_key=True)
    public_token = Column(String(32), nullable=False, unique=True, index=True)
    campaign_id = Column(Integer, ForeignKey("marketing_campaigns.id", ondelete="RESTRICT"), nullable=False, index=True)
    destination_key = Column(String(32), nullable=False, default="it_map")
    destination_path = Column(String(500), nullable=False)
    label = Column(String(160), nullable=False)
    note = Column(String(1000), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    expires_at = Column(String(50), nullable=True, index=True)
    created_by = Column(BigInteger, nullable=True)
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


class MarketingCampaignMetric(Base):
    __tablename__ = "marketing_campaign_metrics"

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("marketing_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_key = Column(String(48), nullable=False)
    metric_value = Column(Integer, nullable=False, default=0)
    updated_at = Column(String(50), nullable=False)


class ManualWorkLog(Base):
    """Non-lesson work included in the effective hourly-rate calculation."""

    __tablename__ = "manual_work_logs"

    id = Column(Integer, primary_key=True)
    worked_on = Column(Date, nullable=False, index=True)
    category = Column(String(24), nullable=False, index=True)  # prep/sales/content/admin
    minutes = Column(Integer, nullable=False)
    note = Column(String(500), nullable=True)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    # Canonical link to the lesson occurrence.  Date/time fields below remain
    # immutable audit snapshots and a compatibility fallback for legacy rows.
    lesson_id = Column(
        Integer,
        ForeignKey("record_dates.id", ondelete="SET NULL"),
        nullable=True,
    )
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

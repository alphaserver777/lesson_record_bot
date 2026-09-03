"""Pydantic schemas for web API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from pydantic import BaseModel, Field


class AuthIn(BaseModel):
    initData: str


class TelegramWidgetAuthIn(BaseModel):
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


class BookIn(BaseModel):
    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    duration: int = 60
    mode: str = "preset"


class CancelIn(BaseModel):
    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")


class SingleLessonIn(BaseModel):
    telegram_id: int
    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    duration: int = 60


class LessonRescheduleIn(BaseModel):
    telegram_id: int
    source_date: date
    source_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    target_date: date
    target_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    duration: int = Field(default=60, ge=15, le=360)


class ManualCompletedLessonIn(BaseModel):
    """A lesson that was held but was never placed into the timetable."""
    telegram_id: int
    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    duration: int = Field(default=60, ge=15, le=360)
    note: str | None = Field(default=None, max_length=255)


class RegularLessonIn(BaseModel):
    telegram_id: int
    day_of_week: int = Field(ge=0, le=6)
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    duration: int = 60


class ManualPaymentIn(BaseModel):
    telegram_id: int
    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    amount: int = Field(ge=0)
    duration: int = 60


class LessonCloseIn(BaseModel):
    lesson_id: int | None = Field(default=None, ge=1)
    telegram_id: int
    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    decision: str = Field(pattern=r"^(paid|unpaid|canceled)$")
    amount: int | None = Field(default=None, ge=0)
    duration: int = 60
    source: str = Field(default="manual", pattern=r"^(manual|balance)$")


class LessonCloseBulkItemIn(BaseModel):
    lesson_id: int | None = Field(default=None, ge=1)
    telegram_id: int
    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    duration: int = 60
    amount: int | None = Field(default=None, ge=0)


class LessonCloseBulkIn(BaseModel):
    items: list[LessonCloseBulkItemIn]
    decision: str = Field(pattern=r"^(paid|unpaid|canceled)$")


class BroadcastIn(BaseModel):
    message: str
    only_unpaid: bool = False


class AdminUserPatchIn(BaseModel):
    telegram_id_new: int | None = None
    merge_if_exists: bool = False
    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    telephone: str | None = None
    price: int | None = None
    balance_lessons_set: int | None = None
    balance_lessons_add: int | None = None
    blocked: bool | None = None


class UserProfileIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    telephone: str = Field(min_length=5, max_length=20)


class LeadCreateIn(BaseModel):
    telegram_id: int | None = None
    full_name: str | None = Field(default=None, max_length=100)
    telephone: str | None = Field(default=None, max_length=20)
    telegram_username: str | None = Field(default=None, max_length=100)
    price: int | None = Field(default=None, ge=0, le=1_000_000)
    source: str = Field(default="direct", min_length=1, max_length=80)
    acquisition_campaign_id: int | None = Field(default=None, ge=1)
    utm_medium: str | None = Field(default=None, max_length=80)
    utm_campaign: str | None = Field(default=None, max_length=120)
    utm_content: str | None = Field(default=None, max_length=120)
    direction: str | None = Field(default=None, max_length=80)
    goal: str | None = Field(default=None, max_length=500)
    student_level: str | None = Field(default=None, max_length=32)
    qualification_status: str = Field(default="new", pattern=r"^(new|qualified|not_qualified)$")
    desired_format: str | None = Field(default=None, max_length=80)
    desired_budget: int | None = Field(default=None, ge=0)
    first_response_at: str | None = Field(default=None, max_length=50)
    stage: str = Field(default="new", min_length=1, max_length=48)
    diagnostic_at: str | None = Field(default=None, max_length=50)
    offer_amount: int | None = Field(default=None, ge=0)
    paid_amount: int | None = Field(default=None, ge=0)
    lost_reason: str | None = Field(default=None, max_length=255)
    next_contact_at: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=1000)


class LeadPatchIn(LeadCreateIn):
    source: str | None = Field(default=None, min_length=1, max_length=80)
    stage: str | None = Field(default=None, min_length=1, max_length=48)


class FunnelStageCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class FunnelStagePatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    sort_order: int | None = Field(default=None, ge=0, le=1000)
    metric_role: str | None = Field(default=None, pattern=r"^(new|qualified|diagnostic_scheduled|diagnostic_held|offer|won|lost)$")


class MarketingCampaignIn(BaseModel):
    source_key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    active_from: date | None = None
    active_to: date | None = None
    target_action_label: str = Field(default="Целевое действие", min_length=1, max_length=100)


class MarketingCampaignPatchIn(BaseModel):
    source_key: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    active_from: date | None = None
    active_to: date | None = None
    target_action_label: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None


class MarketingCampaignMetricsIn(BaseModel):
    views: int = Field(default=0, ge=0)
    dialogs: int = Field(default=0, ge=0)
    target_actions: int = Field(default=0, ge=0)


class MarketingTrackingLinkIn(BaseModel):
    campaign_id: int = Field(ge=1)
    destination_key: str = Field(default="it_map", pattern=r"^(it_map|home)$")
    label: str = Field(min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=1000)
    expires_at: datetime | None = None


class MarketingTrackingLinkPatchIn(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None
    expires_at: datetime | None = None


class MarketingExpenseIn(BaseModel):
    spent_at: date
    amount: int = Field(gt=0)
    source_key: str = Field(min_length=1, max_length=80)
    campaign_id: int | None = None
    category: str = Field(pattern=r"^(placement|advertising|content|contractor)$")
    note: str | None = Field(default=None, max_length=500)


class ManualWorkLogIn(BaseModel):
    worked_on: date
    category: str = Field(pattern=r"^(prep|sales|content|admin)$")
    minutes: int = Field(ge=1, le=1440)
    note: str | None = Field(default=None, max_length=500)


class OpportunityMarketingPatchIn(BaseModel):
    source: str | None = Field(default=None, min_length=1, max_length=80)
    campaign: str | None = Field(default=None, max_length=120)
    diagnostic_scheduled_at: str | None = Field(default=None, max_length=50)
    diagnostic_held_at: str | None = Field(default=None, max_length=50)
    qualification_status: str | None = Field(default=None, pattern=r"^(new|qualified|not_qualified)$")
    desired_format: str | None = Field(default=None, max_length=80)
    desired_budget: int | None = Field(default=None, ge=0)
    goal: str | None = Field(default=None, max_length=500)
    direction: str | None = Field(default=None, max_length=80)
    student_level: str | None = Field(default=None, max_length=32)
    first_response_at: str | None = Field(default=None, max_length=50)
    lost_reason: str | None = Field(default=None, max_length=255)
    next_contact_at: str | None = Field(default=None, max_length=50)
    offer_amount: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=1000)


class ContactFunnelStageIn(BaseModel):
    stage: str = Field(min_length=1, max_length=48)


class ContactPatchIn(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    telephone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, pattern=r"^(lead|active|student|archived)$")
    preferred_channel: str | None = Field(default=None, max_length=20)
    direction: str | None = Field(default=None, max_length=100)
    telegram_username: str | None = Field(default=None, max_length=100)
    acquisition_source: str | None = Field(default=None, max_length=80)
    acquisition_campaign_id: int | None = Field(default=None, ge=1)
    acquisition_campaign: str | None = Field(default=None, max_length=120)
    price: int | None = Field(default=None, ge=0, le=1_000_000)


class ExternalIdentityIn(BaseModel):
    provider: str = Field(pattern=r"^(academy|cards)$")
    subject: str = Field(min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=255)


class ContactPrepaymentIn(BaseModel):
    amount: int = Field(gt=0, le=1_000_000)
    note: str | None = Field(default=None, max_length=500)


class WorkIntervalIn(BaseModel):
    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{2}:\d{2}$")


class WorkDayIn(BaseModel):
    weekday: int = Field(ge=0, le=6)
    enabled: bool = True
    intervals: list[WorkIntervalIn] = Field(default_factory=list)


class WorkScheduleApplyPolicyIn(BaseModel):
    cancel_affected: bool = False
    date_from: date | None = None
    date_to: date | None = None


class WorkScheduleIn(BaseModel):
    days: list[WorkDayIn]
    apply_policy: WorkScheduleApplyPolicyIn | None = None


class WorkSchedulePreviewIn(BaseModel):
    days: list[WorkDayIn]
    date_from: date | None = None
    date_to: date | None = None


class WorkScheduleApplyIn(BaseModel):
    affected_ids: list[int]
    notify_users: bool = True
    reason: str | None = None


class AdminBlockPreviewIn(BaseModel):
    date: date
    all_day: bool = False
    start_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    end_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    note: str | None = None


class AdminBlockCreateIn(AdminBlockPreviewIn):
    strategy: str = Field(default="block_only", pattern=r"^(block_only|block_and_cancel_notify)$")
    notify_reason_template: str | None = Field(default=None, pattern=r"^(illness|business_trip|force_majeure)$")
    notify_reason_custom: str | None = None


class AdminBlockDeleteIn(BaseModel):
    date: date
    all_day: bool = False
    start_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    end_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")


class AdminExtraAvailabilityIn(BaseModel):
    date: date
    start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    note: str | None = None


class PublicBriefIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    telephone: str = Field(min_length=10, max_length=24)
    telegram_username: str | None = Field(default=None, max_length=100)
    persona: str = Field(pattern=r"^(devops|security|hacker)$")
    student_level: str = Field(pattern=r"^(beginner|basic|junior|middle|senior)$")
    goal: str = Field(min_length=5, max_length=500)
    current_problem: str = Field(min_length=3, max_length=700)
    desired_timeline: str = Field(min_length=1, max_length=80)
    weekly_hours: str = Field(min_length=1, max_length=80)
    desired_format: str = Field(default="test_drive", pattern=r"^(test_drive|single|sprint|project|interview|unsure)$")
    consent: bool
    consent_version: str = Field(default="2026-08-12", max_length=32)
    honeypot: str = Field(default="", max_length=200)
    visitor_id: str = Field(min_length=8, max_length=64)
    metrica_client_id: str | None = Field(default=None, max_length=64)
    landing_page: str | None = Field(default=None, max_length=500)
    referrer: str | None = Field(default=None, max_length=500)
    utm_source: str | None = Field(default=None, max_length=80)
    utm_medium: str | None = Field(default=None, max_length=80)
    utm_campaign: str | None = Field(default=None, max_length=120)
    utm_content: str | None = Field(default=None, max_length=120)
    campaign_id: int | None = Field(default=None, ge=1)
    tracking_token: str | None = Field(default=None, min_length=8, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")


class PublicReviewBookingIn(BaseModel):
    enrollment_token: str = Field(min_length=20, max_length=64)
    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    honeypot: str = Field(default="", max_length=200)


class PublicAnalyticsEventIn(BaseModel):
    event_id: str = Field(min_length=8, max_length=80)
    event_type: str = Field(pattern=r"^(tracking_link_opened|landing_view|persona_selected|checkout_started|brief_started|brief_step_completed|brief_submitted|checkout_contact_channel_clicked|payment_confirmed|quest_opened|quest_submitted|slots_viewed|review_requested|review_confirmed|mentorship_offered|mentorship_won|longread_view|longread_25|longread_50|longread_75|longread_100|longread_engaged|longread_part_completed|longread_completed|longread_next_clicked|longread_cta_clicked|profession_interest_clicked)$")
    visitor_id: str = Field(min_length=8, max_length=64)
    brief_token: str | None = Field(default=None, max_length=64)
    path: str | None = Field(default=None, max_length=500)
    utm_source: str | None = Field(default=None, max_length=80)
    utm_medium: str | None = Field(default=None, max_length=80)
    utm_campaign: str | None = Field(default=None, max_length=120)
    utm_content: str | None = Field(default=None, max_length=120)
    campaign_id: int | None = Field(default=None, ge=1)
    tracking_token: str | None = Field(default=None, min_length=8, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    metrica_client_id: str | None = Field(default=None, max_length=64)
    meta: dict[str, Any] = Field(default_factory=dict)


class ReviewBookingDecisionIn(BaseModel):
    status: str = Field(pattern=r"^(approved|rejected)$")


class TestDrivePaymentConfirmIn(BaseModel):
    amount: int = Field(default=1000, ge=1, le=1_000_000)
    quest_url: str | None = Field(default=None, max_length=500)


class TestDriveSubmissionIn(BaseModel):
    enrollment_token: str = Field(min_length=20, max_length=64)
    submission_url: str | None = Field(default=None, max_length=500)
    submission_note: str = Field(min_length=10, max_length=1000)
    honeypot: str = Field(default="", max_length=200)

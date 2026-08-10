"""FastAPI backend for Mini App."""
from __future__ import annotations

import calendar
import datetime
import json
import logging
import os
from uuid import uuid4
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, or_, select, text

from config_data.config import ADMINS_TELEGRAM_ID
from database import transactions
from database.connect import (
    bind_request_session_scope,
    close_db,
    remove_session,
    reset_request_session_scope,
    rollback_session,
    session,
)
from database.models import Contact, FunnelStage, MarketingCampaign, MarketingExpense, MarketingSource, Opportunity, OpportunityStageEvent, Payment, RecordDate, StudentProfile, TelegramIdentity
from loader import bot
from utils.calendar_backend import get_busy_intervals, get_calendar_tz
from utils.schedule import WEEK_SCHEDULE, is_time_in_schedule, refresh_schedule_cache, slots_for_date
from webapi.auth import (
    issue_session_token,
    verify_init_data,
    verify_login_widget_data,
    verify_session_token,
)
from webapi.probes import router as probes_router
from webapi.schemas import (
    AdminBlockCreateIn,
    AdminBlockDeleteIn,
    AdminExtraAvailabilityIn,
    AdminBlockPreviewIn,
    AdminUserPatchIn,
    AuthIn,
    TelegramWidgetAuthIn,
    BookIn,
    BroadcastIn,
    ContactPatchIn,
    ContactFunnelStageIn,
    LessonCloseIn,
    LessonCloseBulkIn,
    FunnelStageCreateIn,
    FunnelStagePatchIn,
    LeadCreateIn,
    LeadPatchIn,
    ManualPaymentIn,
    MarketingCampaignIn,
    MarketingExpenseIn,
    OpportunityMarketingPatchIn,
    RegularLessonIn,
    SingleLessonIn,
    UserProfileIn,
    WorkScheduleApplyIn,
    WorkScheduleIn,
    WorkSchedulePreviewIn,
)

logger = logging.getLogger(__name__)
app = FastAPI(title="Lesson Record MiniApp API", version="1.0.0")
app.state.ready = False
ADMIN_MINIAPP_APPROVALS_ENABLED = os.getenv("ADMIN_MINIAPP_APPROVALS_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
ADMIN_BOT_LEGACY_ENABLED = os.getenv("ADMIN_BOT_LEGACY_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
MINI_APP_URL = os.getenv("MINI_APP_URL", "http://localhost:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(probes_router)


@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    if request.url.path in {"/health", "/ready"}:
        return await call_next(request)
    scope_token = bind_request_session_scope()
    try:
        return await call_next(request)
    except Exception:
        await rollback_session()
        raise
    finally:
        await remove_session()
        reset_request_session_scope(scope_token)


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour_s, minute_s = value.split(":")
    return int(hour_s), int(minute_s)


def _is_valid_custom_step(hour: int, minute: int) -> bool:
    _ = hour
    return minute % 5 == 0


def _check_working_hours(date_value: datetime.date, hour: int, minute: int, duration: int) -> bool:
    # Проверяем по фактическому расписанию, а не по глобальным границам часов.
    return is_time_in_schedule(date_value, hour, minute, duration)


def _date_for_weekday(day_of_week: int) -> datetime.date:
    """Возвращает ближайшую дату нужного weekday (0=Пн..6=Вс)."""
    today = datetime.date.today()
    delta = (day_of_week - today.weekday()) % 7
    return today + datetime.timedelta(days=delta)


def _approval_keyboard(record_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Согласовать", callback_data=f"booking_approve:{record_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"booking_reject:{record_id}"),
            ]
        ]
    )


def _fmt_date_time(date_obj: datetime.date, hour: int, minute: int) -> str:
    return f"{date_obj.isoformat()} {hour:02d}:{minute:02d}"


def _booking_status_filter(status: str) -> Any:
    if status == "pending":
        return RecordDate.booking_status == "pending"
    if status == "approved":
        return (RecordDate.booking_status.is_(None)) | (RecordDate.booking_status == "approved")
    if status == "rejected":
        return RecordDate.booking_status == "rejected"
    raise HTTPException(status_code=422, detail="INVALID_STATUS")


def _booking_kind_label(kind: str | None) -> str:
    return "regular" if (kind or "").lower() == "regular" else "single"


def _profile_display_name(profile: StudentProfile | None) -> str:
    if not profile:
        return ""
    first = (profile.first_name or "").strip()
    last = (profile.last_name or "").strip()
    if first or last:
        return " ".join([last, first]).strip()
    return (profile.full_name or "").strip()


def _minutes_to_hhmm(total_minutes: int) -> str:
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _lesson_amount_for_duration(base_price: int | None, duration: int) -> int:
    price = int(base_price or 0)
    dur = int(duration or 60)
    return max(0, int(round(price * (dur / 60.0))))


def _parse_time_to_minutes(hhmm: str) -> int:
    hh, mm = _parse_hhmm(hhmm)
    return hh * 60 + mm


def _minutes_to_hhmm(total_minutes: int) -> str:
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _block_reason_from_template(template: str | None, custom: str | None) -> str:
    custom_text = (custom or "").strip()
    if custom_text:
        return custom_text
    mapping = {
        "illness": "Заболел",
        "business_trip": "Срочная командировка",
        "force_majeure": "Форс-мажор",
    }
    return mapping.get((template or "").strip(), "изменение расписания")


def _normalize_block_payload(
    date_value: datetime.date,
    all_day: bool,
    start_time: str | None,
    end_time: str | None,
) -> dict[str, Any]:
    if all_day:
        segments = transactions.block_segments_for_date(date_value, all_day=True)
        if not segments:
            raise HTTPException(status_code=422, detail={"code": "NO_WORKING_INTERVALS"})
        first_start = min(seg[0] for seg in segments)
        last_end = max(seg[1] for seg in segments)
        return {
            "all_day": True,
            "segments": segments,
            "start_minute": first_start,
            "end_minute": last_end,
            "start_time": _minutes_to_hhmm(first_start),
            "end_time": _minutes_to_hhmm(last_end),
        }

    if not start_time or not end_time:
        raise HTTPException(status_code=422, detail={"code": "TIME_RANGE_REQUIRED"})
    start_minute = _parse_time_to_minutes(start_time)
    end_minute = _parse_time_to_minutes(end_time)
    if end_minute <= start_minute:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INTERVAL_RANGE"})
    if start_minute % 5 or end_minute % 5:
        raise HTTPException(status_code=422, detail={"code": "INVALID_TIME_STEP"})

    segments = transactions.block_segments_for_date(
        date_value,
        all_day=False,
        start_minute=start_minute,
        end_minute=end_minute,
    )
    if not segments:
        raise HTTPException(status_code=422, detail={"code": "OUTSIDE_WORKING_HOURS"})
    covered = sum(max(0, seg_end - seg_start) for seg_start, seg_end in segments)
    if covered != (end_minute - start_minute):
        raise HTTPException(status_code=422, detail={"code": "OUTSIDE_WORKING_HOURS"})
    return {
        "all_day": False,
        "segments": segments,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "start_time": _minutes_to_hhmm(start_minute),
        "end_time": _minutes_to_hhmm(end_minute),
    }


def _safe_delta_pct(now_value: int, prev_value: int) -> float:
    if prev_value == 0:
        return 100.0 if now_value > 0 else 0.0
    return round(((now_value - prev_value) / prev_value) * 100.0, 2)


def _trend_name(delta: int) -> str:
    if delta > 0:
        return "progress"
    if delta < 0:
        return "regress"
    return "stagnation"


def _combined_signal(revenue_delta: int, lessons_delta: int) -> str:
    if revenue_delta == 0 and lessons_delta == 0:
        return "stagnation"
    if revenue_delta >= 0 and lessons_delta >= 0 and (revenue_delta > 0 or lessons_delta > 0):
        return "progress"
    if revenue_delta <= 0 and lessons_delta <= 0 and (revenue_delta < 0 or lessons_delta < 0):
        return "regress"
    return "mixed"


def _period_bounds(anchor_date: datetime.date, mode: str) -> tuple[datetime.date, datetime.date, datetime.date, datetime.date]:
    if mode == "week":
        current_from = anchor_date - datetime.timedelta(days=anchor_date.weekday())
        current_to = current_from + datetime.timedelta(days=6)
        prev_to = current_from - datetime.timedelta(days=1)
        prev_from = prev_to - datetime.timedelta(days=6)
        return current_from, current_to, prev_from, prev_to

    if mode == "month":
        current_from = anchor_date.replace(day=1)
        next_month = datetime.date(
            current_from.year + (1 if current_from.month == 12 else 0),
            1 if current_from.month == 12 else current_from.month + 1,
            1,
        )
        current_to = next_month - datetime.timedelta(days=1)
        prev_to = current_from - datetime.timedelta(days=1)
        prev_from = prev_to.replace(day=1)
        return current_from, current_to, prev_from, prev_to

    if mode == "quarter":
        quarter_start_month = ((anchor_date.month - 1) // 3) * 3 + 1
        current_from = datetime.date(anchor_date.year, quarter_start_month, 1)
        next_quarter_month = quarter_start_month + 3
        next_quarter_year = anchor_date.year + (1 if next_quarter_month > 12 else 0)
        next_quarter_month = ((next_quarter_month - 1) % 12) + 1
        next_quarter = datetime.date(next_quarter_year, next_quarter_month, 1)
        current_to = next_quarter - datetime.timedelta(days=1)
        prev_to = current_from - datetime.timedelta(days=1)
        prev_quarter_start_month = ((prev_to.month - 1) // 3) * 3 + 1
        prev_from = datetime.date(prev_to.year, prev_quarter_start_month, 1)
        return current_from, current_to, prev_from, prev_to

    raise HTTPException(status_code=422, detail={"code": "INVALID_MODE", "message": "mode must be week, month or quarter"})


def _normalized_days_payload(days: list[Any]) -> list[dict[str, Any]]:
    by_weekday: dict[int, dict[str, Any]] = {}
    for day in days:
        weekday = int(day.weekday)
        enabled = bool(day.enabled)
        intervals = []
        for it in day.intervals:
            start_min = _parse_time_to_minutes(it.start)
            end_min = _parse_time_to_minutes(it.end)
            if start_min % 5 or end_min % 5:
                raise HTTPException(status_code=422, detail="INVALID_TIME_STEP")
            if end_min <= start_min:
                raise HTTPException(status_code=422, detail="INVALID_INTERVAL_RANGE")
            if (end_min - start_min) < 30:
                raise HTTPException(status_code=422, detail="INTERVAL_TOO_SHORT")
            intervals.append((start_min, end_min))

        intervals.sort(key=lambda x: (x[0], x[1]))
        for idx in range(1, len(intervals)):
            prev = intervals[idx - 1]
            cur = intervals[idx]
            if cur[0] < prev[1]:
                raise HTTPException(status_code=422, detail="INTERVALS_OVERLAP")

        by_weekday[weekday] = {"weekday": weekday, "enabled": enabled, "intervals": intervals}

    # Заполняем все дни недели, если не переданы.
    normalized: list[dict[str, Any]] = []
    for weekday in range(7):
        normalized.append(by_weekday.get(weekday, {"weekday": weekday, "enabled": False, "intervals": []}))
    return normalized


def _is_slot_allowed(intervals_map: dict[int, list[tuple[int, int]]], date_value: datetime.date, hour: int, minute: int, duration: int) -> bool:
    day_intervals = intervals_map.get(date_value.weekday(), [])
    if not day_intervals:
        return False
    start_min = hour * 60 + minute
    end_min = start_min + duration
    for int_start, int_end in day_intervals:
        if int_start <= start_min and end_min <= int_end:
            return True
    return False


async def _current_intervals_map() -> dict[int, list[tuple[int, int]]]:
    rows = await session.execute(
        text(
            "SELECT weekday, start_minute, end_minute "
            "FROM working_intervals "
            "WHERE is_active IS TRUE "
            "ORDER BY weekday, start_minute, end_minute"
        )
    )
    intervals_map: dict[int, list[tuple[int, int]]] = {}
    for row in rows:
        weekday = int(row.weekday)
        intervals_map.setdefault(weekday, []).append((int(row.start_minute), int(row.end_minute)))
    return intervals_map


def _serialize_day_item(item: Any) -> dict[str, Any]:
    return {
        "full_name": item[0],
        "phone": item[1],
        "hour": int(item[2]),
        "minute": int(item[3]),
        "kind": item[4],
        "telegram_id": item[5],
        "duration": item[6],
        "username": item[7] if len(item) > 7 else None,
        "time": f"{int(item[2]):02d}:{int(item[3]):02d}",
    }


def _normalize_http_error_for_booking(status: str) -> HTTPException:
    if status == "slot_busy":
        return HTTPException(status_code=409, detail={"code": "SLOT_BUSY"})
    if status in ("already_approved", "already_rejected"):
        return HTTPException(status_code=409, detail={"code": "ALREADY_PROCESSED", "status": status})
    if status == "not_found":
        return HTTPException(status_code=404, detail={"code": "BOOKING_NOT_FOUND"})
    if status == "calendar_error":
        return HTTPException(status_code=500, detail={"code": "CALENDAR_ERROR"})
    return HTTPException(status_code=400, detail={"code": "INVALID_STATUS", "status": status})


async def _audit(admin_id: int, action: str, entity: str, payload: dict[str, Any]) -> None:
    await session.execute(
        text(
            "INSERT INTO admin_audit_log (admin_id, action, entity, payload_json, created_at) "
            "VALUES (:admin_id, :action, :entity, :payload_json, :created_at)"
        ),
        {
            "admin_id": admin_id,
            "action": action,
            "entity": entity,
            "payload_json": json.dumps(payload, ensure_ascii=False, default=str),
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    )
    await session.commit()


def _role_for_user(telegram_id: int) -> str:
    return "admin" if telegram_id in ADMINS_TELEGRAM_ID else "user"


async def get_current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = verify_session_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return payload


async def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="FORBIDDEN")
    return user


@app.on_event("startup")
async def startup() -> None:
    await transactions.init_db()

    # Seed one-time from static fallback if table is empty.
    count_row = await session.execute(text("SELECT COUNT(*) AS c FROM working_intervals"))
    count_value = int((count_row.one_or_none() or [0])[0])
    if count_value == 0:
        for weekday, intervals in WEEK_SCHEDULE.items():
            for start_hhmm, end_hhmm in intervals:
                start_min = _parse_time_to_minutes(start_hhmm)
                end_min = _parse_time_to_minutes(end_hhmm)
                await session.execute(
                    text(
                        "INSERT INTO working_intervals (weekday, start_minute, end_minute, is_active, created_at, updated_at) "
                        "VALUES (:weekday, :start_minute, :end_minute, :is_active, :created_at, :updated_at)"
                    ),
                    {
                        "weekday": int(weekday),
                        "start_minute": int(start_min),
                        "end_minute": int(end_min),
                        "is_active": True,
                        "created_at": datetime.datetime.now().isoformat(),
                        "updated_at": datetime.datetime.now().isoformat(),
                    },
                )
    await session.commit()
    await refresh_schedule_cache()
    await remove_session()


@app.on_event("shutdown")
async def shutdown() -> None:
    app.state.ready = False
    await close_db()


@app.on_event("startup")
async def mark_ready() -> None:
    app.state.ready = True


@app.post("/api/webapp/auth/telegram")
async def auth_telegram(payload: AuthIn) -> dict[str, Any]:
    try:
        data = verify_init_data(payload.initData)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=f"auth failed: {exc}") from exc

    await transactions.upsert_student_profile(
        telegram_id=data["telegram_id"],
        username=data.get("username") or None,
    )
    await transactions.update_visit_date(data["telegram_id"])

    role = _role_for_user(data["telegram_id"])
    token = issue_session_token(data["telegram_id"], role)
    return {
        "access_token": token,
        "user": {
            "telegram_id": data["telegram_id"],
            "role": role,
            "full_name": None,
            "username": data.get("username"),
        },
    }


@app.post("/api/auth/telegram/login-widget")
async def auth_telegram_login_widget(payload: TelegramWidgetAuthIn) -> dict[str, Any]:
    try:
        data = verify_login_widget_data(payload.model_dump())
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail=f"auth failed: {exc}") from exc
    await transactions.upsert_student_profile(
        telegram_id=data["telegram_id"],
        first_name=data.get("first_name"),
        last_name=data.get("last_name"),
        username=data.get("username") or None,
    )
    await transactions.update_visit_date(data["telegram_id"])
    role = _role_for_user(data["telegram_id"])
    return {
        "access_token": issue_session_token(data["telegram_id"], role),
        "user": {
            "telegram_id": data["telegram_id"],
            "role": role,
            "full_name": data.get("full_name") or None,
            "username": data.get("username"),
            "auth_method": "telegram_widget",
        },
    }


@app.get("/api/me")
async def me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    profile = await transactions.get_student_profile(int(user["sub"]))
    display_name = _profile_display_name(profile)
    return {
        "telegram_id": int(user["sub"]),
        "role": user["role"],
        "profile": {
            "full_name": display_name or (profile.full_name if profile else None),
            "first_name": profile.first_name if profile else None,
            "last_name": profile.last_name if profile else None,
            "username": profile.telegram_username if profile else None,
            "telephone": profile.telephone if profile else None,
            "price": profile.price if profile else None,
            "balance_lessons": profile.balance_lessons if profile else 0,
            "profile_completed": bool(profile and profile.first_name and profile.last_name and profile.telephone),
        },
    }


@app.post("/api/user/profile")
async def user_profile_upsert(payload: UserProfileIn, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    telegram_id = int(user["sub"])
    profile = await transactions.upsert_student_profile(
        telegram_id=telegram_id,
        first_name=payload.first_name,
        last_name=payload.last_name,
        telephone=payload.telephone,
    )
    identity = (
        await session.execute(select(TelegramIdentity).where(TelegramIdentity.telegram_id == telegram_id))
    ).scalar_one_or_none()
    if identity is not None:
        contact = await session.get(Contact, identity.contact_id)
        if contact is not None:
            contact.first_name = profile.first_name
            contact.last_name = profile.last_name
            contact.telephone = profile.telephone
            contact.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            await session.commit()
    return {
        "status": "ok",
        "profile": {
            "full_name": _profile_display_name(profile),
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "username": profile.telegram_username,
            "telephone": profile.telephone,
            "profile_completed": bool(profile.first_name and profile.last_name and profile.telephone),
        },
    }


@app.get("/api/user/calendar")
async def user_calendar(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    _ = user
    year, mon = month.split("-")
    y, m = int(year), int(mon)
    today = datetime.date.today()
    days = []
    for day in range(1, calendar.monthrange(y, m)[1] + 1):
        d = datetime.date(y, m, day)
        if d < today:
            days.append({"date": d.isoformat(), "available": False, "reason": "past"})
            continue
        slots = await _available_slots_for_date(d)
        free_count = sum(1 for s in slots if s.get("available"))
        days.append({"date": d.isoformat(), "available": free_count > 0, "slots_count": free_count})
    return {"month": month, "days": days}


async def _available_slots_for_date(date_obj: datetime.date, duration_minutes: int = 60) -> list[dict[str, Any]]:
    now_local = datetime.datetime.now(get_calendar_tz()).replace(tzinfo=None)
    busy = await get_busy_intervals(date_obj)
    slots = []
    for hour, minute in slots_for_date(date_obj, now_local):
        start = datetime.datetime.combine(date_obj, datetime.time(hour, minute), tzinfo=get_calendar_tz())
        end = start + datetime.timedelta(minutes=duration_minutes)
        busy_hit = any(start < b_end and end > b_start for b_start, b_end in busy)
        local_overlap = await transactions.is_slot_overlapping_local(
            date_obj,
            hour,
            minute,
            duration_minutes,
        )
        slots.append({
            "time": f"{hour:02d}:{minute:02d}",
            "available": not busy_hit and not local_overlap,
            "reason_if_blocked": "busy" if busy_hit or local_overlap else None,
        })
    return slots


@app.get("/api/user/slots")
async def user_slots(
    date: datetime.date,
    duration: int = Query(default=60, ge=30, le=180),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _ = user
    return {"date": date.isoformat(), "slots": await _available_slots_for_date(date, duration)}


@app.post("/api/user/book")
async def user_book(payload: BookIn, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    telegram_id = int(user["sub"])
    hh, mm = _parse_hhmm(payload.time)

    if not _is_valid_custom_step(hh, mm):
        raise HTTPException(status_code=422, detail="INVALID_TIME_STEP")
    if not _check_working_hours(payload.date, hh, mm, payload.duration):
        raise HTTPException(status_code=422, detail="OUTSIDE_WORKING_HOURS")
    if payload.date < datetime.date.today():
        raise HTTPException(status_code=422, detail="PAST_DATE")

    if await transactions.is_slot_busy(payload.date, hh, mm, payload.duration):
        alternatives = []
        for s in await _available_slots_for_date(payload.date, payload.duration):
            if s["available"]:
                alternatives.append(s["time"])
            if len(alternatives) == 3:
                break
        raise HTTPException(status_code=409, detail={"code": "SLOT_BUSY", "alternatives": alternatives})

    if await transactions.is_slot_overlapping_local(payload.date, hh, mm, payload.duration):
        raise HTTPException(status_code=409, detail={"code": "SLOT_BUSY", "alternatives": []})

    booking_kind = "regular" if payload.mode == "regular" else "single"
    booking_id = await transactions.add_pending_single_slot(
        telegram_id=telegram_id,
        date=payload.date,
        hour=hh,
        minute=mm,
        duration_minutes=payload.duration,
        kind=booking_kind,
    )

    profile = await transactions.get_student_profile(telegram_id)
    user_name = profile.full_name if profile and profile.full_name else f"id={telegram_id}"
    request_text = (
        "🆕 Новая запись на согласование\n"
        f"Пользователь: {user_name}\n"
        f"ID: {telegram_id}\n"
        f"Дата: {payload.date.isoformat()}\n"
        f"Время: {hh:02d}:{mm:02d}\n"
        f"Длительность: {payload.duration} мин\n"
        f"Тип: {'Регулярное' if booking_kind == 'regular' else 'Разовое'}\n"
        f"Mini App: {MINI_APP_URL}"
    )
    for admin_id in ADMINS_TELEGRAM_ID:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=request_text,
                reply_markup=_approval_keyboard(booking_id),
            )
        except TelegramBadRequest:
            logger.warning("failed to send approval request to admin=%s booking=%s", admin_id, booking_id)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("unexpected error sending approval request admin=%s booking=%s: %s", admin_id, booking_id, exc)

    return {"status": "pending", "booking_id": booking_id}


@app.get("/api/user/bookings")
async def user_bookings(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    telegram_id = int(user["sub"])
    recs = await transactions.view_record_with_status(telegram_id)
    regular = await transactions.view_regular_lessons(telegram_id)
    return {
        "single": [
            {
                "date": r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
                "time": f"{int(r[1]):02d}:{int(r[2]):02d}",
                "duration": int(r[3] or 60),
                "status": r[4] or "approved",
                "kind": r[5] or "single",
            }
            for r in recs
        ],
        "regular": [
            {
                "day_of_week": l.day_of_week,
                "time": f"{int(l.hour or 0):02d}:{int(l.minute or 0):02d}",
                "duration": l.duration_minutes or 60,
            }
            for l in regular
        ],
    }


@app.post("/api/user/bookings/cancel")
async def user_cancel(payload: BookIn, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    telegram_id = int(user["sub"])
    hh, mm = _parse_hhmm(payload.time)
    await transactions.delete_single_slot(
        telegram_id,
        payload.date,
        hh,
        mm,
        cancel_event_type="canceled_by_client",
        source_context="miniapp",
        note="Отменено пользователем",
    )
    return {"status": "ok"}


@app.get("/api/admin/users")
async def admin_users(query: str | None = None, page: int = 1, page_size: int = 20, _: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    rows = await (transactions.search_client(query) if query else transactions.view_clients())
    profiles = [r[0] for r in rows if r and r[0]]
    profiles.sort(key=lambda x: (_profile_display_name(x) or "").lower())
    total = len(profiles)
    start = max(0, (page - 1) * page_size)
    items = profiles[start:start + page_size]
    ids = [int(p.telegram_id) for p in items if p and p.telegram_id is not None]
    last_lessons = await transactions.last_lessons_for_clients(ids)
    active_cutoff = datetime.date.today() - datetime.timedelta(days=7)
    return {
        "items": [
            {
                "telegram_id": p.telegram_id,
                "full_name": _profile_display_name(p) or p.full_name,
                "first_name": p.first_name,
                "last_name": p.last_name,
                "username": p.telegram_username,
                "phone": p.telephone,
                "blocked": bool(p.blocked),
                "balance_lessons": p.balance_lessons or 0,
                "price": p.price or 0,
                "last_lesson_date": last_lessons.get(int(p.telegram_id), {}).get("date"),
                "last_lesson_time": last_lessons.get(int(p.telegram_id), {}).get("time"),
                "active_recent": bool(
                    last_lessons.get(int(p.telegram_id), {}).get("date")
                    and datetime.date.fromisoformat(last_lessons[int(p.telegram_id)]["date"]) >= active_cutoff
                ),
            }
            for p in items
        ],
        "total": total,
        "page": page,
    }


@app.get("/api/admin/users/{telegram_id}")
async def admin_user(telegram_id: int, _: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    p = await transactions.get_student_profile(telegram_id)
    if not p:
        raise HTTPException(status_code=404, detail="not found")
    rec_count = await transactions.count_date_rec(telegram_id)
    regular = await transactions.view_regular_lessons(telegram_id)
    return {
        "telegram_id": p.telegram_id,
        "full_name": _profile_display_name(p) or p.full_name,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "username": p.telegram_username,
        "phone": p.telephone,
        "blocked": bool(p.blocked),
        "balance_lessons": p.balance_lessons or 0,
        "price": p.price or 0,
        "records_count": rec_count[0] if rec_count else 0,
        "regular": [
            {"day_of_week": l.day_of_week, "time": f"{int(l.hour or 0):02d}:{int(l.minute or 0):02d}", "duration": l.duration_minutes or 60}
            for l in regular
        ],
    }


@app.patch("/api/admin/users/{telegram_id}")
async def admin_patch_user(
    telegram_id: int,
    payload: AdminUserPatchIn,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    profile = await transactions.get_student_profile(telegram_id)
    if not profile:
        raise HTTPException(status_code=404, detail="not found")

    target_telegram_id = telegram_id
    if payload.telegram_id_new is not None and payload.telegram_id_new != telegram_id:
        try:
            await transactions.rebind_student_telegram_id(telegram_id, int(payload.telegram_id_new))
            target_telegram_id = int(payload.telegram_id_new)
        except ValueError:
            if payload.merge_if_exists:
                try:
                    await transactions.merge_student_into_existing(telegram_id, int(payload.telegram_id_new))
                    target_telegram_id = int(payload.telegram_id_new)
                except LookupError:
                    raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Профиль не найден"}) from None
            else:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "TELEGRAM_ID_ALREADY_EXISTS", "message": "Пользователь с таким Telegram ID уже существует"},
                ) from None
        except LookupError:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Профиль не найден"}) from None

    updates: dict[str, Any] = {}
    if payload.full_name is not None:
        updates["full_name"] = payload.full_name
    if payload.first_name is not None:
        updates["first_name"] = payload.first_name
    if payload.last_name is not None:
        updates["last_name"] = payload.last_name
    if payload.telephone is not None:
        updates["telephone"] = payload.telephone
    if payload.price is not None:
        updates["price"] = payload.price
    if payload.balance_lessons_set is not None:
        updates["balance_lessons"] = payload.balance_lessons_set
    if updates:
        await transactions.upsert_student_profile(telegram_id=target_telegram_id, **updates)

    if payload.balance_lessons_add is not None:
        await transactions.change_balance(target_telegram_id, payload.balance_lessons_add)

    if payload.blocked is not None:
        await transactions.block_unblock_user(target_telegram_id, "bl" if payload.blocked else "un")

    await _audit(int(admin["sub"]), "update", "user", {"telegram_id": telegram_id, **payload.model_dump()})
    updated = await transactions.get_student_profile(target_telegram_id)
    return {
        "status": "ok",
        "item": {
            "telegram_id": updated.telegram_id,
            "full_name": _profile_display_name(updated) or updated.full_name,
            "first_name": updated.first_name,
            "last_name": updated.last_name,
            "username": updated.telegram_username,
            "phone": updated.telephone,
            "blocked": bool(updated.blocked),
            "balance_lessons": updated.balance_lessons or 0,
            "price": updated.price or 0,
        },
    }


def _contact_name(contact: Contact) -> str:
    return " ".join(part for part in (contact.last_name, contact.first_name) if part).strip()


async def _canonical_names_by_telegram_id(telegram_ids: list[int | None]) -> dict[int, str]:
    """Return display names from the canonical contact directory, not legacy rows."""
    ids = {int(item) for item in telegram_ids if item is not None}
    if not ids:
        return {}
    rows = await session.execute(
        select(TelegramIdentity.telegram_id, Contact)
        .join(Contact, Contact.id == TelegramIdentity.contact_id)
        .where(TelegramIdentity.telegram_id.in_(ids))
    )
    return {
        int(telegram_id): name
        for telegram_id, contact in rows.all()
        if (name := _contact_name(contact))
    }


def _split_contact_name(full_name: str | None) -> tuple[str | None, str | None]:
    parts = [part for part in (full_name or "").strip().split() if part]
    if len(parts) > 1:
        return " ".join(parts[1:]), parts[0]
    return (parts[0], None) if parts else (None, None)


DEFAULT_FUNNEL_STAGES = [
    ("new", "Новые"),
    ("qualified", "Квалификация"),
    ("diagnostic_booked", "Диагностика"),
    ("diagnostic_done", "После диагностики"),
    ("offer_sent", "Предложение"),
    ("won", "Оплата / ученик"),
    ("lost", "Неактуально"),
]


async def _funnel_stages() -> list[FunnelStage]:
    stages = (await session.execute(select(FunnelStage).order_by(FunnelStage.sort_order, FunnelStage.key))).scalars().all()
    if stages:
        return stages
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for index, (key, name) in enumerate(DEFAULT_FUNNEL_STAGES):
        session.add(FunnelStage(key=key, name=name, sort_order=index, created_at=now, updated_at=now))
    await session.commit()
    return (await session.execute(select(FunnelStage).order_by(FunnelStage.sort_order, FunnelStage.key))).scalars().all()


def _stage_out(stage: FunnelStage) -> dict[str, Any]:
    return {"key": stage.key, "name": stage.name, "sort_order": stage.sort_order, "metric_role": stage.metric_role}


@app.get("/api/admin/funnel/stages")
async def admin_funnel_stages(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    return {"items": [_stage_out(item) for item in await _funnel_stages()]}


@app.post("/api/admin/funnel/stages")
async def admin_create_funnel_stage(payload: FunnelStageCreateIn, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    stages = await _funnel_stages()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    stage = FunnelStage(key=f"custom_{uuid4().hex[:12]}", name=payload.name.strip(), sort_order=len(stages), created_at=now, updated_at=now)
    session.add(stage)
    await session.commit()
    await _audit(int(admin["sub"]), "create", "funnel_stage", {"key": stage.key, "name": stage.name})
    return {"item": _stage_out(stage)}


@app.patch("/api/admin/funnel/stages/{stage_key}")
async def admin_patch_funnel_stage(stage_key: str, payload: FunnelStagePatchIn, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    stage = await session.get(FunnelStage, stage_key)
    if stage is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Этап не найден"})
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(stage, field, value.strip() if isinstance(value, str) else value)
    stage.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    await session.commit()
    await _audit(int(admin["sub"]), "update", "funnel_stage", {"key": stage.key, **payload.model_dump(exclude_unset=True)})
    return {"item": _stage_out(stage)}


@app.delete("/api/admin/funnel/stages/{stage_key}")
async def admin_delete_funnel_stage(stage_key: str, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    stage = await session.get(FunnelStage, stage_key)
    if stage is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Этап не найден"})
    used = (await session.execute(select(func.count(Opportunity.id)).where(Opportunity.stage == stage_key))).scalar_one()
    if used:
        raise HTTPException(status_code=409, detail={"code": "STAGE_IN_USE", "message": "Сначала перенесите клиентов из этого этапа"})
    await session.delete(stage)
    await session.commit()
    await _audit(int(admin["sub"]), "delete", "funnel_stage", {"key": stage_key})
    return {"status": "ok"}


def _contact_out(
    contact: Contact,
    identity: TelegramIdentity | None,
    profile: StudentProfile | None,
    opportunities_count: int = 0,
    current_stage: str | None = None,
    current_source: str | None = None,
) -> dict[str, Any]:
    display_name = _contact_name(contact) or _profile_display_name(profile)
    return {
        "id": contact.id,
        "full_name": display_name or "Без имени",
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "telephone": contact.telephone,
        "status": contact.status,
        "is_archived": bool(contact.is_archived),
        "preferred_channel": contact.preferred_channel,
        "telegram_id": identity.telegram_id if identity else None,
        "telegram_username": identity.username if identity else None,
        "is_student": profile is not None,
        "direction": profile.direction if profile else None,
        "balance_lessons": int(profile.balance_lessons or 0) if profile else 0,
        "price": int(profile.price or 0) if profile else 0,
        "opportunities_count": int(opportunities_count or 0),
        "current_stage": current_stage or ("won" if profile is not None else "new"),
        "current_source": current_source,
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
    }


@app.get("/api/admin/contacts")
async def admin_list_contacts(
    query: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 30,
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Unified directory: a person appears once regardless of lifecycle."""
    latest_opportunity_stage = (
        select(Opportunity.stage)
        .where(Opportunity.contact_id == Contact.id)
        .order_by(Opportunity.updated_at.desc(), Opportunity.id.desc())
        .limit(1)
        .correlate(Contact)
        .scalar_subquery()
    )
    latest_opportunity_source = (
        select(Opportunity.source)
        .where(Opportunity.contact_id == Contact.id)
        .order_by(Opportunity.updated_at.desc(), Opportunity.id.desc())
        .limit(1)
        .correlate(Contact)
        .scalar_subquery()
    )
    stmt = (
        select(
            Contact,
            TelegramIdentity,
            StudentProfile,
            func.count(Opportunity.id).label("opportunities_count"),
            latest_opportunity_stage.label("current_stage"),
            latest_opportunity_source.label("current_source"),
        )
        .outerjoin(TelegramIdentity, TelegramIdentity.contact_id == Contact.id)
        .outerjoin(StudentProfile, StudentProfile.contact_id == Contact.id)
        .outerjoin(Opportunity, Opportunity.contact_id == Contact.id)
        .group_by(Contact.id, TelegramIdentity.id, StudentProfile.telegram_id)
        .order_by(Contact.is_archived.asc(), Contact.updated_at.desc(), Contact.id.desc())
    )
    if status:
        stmt = stmt.where(Contact.status == status)
    if query and query.strip():
        pattern = f"%{query.strip()}%"
        stmt = stmt.where(or_(
            Contact.first_name.ilike(pattern),
            Contact.last_name.ilike(pattern),
            Contact.telephone.ilike(pattern),
            TelegramIdentity.username.ilike(pattern),
        ))
    rows = (await session.execute(stmt)).all()
    total = len(rows)
    safe_page = max(1, page)
    safe_size = min(max(1, page_size), 100)
    start = (safe_page - 1) * safe_size
    return {
        "items": [
            _contact_out(contact, identity, profile, count, current_stage, current_source)
            for contact, identity, profile, count, current_stage, current_source in rows[start:start + safe_size]
        ],
        "total": total,
        "page": safe_page,
        "page_size": safe_size,
    }


@app.get("/api/admin/contacts/{contact_id}")
async def admin_contact_detail(contact_id: int, _: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    row = (
        await session.execute(
            select(Contact, TelegramIdentity, StudentProfile)
            .outerjoin(TelegramIdentity, TelegramIdentity.contact_id == Contact.id)
            .outerjoin(StudentProfile, StudentProfile.contact_id == Contact.id)
            .where(Contact.id == contact_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Контакт не найден"})
    contact, identity, profile = row
    opportunities = (
        await session.execute(select(Opportunity).where(Opportunity.contact_id == contact.id).order_by(Opportunity.updated_at.desc()))
    ).scalars().all()
    telegram_id = identity.telegram_id if identity else None
    lessons: list[dict[str, Any]] = []
    payments: list[dict[str, Any]] = []
    if telegram_id is not None:
        lesson_rows = (
            await session.execute(
                select(RecordDate)
                .where(RecordDate.telegram_id == telegram_id)
                .order_by(RecordDate.record_date.desc(), RecordDate.hour.desc(), RecordDate.minute.desc())
                .limit(12)
            )
        ).scalars().all()
        lessons = [{
            "date": item.record_date.isoformat(), "time": f"{int(item.hour):02d}:{int(item.minute or 0):02d}",
            "duration": item.duration_minutes or 60, "kind": item.kind or "single",
            "booking_status": item.booking_status or "approved", "presence_status": item.presence_status,
        } for item in lesson_rows]
        payment_rows = await session.execute(text("""
            SELECT lesson_date, amount, status, source
            FROM payments WHERE telegram_id = :telegram_id
            ORDER BY lesson_date DESC, id DESC LIMIT 12
        """), {"telegram_id": telegram_id})
        payments = [{"date": str(item[0]), "amount": int(item[1] or 0), "status": item[2], "source": item[3]} for item in payment_rows.all()]
    paid_total = sum(item["amount"] for item in payments if item["status"] == "paid")
    return {
        "contact": _contact_out(contact, identity, profile, len(opportunities)),
        "opportunities": [_lead_out(item, contact, identity) for item in opportunities],
        "lessons": lessons,
        "payments": payments,
        "paid_total_recent": paid_total,
    }


@app.patch("/api/admin/contacts/{contact_id}")
async def admin_patch_contact(
    contact_id: int,
    payload: ContactPatchIn,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    contact = await session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Контакт не найден"})
    updates = payload.model_dump(exclude_unset=True)
    direction = updates.pop("direction", None)
    telegram_username = updates.pop("telegram_username", None)
    for field, value in updates.items():
        setattr(contact, field, value)
    profile = (
        await session.execute(select(StudentProfile).where(StudentProfile.contact_id == contact.id))
    ).scalar_one_or_none()
    if profile is not None:
        if "first_name" in updates or "last_name" in updates:
            profile.first_name = contact.first_name
            profile.last_name = contact.last_name
            profile.full_name = _contact_name(contact) or profile.full_name
        if direction is not None:
            profile.direction = direction
        if telegram_username is not None:
            profile.telegram_username = telegram_username.strip().lstrip("@") or None
    if telegram_username is not None:
        identity = (
            await session.execute(select(TelegramIdentity).where(TelegramIdentity.contact_id == contact.id))
        ).scalar_one_or_none()
        if identity is not None:
            identity.username = telegram_username.strip().lstrip("@") or None
    contact.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    await session.commit()
    await _audit(int(admin["sub"]), "update", "contact", {"contact_id": contact.id, **payload.model_dump(exclude_unset=True)})
    return {"status": "ok"}


@app.delete("/api/admin/contacts/{contact_id}/profile")
async def admin_archive_contact_profile(contact_id: int, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    """Archive a duplicate/inactive student profile without touching history."""
    contact = await session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Контакт не найден"})
    profile = (
        await session.execute(select(StudentProfile).where(StudentProfile.contact_id == contact_id))
    ).scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=409, detail={"code": "PROFILE_NOT_FOUND", "message": "У контакта нет профиля ученика"})
    profile.is_deleted = True
    profile.blocked = True
    contact.status = "archived"
    contact.is_archived = True
    contact.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    await session.commit()
    await _audit(int(admin["sub"]), "archive", "student_profile", {"contact_id": contact_id, "telegram_id": profile.telegram_id})
    return {"status": "ok", "contact_id": contact_id}


@app.patch("/api/admin/contacts/{contact_id}/funnel-stage")
async def admin_set_contact_funnel_stage(
    contact_id: int,
    payload: ContactFunnelStageIn,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    contact = await session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Контакт не найден"})
    stages = {item.key for item in await _funnel_stages()}
    if payload.stage not in stages:
        raise HTTPException(status_code=422, detail={"code": "INVALID_STAGE", "message": "Этап не существует"})
    opportunity = (
        await session.execute(
            select(Opportunity).where(Opportunity.contact_id == contact.id).order_by(Opportunity.updated_at.desc(), Opportunity.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if opportunity is None:
        profile = (
            await session.execute(select(StudentProfile).where(StudentProfile.contact_id == contact.id))
        ).scalar_one_or_none()
        opportunity = Opportunity(
            contact_id=contact.id,
            source="manual",
            direction=profile.direction if profile else None,
            stage=payload.stage,
            created_at=now,
            updated_at=now,
        )
        session.add(opportunity)
        await session.flush()
        session.add(OpportunityStageEvent(opportunity_id=opportunity.id, from_stage=None, to_stage=payload.stage, occurred_at=now, actor_id=int(admin["sub"]), source="kanban"))
    else:
        previous_stage = opportunity.stage
        opportunity.stage = payload.stage
        opportunity.updated_at = now
        if previous_stage != payload.stage:
            session.add(OpportunityStageEvent(opportunity_id=opportunity.id, from_stage=previous_stage, to_stage=payload.stage, occurred_at=now, actor_id=int(admin["sub"]), source="kanban"))
    contact.updated_at = now
    await session.commit()
    await _audit(int(admin["sub"]), "move", "opportunity", {"contact_id": contact.id, "opportunity_id": opportunity.id, "stage": payload.stage})
    return {"status": "ok", "opportunity_id": opportunity.id}


def _lead_out(lead: Opportunity, contact: Contact, identity: TelegramIdentity | None = None) -> dict[str, Any]:
    return {
        "id": lead.id, "contact_id": contact.id,
        "telegram_id": identity.telegram_id if identity else None,
        "full_name": _contact_name(contact), "telephone": contact.telephone,
        "source": lead.source, "utm_medium": lead.utm_medium,
        "utm_campaign": lead.utm_campaign, "utm_content": lead.utm_content,
        "direction": lead.direction, "goal": lead.goal, "stage": lead.stage,
        "diagnostic_at": lead.diagnostic_at, "diagnostic_scheduled_at": lead.diagnostic_scheduled_at,
        "diagnostic_held_at": lead.diagnostic_held_at, "offer_amount": lead.offer_amount,
        "paid_amount": lead.paid_amount, "lost_reason": lead.lost_reason,
        "next_contact_at": lead.next_contact_at, "notes": lead.notes,
        "created_at": lead.created_at, "updated_at": lead.updated_at,
    }


@app.get("/api/admin/leads")
async def admin_list_leads(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    result = await session.execute(
        select(Opportunity, Contact, TelegramIdentity)
        .join(Contact, Contact.id == Opportunity.contact_id)
        .outerjoin(TelegramIdentity, TelegramIdentity.contact_id == Contact.id)
        .order_by(Opportunity.updated_at.desc(), Opportunity.id.desc())
    )
    return {"items": [_lead_out(opportunity, contact, identity) for opportunity, contact, identity in result.all()]}


@app.post("/api/admin/leads")
async def admin_create_lead(payload: LeadCreateIn, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    identity = None
    contact = None
    if payload.telegram_id is not None:
        identity = (
            await session.execute(select(TelegramIdentity).where(TelegramIdentity.telegram_id == payload.telegram_id))
        ).scalar_one_or_none()
        if identity is None:
            raise HTTPException(status_code=422, detail={"code": "PROFILE_NOT_FOUND", "message": "Сначала подтвердите Telegram-профиль ученика"})
        contact = await session.get(Contact, identity.contact_id)
    if contact is None and payload.telephone:
        matches = (
            await session.execute(select(Contact).where(Contact.telephone == payload.telephone).limit(2))
        ).scalars().all()
        if len(matches) == 1:
            contact = matches[0]
    if contact is None:
        first_name, last_name = _split_contact_name(payload.full_name)
        contact = Contact(
            first_name=first_name,
            last_name=last_name,
            telephone=payload.telephone,
            preferred_channel="telegram" if identity else "phone",
            status="lead",
            is_archived=False,
            acquisition_source=payload.source.strip().lower() if payload.source.strip().lower() in {"avito", "youtube", "telegram", "referral", "site", "direct", "other"} else "other",
            acquisition_campaign=payload.utm_campaign,
            acquired_at=datetime.date.today(),
            created_at=now,
            updated_at=now,
        )
        session.add(contact)
        await session.flush()
    lead_data = payload.model_dump(exclude={"telegram_id", "full_name", "telephone"})
    stages = await _funnel_stages()
    stage_keys = {stage.key for stage in stages}
    lead_data["stage"] = lead_data["stage"] if lead_data["stage"] in stage_keys else stages[0].key
    lead = Opportunity(contact_id=contact.id, **lead_data, created_at=now, updated_at=now)
    session.add(lead)
    await session.flush()
    session.add(OpportunityStageEvent(opportunity_id=lead.id, from_stage=None, to_stage=lead.stage, occurred_at=now, actor_id=int(admin["sub"]), source="create"))
    await session.commit()
    await session.refresh(lead)
    await _audit(int(admin["sub"]), "create", "lead", {"lead_id": lead.id, "source": lead.source})
    return {"item": _lead_out(lead, contact, identity)}


@app.patch("/api/admin/leads/{lead_id}")
async def admin_patch_lead(lead_id: int, payload: LeadPatchIn, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    lead = await session.get(Opportunity, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Лид не найден"})
    contact = await session.get(Contact, lead.contact_id)
    if not contact:
        raise HTTPException(status_code=409, detail={"code": "CONTACT_NOT_FOUND", "message": "Контакт лида не найден"})
    updates = payload.model_dump(exclude_unset=True)
    previous_stage = lead.stage
    if "stage" in updates:
        stage_keys = {stage.key for stage in await _funnel_stages()}
        if updates["stage"] not in stage_keys:
            raise HTTPException(status_code=422, detail={"code": "INVALID_STAGE", "message": "Этап не существует"})
    if "full_name" in updates:
        contact.first_name, contact.last_name = _split_contact_name(updates.pop("full_name"))
    if "telephone" in updates:
        contact.telephone = updates.pop("telephone")
    if "telegram_id" in updates:
        telegram_id = updates.pop("telegram_id")
        if telegram_id is not None:
            identity = (
                await session.execute(select(TelegramIdentity).where(TelegramIdentity.telegram_id == telegram_id))
            ).scalar_one_or_none()
            if identity is None:
                raise HTTPException(status_code=422, detail={"code": "PROFILE_NOT_FOUND", "message": "Telegram-профиль не найден"})
            lead.contact_id = identity.contact_id
            contact = await session.get(Contact, identity.contact_id)
    for key, value in updates.items():
        setattr(lead, key, value)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    contact.updated_at = now
    lead.updated_at = now
    if "stage" in updates and previous_stage != lead.stage:
        session.add(OpportunityStageEvent(opportunity_id=lead.id, from_stage=previous_stage, to_stage=lead.stage, occurred_at=now, actor_id=int(admin["sub"]), source="edit"))
    await session.commit()
    await _audit(int(admin["sub"]), "update", "lead", {"lead_id": lead.id, "stage": lead.stage})
    identity = (
        await session.execute(select(TelegramIdentity).where(TelegramIdentity.contact_id == contact.id))
    ).scalar_one_or_none()
    return {"item": _lead_out(lead, contact, identity)}


@app.get("/api/admin/leads/summary")
async def admin_leads_summary(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    result = await session.execute(select(Opportunity))
    items = result.scalars().all()
    by_source: dict[str, dict[str, int]] = {}
    for lead in items:
        row = by_source.setdefault(lead.source or "direct", {"leads": 0, "diagnostics": 0, "won": 0, "paid_amount": 0})
        row["leads"] += 1
        row["diagnostics"] += int(lead.stage in {"diagnostic_booked", "diagnostic_done", "offer_sent", "won"})
        row["won"] += int(lead.stage == "won")
        row["paid_amount"] += int(lead.paid_amount or 0)
    return {"total": len(items), "by_source": [{"source": key, **value} for key, value in sorted(by_source.items())]}


@app.patch("/api/admin/opportunities/{opportunity_id}/marketing")
async def admin_patch_opportunity_marketing(opportunity_id: int, payload: OpportunityMarketingPatchIn, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    opportunity = await session.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Сделка не найдена"})
    updates = payload.model_dump(exclude_unset=True)
    if "campaign" in updates:
        updates["utm_campaign"] = updates.pop("campaign") or None
    for key, value in updates.items():
        setattr(opportunity, key, value)
    opportunity.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    await session.commit()
    await _audit(int(admin["sub"]), "update", "opportunity_marketing", {"opportunity_id": opportunity_id, **payload.model_dump(exclude_unset=True)})
    return {"status": "ok"}


@app.get("/api/admin/marketing/sources")
async def admin_marketing_sources(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    items = (await session.execute(select(MarketingSource).order_by(MarketingSource.name))).scalars().all()
    return {"items": [{"key": item.key, "name": item.name, "channel": item.channel, "is_active": bool(item.is_active)} for item in items]}


@app.get("/api/admin/marketing/campaigns")
async def admin_marketing_campaigns(source_key: str | None = None, _: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    statement = select(MarketingCampaign).order_by(MarketingCampaign.source_key, MarketingCampaign.name)
    if source_key:
        statement = statement.where(MarketingCampaign.source_key == source_key)
    items = (await session.execute(statement)).scalars().all()
    return {"items": [{"id": item.id, "source_key": item.source_key, "name": item.name, "is_active": bool(item.is_active)} for item in items]}


@app.post("/api/admin/marketing/campaigns")
async def admin_create_marketing_campaign(payload: MarketingCampaignIn, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    if await session.get(MarketingSource, payload.source_key) is None:
        raise HTTPException(status_code=422, detail={"code": "INVALID_SOURCE", "message": "Источник не найден"})
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    item = MarketingCampaign(source_key=payload.source_key, name=payload.name.strip(), created_at=now, updated_at=now)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    await _audit(int(admin["sub"]), "create", "marketing_campaign", {"id": item.id, "source": item.source_key, "name": item.name})
    return {"item": {"id": item.id, "source_key": item.source_key, "name": item.name}}


@app.get("/api/admin/marketing/expenses")
async def admin_marketing_expenses(date_from: datetime.date, date_to: datetime.date, _: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    rows = await session.execute(select(MarketingExpense, MarketingCampaign).outerjoin(MarketingCampaign, MarketingCampaign.id == MarketingExpense.campaign_id).where(MarketingExpense.spent_at.between(date_from, date_to)).order_by(MarketingExpense.spent_at.desc(), MarketingExpense.id.desc()))
    return {"items": [{"id": expense.id, "spent_at": expense.spent_at.isoformat(), "amount": expense.amount, "source_key": expense.source_key, "campaign_id": expense.campaign_id, "campaign_name": campaign.name if campaign else None, "category": expense.category, "note": expense.note} for expense, campaign in rows.all()]}


@app.post("/api/admin/marketing/expenses")
async def admin_create_marketing_expense(payload: MarketingExpenseIn, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    if await session.get(MarketingSource, payload.source_key) is None:
        raise HTTPException(status_code=422, detail={"code": "INVALID_SOURCE", "message": "Источник не найден"})
    if payload.campaign_id is not None:
        campaign = await session.get(MarketingCampaign, payload.campaign_id)
        if campaign is None or campaign.source_key != payload.source_key:
            raise HTTPException(status_code=422, detail={"code": "INVALID_CAMPAIGN", "message": "Кампания не принадлежит источнику"})
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    item = MarketingExpense(**payload.model_dump(), created_at=now, updated_at=now)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    await _audit(int(admin["sub"]), "create", "marketing_expense", {"expense_id": item.id, **payload.model_dump(mode="json")})
    return {"item": {"id": item.id}}


@app.delete("/api/admin/users/{telegram_id}")
async def admin_delete_user(telegram_id: int, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    ok = await transactions.soft_delete_user(telegram_id)
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Профиль не найден"})
    await _audit(int(admin["sub"]), "delete", "user", {"telegram_id": telegram_id, "mode": "soft_delete"})
    return {"status": "ok"}


@app.get("/api/admin/users/{telegram_id}/bookings")
async def admin_user_bookings(
    telegram_id: int,
    scope: str = Query(default="upcoming", pattern=r"^(upcoming|archive)$"),
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    recs = await transactions.view_record_with_status(telegram_id)
    now_local = datetime.datetime.now(get_calendar_tz()).replace(tzinfo=None)
    items: list[dict[str, Any]] = []
    for r in recs:
        d = r[0]
        hh, mm = int(r[1]), int(r[2])
        dt = datetime.datetime.combine(d, datetime.time(hh, mm))
        is_archive = dt < now_local
        if scope == "archive" and not is_archive:
            continue
        if scope == "upcoming" and is_archive:
            continue
        items.append(
            {
                "date": d.isoformat() if hasattr(d, "isoformat") else str(d),
                "time": f"{hh:02d}:{mm:02d}",
                "duration": int(r[3] or 60),
                "status": r[4] or "approved",
                "kind": _booking_kind_label(r[5]),
            }
        )
    items.sort(key=lambda x: (x["date"], x["time"]), reverse=(scope == "archive"))
    return {"scope": scope, "items": items}


@app.get("/api/admin/approvals")
async def admin_approvals(
    status: str = Query(default="pending", pattern=r"^(pending|approved|rejected)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    if not ADMIN_MINIAPP_APPROVALS_ENABLED:
        raise HTTPException(status_code=404, detail="DISABLED")

    rows = await session.execute(
        select(RecordDate, StudentProfile)
        .join(StudentProfile, StudentProfile.telegram_id == RecordDate.telegram_id, isouter=True)
        .where(
            RecordDate.telegram_id.is_not(None),
            RecordDate.kind.not_in(["block", "allow"]),
            _booking_status_filter(status),
        )
        .order_by(RecordDate.record_date.asc(), RecordDate.hour.asc(), RecordDate.minute.asc(), RecordDate.id.asc())
    )
    all_rows = rows.all()
    total = len(all_rows)
    start = (page - 1) * page_size
    page_rows = all_rows[start:start + page_size]
    items = []
    for rec, profile in page_rows:
        items.append(
            {
                "record_id": int(rec.id),
                "telegram_id": int(rec.telegram_id),
                "full_name": profile.full_name if profile else None,
                "username": profile.telegram_username if profile else None,
                "phone": profile.telephone if profile else None,
                "date": rec.record_date.isoformat(),
                "time": f"{int(rec.hour):02d}:{int(rec.minute):02d}",
                "duration": int(rec.duration_minutes or 60),
                "kind": _booking_kind_label(rec.kind),
                "status": rec.booking_status or "approved",
            }
        )
    return {"status": status, "items": items, "total": total, "page": page}


@app.get("/api/admin/schedule/context")
async def admin_schedule_context(
    date: datetime.date,
    time: str = Query(..., pattern=r"^\d{2}:\d{2}$"),
    duration: int = Query(default=60, ge=30, le=180),
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    hh, mm = _parse_hhmm(time)
    target_minutes = hh * 60 + mm
    items_raw = await transactions.viewing_recordings_day_db(date, show_blocks=True)
    items = [_serialize_day_item(i) for i in items_raw]
    items = sorted(items, key=lambda i: (i["hour"], i["minute"]))

    before = [i for i in items if (i["hour"] * 60 + i["minute"]) < target_minutes][-3:]
    after = [i for i in items if (i["hour"] * 60 + i["minute"]) > target_minutes][:3]

    return {
        "date": date.isoformat(),
        "target": {"time": f"{hh:02d}:{mm:02d}", "duration": duration},
        "neighbors_before": before,
        "neighbors_after": after,
        "day_load": items,
    }


@app.get("/api/admin/approvals/{record_id}")
async def admin_approval_details(record_id: int, _: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    if not ADMIN_MINIAPP_APPROVALS_ENABLED:
        raise HTTPException(status_code=404, detail="DISABLED")

    rec = await transactions.get_record_by_id(record_id)
    if not rec:
        raise HTTPException(status_code=404, detail={"code": "BOOKING_NOT_FOUND"})
    profile = await transactions.get_student_profile(rec.telegram_id)
    context = await admin_schedule_context(rec.record_date, f"{int(rec.hour):02d}:{int(rec.minute):02d}", int(rec.duration_minutes or 60), _)
    return {
        "record_id": int(rec.id),
        "telegram_id": int(rec.telegram_id),
        "full_name": profile.full_name if profile else None,
        "username": profile.telegram_username if profile else None,
        "phone": profile.telephone if profile else None,
        "date": rec.record_date.isoformat(),
        "time": f"{int(rec.hour):02d}:{int(rec.minute):02d}",
        "duration": int(rec.duration_minutes or 60),
        "kind": _booking_kind_label(rec.kind),
        "status": rec.booking_status or "approved",
        "neighbors_before": context["neighbors_before"],
        "neighbors_after": context["neighbors_after"],
        "day_load": context["day_load"],
    }


@app.post("/api/admin/approvals/{record_id}/approve")
async def admin_approval_approve(record_id: int, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    if not ADMIN_MINIAPP_APPROVALS_ENABLED:
        raise HTTPException(status_code=404, detail="DISABLED")

    status, rec = await transactions.approve_pending_booking(record_id, int(admin["sub"]))
    if status != "approved":
        raise _normalize_http_error_for_booking(status)

    try:
        await bot.send_message(
            chat_id=rec.telegram_id,
            text=f"✅ Ваша запись согласована: {_fmt_date_time(rec.record_date, rec.hour, rec.minute)}",
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("failed to notify approved booking id=%s: %s", record_id, exc)

    await _audit(int(admin["sub"]), "approve", "booking", {"record_id": record_id})
    return {"status": "approved", "record_id": record_id}


@app.post("/api/admin/approvals/{record_id}/reject")
async def admin_approval_reject(record_id: int, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    if not ADMIN_MINIAPP_APPROVALS_ENABLED:
        raise HTTPException(status_code=404, detail="DISABLED")

    status, rec = await transactions.reject_pending_booking(record_id, int(admin["sub"]))
    if status != "rejected":
        raise _normalize_http_error_for_booking(status)

    try:
        await bot.send_message(
            chat_id=rec.telegram_id,
            text=f"❌ Ваша запись отклонена: {_fmt_date_time(rec.record_date, rec.hour, rec.minute)}",
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("failed to notify rejected booking id=%s: %s", record_id, exc)

    await _audit(int(admin["sub"]), "reject", "booking", {"record_id": record_id})
    return {"status": "rejected", "record_id": record_id}


@app.post("/api/admin/lessons/single")
async def admin_add_single(payload: SingleLessonIn, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    hh, mm = _parse_hhmm(payload.time)
    if not _is_valid_custom_step(hh, mm):
        raise HTTPException(status_code=422, detail="INVALID_TIME_STEP")
    if not _check_working_hours(payload.date, hh, mm, payload.duration):
        raise HTTPException(status_code=422, detail="OUTSIDE_WORKING_HOURS")
    if await transactions.is_slot_busy(payload.date, hh, mm, payload.duration):
        raise HTTPException(status_code=409, detail="SLOT_BUSY")
    if await transactions.is_slot_overlapping_local(payload.date, hh, mm, payload.duration):
        raise HTTPException(status_code=409, detail="SLOT_BUSY")
    ok = await transactions.add_single_slot(payload.telegram_id, payload.date, hh, mm, payload.duration)
    if not ok:
        raise HTTPException(status_code=500, detail="CREATE_FAILED")
    try:
        await bot.send_message(
            chat_id=payload.telegram_id,
            text=(
                "📌 Вам назначено занятие администратором\n"
                f"Дата: {payload.date.isoformat()}\n"
                f"Время: {hh:02d}:{mm:02d}\n"
                f"Длительность: {payload.duration} мин\n"
                "Тип: Разовое"
            ),
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("failed to notify user about admin single lesson telegram_id=%s: %s", payload.telegram_id, exc)
    await _audit(int(admin["sub"]), "create", "single_lesson", payload.model_dump())
    return {"status": "ok"}


@app.post("/api/admin/lessons/regular")
async def admin_add_regular(payload: RegularLessonIn, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    hh, mm = _parse_hhmm(payload.time)
    if not _is_valid_custom_step(hh, mm):
        raise HTTPException(status_code=422, detail="INVALID_TIME_STEP")
    sample_date = _date_for_weekday(payload.day_of_week)
    if not _check_working_hours(sample_date, hh, mm, payload.duration):
        raise HTTPException(status_code=422, detail="OUTSIDE_WORKING_HOURS")
    await transactions.add_regular_slot(payload.telegram_id, payload.day_of_week, hh, mm, payload.duration)
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    try:
        await bot.send_message(
            chat_id=payload.telegram_id,
            text=(
                "📌 Вам назначено регулярное занятие администратором\n"
                f"День: {day_names[payload.day_of_week]}\n"
                f"Время: {hh:02d}:{mm:02d}\n"
                f"Длительность: {payload.duration} мин\n"
                "Тип: Регулярное"
            ),
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("failed to notify user about admin regular lesson telegram_id=%s: %s", payload.telegram_id, exc)
    await _audit(int(admin["sub"]), "create", "regular_lesson", payload.model_dump())
    return {"status": "ok"}


@app.patch("/api/admin/lessons/{lesson_id}")
async def admin_patch_lesson(lesson_id: int, payload: SingleLessonIn, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    _ = lesson_id
    hh, mm = _parse_hhmm(payload.time)
    await transactions.reschedule_single_slot(
        payload.telegram_id,
        payload.date,
        hh,
        mm,
        payload.date,
        hh,
        mm,
        payload.duration,
        source_context="admin",
    )
    await _audit(int(admin["sub"]), "update", "lesson", {"lesson_id": lesson_id, **payload.model_dump()})
    return {"status": "ok"}


@app.delete("/api/admin/lessons/{lesson_id}")
async def admin_del_lesson(
    lesson_id: int,
    date: datetime.date,
    time: str,
    telegram_id: int,
    scope: str = Query(default="single", pattern=r"^(single|all_regular)$"),
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    _ = lesson_id
    hh, mm = _parse_hhmm(time)

    if scope == "all_regular":
        await transactions.delete_regular_slot(
            telegram_id,
            date.weekday(),
            hh,
            mm,
            delete_future_single=True,
            cancel_event_type="canceled_by_admin",
            source_context="admin",
            note="Удалено администратором",
        )
        await _audit(
            int(admin["sub"]),
            "delete",
            "regular_series",
            {"lesson_id": lesson_id, "date": date.isoformat(), "time": time, "telegram_id": telegram_id, "scope": scope},
        )
        return {"status": "ok", "scope": scope}

    # Для регулярки удаляем только конкретный день и оставляем серию.
    slot_kind = await transactions.get_lesson_kind(date, hh, mm, telegram_id)
    if slot_kind == "regular":
        canceled = await transactions.cancel_regular_occurrence(
            telegram_id,
            date,
            hh,
            mm,
            note="Отменено администратором",
            cancel_event_type="canceled_by_admin",
            source_context="admin",
        )
        if not canceled:
            await transactions.cancel_regular_slot_with_allow(date, hh, mm, note="Отменено администратором")
        await _audit(
            int(admin["sub"]),
            "delete",
            "regular_occurrence",
            {"lesson_id": lesson_id, "date": date.isoformat(), "time": time, "telegram_id": telegram_id, "scope": scope},
        )
        return {"status": "ok", "scope": scope}

    await transactions.delete_single_slot(
        telegram_id,
        date,
        hh,
        mm,
        cancel_event_type="canceled_by_admin",
        source_context="admin",
        note="Удалено администратором",
    )
    await _audit(
        int(admin["sub"]),
        "delete",
        "lesson",
        {"lesson_id": lesson_id, "date": date.isoformat(), "time": time, "telegram_id": telegram_id, "scope": scope},
    )
    return {"status": "ok", "scope": scope}


@app.get("/api/admin/work-schedule")
async def admin_get_work_schedule(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    intervals_map = await _current_intervals_map()
    days: list[dict[str, Any]] = []
    for weekday in range(7):
        intervals = intervals_map.get(weekday, [])
        days.append(
            {
                "weekday": weekday,
                "enabled": len(intervals) > 0,
                "intervals": [{"start": _minutes_to_hhmm(s), "end": _minutes_to_hhmm(e)} for s, e in intervals],
            }
        )
    return {"days": days}


@app.put("/api/admin/work-schedule")
async def admin_put_work_schedule(payload: WorkScheduleIn, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    days = _normalized_days_payload(payload.days)
    await session.execute(text("DELETE FROM working_intervals"))
    for day in days:
        if not day["enabled"]:
            continue
        for start_min, end_min in day["intervals"]:
            await session.execute(
                text(
                    "INSERT INTO working_intervals (weekday, start_minute, end_minute, is_active, created_at, updated_at) "
                    "VALUES (:weekday, :start_minute, :end_minute, :is_active, :created_at, :updated_at)"
                ),
                {
                    "weekday": day["weekday"],
                    "start_minute": start_min,
                    "end_minute": end_min,
                    "is_active": True,
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                },
            )
    await session.commit()
    await refresh_schedule_cache()
    await _audit(int(admin["sub"]), "update", "work_schedule", {"days": len(days)})
    return await admin_get_work_schedule(admin)


@app.post("/api/admin/work-schedule/preview-impact")
async def admin_preview_work_schedule_impact(
    payload: WorkSchedulePreviewIn,
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    days = _normalized_days_payload(payload.days)
    intervals_map = {d["weekday"]: d["intervals"] for d in days if d["enabled"]}
    date_from = payload.date_from or datetime.date.today()
    date_to = payload.date_to or (date_from + datetime.timedelta(days=30))

    rows = await session.execute(
        select(RecordDate, StudentProfile)
        .join(StudentProfile, StudentProfile.telegram_id == RecordDate.telegram_id, isouter=True)
        .where(
            RecordDate.record_date >= date_from,
            RecordDate.record_date <= date_to,
            RecordDate.telegram_id.is_not(None),
            RecordDate.kind.not_in(["block", "allow"]),
            (RecordDate.booking_status.is_(None)) | (RecordDate.booking_status != "rejected"),
        )
        .order_by(RecordDate.record_date.asc(), RecordDate.hour.asc(), RecordDate.minute.asc(), RecordDate.id.asc())
    )

    affected: list[dict[str, Any]] = []
    for rec, profile in rows.all():
        duration = int(rec.duration_minutes or 60)
        if _is_slot_allowed(intervals_map, rec.record_date, int(rec.hour), int(rec.minute), duration):
            continue
        affected.append(
            {
                "record_id": int(rec.id),
                "telegram_id": int(rec.telegram_id),
                "full_name": profile.full_name if profile else None,
                "date": rec.record_date.isoformat(),
                "time": f"{int(rec.hour):02d}:{int(rec.minute):02d}",
                "duration": duration,
                "status": rec.booking_status or "approved",
                "kind": _booking_kind_label(rec.kind),
            }
        )
    return {"date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "affected": affected, "total": len(affected)}


@app.post("/api/admin/work-schedule/apply-impact")
async def admin_apply_work_schedule_impact(
    payload: WorkScheduleApplyIn,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    deleted = 0
    notified = 0
    reason = payload.reason or "изменение рабочего расписания"
    for record_id in payload.affected_ids:
        rec = await transactions.get_record_by_id(int(record_id))
        if not rec or rec.telegram_id is None:
            continue
        await transactions.delete_single_slot(
            int(rec.telegram_id),
            rec.record_date,
            int(rec.hour),
            int(rec.minute),
            cancel_event_type="canceled_by_admin",
            source_context="admin",
            note=f"Отменено из-за изменения рабочего расписания: {reason}",
        )
        deleted += 1

        if payload.notify_users:
            try:
                await bot.send_message(
                    chat_id=int(rec.telegram_id),
                    text=(
                        "❗Занятие отменено администратором\n"
                        f"Дата: {rec.record_date.isoformat()}\n"
                        f"Время: {int(rec.hour):02d}:{int(rec.minute):02d}\n"
                        f"Причина: {reason}\n"
                        "Пожалуйста, выберите новый слот в Mini App."
                    ),
                )
                notified += 1
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("failed to notify canceled lesson record_id=%s: %s", record_id, exc)

    await _audit(
        int(admin["sub"]),
        "apply_impact",
        "work_schedule",
        {"affected_ids": payload.affected_ids, "deleted": deleted, "notified": notified},
    )
    return {"status": "ok", "deleted": deleted, "notified": notified}


@app.get("/api/admin/schedule/day")
async def admin_schedule_day(date: datetime.date, _: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    raw_items = await transactions.viewing_recordings_day_db(date, show_blocks=True)

    def _kind_code(kind_label: str) -> str:
        if kind_label == "Регулярное":
            return "regular"
        if kind_label == "Блок":
            return "block"
        return "single"

    def _to_item(row: Any) -> dict[str, Any]:
        kind = row[4]
        kind_code = _kind_code(kind)
        duration_val = int(row[6] or 60) if len(row) > 6 and row[6] is not None else (5 if kind_code == "block" else 60)
        tg_raw = row[5] if len(row) > 5 else None
        tg_id = int(tg_raw) if isinstance(tg_raw, int) else None
        note = str(tg_raw) if kind_code == "block" and isinstance(tg_raw, str) else None
        return {
            "full_name": row[0],
            "phone": row[1],
            "hour": int(row[2]),
            "minute": int(row[3]),
            "kind": kind,
            "kind_code": kind_code,
            "telegram_id": tg_id,
            "duration": duration_val,
            "username": row[7] if len(row) > 7 else None,
            "price_60": int(row[8] or 0) if len(row) > 8 else 0,
            "amount": _lesson_amount_for_duration(int(row[8] or 0) if len(row) > 8 else 0, duration_val),
            "note": note,
        }

    items = [_to_item(i) for i in raw_items]

    # Склеиваем подряд идущие блоки в интервалы, чтобы день не спамился 5-минутными карточками.
    plain_items = [i for i in items if i["kind_code"] != "block"]
    block_items = sorted(
        [i for i in items if i["kind_code"] == "block"],
        key=lambda x: (x["hour"], x["minute"]),
    )
    merged_blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for item in block_items:
        start = int(item["hour"]) * 60 + int(item["minute"])
        end = start + max(5, int(item.get("duration") or 5))
        if current is None:
            current = {**item, "_start": start, "_end": end, "slot_count": 1}
            continue
        if start <= int(current["_end"]):
            current["_end"] = max(int(current["_end"]), end)
            current["slot_count"] = int(current.get("slot_count") or 1) + 1
            if not current.get("note") and item.get("note"):
                current["note"] = item["note"]
            continue
        merged_blocks.append(current)
        current = {**item, "_start": start, "_end": end, "slot_count": 1}
    if current is not None:
        merged_blocks.append(current)

    block_result: list[dict[str, Any]] = []
    for block in merged_blocks:
        start_min = int(block["_start"])
        end_min = int(block["_end"])
        block["hour"] = start_min // 60
        block["minute"] = start_min % 60
        block["duration"] = max(5, end_min - start_min)
        block["end_hour"] = end_min // 60
        block["end_minute"] = end_min % 60
        block["end_time"] = f"{int(block['end_hour']):02d}:{int(block['end_minute']):02d}"
        block.pop("_start", None)
        block.pop("_end", None)
        block_result.append(block)

    merged_items = sorted(
        [*plain_items, *block_result],
        key=lambda i: (int(i["hour"]), int(i["minute"]), 0 if i["kind_code"] == "block" else 1),
    )

    return {
        "date": date.isoformat(),
        "items": merged_items,
    }


async def _admin_block_preview(payload: AdminBlockPreviewIn) -> dict[str, Any]:
    normalized = _normalize_block_payload(payload.date, bool(payload.all_day), payload.start_time, payload.end_time)
    current_blocks = await transactions.list_block_ranges_for_date(payload.date)
    conflicts = await transactions.find_conflicting_lessons(payload.date, normalized["segments"])
    return {
        "date": payload.date.isoformat(),
        "all_day": bool(normalized["all_day"]),
        "start_time": normalized["start_time"],
        "end_time": normalized["end_time"],
        "segments": normalized["segments"],
        "current_blocks": current_blocks,
        "conflicts": conflicts,
        "conflicts_total": len(conflicts),
    }


@app.get("/api/admin/blocks")
async def admin_get_blocks(date: datetime.date, _: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    blocks = await transactions.list_block_ranges_for_date(date)
    return {"date": date.isoformat(), "blocks": blocks}


@app.post("/api/admin/blocks/preview")
async def admin_preview_blocks(
    payload: AdminBlockPreviewIn,
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    preview = await _admin_block_preview(payload)
    preview.pop("segments", None)
    return preview


@app.post("/api/admin/blocks")
async def admin_create_blocks(
    payload: AdminBlockCreateIn,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    preview = await _admin_block_preview(payload)
    segments = preview.pop("segments", [])
    reason = _block_reason_from_template(payload.notify_reason_template, payload.notify_reason_custom)
    note = (payload.note or "").strip() or "Резерв администратора"
    canceled = 0
    notified = 0

    if payload.strategy == "block_and_cancel_notify":
        for item in preview["conflicts"]:
            hh, mm = _parse_hhmm(item["time"])
            if item["kind"] == "regular":
                canceled_now = await transactions.cancel_regular_occurrence(
                    int(item["telegram_id"]),
                    payload.date,
                    hh,
                    mm,
                    note=f"Отменено из-за брони администратора: {reason}",
                    cancel_event_type="canceled_by_admin",
                    source_context="admin",
                )
                if not canceled_now and item["source"] == "record":
                    await transactions.delete_single_slot(
                        int(item["telegram_id"]),
                        payload.date,
                        hh,
                        mm,
                        cancel_event_type="canceled_by_admin",
                        source_context="admin",
                        note=f"Отменено из-за брони администратора: {reason}",
                    )
            elif item["source"] == "record":
                await transactions.delete_single_slot(
                    int(item["telegram_id"]),
                    payload.date,
                    hh,
                    mm,
                    cancel_event_type="canceled_by_admin",
                    source_context="admin",
                    note=f"Отменено из-за брони администратора: {reason}",
                )
            canceled += 1
            try:
                await bot.send_message(
                    chat_id=int(item["telegram_id"]),
                    text=(
                        "❗Занятие отменено администратором\n"
                        f"Дата: {payload.date.isoformat()}\n"
                        f"Время: {item['time']}\n"
                        f"Причина: {reason}\n"
                        "Пожалуйста, выберите новый слот в Mini App."
                    ),
                )
                notified += 1
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("failed to notify canceled lesson for block telegram_id=%s: %s", item["telegram_id"], exc)

    created = await transactions.create_block_slots(payload.date, segments, note=note)
    blocks = await transactions.list_block_ranges_for_date(payload.date)
    await _audit(
        int(admin["sub"]),
        "create",
        "block",
        {
            "date": payload.date.isoformat(),
            "all_day": payload.all_day,
            "start_time": preview["start_time"],
            "end_time": preview["end_time"],
            "strategy": payload.strategy,
            "created": created,
            "canceled": canceled,
            "notified": notified,
        },
    )
    return {
        "status": "ok",
        "date": payload.date.isoformat(),
        "created": created,
        "canceled": canceled,
        "notified": notified,
        "strategy": payload.strategy,
        "reason": reason if payload.strategy == "block_and_cancel_notify" else None,
        "blocks": blocks,
    }


@app.delete("/api/admin/blocks")
async def admin_delete_blocks(
    payload: AdminBlockDeleteIn,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    normalized = _normalize_block_payload(payload.date, bool(payload.all_day), payload.start_time, payload.end_time)
    deleted = await transactions.delete_blocks_in_segments(payload.date, normalized["segments"])
    blocks = await transactions.list_block_ranges_for_date(payload.date)
    await _audit(
        int(admin["sub"]),
        "delete",
        "block",
        {
            "date": payload.date.isoformat(),
            "all_day": payload.all_day,
            "start_time": normalized["start_time"],
            "end_time": normalized["end_time"],
            "deleted": deleted,
        },
    )
    return {
        "status": "ok",
        "date": payload.date.isoformat(),
        "deleted": deleted,
        "blocks": blocks,
    }


@app.get("/api/admin/schedule/free")
async def admin_schedule_free(
    date: datetime.date,
    duration: int = Query(default=60, ge=30, le=180),
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    slots = await _available_slots_for_date(date, duration)
    free = [s["time"] for s in slots if s.get("available")]
    return {"date": date.isoformat(), "duration": duration, "slots": free}


@app.get("/api/admin/schedule/extra")
async def admin_schedule_extra(date: datetime.date, _: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    items = await transactions.list_date_availability_overrides(date)
    return {"date": date.isoformat(), "items": items}


@app.post("/api/admin/schedule/extra")
async def admin_create_schedule_extra(
    payload: AdminExtraAvailabilityIn,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    start_minute = _parse_time_to_minutes(payload.start_time)
    end_minute = _parse_time_to_minutes(payload.end_time)
    if end_minute <= start_minute:
        raise HTTPException(status_code=422, detail="INVALID_TIME_RANGE")

    item = await transactions.create_date_availability_override(
        target_date=payload.date,
        start_minute=start_minute,
        end_minute=end_minute,
        note=payload.note,
    )
    await _audit(
        int(admin["sub"]),
        "create",
        "extra_availability",
        {"date": payload.date.isoformat(), "start_time": payload.start_time, "end_time": payload.end_time, "note": payload.note or ""},
    )
    return {
        "status": "ok",
        "date": payload.date.isoformat(),
        "item": item,
        "items": await transactions.list_date_availability_overrides(payload.date),
        "slots": [s["time"] for s in await _available_slots_for_date(payload.date) if s.get("available")],
    }


@app.delete("/api/admin/schedule/extra/{item_id}")
async def admin_delete_schedule_extra(
    item_id: int,
    date: datetime.date,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    deleted = await transactions.delete_date_availability_override(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="EXTRA_AVAILABILITY_NOT_FOUND")
    await _audit(
        int(admin["sub"]),
        "delete",
        "extra_availability",
        {"item_id": item_id, "date": date.isoformat()},
    )
    return {
        "status": "ok",
        "date": date.isoformat(),
        "deleted": True,
        "items": await transactions.list_date_availability_overrides(date),
        "slots": [s["time"] for s in await _available_slots_for_date(date) if s.get("available")],
    }


@app.get("/api/admin/schedule/month")
async def admin_schedule_month(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    duration: int = Query(default=60, ge=30, le=180),
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    year, mon = month.split("-")
    y, m = int(year), int(mon)
    start_date = datetime.date(y, m, 1)
    end_date = datetime.date(y, m, calendar.monthrange(y, m)[1])
    days = await transactions.admin_schedule_month_summary(
        start_date=start_date,
        end_date=end_date,
        duration_minutes=duration,
    )
    return {"month": month, "duration": duration, "days": days}


@app.get("/api/admin/dashboard/today")
async def admin_dashboard_today(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    today = datetime.date.today()
    now_local = datetime.datetime.now(get_calendar_tz()).replace(tzinfo=None)

    items = await transactions.viewing_recordings_day_db(today, show_blocks=False)
    agenda = []
    for i in items:
        hh, mm = int(i[2]), int(i[3])
        slot_dt = datetime.datetime.combine(today, datetime.time(hh, mm))
        agenda.append(
            {
                "time": f"{hh:02d}:{mm:02d}",
                "full_name": i[0],
                "kind": i[4],
                "duration": int(i[6] or 60) if len(i) > 6 else 60,
                "telegram_id": i[5],
                "status": "completed" if slot_dt < now_local else "planned",
            }
        )

    summary_day = await transactions.payments_summary_for_range(today, today)
    month_start = today.replace(day=1)
    summary_month = await transactions.payments_summary_for_range(month_start, today)
    pending_rows = await session.execute(
        text("SELECT COUNT(*) FROM record_dates WHERE booking_status='pending' AND telegram_id IS NOT NULL")
    )
    pending_count = int((pending_rows.one_or_none() or [0])[0])

    debtors = await transactions.list_unpaid_payments()
    return {
        "date": today.isoformat(),
        "agenda": agenda,
        "kpi": {
            "today_lessons": len(agenda),
            "today_income": int(summary_day.get("earned_total", 0)),
            "month_income": int(summary_month.get("earned_total", 0)),
            "pending_approvals": pending_count,
            "debtors": len(debtors),
        },
    }


@app.get("/api/admin/stats/month/activity")
async def stats_month_activity(year: int, month: int, _: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    start = datetime.date(year, month, 1)
    end = datetime.date(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1) - datetime.timedelta(days=1)
    now_local = datetime.datetime.now(get_calendar_tz()).replace(tzinfo=None)

    pay_daily = await transactions.payments_daily_breakdown(start, end)
    revenue_map: dict[str, int] = {}
    for d, _, earned, _, _ in pay_daily:
        key = d.isoformat() if hasattr(d, "isoformat") else str(d)
        revenue_map[key] = int(earned or 0)

    lesson_rows = await session.execute(
        select(
            RecordDate.record_date,
            RecordDate.hour,
            RecordDate.minute,
        ).where(
            RecordDate.record_date >= start,
            RecordDate.record_date <= end,
            RecordDate.telegram_id.is_not(None),
            RecordDate.kind.not_in(["block", "allow"]),
            (RecordDate.booking_status.is_(None)) | (RecordDate.booking_status == "approved"),
        )
    )
    lessons_map: dict[str, int] = {}
    for row in lesson_rows:
        d = row.record_date
        slot_dt = datetime.datetime.combine(d, datetime.time(int(row.hour), int(row.minute)))
        if slot_dt > now_local:
            continue
        key = d.isoformat() if hasattr(d, "isoformat") else str(d)
        lessons_map[key] = lessons_map.get(key, 0) + 1

    days = []
    cursor = start
    while cursor <= end:
        key = cursor.isoformat()
        days.append(
            {
                "date": key,
                "day": cursor.day,
                "revenue": revenue_map.get(key, 0),
                "lessons_done": lessons_map.get(key, 0),
            }
        )
        cursor += datetime.timedelta(days=1)

    return {"year": year, "month": month, "days": days}


@app.post("/api/admin/payments/manual")
async def admin_manual_payment(payload: ManualPaymentIn, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    hh, mm = _parse_hhmm(payload.time)
    profile = await transactions.get_student_profile(payload.telegram_id)
    pay = await transactions.add_payment(
        telegram_id=payload.telegram_id,
        full_name=profile.full_name if profile else None,
        lesson_date=payload.date,
        hour=hh,
        minute=mm,
        duration_minutes=payload.duration,
        amount=payload.amount,
        status="paid",
        source="manual",
    )
    await _audit(int(admin["sub"]), "create", "payment", {"payment_id": pay.id, **payload.model_dump()})
    return {"status": "ok", "payment_id": pay.id}


@app.get("/api/admin/lessons/unclosed")
async def admin_unclosed_lessons(
    limit: int = Query(default=200, ge=1, le=500),
    days_back: int = Query(default=60, ge=1, le=365),
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    now_local = datetime.datetime.now(get_calendar_tz()).replace(tzinfo=None)
    today = now_local.date()
    items: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()

    for delta in range(0, days_back + 1):
        date_value = today - datetime.timedelta(days=delta)
        rows = await transactions.lessons_for_date(date_value)
        for row in rows:
            telegram_id = row[0]
            if telegram_id is None:
                continue
            hh, mm = int(row[1]), int(row[2])
            slot_dt = datetime.datetime.combine(date_value, datetime.time(hh, mm))
            if slot_dt >= now_local:
                continue

            exists_payment = await transactions.find_payment(int(telegram_id), date_value, hh, mm)
            if exists_payment:
                continue

            key = (int(telegram_id), date_value.isoformat(), f"{hh:02d}:{mm:02d}")
            if key in seen:
                continue
            seen.add(key)

            profile = await transactions.get_student_profile(int(telegram_id))
            duration_val = int(row[3] or 60)
            expected_amount = _lesson_amount_for_duration(int(profile.price or 0) if profile else 0, duration_val)
            items.append(
                {
                    "telegram_id": int(telegram_id),
                    "full_name": profile.full_name if profile else None,
                    "date": date_value.isoformat(),
                    "time": f"{hh:02d}:{mm:02d}",
                    "hour": hh,
                    "minute": mm,
                    "duration": duration_val,
                    "kind": "regular" if str(row[4] or "single") == "regular" else "single",
                    "price": int(profile.price or 0) if profile and profile.price is not None else 0,
                    "expected_amount": expected_amount,
                    "balance_lessons": int(profile.balance_lessons or 0) if profile else 0,
                    "can_pay_from_balance": bool(profile and int(profile.balance_lessons or 0) >= expected_amount),
                }
            )
            if len(items) >= limit:
                break
        if len(items) >= limit:
            break

    canonical_names = await _canonical_names_by_telegram_id([item["telegram_id"] for item in items])
    for item in items:
        item["full_name"] = canonical_names.get(item["telegram_id"]) or item["full_name"]
    items.sort(key=lambda i: f"{i['date']} {i['time']}", reverse=True)
    return {"items": items, "total": len(items)}


@app.post("/api/admin/lessons/close")
async def admin_close_lesson(payload: LessonCloseIn, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    hh, mm = _parse_hhmm(payload.time)
    exists = await transactions.find_payment(payload.telegram_id, payload.date, hh, mm)
    if exists:
        raise HTTPException(status_code=409, detail={"code": "ALREADY_PROCESSED", "message": "Решение уже принято"})

    profile = await transactions.get_student_profile(payload.telegram_id)
    expected_amount = _lesson_amount_for_duration(int(profile.price or 0) if profile else 0, int(payload.duration or 60))
    amount = payload.amount
    if payload.source == "balance":
        if payload.decision != "paid":
            raise HTTPException(status_code=422, detail={"code": "BALANCE_REQUIRES_PAID", "message": "Списание баланса возможно только для оплаченного занятия"})
        current_balance = int(profile.balance_lessons or 0) if profile else 0
        if current_balance < expected_amount:
            raise HTTPException(status_code=422, detail={"code": "BALANCE_EMPTY", "message": "Недостаточно баланса занятий"})
        await transactions.change_balance(payload.telegram_id, -expected_amount)
        amount = expected_amount if amount is None else int(amount)
    else:
        if amount is None:
            amount = expected_amount

    pay = await transactions.add_payment(
        telegram_id=payload.telegram_id,
        full_name=profile.full_name if profile else None,
        lesson_date=payload.date,
        hour=hh,
        minute=mm,
        duration_minutes=payload.duration,
        amount=max(0, int(amount)),
        status=payload.decision,
        source="balance" if payload.source == "balance" else "lesson_close",
    )

    await _audit(
        int(admin["sub"]),
        "close",
        "lesson",
        {
            "telegram_id": payload.telegram_id,
            "date": payload.date.isoformat(),
            "time": payload.time,
            "decision": payload.decision,
            "amount": amount,
            "source": payload.source,
            "payment_id": pay.id,
        },
    )
    return {"status": "ok", "payment_id": pay.id}


@app.post("/api/admin/lessons/close-bulk")
async def admin_close_lessons_bulk(payload: LessonCloseBulkIn, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    processed = 0
    skipped = 0
    failed: list[dict[str, Any]] = []

    for item in payload.items:
        hh, mm = _parse_hhmm(item.time)
        try:
            exists = await transactions.find_payment(item.telegram_id, item.date, hh, mm)
            if exists:
                skipped += 1
                continue

            profile = await transactions.get_student_profile(item.telegram_id)
            amount = item.amount
            if amount is None:
                amount = int(profile.price or 0) if profile and profile.price is not None else 0

            await transactions.add_payment(
                telegram_id=item.telegram_id,
                full_name=profile.full_name if profile else None,
                lesson_date=item.date,
                hour=hh,
                minute=mm,
                duration_minutes=item.duration,
                amount=max(0, int(amount)),
                status=payload.decision,
                source="lesson_close",
            )
            processed += 1
        except Exception as exc:  # pylint: disable=broad-except
            failed.append(
                {
                    "telegram_id": item.telegram_id,
                    "date": item.date.isoformat(),
                    "time": item.time,
                    "error": str(exc),
                }
            )

    await _audit(
        int(admin["sub"]),
        "close_bulk",
        "lesson",
        {"decision": payload.decision, "items": len(payload.items), "processed": processed, "skipped": skipped, "failed": len(failed)},
    )
    return {"status": "ok", "processed": processed, "skipped": skipped, "failed": failed}


@app.get("/api/admin/payments/debtors")
async def admin_debtors(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    rows = await transactions.list_unpaid_payments()
    names = await _canonical_names_by_telegram_id([row[0].telegram_id for row in rows])
    return {
        "items": [
            {
                "payment_id": r[0].id,
                "telegram_id": r[0].telegram_id,
                "full_name": names.get(int(r[0].telegram_id)) if r[0].telegram_id is not None else r[0].full_name,
                "date": r[0].lesson_date.isoformat() if hasattr(r[0].lesson_date, "isoformat") else str(r[0].lesson_date),
                "time": f"{int(r[0].hour):02d}:{int(r[0].minute):02d}",
                "amount": r[0].amount,
                "status": r[0].status,
            }
            for r in rows
        ]
    }


@app.post("/api/admin/payments/{payment_id}/mark-paid")
async def admin_mark_debt_paid(payment_id: int, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    ok = await transactions.mark_payment_paid(payment_id)
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Платеж не найден"})
    await _audit(int(admin["sub"]), "update", "payment", {"payment_id": payment_id, "status": "paid"})
    return {"status": "ok", "payment_id": payment_id}


@app.post("/api/admin/broadcast")
async def admin_broadcast(payload: BroadcastIn, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    sent = 0
    rows = await transactions.list_student_profiles()
    ids = [r[0].telegram_id for r in rows if r and r[0] and r[0].telegram_id]
    if payload.only_unpaid:
        unpaid = await transactions.list_unpaid_payments()
        unpaid_ids = {r[0].telegram_id for r in unpaid if r and r[0] and r[0].telegram_id}
        ids = [i for i in ids if i in unpaid_ids]
    for uid in ids:
        try:
            await bot.send_message(chat_id=uid, text=payload.message)
            sent += 1
        except TelegramBadRequest:
            continue
        except Exception:
            continue
    await _audit(int(admin["sub"]), "broadcast", "message", {"sent": sent, "only_unpaid": payload.only_unpaid})
    return {"status": "ok", "sent": sent}


@app.get("/api/admin/system/health")
async def admin_system_health(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    db_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "error",
        "api_time": datetime.datetime.utcnow().isoformat() + "Z",
        "approvals_enabled": ADMIN_MINIAPP_APPROVALS_ENABLED,
        "bot_legacy_enabled": ADMIN_BOT_LEGACY_ENABLED,
    }


@app.get("/api/admin/system/backup")
async def admin_system_backup(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    return {"status": "unknown", "last_backup": None, "note": "read-only placeholder"}


@app.get("/api/admin/stats/day")
async def stats_day(date: datetime.date, _: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    return await transactions.payments_summary_for_range(date, date)


@app.get("/api/admin/stats/week")
async def stats_week(date: datetime.date, _: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    start = date - datetime.timedelta(days=date.weekday())
    end = start + datetime.timedelta(days=6)
    return await transactions.payments_summary_for_range(start, end)


@app.get("/api/admin/stats/month")
async def stats_month(year: int, month: int, _: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    start = datetime.date(year, month, 1)
    end = datetime.date(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1) - datetime.timedelta(days=1)
    return await transactions.payments_summary_for_range(start, end)


@app.get("/api/admin/analytics/marketing")
async def analytics_marketing(
    date_from: datetime.date,
    date_to: datetime.date,
    direction: str | None = None,
    source_key: str | None = None,
    campaign: str | None = None,
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Cash marketing dashboard, attributed permanently to first acquisition."""
    sources = (await session.execute(select(MarketingSource))).scalars().all()
    source_names = {item.key: item.name for item in sources}
    contacts = (await session.execute(select(Contact))).scalars().all()
    opportunities = (await session.execute(select(Opportunity))).scalars().all()
    stage_roles = {item.key: item.metric_role for item in await _funnel_stages()}
    events = (await session.execute(select(OpportunityStageEvent))).scalars().all()
    payments = (await session.execute(select(Payment).where(Payment.status == "paid"))).scalars().all()
    expenses = (await session.execute(select(MarketingExpense).where(MarketingExpense.spent_at.between(date_from, date_to)))).scalars().all()
    campaigns = (await session.execute(select(MarketingCampaign))).scalars().all()
    campaign_names = {item.id: item.name for item in campaigns}

    contact_map = {item.id: item for item in contacts}
    scoped_contacts = [item for item in contacts if item.acquired_at and date_from <= item.acquired_at <= date_to]
    if source_key:
        scoped_contacts = [item for item in scoped_contacts if item.acquisition_source == source_key]
    if campaign:
        scoped_contacts = [item for item in scoped_contacts if item.acquisition_campaign == campaign]
    scoped_ids = {item.id for item in scoped_contacts}
    if direction:
        allowed = {item.contact_id for item in opportunities if item.direction == direction}
        scoped_contacts = [item for item in scoped_contacts if item.id in allowed]
        scoped_ids = {item.id for item in scoped_contacts}

    first_paid: dict[int, Payment] = {}
    for payment in payments:
        if payment.contact_id is None:
            continue
        previous = first_paid.get(payment.contact_id)
        if previous is None or payment.lesson_date < previous.lesson_date:
            first_paid[payment.contact_id] = payment
    cash_payments = [item for item in payments if item.contact_id in scoped_ids and date_from <= item.lesson_date <= date_to]
    new_paid = [item for contact_id, item in first_paid.items() if contact_id in scoped_ids and date_from <= item.lesson_date <= date_to]
    exp_scoped = [item for item in expenses if (not source_key or item.source_key == source_key) and (not campaign or campaign_names.get(item.campaign_id) == campaign)]

    event_roles: dict[int, set[str]] = {}
    for event in events:
        if event.occurred_at[:10] < date_from.isoformat() or event.occurred_at[:10] > date_to.isoformat():
            continue
        opportunity = next((item for item in opportunities if item.id == event.opportunity_id), None)
        if opportunity and opportunity.contact_id in scoped_ids:
            event_roles.setdefault(opportunity.contact_id, set()).add(stage_roles.get(event.to_stage, "new"))

    def ratio(numerator: int | float, denominator: int | float) -> float | None:
        return round(float(numerator) / float(denominator), 2) if denominator else None
    def percent(numerator: int | float, denominator: int | float) -> float | None:
        return round((float(numerator) / float(denominator)) * 100, 1) if denominator else None
    def romi(revenue: int, spend: int) -> float | None:
        return round(((revenue - spend) / spend) * 100, 2) if spend else None

    total_spend = sum(int(item.amount) for item in exp_scoped)
    total_cash = sum(int(item.amount or 0) for item in cash_payments)
    first_revenue = sum(int(item.amount or 0) for item in new_paid)
    qualified = sum("qualified" in event_roles.get(contact_id, set()) for contact_id in scoped_ids)
    diagnostics_scheduled = sum("diagnostic_scheduled" in event_roles.get(contact_id, set()) for contact_id in scoped_ids)
    diagnostics_held = sum("diagnostic_held" in event_roles.get(contact_id, set()) for contact_id in scoped_ids)

    rows = []
    row_keys = {(item.acquisition_source or "unknown", item.acquisition_campaign or None) for item in scoped_contacts}
    row_keys |= {(item.source_key, campaign_names.get(item.campaign_id)) for item in exp_scoped}
    for key, campaign_name in sorted(row_keys, key=lambda item: (item[0], item[1] or "")):
        ids = {item.id for item in scoped_contacts if item.acquisition_source == key and (item.acquisition_campaign or None) == campaign_name}
        spend = sum(int(item.amount) for item in exp_scoped if item.source_key == key and campaign_names.get(item.campaign_id) == campaign_name)
        cash = sum(int(item.amount or 0) for item in cash_payments if item.contact_id in ids)
        new_clients = [item for contact_id, item in first_paid.items() if contact_id in ids and date_from <= item.lesson_date <= date_to]
        ltv = sum(int(item.amount or 0) for item in payments if item.contact_id in ids)
        rows.append({"source_key": key, "source_name": source_names.get(key, key), "campaign_name": campaign_name, "spend": spend, "leads": len(ids), "qualified": sum("qualified" in event_roles.get(contact_id, set()) for contact_id in ids), "diagnostics_scheduled": sum("diagnostic_scheduled" in event_roles.get(contact_id, set()) for contact_id in ids), "diagnostics_held": sum("diagnostic_held" in event_roles.get(contact_id, set()) for contact_id in ids), "new_clients": len(new_clients), "first_revenue": sum(int(item.amount or 0) for item in new_clients), "cash_revenue": cash, "ltv": ltv, "cpl": ratio(spend, len(ids)), "cac": ratio(spend, len(new_clients)), "romi": romi(cash, spend)})

    return {"period": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()}, "kpi": {"spend": total_spend, "leads": len(scoped_ids), "qualified": qualified, "diagnostics_scheduled": diagnostics_scheduled, "diagnostics_held": diagnostics_held, "new_clients": len(new_paid), "first_revenue": first_revenue, "cash_revenue": total_cash, "cpl": ratio(total_spend, len(scoped_ids)), "cpql": ratio(total_spend, qualified), "cac": ratio(total_spend, len(new_paid)), "avg_first_payment": ratio(first_revenue, len(new_paid)), "romi": romi(total_cash, total_spend)}, "funnel": [{"role": role, "count": sum(role in values for values in event_roles.values()), "conversion_from_leads": percent(sum(role in values for values in event_roles.values()), len(scoped_ids))} for role in ["new", "qualified", "diagnostic_scheduled", "diagnostic_held", "offer", "won", "lost"]], "rows": rows, "data_quality": {"contacts_unknown_source": sum(item.acquisition_source == "unknown" for item in contacts), "contacts_missing_campaign": sum(bool(item.acquisition_source not in {"unknown", "direct", "referral"} and not item.acquisition_campaign) for item in contacts), "opportunities_missing_next_contact": sum(bool(item.stage not in {"won", "lost"} and not item.next_contact_at) for item in opportunities)}}


@app.get("/api/admin/analytics/overview")
async def analytics_overview(
    anchor_date: datetime.date,
    mode: str = Query(default="week", pattern=r"^(week|month|quarter)$"),
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    current_from, current_to, prev_from, prev_to = _period_bounds(anchor_date, mode)
    period_closed = anchor_date >= current_to

    cur_sum = await transactions.payments_summary_for_range(current_from, current_to)
    prev_sum = await transactions.payments_summary_for_range(prev_from, prev_to)

    cur_clients = await transactions.client_activity_for_range(current_from, current_to)
    prev_clients = await transactions.client_activity_for_range(prev_from, prev_to)
    cur_ids = {int(i["telegram_id"]) for i in cur_clients if i.get("telegram_id") is not None}
    prev_ids = {int(i["telegram_id"]) for i in prev_clients if i.get("telegram_id") is not None}
    new_active_ids = cur_ids - prev_ids
    became_inactive_ids = (prev_ids - cur_ids) if period_closed else set()

    first_dates = await transactions.first_lesson_dates_for_clients(list(new_active_ids))
    new_clients_with_first_lesson = sum(
        1 for tg_id, first_date in first_dates.items() if current_from <= first_date <= current_to
    )

    paid_now = int(cur_sum.get("earned_total", 0))
    paid_prev = int(prev_sum.get("earned_total", 0))
    lessons_now = int(cur_sum.get("lessons_total", 0))
    lessons_prev = int(prev_sum.get("lessons_total", 0))
    paid_count_now = int(cur_sum.get("lessons_paid", 0))
    paid_count_prev = int(prev_sum.get("lessons_paid", 0))
    unpaid_count_now = max(0, lessons_now - paid_count_now)
    unpaid_count_prev = max(0, lessons_prev - paid_count_prev)
    unpaid_amount_now = max(0, int(cur_sum.get("billed_total", 0)) - paid_now)
    unpaid_amount_prev = max(0, int(prev_sum.get("billed_total", 0)) - paid_prev)

    avg_check_now = int(round(paid_now / paid_count_now)) if paid_count_now > 0 else 0
    avg_check_prev = int(round(paid_prev / paid_count_prev)) if paid_count_prev > 0 else 0
    debt_ratio_now = round((unpaid_count_now / lessons_now) * 100.0, 2) if lessons_now > 0 else 0.0
    debt_ratio_prev = round((unpaid_count_prev / lessons_prev) * 100.0, 2) if lessons_prev > 0 else 0.0

    return {
        "period": {
            "mode": mode,
            "current_from": current_from.isoformat(),
            "current_to": current_to.isoformat(),
            "previous_from": prev_from.isoformat(),
            "previous_to": prev_to.isoformat(),
            "closed": period_closed,
        },
        "finance": {
            "paid_now": paid_now,
            "paid_prev": paid_prev,
            "delta_abs": paid_now - paid_prev,
            "delta_pct": _safe_delta_pct(paid_now, paid_prev),
            "billed_now": int(cur_sum.get("billed_total", 0)),
            "billed_prev": int(prev_sum.get("billed_total", 0)),
            "unpaid_amount_now": unpaid_amount_now,
            "unpaid_amount_prev": unpaid_amount_prev,
        },
        "clients": {
            "active_now": len(cur_ids),
            "active_prev": len(prev_ids),
            "new_active_count": len(new_active_ids),
            "became_inactive_count": len(became_inactive_ids),
            "new_clients_with_first_lesson": int(new_clients_with_first_lesson),
        },
        "ops": {
            "lessons_now": lessons_now,
            "lessons_prev": lessons_prev,
            "paid_lessons_now": paid_count_now,
            "paid_lessons_prev": paid_count_prev,
            "avg_check_now": avg_check_now,
            "avg_check_prev": avg_check_prev,
            "debt_ratio_now": debt_ratio_now,
            "debt_ratio_prev": debt_ratio_prev,
        },
    }


@app.get("/api/admin/analytics/clients-delta")
async def analytics_clients_delta(
    anchor_date: datetime.date,
    mode: str = Query(default="week", pattern=r"^(week|month|quarter)$"),
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    current_from, current_to, prev_from, prev_to = _period_bounds(anchor_date, mode)
    period_closed = anchor_date >= current_to

    cur_clients = await transactions.client_activity_for_range(current_from, current_to)
    prev_clients = await transactions.client_activity_for_range(prev_from, prev_to)
    cur_map = {int(i["telegram_id"]): i for i in cur_clients if i.get("telegram_id") is not None}
    prev_map = {int(i["telegram_id"]): i for i in prev_clients if i.get("telegram_id") is not None}
    new_ids = sorted(cur_map.keys() - prev_map.keys())
    inactive_ids = sorted(prev_map.keys() - cur_map.keys()) if period_closed else []

    first_dates = await transactions.first_lesson_dates_for_clients(new_ids)

    new_active = []
    for tg_id in new_ids:
        item = cur_map[tg_id]
        first_date = first_dates.get(tg_id)
        new_active.append(
            {
                **item,
                "is_first_lesson_in_period": bool(first_date and current_from <= first_date <= current_to),
            }
        )

    became_inactive = [prev_map[tg_id] for tg_id in inactive_ids]
    return {
        "period": {
            "mode": mode,
            "current_from": current_from.isoformat(),
            "current_to": current_to.isoformat(),
            "previous_from": prev_from.isoformat(),
            "previous_to": prev_to.isoformat(),
            "closed": period_closed,
        },
        "new_active": new_active,
        "became_inactive": became_inactive,
    }


@app.get("/api/admin/analytics/timeseries")
async def analytics_timeseries(
    anchor_date: datetime.date,
    mode: str = Query(default="week", pattern=r"^(week|month|quarter)$"),
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    current_from, current_to, prev_from, prev_to = _period_bounds(anchor_date, mode)
    current_points = await transactions.payments_timeseries_for_range(current_from, current_to)
    previous_points = await transactions.payments_timeseries_for_range(prev_from, prev_to)

    points: list[dict[str, Any]] = []
    signal_counts = {
        "progress": 0,
        "regress": 0,
        "stagnation": 0,
        "mixed": 0,
    }
    for idx, point in enumerate(current_points):
        prev_point = previous_points[idx] if idx < len(previous_points) else None
        previous_paid = int(prev_point.get("paid_amount", 0)) if prev_point else 0
        previous_lessons = int(prev_point.get("lessons_done", 0)) if prev_point else 0
        revenue_delta = int(point.get("paid_amount", 0)) - previous_paid
        lessons_delta = int(point.get("lessons_done", 0)) - previous_lessons
        signal = _combined_signal(revenue_delta, lessons_delta)
        signal_counts[signal] += 1
        points.append(
            {
                **point,
                "previous_date": prev_point.get("date") if prev_point else None,
                "previous_paid_amount": previous_paid,
                "previous_lessons_done": previous_lessons,
                "revenue_delta_abs": revenue_delta,
                "lessons_delta_abs": lessons_delta,
                "revenue_trend": _trend_name(revenue_delta),
                "lessons_trend": _trend_name(lessons_delta),
                "signal": signal,
            }
        )

    return {
        "period": {
            "mode": mode,
            "current_from": current_from.isoformat(),
            "current_to": current_to.isoformat(),
            "previous_from": prev_from.isoformat(),
            "previous_to": prev_to.isoformat(),
        },
        "points": points,
        "summary": signal_counts,
    }


@app.get("/api/admin/analytics/revenue-share")
async def analytics_revenue_share(
    anchor_date: datetime.date,
    mode: str = Query(default="week", pattern=r"^(week|month|quarter)$"),
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    current_from, current_to, _, _ = _period_bounds(anchor_date, mode)
    share = await transactions.client_revenue_share_for_range(current_from, current_to)
    return {
        "period": {
            "mode": mode,
            "current_from": current_from.isoformat(),
            "current_to": current_to.isoformat(),
        },
        **share,
    }


@app.get("/api/admin/analytics/overview-v2")
async def analytics_overview_v2(
    anchor_date: datetime.date,
    mode: str = Query(default="week", pattern=r"^(week|month|quarter)$"),
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    current_from, current_to, prev_from, prev_to = _period_bounds(anchor_date, mode)
    current_summary = await transactions.payments_summary_for_range(current_from, current_to)
    previous_summary = await transactions.payments_summary_for_range(prev_from, prev_to)
    revenue_share = await transactions.client_revenue_share_for_range(current_from, current_to)
    ltv = await transactions.client_ltv_leaderboard()
    retention = await transactions.retention_overview()
    revenue_drivers = await transactions.revenue_drivers_for_ranges(current_from, current_to, prev_from, prev_to)
    occupancy = await transactions.occupancy_snapshot(current_from, current_to)
    cancellations = await transactions.analytics_event_breakdown(current_from, current_to)
    repeat_booking = await transactions.repeat_booking_summary()
    regular_vs_single = await transactions.regular_vs_single_summary(current_from, current_to)
    event_coverage = await transactions.analytics_event_log_coverage()

    paid_now = int(current_summary.get("earned_total", 0))
    paid_prev = int(previous_summary.get("earned_total", 0))
    lessons_now = int(current_summary.get("lessons_total", 0))
    lessons_prev = int(previous_summary.get("lessons_total", 0))

    return {
        "period": {
            "mode": mode,
            "current_from": current_from.isoformat(),
            "current_to": current_to.isoformat(),
            "previous_from": prev_from.isoformat(),
            "previous_to": prev_to.isoformat(),
        },
        "executive": {
            "kpi": {
                "paid_now": paid_now,
                "paid_prev": paid_prev,
                "paid_delta_abs": paid_now - paid_prev,
                "paid_delta_pct": _safe_delta_pct(paid_now, paid_prev),
                "lessons_now": lessons_now,
                "lessons_prev": lessons_prev,
                "lessons_delta_abs": lessons_now - lessons_prev,
                "avg_check_now": int(round(paid_now / max(1, int(current_summary.get("lessons_paid", 0) or 0)))) if int(current_summary.get("lessons_paid", 0) or 0) > 0 else 0,
            },
            "revenue_drivers": revenue_drivers,
        },
        "client_value": {
            "revenue_share": revenue_share,
            "ltv_leaderboard": ltv,
            "repeat_booking": repeat_booking,
        },
        "retention": retention,
        "schedule_economics": {
            "occupancy_by_weekday": occupancy.get("weekday", []),
            "occupancy_by_hour": occupancy.get("hour", []),
            "load_heatmap": occupancy.get("heatmap", []),
        },
        "stability": {
            "cancellations": cancellations,
            "regular_vs_single": regular_vs_single,
        },
        "limitations": {
            "cancel_history_note": cancellations.get("coverage_note"),
            "event_tracking": event_coverage,
        },
    }

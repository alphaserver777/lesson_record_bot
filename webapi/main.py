"""FastAPI backend for Mini App."""
from __future__ import annotations

import calendar
import datetime
import logging
import os
import sqlite3
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text

from config_data.config import ADMINS_TELEGRAM_ID
from database import transactions
from database.connect import session
from database.models import RecordDate, StudentProfile
from loader import bot
from utils.calendar_backend import get_busy_intervals, get_calendar_tz
from utils.schedule import WEEK_SCHEDULE, is_time_in_schedule, slots_for_date
from webapi.auth import issue_session_token, verify_init_data, verify_session_token
from webapi.schemas import (
    AdminUserPatchIn,
    AuthIn,
    BookIn,
    BroadcastIn,
    LessonCloseIn,
    LessonCloseBulkIn,
    ManualPaymentIn,
    RegularLessonIn,
    SingleLessonIn,
    WorkScheduleApplyIn,
    WorkScheduleIn,
    WorkSchedulePreviewIn,
)

logger = logging.getLogger(__name__)
app = FastAPI(title="Lesson Record MiniApp API", version="1.0.0")
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


def _minutes_to_hhmm(total_minutes: int) -> str:
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _lesson_amount_for_duration(base_price: int | None, duration: int) -> int:
    price = int(base_price or 0)
    dur = int(duration or 60)
    return max(0, int(round(price * (dur / 60.0))))


def _parse_time_to_minutes(hhmm: str) -> int:
    hh, mm = _parse_hhmm(hhmm)
    return hh * 60 + mm


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
            "WHERE is_active = 1 "
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
            "VALUES (:admin_id, :action, :entity, :payload_json, datetime('now'))"
        ),
        {
            "admin_id": admin_id,
            "action": action,
            "entity": entity,
            "payload_json": str(payload),
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
    await session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS admin_audit_log ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "admin_id INTEGER NOT NULL,"
            "action TEXT NOT NULL,"
            "entity TEXT NOT NULL,"
            "payload_json TEXT,"
            "created_at TEXT NOT NULL)"
        )
    )
    await session.execute(text("CREATE INDEX IF NOT EXISTS idx_record_dates_date_time ON record_dates(record_date, hour, minute)"))
    await session.execute(text("CREATE INDEX IF NOT EXISTS idx_record_dates_telegram_id ON record_dates(telegram_id)"))
    await session.execute(text("CREATE INDEX IF NOT EXISTS idx_profiles_name ON student_profiles(full_name)"))
    await session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS working_intervals ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "weekday INTEGER NOT NULL,"
            "start_minute INTEGER NOT NULL,"
            "end_minute INTEGER NOT NULL,"
            "is_active INTEGER NOT NULL DEFAULT 1,"
            "created_at TEXT NOT NULL DEFAULT (datetime('now')),"
            "updated_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
    )
    await session.execute(text("CREATE INDEX IF NOT EXISTS idx_working_intervals_weekday_active ON working_intervals(weekday, is_active)"))
    await session.execute(text("CREATE INDEX IF NOT EXISTS idx_working_intervals_weekday_start_end ON working_intervals(weekday, start_minute, end_minute)"))

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
                        "VALUES (:weekday, :start_minute, :end_minute, 1, datetime('now'), datetime('now'))"
                    ),
                    {"weekday": int(weekday), "start_minute": int(start_min), "end_minute": int(end_min)},
                )
    await session.commit()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/webapp/auth/telegram")
async def auth_telegram(payload: AuthIn) -> dict[str, Any]:
    try:
        data = verify_init_data(payload.initData)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=f"auth failed: {exc}") from exc

    await transactions.upsert_student_profile(
        telegram_id=data["telegram_id"],
        full_name=data.get("full_name") or None,
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
            "full_name": data.get("full_name"),
            "username": data.get("username"),
        },
    }


@app.get("/api/me")
async def me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    profile = await transactions.get_student_profile(int(user["sub"]))
    return {
        "telegram_id": int(user["sub"]),
        "role": user["role"],
        "profile": {
            "full_name": profile.full_name if profile else None,
            "telephone": profile.telephone if profile else None,
            "price": profile.price if profile else None,
            "balance_lessons": profile.balance_lessons if profile else 0,
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
    await transactions.delete_single_slot(telegram_id, payload.date, hh, mm)
    return {"status": "ok"}


@app.get("/api/admin/users")
async def admin_users(query: str | None = None, page: int = 1, page_size: int = 20, _: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    rows = await (transactions.search_client(query) if query else transactions.view_clients())
    profiles = [r[0] for r in rows if r and r[0]]
    profiles.sort(key=lambda x: (x.full_name or "").lower())
    total = len(profiles)
    start = max(0, (page - 1) * page_size)
    items = profiles[start:start + page_size]
    return {
        "items": [
            {
                "telegram_id": p.telegram_id,
                "full_name": p.full_name,
                "username": p.telegram_username,
                "phone": p.telephone,
                "blocked": bool(p.blocked),
                "balance_lessons": p.balance_lessons or 0,
                "price": p.price or 0,
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
        "full_name": p.full_name,
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
            "full_name": updated.full_name,
            "username": updated.telegram_username,
            "phone": updated.telephone,
            "blocked": bool(updated.blocked),
            "balance_lessons": updated.balance_lessons or 0,
            "price": updated.price or 0,
        },
    }


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
    await transactions.reschedule_single_slot(payload.telegram_id, payload.date, hh, mm, payload.date, hh, mm, payload.duration)
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
        await transactions.delete_regular_slot(telegram_id, date.weekday(), hh, mm, delete_future_single=True)
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
        await transactions.cancel_regular_slot_with_allow(date, hh, mm, note="Отменено администратором")
        await _audit(
            int(admin["sub"]),
            "delete",
            "regular_occurrence",
            {"lesson_id": lesson_id, "date": date.isoformat(), "time": time, "telegram_id": telegram_id, "scope": scope},
        )
        return {"status": "ok", "scope": scope}

    await transactions.delete_single_slot(telegram_id, date, hh, mm)
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
                    "VALUES (:weekday, :start_minute, :end_minute, 1, datetime('now'), datetime('now'))"
                ),
                {"weekday": day["weekday"], "start_minute": start_min, "end_minute": end_min},
            )
    await session.commit()
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
        await transactions.delete_single_slot(int(rec.telegram_id), rec.record_date, int(rec.hour), int(rec.minute))
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
    items = await transactions.viewing_recordings_day_db(date, show_blocks=True)
    def _kind_code(kind_label: str) -> str:
        if kind_label == "Регулярное":
            return "regular"
        if kind_label == "Блок":
            return "block"
        return "single"

    return {
        "date": date.isoformat(),
        "items": [
            {
                "full_name": i[0],
                "phone": i[1],
                "hour": int(i[2]),
                "minute": int(i[3]),
                "kind": i[4],
                "kind_code": _kind_code(i[4]),
                "telegram_id": i[5],
                "duration": i[6],
                "username": i[7] if len(i) > 7 else None,
                "price_60": int(i[8] or 0) if len(i) > 8 else 0,
                "amount": _lesson_amount_for_duration(int(i[8] or 0) if len(i) > 8 else 0, int(i[6] or 60)),
            }
            for i in items
        ],
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


@app.get("/api/admin/schedule/month")
async def admin_schedule_month(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    duration: int = Query(default=60, ge=30, le=180),
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    year, mon = month.split("-")
    y, m = int(year), int(mon)
    today = datetime.date.today()
    days: list[dict[str, Any]] = []

    for day in range(1, calendar.monthrange(y, m)[1] + 1):
        d = datetime.date(y, m, day)
        booked_items = await transactions.viewing_recordings_day_db(d, show_blocks=False)
        booked_count = len(booked_items)
        if d < today:
            free_count = 0
        else:
            slots = await _available_slots_for_date(d, duration)
            free_count = sum(1 for s in slots if s.get("available"))
        days.append(
            {
                "date": d.isoformat(),
                "booked_count": booked_count,
                "free_count": free_count,
                "has_booked": booked_count > 0,
                "has_free": free_count > 0,
                "past": d < today,
            }
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
    return {
        "items": [
            {
                "payment_id": r[0].id,
                "telegram_id": r[0].telegram_id,
                "full_name": r[0].full_name,
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
        db_path = os.getenv("DB_PATH", "database/database.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        conn.close()
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

"""FastAPI backend for Mini App."""
from __future__ import annotations

import calendar
import datetime
import logging
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from config_data.config import ADMINS_TELEGRAM_ID
from database import transactions
from database.connect import session
from loader import bot
from utils.calendar_backend import get_busy_intervals, get_calendar_tz
from utils.schedule import is_time_in_schedule, slots_for_date
from webapi.auth import issue_session_token, verify_init_data, verify_session_token
from webapi.schemas import (
    AuthIn,
    BookIn,
    BroadcastIn,
    ManualPaymentIn,
    RegularLessonIn,
    SingleLessonIn,
)

logger = logging.getLogger(__name__)
app = FastAPI(title="Lesson Record MiniApp API", version="1.0.0")

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


async def _available_slots_for_date(date_obj: datetime.date) -> list[dict[str, Any]]:
    now_local = datetime.datetime.now(get_calendar_tz()).replace(tzinfo=None)
    busy = await get_busy_intervals(date_obj)
    slots = []
    for hour, minute in slots_for_date(date_obj, now_local):
        start = datetime.datetime.combine(date_obj, datetime.time(hour, minute), tzinfo=get_calendar_tz())
        end = start + datetime.timedelta(minutes=60)
        busy_hit = any(start < b_end and end > b_start for b_start, b_end in busy)
        slots.append({
            "time": f"{hour:02d}:{minute:02d}",
            "available": not busy_hit,
            "reason_if_blocked": "busy" if busy_hit else None,
        })
    return slots


@app.get("/api/user/slots")
async def user_slots(date: datetime.date, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    _ = user
    return {"date": date.isoformat(), "slots": await _available_slots_for_date(date)}


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

    if await transactions.is_slot_busy(payload.date, hh, mm):
        alternatives = []
        for s in await _available_slots_for_date(payload.date):
            if s["available"]:
                alternatives.append(s["time"])
            if len(alternatives) == 3:
                break
        raise HTTPException(status_code=409, detail={"code": "SLOT_BUSY", "alternatives": alternatives})

    ok = await transactions.add_single_slot(
        telegram_id=telegram_id,
        date=payload.date,
        hour=hh,
        minute=mm,
        duration_minutes=payload.duration,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="BOOKING_FAILED")

    return {"status": "ok"}


@app.get("/api/user/bookings")
async def user_bookings(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    telegram_id = int(user["sub"])
    recs = await transactions.view_record(telegram_id)
    regular = await transactions.view_regular_lessons(telegram_id)
    return {
        "single": [
            {"date": r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]), "time": f"{int(r[1]):02d}:{int(r[2]):02d}"}
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


@app.post("/api/admin/lessons/single")
async def admin_add_single(payload: SingleLessonIn, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    hh, mm = _parse_hhmm(payload.time)
    if not _is_valid_custom_step(hh, mm):
        raise HTTPException(status_code=422, detail="INVALID_TIME_STEP")
    if not _check_working_hours(payload.date, hh, mm, payload.duration):
        raise HTTPException(status_code=422, detail="OUTSIDE_WORKING_HOURS")
    if await transactions.is_slot_busy(payload.date, hh, mm):
        raise HTTPException(status_code=409, detail="SLOT_BUSY")
    ok = await transactions.add_single_slot(payload.telegram_id, payload.date, hh, mm, payload.duration)
    if not ok:
        raise HTTPException(status_code=500, detail="CREATE_FAILED")
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
async def admin_del_lesson(lesson_id: int, date: datetime.date, time: str, telegram_id: int, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    _ = lesson_id
    hh, mm = _parse_hhmm(time)
    await transactions.delete_single_slot(telegram_id, date, hh, mm)
    await _audit(int(admin["sub"]), "delete", "lesson", {"lesson_id": lesson_id, "date": date.isoformat(), "time": time, "telegram_id": telegram_id})
    return {"status": "ok"}


@app.get("/api/admin/schedule/day")
async def admin_schedule_day(date: datetime.date, _: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    items = await transactions.viewing_recordings_day_db(date, show_blocks=True)
    return {
        "date": date.isoformat(),
        "items": [
            {
                "full_name": i[0],
                "phone": i[1],
                "hour": int(i[2]),
                "minute": int(i[3]),
                "kind": i[4],
                "telegram_id": i[5],
                "duration": i[6],
                "username": i[7] if len(i) > 7 else None,
            }
            for i in items
        ],
    }


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

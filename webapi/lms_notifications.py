from __future__ import annotations

import datetime
import hashlib
import hmac
import html
import json
import os
import time

import aiohttp
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import delete, select

from config_data.config import ADMINS_TELEGRAM_ID
from database.connect import session
from database.models import LmsNotificationEvent
from loader import bot


router = APIRouter()
ALLOWED_TYPES = {"assignment.submitted", "assignment.resubmitted", "assignment.review_digest", "lms.health_failed", "lms.health_recovered"}


def _allowed_sources() -> set[str]:
    return set(os.getenv("LMS_ALLOWED_SOURCE_IPS", "192.168.50.114").split(","))


def _verify(timestamp: str, event_id: str, signature: str, body: bytes) -> None:
    secret = os.getenv("LMS_INTERNAL_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="LMS integration is not configured")
    try:
        stamp = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid timestamp") from exc
    if abs(int(time.time()) - stamp) > 300:
        raise HTTPException(status_code=401, detail="Expired timestamp")
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + event_id.encode() + b"." + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")


def _message(payload: dict) -> tuple[str, str]:
    event_type = payload["event_type"]
    if event_type == "assignment.review_digest":
        count = int(payload.get("count", 0))
        lines = [f"<b>Работы на проверке: {count}</b>"]
        for item in payload.get("items", [])[:20]:
            lines.append(f"• {html.escape(item.get('member_name') or item.get('member') or 'Ученик')} — {html.escape(item.get('assignment_title') or item.get('lesson') or 'Задание')}")
        return "\n".join(lines), payload.get("url", "https://academy.professorit.ru/app/professor-it")
    if event_type == "lms.health_failed":
        return "🔴 <b>LMS Professor IT недоступна</b>\nТри последовательные проверки завершились ошибкой.", payload.get("url", "https://academy.professorit.ru")
    if event_type == "lms.health_recovered":
        return "🟢 <b>LMS Professor IT восстановлена</b>", payload.get("url", "https://academy.professorit.ru")
    title = "Повторная сдача" if event_type == "assignment.resubmitted" else "Новая работа"
    text = (
        f"<b>{title}</b>\n"
        f"Ученик: {html.escape(payload.get('student', ''))}\n"
        f"Курс: {html.escape(payload.get('course', ''))}\n"
        f"Урок: {html.escape(payload.get('lesson', ''))}\n"
        f"Задание: {html.escape(payload.get('assignment', ''))}\n"
        f"Время: {html.escape(payload.get('occurred_at', ''))}"
    )
    return text, payload.get("url", "https://academy.professorit.ru/app/professor-it")


async def deliver(payload: dict) -> None:
    text, url = _message(payload)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть", url=url)]])
    errors = []
    for admin_id in ADMINS_TELEGRAM_ID:
        try:
            await bot.send_message(admin_id, text, reply_markup=keyboard)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    if errors or not ADMINS_TELEGRAM_ID:
        raise RuntimeError("; ".join(errors) or "Список администраторов пуст")


@router.post("/api/internal/lms/notifications")
async def receive_lms_notification(
    request: Request,
    x_professorit_timestamp: str = Header(...),
    x_professorit_event_id: str = Header(...),
    x_professorit_signature: str = Header(...),
):
    source_ip = request.client.host if request.client else ""
    if source_ip not in _allowed_sources():
        raise HTTPException(status_code=403, detail="Source is not allowed")
    body = await request.body()
    _verify(x_professorit_timestamp, x_professorit_event_id, x_professorit_signature, body)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Invalid JSON") from exc
    if payload.get("event_id") != x_professorit_event_id or payload.get("event_type") not in ALLOWED_TYPES:
        raise HTTPException(status_code=422, detail="Invalid event")
    existing = await session.scalar(select(LmsNotificationEvent).where(LmsNotificationEvent.event_id == x_professorit_event_id))
    if existing and existing.state == "delivered":
        return {"ok": True, "duplicate": True}
    event = existing or LmsNotificationEvent(event_id=x_professorit_event_id, event_type=payload["event_type"], payload_json=body.decode(), source_ip=source_ip, state="received", created_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    if not existing:
        session.add(event)
        await session.commit()
    try:
        await deliver(payload)
        event.state = "delivered"
        event.delivered_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        event.last_error = None
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        event.state = "failed"
        event.last_error = str(exc)[:1000]
        await session.commit()
        raise HTTPException(status_code=503, detail="Telegram delivery failed") from exc
    return {"ok": True, "duplicate": False}


async def purge_old_events() -> None:
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)).isoformat()
    await session.execute(delete(LmsNotificationEvent).where(LmsNotificationEvent.created_at < cutoff))
    await session.commit()


_health_failures = 0
_health_down = False


async def check_lms_health() -> None:
    global _health_failures, _health_down
    url = os.getenv("LMS_HEALTH_URL", "https://academy.professorit.ru/api/method/ping")
    healthy = False
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.get(url, allow_redirects=True) as response:
                healthy = response.status == 200
    except Exception:  # noqa: BLE001
        healthy = False
    if healthy:
        _health_failures = 0
        if _health_down:
            _health_down = False
            await deliver({"event_type": "lms.health_recovered", "url": "https://academy.professorit.ru"})
        return
    _health_failures += 1
    if _health_failures >= 3 and not _health_down:
        _health_down = True
        await deliver({"event_type": "lms.health_failed", "url": "https://academy.professorit.ru"})

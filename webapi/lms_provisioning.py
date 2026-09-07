"""Выдача доступа к LMS после подтверждённой оплаты."""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from sqlalchemy import and_, or_, select

from database.connect import session
from database.models import ExternalIdentity, TelegramIdentity, TestDriveEnrollment, TestDriveLmsDelivery
from loader import bot
from webapi.telegram_delivery import send_lead_magnet_message


LMS_URL = os.getenv(
    "LMS_PROVISION_URL",
    "http://192.168.50.114:8000/api/method/professorit_lms.provisioning.provision_test_drive",
)
logger = logging.getLogger(__name__)
_STALE_PROCESSING_AFTER = timedelta(minutes=10)
_MAX_RETRY_DELAY_MINUTES = 60


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _retry_at(attempts: int) -> str:
    delay_minutes = min(2 ** min(attempts, 6), _MAX_RETRY_DELAY_MINUTES)
    return (datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)).isoformat()


def generate_temporary_password(length: int = 14) -> str:
    """Генерирует пароль для отдельных ручных сценариев без неоднозначных символов."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789-_"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _delivery_password(event_id: str) -> str:
    """Даёт повторяемый пароль без хранения учётных данных в PostgreSQL."""
    secret = os.getenv("LMS_INTERNAL_SECRET", "")
    if not secret:
        raise RuntimeError("LMS_INTERNAL_SECRET is not configured")
    digest = hmac.new(secret.encode(), event_id.encode(), hashlib.sha256).hexdigest()
    return f"A{digest[:12]}z9"


async def provision_test_drive(
    *, event_id: str, email: str, first_name: str | None, last_name: str | None, password: str
) -> dict[str, Any]:
    secret = os.getenv("LMS_INTERNAL_SECRET", "")
    if not secret:
        raise RuntimeError("LMS_INTERNAL_SECRET is not configured")
    payload = {
        "event_id": event_id,
        "email": email,
        "first_name": first_name or "",
        "last_name": last_name or "",
        "password": password,
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signed = timestamp.encode() + b"." + event_id.encode() + b"." + body
    signature = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-ProfessorIT-Timestamp": timestamp,
        "X-ProfessorIT-Event-ID": event_id,
        "X-ProfessorIT-Signature": signature,
    }
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as client:
        async with client.post(LMS_URL, data=body, headers=headers) as response:
            response_body = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"LMS returned HTTP {response.status}: {response_body[:300]}")
            result = json.loads(response_body)
    return result.get("message", result)


async def _claim_lms_delivery(enrollment_id: int | None = None) -> int | None:
    """Забирает одну готовую задачу, не удерживая транзакцию во время сети."""
    now = _iso_utc_now()
    stale_before = (datetime.now(timezone.utc) - _STALE_PROCESSING_AFTER).isoformat()
    due = or_(
        and_(TestDriveLmsDelivery.status.in_(("pending", "retrying")), TestDriveLmsDelivery.next_retry_at <= now),
        and_(TestDriveLmsDelivery.status == "processing", TestDriveLmsDelivery.locked_at <= stale_before),
    )
    query = select(TestDriveLmsDelivery).where(due)
    if enrollment_id is not None:
        query = query.where(TestDriveLmsDelivery.enrollment_id == enrollment_id)
    job = (
        await session.execute(
            query.order_by(TestDriveLmsDelivery.next_retry_at, TestDriveLmsDelivery.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
    ).scalar_one_or_none()
    if job is None:
        return None
    job.status = "processing"
    job.attempts += 1
    job.locked_at = now
    job.updated_at = now
    await session.commit()
    return job.id


async def _schedule_lms_delivery_retry(job_id: int, error: Exception | str) -> None:
    job = await session.get(TestDriveLmsDelivery, job_id)
    if job is None or job.status == "delivered":
        return
    now = _iso_utc_now()
    job.status = "retrying"
    job.next_retry_at = _retry_at(job.attempts)
    job.locked_at = None
    job.last_error = str(error)[:1000]
    job.updated_at = now
    await session.commit()


async def _send_credentials(job: TestDriveLmsDelivery) -> None:
    """Отправляет доступ в тот Telegram-канал, через который известен контакт."""
    enrollment = await session.get(TestDriveEnrollment, job.enrollment_id)
    if enrollment is None:
        raise RuntimeError("заявка тест-драйва не найдена")
    identity = (
        await session.execute(
            select(TelegramIdentity).where(TelegramIdentity.contact_id == enrollment.contact_id)
        )
    ).scalar_one_or_none()
    lead_magnet_identity = (
        await session.execute(
            select(ExternalIdentity).where(
                ExternalIdentity.contact_id == enrollment.contact_id,
                ExternalIdentity.provider == "telegram_bot:devops_start_bot",
            )
        )
    ).scalar_one_or_none()
    message = (
        "✅ <b>Оплата прошла. Доступ к тест-драйву открыт.</b>\n\n"
        f"Логин: <code>{html.escape(job.email)}</code>\n"
        f"Пароль: <code>{_delivery_password(job.event_id)}</code>\n"
        "Ссылка: https://academy.professorit.ru/lms/\n\n"
        "После первого входа сохраните пароль в надёжном месте."
    )
    if lead_magnet_identity is not None:
        await send_lead_magnet_message(int(lead_magnet_identity.subject), message)
    elif identity is not None:
        await bot.send_message(identity.telegram_id, message)
    else:
        raise RuntimeError("у контакта не привязан Telegram")


async def _process_claimed_lms_delivery(job_id: int) -> str:
    job = await session.get(TestDriveLmsDelivery, job_id)
    if job is None:
        return "missing"
    try:
        if job.provisioned_at is None:
            await provision_test_drive(
                event_id=job.event_id,
                email=job.email,
                first_name=job.first_name,
                last_name=job.last_name,
                password=_delivery_password(job.event_id),
            )
            enrollment = await session.get(TestDriveEnrollment, job.enrollment_id)
            if enrollment is not None:
                enrollment.status = "quest_ready"
                enrollment.updated_at = _iso_utc_now()
            job.provisioned_at = _iso_utc_now()
            job.updated_at = _iso_utc_now()
            await session.commit()

        await _send_credentials(job)
        now = _iso_utc_now()
        job.status = "delivered"
        job.delivered_at = now
        job.locked_at = None
        job.last_error = None
        job.updated_at = now
        await session.commit()
        return "delivered"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось выдать доступ LMS по задаче %s: %s", job_id, exc)
        await _schedule_lms_delivery_retry(job_id, exc)
        return "retrying"


async def process_due_lms_deliveries(*, limit: int = 10, enrollment_id: int | None = None) -> dict[str, int]:
    """Обрабатывает ожидающие выдачи; ошибки остаются в очереди для повтора."""
    delivered = 0
    retrying = 0
    processed = 0
    for _ in range(limit):
        job_id = await _claim_lms_delivery(enrollment_id)
        if job_id is None:
            break
        processed += 1
        result = await _process_claimed_lms_delivery(job_id)
        if result == "delivered":
            delivered += 1
        elif result == "retrying":
            retrying += 1
        if enrollment_id is not None:
            break
    return {"processed": processed, "delivered": delivered, "retrying": retrying}

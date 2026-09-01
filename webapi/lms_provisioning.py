"""Выдача доступа к LMS после подтверждённой оплаты."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import string
import time
from typing import Any

import aiohttp


LMS_URL = os.getenv(
    "LMS_PROVISION_URL",
    "http://192.168.50.114:8000/api/method/professorit_lms.provisioning.provision_test_drive",
)


def generate_temporary_password(length: int = 14) -> str:
    """Генерирует пароль без неоднозначных символов."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789-_"
    return "".join(secrets.choice(alphabet) for _ in range(length))


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

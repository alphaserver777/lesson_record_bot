"""Telegram WebApp auth helpers."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl

from config_data.config import BOT_TOKEN

SESSION_TTL_SECONDS = 60 * 60 * 24


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def verify_init_data(init_data: str, max_age_seconds: int = 60 * 15) -> dict[str, Any]:
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    hash_hex = pairs.pop("hash", None)
    if not hash_hex:
        raise ValueError("missing hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    calc = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, hash_hex):
        raise ValueError("invalid hash")

    auth_date = int(pairs.get("auth_date", "0"))
    now = int(time.time())
    if auth_date <= 0 or now - auth_date > max_age_seconds:
        raise ValueError("stale auth")

    user_raw = pairs.get("user")
    if not user_raw:
        raise ValueError("missing user")
    user = json.loads(user_raw)
    return {
        "telegram_id": int(user["id"]),
        "username": user.get("username"),
        "full_name": " ".join(filter(None, [user.get("first_name"), user.get("last_name")])),
        "auth_date": auth_date,
    }


def verify_login_widget_data(payload: dict[str, Any], max_age_seconds: int = 60 * 15) -> dict[str, Any]:
    """Verifies signed data returned by the Telegram Login Widget."""
    hash_hex = str(payload.get("hash") or "")
    if not hash_hex:
        raise ValueError("missing hash")
    data = {key: value for key, value in payload.items() if key != "hash" and value not in (None, "")}
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret_key = hashlib.sha256(BOT_TOKEN.encode("utf-8")).digest()
    calculated = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, hash_hex):
        raise ValueError("invalid hash")
    auth_date = int(data.get("auth_date", 0))
    now = int(time.time())
    if auth_date <= 0 or auth_date > now + 60 or now - auth_date > max_age_seconds:
        raise ValueError("stale auth")
    return {
        "telegram_id": int(data["id"]),
        "username": data.get("username"),
        "first_name": data.get("first_name"),
        "last_name": data.get("last_name"),
        "full_name": " ".join(filter(None, [data.get("first_name"), data.get("last_name")])),
        "auth_date": auth_date,
    }


def issue_session_token(telegram_id: int, role: str) -> str:
    payload = {
        "sub": telegram_id,
        "role": role,
        "exp": int(time.time()) + SESSION_TTL_SECONDS,
    }
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64url(hmac.new(BOT_TOKEN.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_session_token(token: str) -> dict[str, Any]:
    try:
        body, sig = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("bad token format") from exc

    expected = _b64url(hmac.new(BOT_TOKEN.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        raise ValueError("bad token signature")

    payload = json.loads(_b64url_decode(body).decode("utf-8"))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("token expired")
    return payload

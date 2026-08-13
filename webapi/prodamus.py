"""Small, dependency-free helpers for signed Prodamus payment links."""
from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode


def _normalized(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalized(value[key]) for key in sorted(value, key=lambda item: str(item))}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalized(item) for item in value]
    return value


def sign_payload(payload: Mapping[str, Any], secret_key: str) -> str:
    """Return the HMAC-SHA256 signature required by Prodamus."""
    normalized = _normalized(payload)
    serialized = json.dumps(normalized, ensure_ascii=True, separators=(",", ":")).replace("/", r"\/")
    return hmac.new(secret_key.encode("utf-8"), serialized.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_signature(payload: Mapping[str, Any], signature: str | None, secret_key: str) -> bool:
    if not signature or not secret_key:
        return False
    expected = sign_payload(payload, secret_key)
    return hmac.compare_digest(expected.lower(), signature.strip().lower())


def _flatten_query(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            nested = f"{prefix}[{key}]" if prefix else str(key)
            result.extend(_flatten_query(item, nested))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            result.extend(_flatten_query(item, f"{prefix}[{index}]"))
    else:
        result.append((prefix, str(value)))
    return result


def build_payment_url(form_url: str, payload: Mapping[str, Any], secret_key: str) -> str:
    unsigned = dict(payload)
    unsigned.pop("signature", None)
    signed = {**unsigned, "signature": sign_payload(unsigned, secret_key)}
    separator = "&" if "?" in form_url else "?"
    return f"{form_url.rstrip('/')}/{separator}{urlencode(_flatten_query(signed))}"

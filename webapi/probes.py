"""Lightweight liveness and readiness probes for Mini App API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request


router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> dict[str, str]:
    if not bool(getattr(request.app.state, "ready", False)):
        raise HTTPException(status_code=503, detail={"status": "not_ready"})
    return {"status": "ready"}

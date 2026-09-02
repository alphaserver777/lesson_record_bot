"""Отправка сервисных сообщений через нужного Telegram-бота."""
from __future__ import annotations

import os

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode


async def send_lead_magnet_message(telegram_id: int, text: str) -> None:
    """Отправляет доступ из @devops_start_bot, если пользователь пришёл через него."""
    token = os.getenv("LEAD_MAGNET_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("LEAD_MAGNET_BOT_TOKEN is not configured")
    proxy = os.getenv("TELEGRAM_PROXY_URL", "").strip()
    session = AiohttpSession(proxy=proxy) if proxy else AiohttpSession()
    client = Bot(token=token, parse_mode=ParseMode.HTML, session=session)
    try:
        await client.send_message(telegram_id, text)
    finally:
        await client.session.close()

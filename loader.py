""" Модуль инициализации телеграмм бота."""
import logging
from asyncio import get_event_loop

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from config_data.config import BOT_TOKEN, TELEGRAM_PROXY_URL
from database.connect import close_db

logger = logging.getLogger("logger_info")


async def start_up():
    """Функция start_up. При запуске выводит текст в консоль."""
    logger.info("Bot started")


async def on_shutdown():
    """Функция on_shutdown. При завершении выводит текст в консоль."""
    await close_db()
    logger.info("Bot stopped")

telegram_session = (
    AiohttpSession(proxy=TELEGRAM_PROXY_URL)
    if TELEGRAM_PROXY_URL
    else None
)
bot = Bot(
    token=BOT_TOKEN,
    parse_mode=ParseMode.HTML,
    session=telegram_session,
)
loop = get_event_loop()
dp = Dispatcher()

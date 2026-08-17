""" Модуль запуска телеграмм бота."""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher

from database.connect import close_db
from database.transactions import init_db
from health_server import HealthState, start_health_server
from handlers.routers import register_routers
from loader import bot, dp, on_shutdown, start_up
from middlewares.who_here import WhoHereMiddleware
from utils.commands import set_default_commands
from utils.restart_services import restarting_services


async def main(bot: Bot, dp: Dispatcher) -> None:
    """Функция main. Запускает бота."""
    health_state = HealthState()
    health_server = await start_health_server(health_state)

    await set_default_commands(bot)

    dp.startup.register(start_up)
    dp.shutdown.register(on_shutdown)

    dp.message.middleware(WhoHereMiddleware())
    dp.callback_query.middleware(WhoHereMiddleware())

    register_routers(dp)

    await init_db()

    services_task = asyncio.create_task(restarting_services())

    await bot.delete_webhook(drop_pending_updates=True)
    health_state.ready = True
    try:
        await dp.start_polling(bot)
    finally:
        services_task.cancel()
        await asyncio.gather(services_task, return_exceptions=True)
        await close_db()
        health_state.ready = False
        health_server.close()
        await health_server.wait_closed()


if __name__ == "__main__":
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main(bot, dp))

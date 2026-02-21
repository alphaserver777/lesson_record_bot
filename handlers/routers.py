"""Minimal router registration: Mini App entry + presence callbacks only."""
from aiogram import F, Router
from aiogram.filters import CommandStart

from handlers.custom_handlers.actioins_users.presence_response import (
    presence_no,
    presence_yes,
)
from handlers.default_heandlers.start import start_command


def register_routers(router: Router):
    """Register only essential handlers in notification mode."""
    router.message.register(start_command, CommandStart())
    router.callback_query.register(start_command, F.data == "open_miniapp")

    router.callback_query.register(presence_yes, F.data.startswith("presence_yes="))
    router.callback_query.register(presence_no, F.data.startswith("presence_no="))

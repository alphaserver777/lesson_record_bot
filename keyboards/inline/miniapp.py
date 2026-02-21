"""Inline keyboards for opening Telegram Mini App."""
from aiogram import types


def open_miniapp_kb(mini_app_url: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🚀 Открыть Mini App",
                    web_app=types.WebAppInfo(url=mini_app_url),
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🌐 Открыть в браузере",
                    url=mini_app_url,
                )
            ],
        ]
    )

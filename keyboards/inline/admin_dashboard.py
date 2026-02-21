"""Клавиатуры нового admin dashboard."""
from aiogram import types


def admin_dashboard_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users:list:1")],
            [types.InlineKeyboardButton(text="📚 Занятия", callback_data="admin:lessons:menu")],
            [types.InlineKeyboardButton(text="🗓️ Расписание", callback_data="admin:schedule:menu")],
            [types.InlineKeyboardButton(text="⬅️ Назад к календарю", callback_data="start_command=calendar_day")],
        ]
    )


def users_nav_kb(page: int, has_prev: bool, has_next: bool) -> types.InlineKeyboardMarkup:
    row = []
    if has_prev:
        row.append(types.InlineKeyboardButton(text="⬅️", callback_data=f"admin:users:list:{page-1}"))
    row.append(types.InlineKeyboardButton(text=f"стр. {page}", callback_data="ignore"))
    if has_next:
        row.append(types.InlineKeyboardButton(text="➡️", callback_data=f"admin:users:list:{page+1}"))
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            row if row else [types.InlineKeyboardButton(text=f"стр. {page}", callback_data="ignore")],
            [types.InlineKeyboardButton(text="🔍 Поиск", callback_data="admin:users:search")],
            [types.InlineKeyboardButton(text="⬅️ В dashboard", callback_data="admin:menu")],
        ]
    )


def user_card_actions_kb(telegram_id: int, blocked: bool, page: int = 1) -> types.InlineKeyboardMarkup:
    block_cb = f"confirm_yes_no=blocked={telegram_id}=un" if blocked else f"confirm_yes_no=blocked={telegram_id}=bl"
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text="✏️ Редактировать профиль", callback_data=f"edit_client={telegram_id}"),
            ],
            [
                types.InlineKeyboardButton(text="➕ Разовое занятие", callback_data=f"admin:lesson:add_single:{telegram_id}"),
                types.InlineKeyboardButton(text="🔁 Регулярное занятие", callback_data=f"admin:lesson:add_regular:{telegram_id}"),
            ],
            [
                types.InlineKeyboardButton(text="📋 Записи клиента", callback_data=f"view_recordings={telegram_id}"),
                types.InlineKeyboardButton(text="🛑 Отменить занятие", callback_data=f"cancel_lesson={telegram_id}"),
            ],
            [
                types.InlineKeyboardButton(text="💳 Ручная оплата", callback_data=f"add_manual_pay={telegram_id}"),
                types.InlineKeyboardButton(text=("🔓 Разблокировать" if blocked else "🔒 Заблокировать"), callback_data=block_cb),
            ],
            [
                types.InlineKeyboardButton(text="⬅️ К списку", callback_data=f"admin:users:list:{page}"),
                types.InlineKeyboardButton(text="🏠 Dashboard", callback_data="admin:menu"),
            ],
        ]
    )


def lessons_menu_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="👥 Выбрать клиента", callback_data="admin:users:list:1")],
            [types.InlineKeyboardButton(text="⬅️ В dashboard", callback_data="admin:menu")],
        ]
    )


def schedule_menu_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="📅 Выбрать день", callback_data="admin:schedule:pick_day")],
            [types.InlineKeyboardButton(text="⬅️ В dashboard", callback_data="admin:menu")],
        ]
    )

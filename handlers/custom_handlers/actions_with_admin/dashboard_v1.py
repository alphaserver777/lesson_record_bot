"""V1 dashboard handlers: users, lessons, schedule (dual-mode with legacy redirects)."""
import datetime
import logging

from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from config_data.config import ADMINS_TELEGRAM_ID
from database import transactions
from keyboards.inline.admin_calendar_v2 import (
    namespaced_month_calendar,
    regular_duration_kb,
    regular_time_kb,
    regular_weekday_kb,
    slot_picker,
)
from keyboards.inline.admin_dashboard import (
    admin_dashboard_kb,
    lessons_menu_kb,
    schedule_menu_kb,
    user_card_actions_kb,
    users_nav_kb,
)
from states.states import AdminUsersState

logger = logging.getLogger(__name__)
USERS_PAGE_SIZE = 8


def _is_admin(user_id: int) -> bool:
    return user_id in ADMINS_TELEGRAM_ID


async def _replace_screen(
    callback: types.CallbackQuery,
    text: str,
    reply_markup: types.InlineKeyboardMarkup | None = None,
) -> None:
    """Render next admin screen in-place; fallback to delete+send when edit is impossible."""
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        msg = (exc.message or "").lower()
        if "message is not modified" in msg:
            return
        logger.warning("edit_text failed in dashboard_v1: %s", exc)
        try:
            await callback.message.delete()
        except TelegramBadRequest as del_exc:
            logger.warning("delete_message failed in dashboard_v1: %s", del_exc)
        await callback.message.answer(text, reply_markup=reply_markup)


async def admin_dashboard(message: types.CallbackQuery | types.Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        if isinstance(message, types.CallbackQuery):
            await message.answer("Нет доступа", show_alert=True)
        else:
            await message.answer("Нет доступа")
        return
    await state.clear()
    text = "⚙️ Dashboard\n\nВыберите раздел:"
    if isinstance(message, types.CallbackQuery):
        await _replace_screen(message, text, admin_dashboard_kb())
        await message.answer()
    else:
        await message.answer(text, reply_markup=admin_dashboard_kb())


async def legacy_redirect_view_clients(callback: types.CallbackQuery, state: FSMContext) -> None:
    logger.info("legacy callback used: view_clients -> admin:users:list:1")
    await _send_users_page(callback, state, page=1)


async def legacy_redirect_search_client(callback: types.CallbackQuery, state: FSMContext) -> None:
    logger.info("legacy callback used: search_client -> admin:users:search")
    await admin_users_search_prompt(callback, state)


async def legacy_redirect_add_single(callback: types.CallbackQuery, state: FSMContext) -> None:
    logger.info("legacy callback used: add_single=* -> admin:lesson:add_single:*")
    legacy_id = callback.data.split("=")[1]
    await _show_add_single_calendar(callback, int(legacy_id), state)


async def _send_users_page(callback: types.CallbackQuery, state: FSMContext, page: int) -> None:
    rows = await transactions.view_clients()
    profiles = [r[0] for r in rows]
    profiles.sort(key=lambda x: (x.full_name or "").lower())
    start = (page - 1) * USERS_PAGE_SIZE
    end = start + USERS_PAGE_SIZE
    page_items = profiles[start:end]
    total_pages = max(1, (len(profiles) + USERS_PAGE_SIZE - 1) // USERS_PAGE_SIZE)
    page = min(page, total_pages)

    buttons = []
    for p in page_items:
        name = (p.full_name or f"ID {p.telegram_id}")[:32]
        status = "🚫" if p.blocked else "✅"
        buttons.append(
            [types.InlineKeyboardButton(text=f"{status} {name}", callback_data=f"admin:user:{p.telegram_id}:{page}")]
        )

    nav = users_nav_kb(page=page, has_prev=page > 1, has_next=page < total_pages)
    buttons.extend(nav.inline_keyboard)
    await _replace_screen(
        callback,
        f"👥 Пользователи\nСтраница {page}/{total_pages}\n\nВыберите клиента:",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()
    await state.clear()


async def admin_users_list(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    page = 1
    parts = callback.data.split(":")
    if len(parts) >= 4:
        try:
            page = max(1, int(parts[3]))
        except ValueError:
            page = 1

    await _send_users_page(callback, state, page=page)


async def admin_users_search_prompt(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await _replace_screen(callback, "Введите имя / телефон / telegram_id:")
    await state.set_state(AdminUsersState.search_query)
    await callback.answer()


async def admin_users_search_run(message: types.Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа")
        return
    query = (message.text or "").strip()
    rows = await transactions.search_client(query)
    if not rows and query.isdigit():
        profile = await transactions.get_student_profile(int(query))
        rows = [(profile,)] if profile else []

    if not rows:
        await message.answer("Ничего не найдено.", reply_markup=admin_dashboard_kb())
        await state.clear()
        return

    kb_rows = []
    for row in rows[:20]:
        p = row[0]
        if not p:
            continue
        kb_rows.append([types.InlineKeyboardButton(text=p.full_name or str(p.telegram_id), callback_data=f"admin:user:{p.telegram_id}:1")])
    kb_rows.append([types.InlineKeyboardButton(text="⬅️ В dashboard", callback_data="admin:menu")])
    await message.answer("Результаты поиска:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await state.clear()


async def admin_user_card(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    parts = callback.data.split(":")
    telegram_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 1
    profile = await transactions.get_student_profile(telegram_id)
    if not profile:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    rec_count = await transactions.count_date_rec(telegram_id)
    regular = await transactions.view_regular_lessons(telegram_id)
    regular_info = "—"
    if regular:
        regular_info = "; ".join(
            f"{(l.day_of_week if l.day_of_week is not None else '?')} {int(l.hour or 0):02d}:{int(l.minute or 0):02d}"
            for l in regular[:5]
        )
    text = (
        f"👤 {profile.full_name or 'Без имени'}\n"
        f"ID: {profile.telegram_id}\n"
        f"Телефон: {profile.telephone or '—'}\n"
        f"Username: @{profile.telegram_username or '—'}\n"
        f"Баланс: {profile.balance_lessons or 0}\n"
        f"Цена: {profile.price or 0}\n"
        f"Статус: {'Заблокирован' if profile.blocked else 'Активен'}\n"
        f"Записей: {rec_count[0] if rec_count else 0}\n"
        f"Регулярные: {regular_info}"
    )
    await _replace_screen(
        callback,
        text,
        user_card_actions_kb(profile.telegram_id, bool(profile.blocked), page),
    )
    await callback.answer()
    await state.clear()


async def admin_lessons_menu(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await _replace_screen(
        callback,
        "📚 Занятия\n\nВыберите клиента в разделе «Пользователи», затем используйте кнопки карточки клиента.",
        reply_markup=lessons_menu_kb(),
    )
    await callback.answer()
    await state.clear()


async def admin_schedule_menu(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await _replace_screen(callback, "🗓️ Расписание", schedule_menu_kb())
    await callback.answer()
    await state.clear()


async def admin_schedule_pick_day(callback: types.CallbackQuery, state: FSMContext) -> None:
    kb = await namespaced_month_calendar("schedule", datetime.date.today())
    await _replace_screen(callback, "Выберите день для просмотра расписания:", kb)
    await callback.answer()
    await state.clear()


async def admin_schedule_day(
    callback: types.CallbackQuery,
    state: FSMContext,
    day_override: datetime.date | None = None,
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    day = day_override
    if day is None:
        date_str = callback.data.split(":")[3]
        day = datetime.date.fromisoformat(date_str)
    items = await transactions.viewing_recordings_day_db(day, show_blocks=False)
    if not items:
        await _replace_screen(
            callback,
            f"🗓️ {day.isoformat()}\nЗаписей нет.",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ К расписанию", callback_data="admin:schedule:menu")]]),
        )
        await callback.answer()
        return

    lines = [f"🗓️ Расписание на {day.isoformat()}:"]
    for user in items:
        hh, mm = int(user[2]), int(user[3])
        lines.append(f"{hh:02d}:{mm:02d} • {user[0]} • {user[4]} • {user[6]} мин")
    await _replace_screen(
        callback,
        "\n".join(lines),
        types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="⬅️ К расписанию", callback_data="admin:schedule:menu")]
            ]
        ),
    )
    await callback.answer()
    await state.clear()


async def calendar_month_nav(callback: types.CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    # calendar:month:{prev|next}:{context}:{yyyy-mm}
    context = parts[3]
    y, m = parts[4].split("-")
    date_obj = datetime.date(int(y), int(m), 1)
    kb = await namespaced_month_calendar(context, date_obj)
    await _replace_screen(callback, "Выберите дату:", kb)
    await callback.answer()
    await state.clear()


async def calendar_day_nav(callback: types.CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    # calendar:day:{context}:{yyyy-mm-dd}
    context = parts[2]
    date_str = parts[3]
    date_obj = datetime.date.fromisoformat(date_str)

    if context == "schedule":
        await admin_schedule_day(callback, state, day_override=date_obj)
        return

    if context.startswith("addsingle-"):
        kb = await slot_picker(date_obj, context)
        await _replace_screen(callback, f"Дата: {date_obj.isoformat()}\nВыберите свободный слот:", kb)
        await callback.answer()
        await state.clear()
        return

    await callback.answer("Неизвестный контекст", show_alert=True)


async def slot_pick(callback: types.CallbackQuery, state: FSMContext) -> None:
    # slot:pick:{context}:{yyyy-mm-dd}:{HH}:{MM}
    parts = callback.data.split(":")
    context = parts[2]
    date_obj = datetime.date.fromisoformat(parts[3])
    hh = int(parts[4])
    mm = int(parts[5])

    if context.startswith("addsingle-"):
        telegram_id = int(context.split("-")[1])
        if await transactions.is_slot_busy(date_obj, hh, mm):
            await callback.answer("Слот уже занят", show_alert=True)
            return
        ok = await transactions.add_single_slot(
            telegram_id=telegram_id,
            date=date_obj,
            hour=hh,
            minute=mm,
        )
        if ok:
            await _replace_screen(
                callback,
                f"✅ Разовое занятие создано: {date_obj.isoformat()} {hh:02d}:{mm:02d}",
                reply_markup=types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [types.InlineKeyboardButton(text="👤 К карточке клиента", callback_data=f"admin:user:{telegram_id}:1")],
                        [types.InlineKeyboardButton(text="🏠 Dashboard", callback_data="admin:menu")],
                    ]
                ),
            )
        else:
            await _replace_screen(callback, "Не удалось создать запись. Попробуйте позже.")
        await callback.answer()
        await state.clear()
        return

    await callback.answer("Неизвестный контекст", show_alert=True)


async def admin_add_single_start(callback: types.CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    telegram_id = int(parts[-1])
    await _show_add_single_calendar(callback, telegram_id, state)


async def _show_add_single_calendar(callback: types.CallbackQuery, telegram_id: int, state: FSMContext) -> None:
    context = f"addsingle-{telegram_id}"
    kb = await namespaced_month_calendar(context, datetime.date.today())
    await _replace_screen(
        callback,
        "📚 Добавление разового занятия\n1) Выберите дату\n2) Выберите свободное время",
        reply_markup=kb,
    )
    await callback.answer()
    await state.clear()


async def admin_add_regular_start(callback: types.CallbackQuery, state: FSMContext) -> None:
    telegram_id = int(callback.data.split(":")[-1])
    await _replace_screen(
        callback,
        "🔁 Регулярное занятие\nВыберите день недели:",
        regular_weekday_kb(telegram_id),
    )
    await callback.answer()
    await state.clear()


async def admin_add_regular_day(callback: types.CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    telegram_id = int(parts[3])
    day_of_week = int(parts[4])
    await _replace_screen(
        callback,
        f"Выбран день: {day_of_week}. Выберите время:",
        reply_markup=regular_time_kb(telegram_id, day_of_week),
    )
    await callback.answer()
    await state.clear()


async def admin_add_regular_time(callback: types.CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    telegram_id = int(parts[3])
    day_of_week = int(parts[4])
    hh = int(parts[5])
    mm = int(parts[6])
    await _replace_screen(
        callback,
        f"Выбрано время: {hh:02d}:{mm:02d}\nВыберите длительность:",
        reply_markup=regular_duration_kb(telegram_id, day_of_week, hh, mm),
    )
    await callback.answer()
    await state.clear()


async def admin_add_regular_save(callback: types.CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    telegram_id = int(parts[3])
    day_of_week = int(parts[4])
    hh = int(parts[5])
    mm = int(parts[6])
    duration = int(parts[7])
    await transactions.add_regular_slot(
        telegram_id=telegram_id,
        day_of_week=day_of_week,
        hour=hh,
        minute=mm,
        duration_minutes=duration,
    )
    await _replace_screen(
        callback,
        f"✅ Регулярное занятие добавлено: день {day_of_week}, {hh:02d}:{mm:02d}, {duration} мин",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="👤 К карточке клиента", callback_data=f"admin:user:{telegram_id}:1")],
                [types.InlineKeyboardButton(text="🏠 Dashboard", callback_data="admin:menu")],
            ]
        ),
    )
    await callback.answer()
    await state.clear()

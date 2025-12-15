"""Модуль вывода всех пользователей."""
from aiogram import types
from aiogram.fsm.context import FSMContext

from database import transactions
from keyboards.inline.back_admin_menu import back_admin_menu_button
from keyboards.inline.detail_client import details_client_buttons


async def view_clients(
    message: [types.CallbackQuery, types.Message], state: FSMContext
) -> None:
    """
    Функция view_clients. Коллбэк с датой view_clients запускает данную функцию.
    Вывод всех пользователей.
    """
    lst_clients = await transactions.view_clients()

    if lst_clients:
        for client in lst_clients:
            profile = client[0]
            count_date_rec = await transactions.count_date_rec(profile.telegram_id)
            last_visit = profile.last_visit_date or ""
            try:
                last_visit_date = last_visit.split("T")[0] if "T" in last_visit else last_visit.split()[0]
                y, m, d = last_visit_date.split("-")
                last_visit_date = f"{d}-{m}-{y}"
            except Exception:
                last_visit_date = "неизвестно"

            kb = details_client_buttons(profile.telegram_id, profile.blocked)
            await message.message.answer(
                f"""Полное имя: {profile.full_name or "не указано"}
            Телефон: {profile.telephone if profile.telephone else "нет телефона"}
            Статус: {"заблокирован" if profile.blocked else "разблокирован"}
            Количество записей: {count_date_rec[0]}
            Последний вход: {last_visit_date}
        """,
                reply_markup=kb,
            )
    else:
        await message.message.answer("Пока что нет ни одного клиента")

    kb = back_admin_menu_button()
    await message.message.answer("Вернуться в админ в меню?", reply_markup=kb)
    await state.clear()

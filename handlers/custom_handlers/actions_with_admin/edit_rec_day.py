"""Модуль изменения записи на конкретный день."""
import datetime
import logging

from aiogram import types
from aiogram.fsm.context import FSMContext

from database import transactions
from keyboards.inline.back_admin_menu import back_admin_menu_button
from states.states import AdminEditOccurrenceState

logger = logging.getLogger(__name__)


async def edit_record_day_1(callback: types.CallbackQuery, state: FSMContext) -> None:
    """
    Старт изменения записи (коллбэк rec_edit=YYYY-MM-DD=HH_MM=TGID).
    """
    data_split = callback.data.split("=")
    if len(data_split) < 4:
        await callback.answer()
        await callback.message.answer("Не удалось определить запись.")
        return

    try:
        date = datetime.datetime.strptime(data_split[1], "%Y-%m-%d").date()
        time_parts = data_split[2].split("_")
        hour = int(time_parts[0])
        minute = int(time_parts[1]) if len(time_parts) > 1 else 0
        telegram_id = int(data_split[3])
    except (ValueError, TypeError):
        await callback.answer()
        await callback.message.answer("Не удалось определить запись.")
        return

    await state.update_data(
        edit_date=date,
        edit_hour=hour,
        edit_minute=minute,
        edit_telegram_id=telegram_id,
    )
    await state.set_state(AdminEditOccurrenceState.new_date)
    await callback.answer()
    await callback.message.answer(
        "Введите новую дату занятия (ГГГГ-ММ-ДД) или \"х\", чтобы оставить прежнюю."
    )


async def edit_record_day_2(message: types.Message, state: FSMContext) -> None:
    """Принимает новую дату."""
    text = (message.text or "").strip().lower()
    data = await state.get_data()
    old_date = data.get("edit_date")
    if not old_date:
        await message.answer("Не удалось определить запись.")
        await state.clear()
        return

    if text in ("х", "x", ""):
        new_date = old_date
    else:
        try:
            new_date = datetime.datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            await message.answer("Неверный формат даты. Используйте ГГГГ-ММ-ДД.")
            return

    await state.update_data(edit_new_date=new_date)
    await state.set_state(AdminEditOccurrenceState.new_time)
    await message.answer("Введите новое время занятия (ЧЧ:ММ) или \"х\", чтобы оставить прежнее.")


async def edit_record_day_3(message: types.Message, state: FSMContext) -> None:
    """Принимает новое время и спрашивает длительность."""
    text = (message.text or "").strip().lower()
    data = await state.get_data()

    old_date = data.get("edit_date")
    old_hour = data.get("edit_hour")
    old_minute = data.get("edit_minute")
    new_date = data.get("edit_new_date", old_date)

    if old_date is None or old_hour is None or old_minute is None:
        await message.answer("Не удалось определить запись.")
        await state.clear()
        return

    if text in ("х", "x", ""):
        new_hour, new_minute = old_hour, old_minute
    else:
        try:
            new_hour, new_minute = map(int, text.split(":"))
        except ValueError:
            await message.answer("Неверный формат времени. Используйте ЧЧ:ММ.")
            return

    await state.update_data(edit_new_hour=new_hour, edit_new_minute=new_minute)
    await state.set_state(AdminEditOccurrenceState.new_duration)
    await message.answer("Введите длительность занятия в минутах или \"х\", чтобы оставить прежнюю.")


async def edit_record_day_4(message: types.Message, state: FSMContext) -> None:
    """Принимает длительность и переносит запись."""
    text = (message.text or "").strip().lower()
    data = await state.get_data()

    old_date = data.get("edit_date")
    old_hour = data.get("edit_hour")
    old_minute = data.get("edit_minute")
    telegram_id = data.get("edit_telegram_id")
    new_date = data.get("edit_new_date", old_date)
    new_hour = data.get("edit_new_hour", old_hour)
    new_minute = data.get("edit_new_minute", old_minute)

    if old_date is None or old_hour is None or old_minute is None or telegram_id is None:
        await message.answer("Не удалось определить запись.")
        await state.clear()
        return

    if (new_date, new_hour, new_minute) != (old_date, old_hour, old_minute):
        slot = await transactions.get_info_user(new_date, new_hour, new_minute)
        if slot:
            await message.answer("Этот слот уже занят. Выберите другое время.")
            await state.clear()
            return

    new_duration = None
    if text not in ("х", "x", ""):
        try:
            new_duration = int(text)
        except ValueError:
            await message.answer("Неверная длительность. Введите число минут.")
            return

    slot_info = await transactions.get_record_slot_info(
        telegram_id, old_date, old_hour, old_minute
    )
    if not slot_info:
        await message.answer("Запись не найдена.")
        await state.clear()
        return

    kind, duration = slot_info
    if new_duration:
        duration = new_duration
    ok = False
    try:
        if kind == "regular":
            await transactions.cancel_regular_slot_with_allow(
                old_date, old_hour, old_minute, note="Перенос занятия"
            )
            ok = await transactions.add_single_slot(
                telegram_id,
                new_date,
                new_hour,
                new_minute,
                duration_minutes=duration,
            )
        else:
            ok = await transactions.reschedule_single_slot(
                telegram_id,
                old_date,
                old_hour,
                old_minute,
                new_date,
                new_hour,
                new_minute,
                duration_minutes=duration,
            )
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Ошибка переноса записи: %s", exc)
        ok = False

    await state.clear()
    kb = back_admin_menu_button()
    if ok:
        await message.answer(
            f"Запись перенесена на {new_date.strftime('%Y-%m-%d')} {new_hour:02d}:{new_minute:02d}.",
            reply_markup=kb,
        )
    else:
        await message.answer("Не удалось перенести запись, попробуйте позже.", reply_markup=kb)

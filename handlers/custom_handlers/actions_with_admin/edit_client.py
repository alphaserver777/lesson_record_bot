"""Редактирование данных студента администратором."""
import datetime
import logging

from aiogram import types
from aiogram.fsm.context import FSMContext

from database import transactions
from database.models import RecordDate
from database.connect import session
from keyboards.inline.back_admin_menu import back_admin_menu_button
from utils.google_calendar import create_block_event
from utils.schedule import SLOT_DURATION_MINUTES
from states.states import (
    AdminEditState,
    AdminAddSingleState,
    AdminAddRegularState,
    AdminCancelState,
)

logger = logging.getLogger(__name__)


async def edit_client_menu(callback: types.CallbackQuery, state: FSMContext):
    telegram_id = int(callback.data.split("=")[1])
    await state.update_data(edit_telegram_id=telegram_id)
    kb = back_admin_menu_button()
    text = (
        "Что изменить?\n"
        "1) Цена за занятие — отправьте число.\n"
        "2) Баланс занятий — отправьте целое число (установить).\n\n"
        "Выберите действие:"
    )
    await callback.message.answer(
        text,
        reply_markup=kb
    )
    await callback.message.answer(
        "Изменить цену?", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Изменить цену", callback_data=f"edit_price={telegram_id}")],
            [types.InlineKeyboardButton(text="Изменить баланс", callback_data=f"edit_balance={telegram_id}")],
            [types.InlineKeyboardButton(text="Добавить разовое занятие", callback_data=f"add_single={telegram_id}")],
        ])
    )
    await callback.answer()


async def edit_price_start(callback: types.CallbackQuery, state: FSMContext):
    telegram_id = int(callback.data.split("=")[1])
    await state.update_data(edit_telegram_id=telegram_id)
    await callback.message.answer("Введите новую цену за занятие (число):")
    await state.set_state(AdminEditState.edit_price)
    await callback.answer()


async def edit_price_set(message: types.Message, state: FSMContext):
    try:
        price = int(message.text.strip())
        if price < 0:
            raise ValueError
    except Exception:
        await message.answer("Нужно число (>=0). Попробуйте ещё раз.")
        return
    data = await state.get_data()
    telegram_id = data.get("edit_telegram_id")
    await transactions.upsert_student_profile(telegram_id=telegram_id, price=price)
    await message.answer(f"Цена обновлена: {price} ₽")
    await state.clear()


async def edit_balance_start(callback: types.CallbackQuery, state: FSMContext):
    telegram_id = int(callback.data.split("=")[1])
    await state.update_data(edit_telegram_id=telegram_id)
    await callback.message.answer("Введите новый баланс уроков (целое число):")
    await state.set_state(AdminEditState.edit_balance)
    await callback.answer()


async def edit_balance_set(message: types.Message, state: FSMContext):
    try:
        balance = int(message.text.strip())
    except Exception:
        await message.answer("Нужно целое число. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    telegram_id = data.get("edit_telegram_id")
    await transactions.set_balance(telegram_id, balance)
    await message.answer(f"Баланс обновлён: {balance}")
    await state.clear()


async def add_single_start(callback: types.CallbackQuery, state: FSMContext):
    telegram_id = int(callback.data.split("=")[1])
    await state.update_data(edit_telegram_id=telegram_id)
    await callback.message.answer("Введите дату занятия в формате ГГГГ-ММ-ДД:")
    await state.set_state(AdminAddSingleState.date)
    await callback.answer()


async def add_single_date(message: types.Message, state: FSMContext):
    try:
        date = datetime.datetime.strptime(message.text.strip(), "%Y-%m-%d").date()
    except Exception:
        await message.answer("Неверный формат. Введите дату как ГГГГ-ММ-ДД.")
        return
    await state.update_data(single_date=date)
    await message.answer("Введите время занятия в формате ЧЧ:ММ (24-часовой формат):")
    await state.set_state(AdminAddSingleState.time)


async def add_single_time(message: types.Message, state: FSMContext):
    try:
        time = datetime.datetime.strptime(message.text.strip(), "%H:%M").time()
    except Exception:
        await message.answer("Неверный формат. Введите время как ЧЧ:ММ.")
        return
    data = await state.get_data()
    telegram_id = data.get("edit_telegram_id")
    date = data.get("single_date")
    if not date or telegram_id is None:
        logger.warning("Нет данных состояния для добавления занятия: date=%s, telegram_id=%s", date, telegram_id)
        await message.answer("Не хватает данных для записи. Начните добавление заново.")
        await state.clear()
        return
    try:
        ok = await transactions.add_single_slot(
            telegram_id=telegram_id,
            date=date,
            hour=time.hour,
            minute=time.minute,
            duration_minutes=60,
            summary="Запись (админ)",
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Ошибка при добавлении разового занятия: %s", exc)
        await message.answer("Не удалось добавить запись. Попробуйте позже.")
        await state.clear()
        return
    if ok:
        await message.answer(f"Запись добавлена: {date} {time.strftime('%H:%M')}")
    else:
        await message.answer("Не удалось добавить запись. Попробуйте позже.")
    await state.clear()


# --- Регулярные занятия ---
def _parse_day_of_week(text: str) -> int | None:
    mapping = {
        "пн": 0, "понедельник": 0,
        "вт": 1, "вторник": 1,
        "ср": 2, "среда": 2,
        "чт": 3, "четверг": 3,
        "пт": 4, "пятница": 4,
        "сб": 5, "суббота": 5,
        "вс": 6, "воскресенье": 6,
    }
    try:
        if text.isdigit():
            val = int(text)
            if 0 <= val <= 6:
                return val
        return mapping.get(text.lower())
    except Exception:
        return None


async def add_regular_start(callback: types.CallbackQuery, state: FSMContext):
    telegram_id = int(callback.data.split("=")[1])
    await state.update_data(edit_telegram_id=telegram_id)
    await callback.message.answer("Введите день недели (0-6 или Пн/Вт/...):")
    await state.set_state(AdminAddRegularState.day)
    await callback.answer()


async def add_regular_day(message: types.Message, state: FSMContext):
    day = _parse_day_of_week(message.text.strip())
    if day is None:
        await message.answer("Неверный день. Введите 0-6 или Пн/Вт/Ср/Чт/Пт/Сб/Вс.")
        return
    await state.update_data(regular_day=day)
    await message.answer("Введите время занятия (ЧЧ:ММ):")
    await state.set_state(AdminAddRegularState.time)


async def add_regular_time(message: types.Message, state: FSMContext):
    try:
        time = datetime.datetime.strptime(message.text.strip(), "%H:%M").time()
    except Exception:
        await message.answer("Неверный формат. Введите время как ЧЧ:ММ.")
        return
    await state.update_data(regular_time=time)
    await message.answer("Введите длительность в минутах (по умолчанию 60):")
    await state.set_state(AdminAddRegularState.duration)


async def add_regular_duration(message: types.Message, state: FSMContext):
    try:
        duration = int(message.text.strip())
        if duration <= 0:
            raise ValueError
    except Exception:
        await message.answer("Нужно положительное число минут.")
        return
    data = await state.get_data()
    telegram_id = data.get("edit_telegram_id")
    day = data.get("regular_day")
    time = data.get("regular_time")
    await transactions.add_regular_slot(
        telegram_id=telegram_id,
        day_of_week=day,
        hour=time.hour,
        minute=time.minute,
        duration_minutes=duration,
        full_name="Регулярное занятие",
    )
    await message.answer(f"Регулярное занятие добавлено: день {day}, {time.strftime('%H:%M')} ({duration} мин).")
    await state.clear()


# --- Отмена занятий ---
async def cancel_lesson_start(callback: types.CallbackQuery, state: FSMContext):
    telegram_id = int(callback.data.split("=")[1])
    await state.update_data(edit_telegram_id=telegram_id)
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Отменить разовое (дата)", callback_data="cancel_single_date")],
        [types.InlineKeyboardButton(text="Отменить одно занятие из регулярных", callback_data="cancel_regular_once")],
        [types.InlineKeyboardButton(text="Отменить регулярное полностью", callback_data="cancel_regular_all")],
    ])
    await callback.message.answer("Что отменить?", reply_markup=kb)
    await callback.answer()


async def cancel_single_date(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(cancel_mode="single")
    await callback.message.answer("Введите дату отменяемого занятия (ГГГГ-ММ-ДД):")
    await state.set_state(AdminCancelState.date)
    await callback.answer()


async def cancel_regular_once(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(cancel_mode="once")
    await callback.message.answer("Введите дату отмены одного занятия (ГГГГ-ММ-ДД):")
    await state.set_state(AdminCancelState.date)
    await callback.answer()


async def cancel_regular_all(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(cancel_mode="all")
    await callback.message.answer("Введите день регулярного занятия (0-6 или Пн/Вт/...):")
    await state.set_state(AdminCancelState.mode)
    await callback.answer()


async def cancel_date_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    mode = data.get("cancel_mode")
    if mode in ("single", "once"):
        try:
            date = datetime.datetime.strptime(message.text.strip(), "%Y-%m-%d").date()
        except Exception:
            await message.answer("Неверный формат даты. ГГГГ-ММ-ДД.")
            return
        await state.update_data(cancel_date=date)
        await message.answer("Введите время занятия (ЧЧ:ММ):")
        await state.set_state(AdminCancelState.time)
    else:
        await message.answer("Сначала выберите тип отмены.")


async def cancel_day_input(message: types.Message, state: FSMContext):
    day = _parse_day_of_week(message.text.strip())
    if day is None:
        await message.answer("Неверный день. Введите 0-6 или Пн/Вт/Ср/Чт/Пт/Сб/Вс.")
        return
    await state.update_data(cancel_day=day)
    await message.answer("Введите время занятия (ЧЧ:ММ) для отмены регулярки:")
    await state.set_state(AdminCancelState.time)


async def cancel_time_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    mode = data.get("cancel_mode")
    try:
        time = datetime.datetime.strptime(message.text.strip(), "%H:%M").time()
    except Exception:
        await message.answer("Неверный формат времени. ЧЧ:ММ.")
        return

    telegram_id = data.get("edit_telegram_id")
    if mode == "single":
        date = data.get("cancel_date")
        await transactions.delete_single_slot(telegram_id, date, time.hour, time.minute)
        await message.answer(f"Занятие {date} {time.strftime('%H:%M')} удалено.")
    elif mode == "once":
        date = data.get("cancel_date")
        await transactions.delete_single_slot(telegram_id, date, time.hour, time.minute)
        try:
            event_id = await create_block_event(date, time.hour, time.minute, SLOT_DURATION_MINUTES)
        except Exception:
            event_id = None
        rec = RecordDate(
            telegram_id=None,
            record_date=date,
            hour=time.hour,
            minute=time.minute,
            duration_minutes=SLOT_DURATION_MINUTES,
            event_id=event_id,
        )
        session.add(rec)
        await session.commit()
        await message.answer(f"Занятие {date} {time.strftime('%H:%M')} отменено разово.")
    elif mode == "all":
        cancel_day = data.get("cancel_day")
        await transactions.delete_regular_slot(
            telegram_id=telegram_id,
            day_of_week=cancel_day,
            hour=time.hour,
            minute=time.minute,
            delete_future_single=True,
        )
        await message.answer(f"Регулярные занятия (день {cancel_day}, {time.strftime('%H:%M')}) отменены полностью.")
    else:
        await message.answer("Сначала выберите тип отмены.")
    await state.clear()

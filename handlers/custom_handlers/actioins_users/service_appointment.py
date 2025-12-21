"""Модуль записи клиента"""
import datetime

from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove

from config_data import config
from config_data.config import ADMINS_TELEGRAM_ID
from database import transactions
from handlers.default_heandlers.start import start_command
from keyboards.reply.list_button import list_button
from keyboards.inline.approve_decline import approve_decline_kb
from loader import bot
from states.states import ServiceDateState
from utils.google_calendar import GoogleCalendarError, get_busy_intervals, get_calendar_tz
from utils.schedule import SLOT_DURATION_MINUTES, format_slot, slots_for_date
from aiogram.exceptions import TelegramBadRequest
import logging
from types import SimpleNamespace

logger = logging.getLogger(__name__)

BEGINNING_WORKING_DAY = config.BEGINNING_WORKING_DAY
END_WORKING_DAY = config.END_WORKING_DAY


async def service_appointment_1(message: types.Message, state: FSMContext):
    """Функция service_appointment_1. Выводит свободное время на день."""
    selected_date = datetime.datetime.strptime(
        message.data.split("_")[2], "%Y-%m-%d"
    )
    selected_date = selected_date.date()
    telegram_id = message.from_user.id

    await message.message.answer(
        f"Выбрана дата: {selected_date.day}-{selected_date.month}-{selected_date.year}"
    )

    try:
        busy_intervals = await get_busy_intervals(selected_date)
    except GoogleCalendarError as err:
        await message.message.answer(
            "Не удалось загрузить занятые слоты из календаря, попробуйте позже."
        )
        await state.clear()
        await start_command(message, state)
        return

    region_time = datetime.datetime.now(get_calendar_tz()).replace(tzinfo=None)
    available_slots = slots_for_date(selected_date, region_time)

    def _is_busy(slot_hour: int, slot_minute: int) -> bool:
        slot_start = datetime.datetime.combine(
            selected_date, datetime.time(slot_hour, slot_minute), tzinfo=get_calendar_tz()
        )
        slot_end = slot_start + datetime.timedelta(minutes=SLOT_DURATION_MINUTES)
        for start, end in busy_intervals:
            if slot_start < end and slot_end > start:
                return True
        return False

    working_slots = [
        [f"{h}:{m:02d}", -1] if _is_busy(h, m) else [f"{h}:{m:02d}", f"{h}:{m:02d}"]
        for h, m in available_slots
    ]

    working_slots.append([0, "Выбрать другую дату"])
    kb = list_button(working_slots)
    await message.message.answer("Выберите свободное время:", reply_markup=kb)

    await state.update_data(
        {
        "telegram_id": telegram_id,
        "firts_name": message.from_user.first_name,
        "last_name": message.from_user.last_name,
        "username": message.from_user.username,
        "selected_date": selected_date,
        "working_slots": working_slots
        }
    )

    await state.set_state(ServiceDateState.service_time)


async def service_appointment_2(
    message: [types.CallbackQuery, types.Message], state: FSMContext
):
    """Функция service_appointment_2. Проверяет введено ли правильно время."""
    flag = False
    try:
        input_text = message.text
        if "Выбрать" in input_text:
            await state.clear()
            await start_command(message, state)
        else:
            context_data = await state.get_data()
            for i in context_data.get("working_slots"):
                if i[1] == input_text:
                    flag = True

            if flag:
                hour, minute = input_text.split(":")
                await state.update_data(
                    {
                        "selected_hour": int(hour),
                        "selected_minute": int(minute),
                    }
                )

                confirm_buttons = list_button([(0, "Подтвердить"), (0, "Отменить"), (0, "Выбрать другую дату")])
                await message.answer(
                    f"Вы выбрали {input_text}. Подтвердить запись?",
                    reply_markup=confirm_buttons,
                )
                await state.set_state(ServiceDateState.service_confirm_time)

            else:
                await message.answer("Это время уже занято. Выберите свободное время из списка.")

    except ValueError:
        await message.answer("Выберите свободное время из списка.")


async def _finalize_booking(message: types.Message, state: FSMContext, contact_info: dict):
    """Общий код создания записи и уведомлений."""
    context_data = await state.get_data()
    selected_date = context_data.get("selected_date")
    selected_hour = context_data.get("selected_hour")
    selected_minute = context_data.get("selected_minute")
    username = context_data.get("username")

    try:
        slot_busy = await transactions.is_slot_busy(selected_date, selected_hour, selected_minute)
    except GoogleCalendarError:
        await message.answer(
            "Не удалось проверить свободное время в календаре, попробуйте позже.",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.clear()
        await start_command(message, state)
        return

    if not slot_busy and selected_date >= datetime.datetime.now().date():
        created = await transactions.set_date_time_appointment(
            contact_info, selected_date, selected_hour, selected_minute
        )
        if not created:
            await message.answer(
                "Не получилось создать запись в календаре, попробуйте ещё раз.",
                reply_markup=ReplyKeyboardRemove(),
            )
            await state.clear()
            await start_command(message, state)
            return

        sending_text = f"""Новая запись!!!
    Имя: {contact_info.get('last_name','')} {contact_info.get('first_name','')}
    На {selected_date.day}-{selected_date.month}-{selected_date.year} в {format_slot(selected_hour, selected_minute)}.
    Номер телефона: {contact_info.get('phone_number')}
    Профиль: <a href="tg://user?id={contact_info.get('user_id')}">{'@'+username if username else 'написать'}</a>
        """

        admin_kb = approve_decline_kb(
            user_id=contact_info.get("user_id"),
            date=selected_date,
            hour=selected_hour,
            minute=selected_minute
        )
        for admin_telegram_id in ADMINS_TELEGRAM_ID:
            try:
                await bot.send_message(
                    chat_id=admin_telegram_id,
                    text=sending_text,
                    parse_mode="HTML",
                    reply_markup=admin_kb
                )
            except TelegramBadRequest as exc:
                logger.warning("Не удалось отправить уведомление админу %s: %s", admin_telegram_id, exc)

        await message.answer(
            f"""Вы записаны на {selected_date.day}-{selected_date.month}-{selected_date.year} в {format_slot(selected_hour, selected_minute)}.
    Ваш номер {contact_info.get('phone_number')} получен.
    Преподаватель увидел Вашу запись, ожидайте подтверждение записи.
    Спасибо!
            """,
            reply_markup=ReplyKeyboardRemove(),
        )
        await message.answer("Запись отправлена на согласование", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer(
            "Что-то пошло не так, Попробуйте ещё раз.",
            reply_markup=ReplyKeyboardRemove(),
        )

    await state.clear()
    await start_command(message, state)


async def service_appointment_3(message: types.Message, state: FSMContext):
    """
    Функция service_appointment_3. Обрабатывает контакт и завершает запись.
    """
    contact = message.contact
    contact_info = {
        "phone_number": contact.phone_number,
        "user_id": contact.user_id,
        "first_name": contact.first_name or message.from_user.first_name,
        "last_name": contact.last_name or message.from_user.last_name,
    }
    await _finalize_booking(message, state, contact_info)


async def service_appointment_confirm(message: types.Message, state: FSMContext):
    """
    Подтверждение/отмена выбранного времени без запроса контакта.
    """
    text = (message.text or "").lower()
    if "отмен" in text or "друг" in text or "верн" in text:
        await state.clear()
        await start_command(message, state)
        return
    if "подтверд" not in text:
        await message.answer("Выберите Подтвердить или Отменить.")
        return

    context_data = await state.get_data()
    telegram_id = context_data.get("telegram_id")
    profile = await transactions.get_student_profile(telegram_id)
    if not profile or not profile.telephone:
        # нет телефона — попросим контакт как запасной путь
        kb = await contact_button()
        await message.answer("Отправьте контакт через кнопку ниже, чтобы завершить запись.", reply_markup=kb)
        await state.set_state(ServiceDateState.service_cancel)
        return

    full_name = profile.full_name or ""
    if " " in full_name:
        last_name, first_name = full_name.split(" ", 1)
    else:
        last_name, first_name = full_name, ""

    contact_info = {
        "phone_number": profile.telephone,
        "user_id": telegram_id,
        "first_name": first_name,
        "last_name": last_name,
    }
    await _finalize_booking(message, state, contact_info)

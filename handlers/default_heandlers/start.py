"""Start handler in minimal bot mode (Mini App entrypoint)."""
import logging

from aiogram import types
from aiogram.fsm.context import FSMContext

from config_data.config import MINI_APP_URL
from database import transactions
from keyboards.inline.miniapp import open_miniapp_kb

start_logger = logging.getLogger(__name__)


async def start_command(message: [types.CallbackQuery, types.Message], state: FSMContext = None) -> None:
    """Send Mini App entrypoint and keep bot focused on presence notifications only."""
    telegram_id = message.from_user.id
    full_name = message.from_user.full_name

    await transactions.upsert_student_profile(
        telegram_id=telegram_id,
        full_name=full_name,
        username=message.from_user.username,
    )
    await transactions.update_visit_date(telegram_id)

    text = (
        "<b>Бот работает в режиме уведомлений.</b>\n"
        "Запись, расписание и админ-управление теперь в Mini App."
    )

    kb = open_miniapp_kb(MINI_APP_URL)

    if isinstance(message, types.Message):
        await message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        await message.message.answer(text, parse_mode="HTML", reply_markup=kb)
        await message.answer()

    if state:
        await state.clear()

    start_logger.info("start_logger-UserID=%s %s", telegram_id, full_name)

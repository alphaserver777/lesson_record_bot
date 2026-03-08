"""Start handler in minimal bot mode (Mini App entrypoint)."""
import logging

from aiogram import exceptions, types
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove

from config_data.config import MINI_APP_URL
from database import transactions
from keyboards.inline.miniapp import open_miniapp_kb

start_logger = logging.getLogger(__name__)


async def start_command(message: [types.CallbackQuery, types.Message], state: FSMContext = None) -> None:
    """Send Mini App entrypoint and keep bot focused on presence notifications only."""
    telegram_id = message.from_user.id
    full_name = message.from_user.full_name
    first_name = getattr(message.from_user, "first_name", None)
    last_name = getattr(message.from_user, "last_name", None)
    username = getattr(message.from_user, "username", None)
    chat = message.message.chat if isinstance(message, types.CallbackQuery) else message.chat
    bot = message.message.bot if isinstance(message, types.CallbackQuery) else message.bot

    await transactions.upsert_student_profile(
        telegram_id=telegram_id,
        full_name=full_name,
        first_name=first_name,
        last_name=last_name,
        username=username,
    )
    await transactions.update_visit_date(telegram_id)

    text = (
        "<b>Бот работает в режиме уведомлений.</b>\n"
        "Запись, расписание и админ-управление теперь в Mini App."
    )

    kb = open_miniapp_kb(MINI_APP_URL)
    entry_chat_id, entry_message_id = await transactions.get_miniapp_entry_message(telegram_id)
    active_message_id = entry_message_id if entry_chat_id == chat.id else None

    if active_message_id:
        try:
            await bot.edit_message_text(
                chat_id=chat.id,
                message_id=active_message_id,
                text=text,
                parse_mode="HTML",
                reply_markup=kb,
            )
        except Exception:  # pylint: disable=broad-except
            await transactions.set_miniapp_entry_message(telegram_id, None, None)
            active_message_id = None

    if active_message_id is None:
        target = message.message if isinstance(message, types.CallbackQuery) else message
        sent_message = await target.answer(
            text,
            parse_mode="HTML",
            reply_markup=kb,
        )
        active_message_id = sent_message.message_id
        await transactions.set_miniapp_entry_message(telegram_id, chat.id, sent_message.message_id)
        # Снимаем legacy reply keyboard вроде "Админ меню" без отдельного видимого системного сообщения.
        try:
            cleanup_msg = await bot.send_message(chat.id, "\u2060", reply_markup=ReplyKeyboardRemove())
            await bot.delete_message(chat.id, cleanup_msg.message_id)
        except Exception:  # pylint: disable=broad-except
            pass

    try:
        await bot.pin_chat_message(chat_id=chat.id, message_id=active_message_id, disable_notification=True)
    except exceptions.TelegramBadRequest:
        pass
    except Exception:  # pylint: disable=broad-except
        pass

    if isinstance(message, types.CallbackQuery):
        await message.answer("Mini App закреплён в чате")

    if state:
        await state.clear()

    start_logger.info("start_logger-UserID=%s %s", telegram_id, full_name)

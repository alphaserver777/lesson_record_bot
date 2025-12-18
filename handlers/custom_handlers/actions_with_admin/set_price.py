"""Получение стоимости занятия от администратора."""
import re
from aiogram import types

from config_data.config import ADMINS_TELEGRAM_ID
from database import transactions


PRICE_TOKEN_RE = re.compile(r"\[price:(\d+)\]")


async def request_price_for_student(full_name: str, telegram_id: int, username: str | None) -> list[types.Message]:
    """
    Отправляет админам запрос ввести стоимость часа для студента.
    Возвращает список отправленных сообщений (может пригодиться для логов/тестов).
    """
    from loader import bot  # локальный импорт, чтобы избегать циклов

    results = []
    username_part = f"@{username}" if username else "нет username"
    text = (
        f"Новый студент зарегистрировался:\n"
        f"{full_name} ({username_part}, id {telegram_id}).\n\n"
        "Ответьте на это сообщение числом — стоимость часа (в рублях).\n"
        f"[price:{telegram_id}]"
    )
    for admin_id in ADMINS_TELEGRAM_ID:
        try:
            msg = await bot.send_message(admin_id, text, reply_markup=types.ForceReply(selective=True))
            results.append(msg)
        except Exception:
            # Если не удалось отправить админу, продолжаем к следующему
            continue
    return results


async def handle_price_reply(message: types.Message):
    """
    Обрабатывает ответ администратора на запрос стоимости.
    Ожидает ответ на сообщение с маркером [price:<id>].
    """
    # Проверяем, что пишет админ
    if message.from_user.id not in ADMINS_TELEGRAM_ID:
        return

    reply = message.reply_to_message
    if not reply or not reply.text:
        return

    match = PRICE_TOKEN_RE.search(reply.text)
    if not match:
        return

    student_id = int(match.group(1))
    # Парсим число
    try:
        price = int(message.text.strip())
        if price <= 0:
            raise ValueError
    except Exception:
        await message.answer("Введите стоимость числом (положительное значение).")
        return

    await transactions.upsert_student_profile(telegram_id=student_id, price=price)
    await message.answer(f"Цена для студента {student_id} сохранена: {price} ₽")

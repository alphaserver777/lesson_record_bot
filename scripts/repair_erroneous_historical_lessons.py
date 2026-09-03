"""Отчёт и безопасная очистка строк, ошибочно созданных из истории оплат.

Сначала запустите без --apply и проверьте список. Перед --apply обязателен
свежий PostgreSQL dump. Удаление сохраняет оплаты: внешний ключ lesson_id
имеет правило ON DELETE SET NULL.
"""
import argparse
import asyncio
import datetime

from sqlalchemy import delete, select

from database.connect import engine, remove_session, session
from database.models import RecordDate


NOTE = "Восстановлено из истории оплат"


async def main(apply: bool) -> int:
    if engine.dialect.name != "postgresql":
        raise RuntimeError("скрипт допускается запускать только с PostgreSQL")

    statement = (
        select(RecordDate)
        .where(
            RecordDate.note == NOTE,
            RecordDate.record_date < datetime.date.today(),
        )
        .order_by(RecordDate.record_date, RecordDate.hour, RecordDate.minute, RecordDate.id)
    )
    rows = (await session.execute(statement)).scalars().all()
    for row in rows:
        print(f"{row.id}: {row.record_date} {int(row.hour):02d}:{int(row.minute):02d} telegram_id={row.telegram_id} kind={row.kind}")
    print(f"Найдено ошибочно восстановленных прошлых занятий: {len(rows)}")

    if not apply:
        print("Режим отчёта: данные не изменены. Для удаления после backup: --apply")
        return len(rows)

    if rows:
        await session.execute(
            delete(RecordDate).where(RecordDate.id.in_([int(row.id) for row in rows]))
        )
        await session.commit()
    print(f"Удалено: {len(rows)}. Связанные оплаты сохранены с пустым lesson_id.")
    return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="удалить строки после проверки отчёта и резервной копии")
    args = parser.parse_args()
    async def run() -> int:
        try:
            return await main(args.apply)
        finally:
            await remove_session()

    asyncio.run(run())

import datetime
import os
import tempfile
import unittest


_db_file = tempfile.NamedTemporaryFile(prefix="lesson-payment-", suffix=".db", delete=False)
_db_file.close()
os.environ["DB_PATH"] = _db_file.name
os.environ.pop("DATABASE_URL", None)

from sqlalchemy import delete, func, select  # noqa: E402

from database import transactions  # noqa: E402
from database.connect import remove_session, session  # noqa: E402
from database.models import (  # noqa: E402
    AnalyticsEvent,
    Contact,
    Payment,
    RecordDate,
    RegularLesson,
    StudentProfile,
    TelegramIdentity,
)


class CanonicalLessonPaymentTest(unittest.IsolatedAsyncioTestCase):
    telegram_id = 900000001

    async def asyncSetUp(self) -> None:
        await transactions.init_db()
        for model in (AnalyticsEvent, Payment, RecordDate, RegularLesson, TelegramIdentity, StudentProfile, Contact):
            await session.execute(delete(model))
        await session.commit()
        session.add(
            StudentProfile(
                telegram_id=self.telegram_id,
                full_name="Тест Ученик",
                price=2000,
                balance_lessons=0,
            )
        )
        await session.commit()

    async def test_completed_profile_is_idempotently_linked_to_crm_contact(self) -> None:
        profile = await session.get(StudentProfile, self.telegram_id)
        profile.first_name = "Максим"
        profile.last_name = "Филиппов"
        profile.telephone = "89267557900"
        profile.telegram_username = "Filippovms"

        first = await transactions.ensure_canonical_contact_for_profile(profile)
        second = await transactions.ensure_canonical_contact_for_profile(profile)
        await session.commit()

        self.assertEqual(first.id, second.id)
        self.assertEqual(profile.contact_id, first.id)
        self.assertEqual(first.status, "lead")
        identity = (
            await session.execute(
                select(TelegramIdentity).where(TelegramIdentity.telegram_id == self.telegram_id)
            )
        ).scalar_one()
        self.assertEqual(identity.contact_id, first.id)
        contacts_count = (await session.execute(select(func.count(Contact.id)))).scalar_one()
        self.assertEqual(contacts_count, 1)

        record_id = await transactions.add_pending_single_slot(
            self.telegram_id,
            datetime.date.today() + datetime.timedelta(days=3),
            21,
            30,
        )
        record = await session.get(RecordDate, record_id)
        self.assertEqual(record.contact_id, first.id)

    async def asyncTearDown(self) -> None:
        await remove_session()

    async def test_regular_lesson_payment_survives_new_session(self) -> None:
        lesson_date = datetime.date.today() - datetime.timedelta(days=1)
        session.add(
            RegularLesson(
                telegram_id=self.telegram_id,
                full_name="Тест Ученик",
                day_of_week=lesson_date.weekday(),
                hour=10,
                minute=0,
                duration_minutes=60,
            )
        )
        await session.commit()

        payment = await transactions.add_payment(
            telegram_id=self.telegram_id,
            full_name="Тест Ученик",
            lesson_date=lesson_date,
            hour=10,
            minute=0,
            duration_minutes=60,
            amount=2000,
            status="paid",
            source="lesson_close",
        )
        self.assertIsNotNone(payment.lesson_id)
        lesson_id = int(payment.lesson_id)

        await remove_session()  # equivalent to a fresh request after restart
        restored = await transactions.find_payment(
            self.telegram_id,
            lesson_date,
            10,
            0,
            lesson_id=lesson_id,
        )
        self.assertIsNotNone(restored)
        self.assertEqual(restored.status, "paid")
        self.assertEqual(restored.lesson_id, lesson_id)

    async def test_reschedule_keeps_financial_decision(self) -> None:
        old_date = datetime.date.today() + datetime.timedelta(days=1)
        new_date = old_date + datetime.timedelta(days=1)
        record = RecordDate(
            telegram_id=self.telegram_id,
            record_date=old_date,
            hour=18,
            minute=0,
            duration_minutes=60,
            kind="single",
            booking_status="approved",
        )
        session.add(record)
        await session.commit()
        lesson_id = int(record.id)

        await transactions.add_payment(
            telegram_id=self.telegram_id,
            full_name="Тест Ученик",
            lesson_date=old_date,
            hour=18,
            minute=0,
            duration_minutes=60,
            amount=2000,
            status="paid",
            source="lesson_close",
            lesson_id=lesson_id,
        )
        moved = await transactions.reschedule_single_slot(
            self.telegram_id,
            old_date,
            18,
            0,
            new_date,
            10,
            0,
            60,
        )
        self.assertTrue(moved)

        await remove_session()
        restored = await transactions.find_payment(
            self.telegram_id,
            new_date,
            10,
            0,
            lesson_id=lesson_id,
        )
        self.assertIsNotNone(restored)
        self.assertEqual(restored.status, "paid")
        self.assertEqual(restored.lesson_date, new_date)
        self.assertEqual((restored.hour, restored.minute), (10, 0))

    async def test_cleanup_preserves_canonical_lesson(self) -> None:
        lesson_date = datetime.date.today() - datetime.timedelta(days=30)
        record = RecordDate(
            telegram_id=self.telegram_id,
            record_date=lesson_date,
            hour=12,
            minute=0,
            duration_minutes=60,
            kind="single",
            booking_status="approved",
        )
        session.add(record)
        await session.commit()
        lesson_id = int(record.id)

        await transactions.deleting_records_older_7_days()

        self.assertIsNotNone(await session.get(RecordDate, lesson_id))

    async def test_migration_links_latest_legacy_decision(self) -> None:
        lesson_date = datetime.date.today() - datetime.timedelta(days=2)
        record = RecordDate(
            telegram_id=self.telegram_id,
            record_date=lesson_date,
            hour=15,
            minute=30,
            duration_minutes=60,
            kind="single",
            booking_status="approved",
        )
        session.add(record)
        await session.flush()
        older = Payment(
            telegram_id=self.telegram_id,
            full_name="Тест Ученик",
            lesson_date=lesson_date,
            hour=15,
            minute=30,
            duration_minutes=60,
            amount=2000,
            status="canceled",
            source="manual",
        )
        latest = Payment(
            telegram_id=self.telegram_id,
            full_name="Тест Ученик",
            lesson_date=lesson_date,
            hour=15,
            minute=30,
            duration_minutes=60,
            amount=2000,
            status="paid",
            source="lesson_close",
        )
        session.add_all([older, latest])
        await session.commit()

        await transactions._ensure_payment_lesson_link()  # pylint: disable=protected-access
        await session.refresh(older)
        await session.refresh(latest)

        self.assertIsNone(older.lesson_id)
        self.assertEqual(latest.lesson_id, record.id)

    async def test_migration_restores_deleted_historical_lesson(self) -> None:
        lesson_date = datetime.date.today() - datetime.timedelta(days=90)
        payment = Payment(
            telegram_id=self.telegram_id,
            full_name="Тест Ученик",
            lesson_date=lesson_date,
            hour=19,
            minute=0,
            duration_minutes=120,
            amount=4000,
            status="paid",
            source="lesson_close",
        )
        session.add(payment)
        await session.commit()

        await transactions._ensure_payment_lesson_link()  # pylint: disable=protected-access
        await session.refresh(payment)

        self.assertIsNotNone(payment.lesson_id)
        restored = await session.get(RecordDate, int(payment.lesson_id))
        self.assertIsNotNone(restored)
        self.assertEqual(restored.kind, "historical")
        self.assertEqual(restored.record_date, lesson_date)
        self.assertEqual(restored.duration_minutes, 120)


if __name__ == "__main__":
    unittest.main()

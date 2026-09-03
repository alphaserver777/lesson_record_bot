import datetime
import os
import unittest

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL or "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/professorit_test"

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


@unittest.skipUnless(TEST_DATABASE_URL, "нужна TEST_DATABASE_URL для PostgreSQL")
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

    async def test_telegram_profile_reuses_website_contact_by_normalized_phone(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        website_contact = Contact(
            first_name="Максим",
            telephone="79267557900",
            preferred_channel="phone",
            status="lead",
            is_archived=False,
            acquisition_source="avito",
            created_at=now,
            updated_at=now,
        )
        session.add(website_contact)
        await session.commit()

        profile = await session.get(StudentProfile, self.telegram_id)
        profile.telephone = "+7 (926) 755-79-00"
        contact = await transactions.ensure_canonical_contact_for_profile(profile)
        await session.commit()

        self.assertEqual(contact.id, website_contact.id)
        self.assertEqual(profile.contact_id, website_contact.id)
        self.assertEqual(profile.telephone, "79267557900")
        identity = (
            await session.execute(
                select(TelegramIdentity).where(TelegramIdentity.telegram_id == self.telegram_id)
            )
        ).scalar_one()
        self.assertEqual(identity.contact_id, website_contact.id)
        contacts_count = (await session.execute(select(func.count(Contact.id)))).scalar_one()
        self.assertEqual(contacts_count, 1)

    async def test_locked_name_changes_only_with_admin_override(self) -> None:
        profile = await transactions.upsert_student_profile(
            telegram_id=self.telegram_id,
            first_name="Иван",
            last_name="Петров",
            telephone="79990000000",
        )
        profile.name_locked = True
        await session.commit()

        profile = await transactions.upsert_student_profile(
            telegram_id=self.telegram_id,
            first_name="Странный",
            last_name="Ник",
        )
        self.assertEqual((profile.first_name, profile.last_name), ("Иван", "Петров"))

        profile = await transactions.upsert_student_profile(
            telegram_id=self.telegram_id,
            first_name="Иван",
            last_name="Сидоров",
            allow_locked_name_update=True,
        )
        self.assertEqual((profile.first_name, profile.last_name), ("Иван", "Сидоров"))

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

    async def test_startup_schema_check_does_not_link_legacy_payments(self) -> None:
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
        self.assertIsNone(latest.lesson_id)

    async def test_startup_schema_check_does_not_restore_historical_lesson(self) -> None:
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

        self.assertIsNone(payment.lesson_id)
        restored = (
            await session.execute(
                select(RecordDate).where(
                    RecordDate.telegram_id == self.telegram_id,
                    RecordDate.record_date == lesson_date,
                    RecordDate.hour == 19,
                    RecordDate.minute == 0,
                )
            )
        ).scalar_one_or_none()
        self.assertIsNone(restored)

    async def test_rejected_booking_is_not_shown_in_calendar(self) -> None:
        lesson_date = datetime.date.today() + datetime.timedelta(days=7)
        record_id = await transactions.add_pending_single_slot(
            self.telegram_id,
            lesson_date,
            21,
            30,
        )

        status, _ = await transactions.reject_pending_booking(record_id, admin_id=1)
        self.assertEqual(status, "rejected")

        calendar_items = await transactions.viewing_recordings_day_db(lesson_date, show_blocks=True)
        self.assertEqual(calendar_items, [])


if __name__ == "__main__":
    unittest.main()

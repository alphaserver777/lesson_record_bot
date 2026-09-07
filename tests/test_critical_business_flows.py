import datetime
import os
import unittest
from unittest.mock import AsyncMock, patch

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL or "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/professorit_test"

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from database import transactions  # noqa: E402
from database.connect import engine, remove_session, session  # noqa: E402
from database.models import Contact, Opportunity, Payment, RecordDate, TestDriveEnrollment, WebAnalyticsEvent  # noqa: E402
from webapi import main as api  # noqa: E402
from webapi.prodamus import sign_payload  # noqa: E402


class _WebhookRequest:
    def __init__(self, payload: dict[str, str], signature: str):
        self.headers = {"Sign": signature}
        self._payload = payload

    async def form(self):
        return _WebhookForm(self._payload)


class _WebhookForm(dict):
    def multi_items(self):
        return self.items()


@unittest.skipUnless(TEST_DATABASE_URL, "нужна TEST_DATABASE_URL для PostgreSQL")
class CriticalBusinessFlowsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await transactions.init_db()
        await session.execute(text("TRUNCATE TABLE contacts, student_profiles RESTART IDENTITY CASCADE"))
        await session.commit()

    async def asyncTearDown(self) -> None:
        await remove_session()
        # IsolatedAsyncioTestCase creates a loop for every test. asyncpg
        # connections belong to one loop, so the pool must not cross this
        # boundary or a later business-flow check fails before it starts.
        await engine.dispose()

    async def _enrollment(self, *, email: str | None = "student@example.test") -> TestDriveEnrollment:
        now = "2026-09-07T10:00:00+00:00"
        contact = Contact(
            first_name="Тест",
            last_name="Ученик",
            telephone="79990000000",
            email=email,
            status="lead",
            acquisition_source="test",
            created_at=now,
            updated_at=now,
        )
        session.add(contact)
        await session.flush()
        opportunity = Opportunity(
            contact_id=contact.id,
            source="test",
            qualification_status="new",
            stage="new",
            created_at=now,
            updated_at=now,
        )
        session.add(opportunity)
        await session.flush()
        enrollment = TestDriveEnrollment(
            public_token="a" * 32,
            idempotency_key="critical-payment-test",
            contact_id=contact.id,
            opportunity_id=opportunity.id,
            persona="devops",
            price_amount=1000,
            status="awaiting_payment",
            created_at=now,
            updated_at=now,
        )
        session.add(enrollment)
        await session.commit()
        return enrollment

    @staticmethod
    def _payment_payload(enrollment: TestDriveEnrollment, *, amount: str = "1000") -> dict[str, str]:
        return {
            "payment_status": "success",
            "sum": amount,
            "order_id": f"td-{enrollment.id}-{enrollment.public_token}",
            "_param_enrollment_token": enrollment.public_token,
            "customer_email": "student@example.test",
        }

    async def test_prodamus_payment_is_recorded_once_and_duplicate_is_safe(self) -> None:
        enrollment = await self._enrollment()
        payload = self._payment_payload(enrollment)
        signature = sign_payload(payload, "critical-test-secret")
        provision = AsyncMock()
        notify = AsyncMock()

        with (
            patch.object(api, "PRODAMUS_SECRET_KEY", "critical-test-secret"),
            patch.object(api, "provision_test_drive", provision),
            patch.object(api, "_notify_admins", notify),
        ):
            first = await api.public_prodamus_webhook(_WebhookRequest(payload, signature))
            second = await api.public_prodamus_webhook(_WebhookRequest(payload, signature))

        self.assertEqual(first.body, b"ok")
        self.assertEqual(second.body, b"ok")
        self.assertEqual(provision.await_count, 1)
        self.assertEqual(notify.await_count, 1)
        self.assertEqual((await session.execute(select(func.count(Payment.id)))).scalar_one(), 1)
        self.assertEqual((await session.execute(select(func.count(WebAnalyticsEvent.id)))).scalar_one(), 1)
        saved = await session.get(TestDriveEnrollment, enrollment.id)
        self.assertEqual(saved.status, "quest_ready")
        self.assertIsNotNone(saved.payment_id)

    async def test_prodamus_rejects_invalid_signature_and_wrong_amount_without_revenue(self) -> None:
        enrollment = await self._enrollment(email=None)
        payload = self._payment_payload(enrollment, amount="999")

        with patch.object(api, "PRODAMUS_SECRET_KEY", "critical-test-secret"):
            with self.assertRaises(HTTPException) as invalid_signature:
                await api.public_prodamus_webhook(_WebhookRequest(payload, "invalid"))
            self.assertEqual(invalid_signature.exception.status_code, 403)

            signature = sign_payload(payload, "critical-test-secret")
            with self.assertRaises(HTTPException) as invalid_amount:
                await api.public_prodamus_webhook(_WebhookRequest(payload, signature))
            self.assertEqual(invalid_amount.exception.status_code, 409)

        self.assertEqual((await session.execute(select(func.count(Payment.id)))).scalar_one(), 0)
        saved = await session.get(TestDriveEnrollment, enrollment.id)
        self.assertEqual(saved.status, "awaiting_payment")
        self.assertIsNone(saved.payment_id)

    async def test_lms_failure_does_not_cancel_confirmed_payment(self) -> None:
        enrollment = await self._enrollment()
        payload = self._payment_payload(enrollment)
        signature = sign_payload(payload, "critical-test-secret")

        with (
            patch.object(api, "PRODAMUS_SECRET_KEY", "critical-test-secret"),
            patch.object(api, "provision_test_drive", AsyncMock(side_effect=RuntimeError("LMS unavailable"))),
            patch.object(api, "_notify_admins", AsyncMock()),
        ):
            with self.assertRaises(HTTPException) as failed_delivery:
                await api.public_prodamus_webhook(_WebhookRequest(payload, signature))

        self.assertEqual(failed_delivery.exception.status_code, 503)
        self.assertEqual((await session.execute(select(func.count(Payment.id)))).scalar_one(), 1)
        saved = await session.get(TestDriveEnrollment, enrollment.id)
        self.assertEqual(saved.status, "payment_received")
        self.assertIsNotNone(saved.payment_id)

    async def test_approved_booking_blocks_a_second_overlapping_booking(self) -> None:
        telegram_id = 900000001
        date = datetime.date(2026, 10, 1)
        await transactions.upsert_student_profile(
            telegram_id=telegram_id,
            first_name="Тест",
            last_name="Ученик",
            telephone="79990000000",
        )
        first_id = await transactions.add_pending_single_slot(telegram_id, date, 19, 0)

        with (
            patch("database.transactions.is_slot_busy", AsyncMock(return_value=False)),
            patch("database.transactions.create_simple_event", AsyncMock(return_value="calendar-event-1")),
        ):
            first_status, first = await transactions.approve_pending_booking(first_id, admin_id=1)
            second_id = await transactions.add_pending_single_slot(telegram_id, date, 19, 30)
            second_status, second = await transactions.approve_pending_booking(second_id, admin_id=1)

        self.assertEqual(first_status, "approved")
        self.assertEqual(first.booking_status, "approved")
        self.assertEqual(second_status, "slot_busy")
        self.assertEqual(second.booking_status, "pending")
        approved_count = (
            await session.execute(
                select(func.count(RecordDate.id)).where(RecordDate.booking_status == "approved")
            )
        ).scalar_one()
        self.assertEqual(approved_count, 1)


if __name__ == "__main__":
    unittest.main()

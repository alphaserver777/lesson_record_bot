import os
import unittest

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL or "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/professorit_test"

from sqlalchemy import delete, select, text  # noqa: E402

from database import transactions  # noqa: E402
from database.connect import remove_session, session  # noqa: E402
from database.models import MarketingCampaign, MarketingSource, MarketingTrackingLink, WebAnalyticsEvent  # noqa: E402
from webapi.schemas import PublicAnalyticsEventIn, PublicBriefIn  # noqa: E402


@unittest.skipUnless(TEST_DATABASE_URL, "нужна TEST_DATABASE_URL для PostgreSQL")
class MarketingTrackingLinkTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await transactions.init_db()
        for model in (WebAnalyticsEvent, MarketingTrackingLink, MarketingCampaign, MarketingSource):
            await session.execute(delete(model))
        await session.commit()
        now = "2026-08-18T10:00:00+00:00"
        session.add(MarketingSource(key="youtube", name="YouTube", channel="video", is_active=True, created_at=now, updated_at=now))
        session.add(MarketingCampaign(id=101, source_key="youtube", name="Карта · YouTube", target_action_label="КАРТА", is_active=True, created_at=now, updated_at=now))
        await session.commit()

    async def asyncTearDown(self) -> None:
        await remove_session()

    async def test_link_and_event_are_joined_by_tracking_link_id(self) -> None:
        now = "2026-08-18T10:00:00+00:00"
        link = MarketingTrackingLink(
            public_token="a8K2mQ7xTestLink",
            campaign_id=101,
            destination_key="it_map",
            destination_path="/guide/kak-voiti-v-it/",
            label="YouTube · ролик",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(link)
        await session.flush()
        session.add(WebAnalyticsEvent(
            event_id="tracking-test-event",
            event_type="longread_view",
            visitor_id="visitor-test-101",
            path="/guide/kak-voiti-v-it/",
            campaign_id=101,
            tracking_link_id=link.id,
            created_at=now,
        ))
        await session.commit()

        stored = (
            await session.execute(
                select(WebAnalyticsEvent).where(WebAnalyticsEvent.tracking_link_id == link.id)
            )
        ).scalar_one()
        self.assertEqual(stored.campaign_id, 101)
        self.assertEqual(stored.visitor_id, "visitor-test-101")
        columns = await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'web_analytics_events'"
            )
        )
        self.assertIn("tracking_link_id", {str(row[0]) for row in columns})

    def test_public_payloads_accept_opaque_tracking_token(self) -> None:
        event = PublicAnalyticsEventIn(
            event_id="event-123456",
            event_type="longread_view",
            visitor_id="visitor-123456",
            tracking_token="a8K2mQ7xTestLink",
        )
        self.assertEqual(event.tracking_token, "a8K2mQ7xTestLink")
        brief = PublicBriefIn(
            full_name="Тест Пользователь",
            telephone="+79990000000",
            persona="devops",
            student_level="beginner",
            goal="Выйти на первую работу",
            current_problem="Не понимаю маршрут",
            desired_timeline="2 месяца",
            weekly_hours="14 часов",
            consent=True,
            visitor_id="visitor-123456",
            tracking_token="a8K2mQ7xTestLink",
        )
        self.assertEqual(brief.tracking_token, event.tracking_token)


if __name__ == "__main__":
    unittest.main()

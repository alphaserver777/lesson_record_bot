import os
import unittest

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL or "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/professorit_test"
os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
os.environ.setdefault("BEGINNING_WORKING_DAY", "9")
os.environ.setdefault("END_WORKING_DAY", "22")
os.environ.setdefault("ADMINS_TELEGRAM_ID", "")
os.environ.setdefault("PUBLIC_MARKETING_URL", "https://professorit.ru")

from sqlalchemy import delete, select  # noqa: E402
from starlette.requests import Request  # noqa: E402

from database import transactions  # noqa: E402
from database.connect import remove_session, session  # noqa: E402
from database.models import MarketingCampaign, MarketingSource, MarketingTrackingLink, WebAnalyticsEvent  # noqa: E402
from webapi.main import public_track_event, public_tracking_redirect  # noqa: E402
from webapi.schemas import PublicAnalyticsEventIn  # noqa: E402


@unittest.skipUnless(TEST_DATABASE_URL, "нужна TEST_DATABASE_URL для PostgreSQL")
class PublicTrackingRedirectTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await transactions.init_db()
        for model in (WebAnalyticsEvent, MarketingTrackingLink, MarketingCampaign, MarketingSource):
            await session.execute(delete(model))
        now = "2026-08-18T10:00:00+00:00"
        session.add(MarketingSource(key="youtube", name="YouTube", channel="video", is_active=True, created_at=now, updated_at=now))
        session.add(MarketingCampaign(id=202, source_key="youtube", name="YouTube · Карта", target_action_label="КАРТА", is_active=True, created_at=now, updated_at=now))
        session.add(MarketingTrackingLink(
            id=303,
            public_token="redirectToken123",
            campaign_id=202,
            destination_key="it_map",
            destination_path="/guide/kak-voiti-v-it/",
            label="Описание ролика",
            is_active=True,
            created_at=now,
            updated_at=now,
        ))
        await session.commit()

    async def asyncTearDown(self) -> None:
        await remove_session()

    async def test_redirect_records_open_and_passes_tracking_reference(self) -> None:
        request = Request({
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/r/redirectToken123",
            "raw_path": b"/r/redirectToken123",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("professorit.ru", 443),
        })
        response = await public_tracking_redirect("redirectToken123", request)
        self.assertEqual(response.status_code, 302)
        self.assertIn("tracking_ref=redirectToken123", response.headers["location"])
        self.assertIn("campaign_id=202", response.headers["location"])
        self.assertIn("professorit_visitor_id=", response.headers["set-cookie"])

        event = (
            await session.execute(
                select(WebAnalyticsEvent).where(WebAnalyticsEvent.tracking_link_id == 303)
            )
        ).scalar_one()
        self.assertEqual(event.event_type, "tracking_link_opened")
        self.assertEqual(event.campaign_id, 202)

        await public_track_event(PublicAnalyticsEventIn(
            event_id="longread-event-from-link",
            event_type="longread_view",
            visitor_id=event.visitor_id,
            path="/guide/kak-voiti-v-it/",
            tracking_token="redirectToken123",
            meta={"series": "it-entry-map-2026", "sid": "test-session", "part": 1, "part_count": 4},
        ), request)
        longread = (
            await session.execute(
                select(WebAnalyticsEvent).where(WebAnalyticsEvent.event_id == "longread-event-from-link")
            )
        ).scalar_one()
        self.assertEqual(longread.tracking_link_id, 303)
        self.assertEqual(longread.campaign_id, 202)
        self.assertEqual(longread.utm_source, "youtube")


if __name__ == "__main__":
    unittest.main()

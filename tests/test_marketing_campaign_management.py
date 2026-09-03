import datetime
import os
import unittest

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL or "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/professorit_test"

from sqlalchemy import delete  # noqa: E402

from database import transactions  # noqa: E402
from database.connect import remove_session, session  # noqa: E402
from database.models import MarketingCampaign, MarketingSource  # noqa: E402
from webapi.main import admin_create_marketing_campaign, admin_patch_marketing_campaign, analytics_marketing  # noqa: E402
from webapi.schemas import MarketingCampaignIn, MarketingCampaignPatchIn  # noqa: E402


@unittest.skipUnless(TEST_DATABASE_URL, "нужна TEST_DATABASE_URL для PostgreSQL")
class MarketingCampaignManagementTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await transactions.init_db()
        await session.execute(delete(MarketingCampaign))
        await session.execute(delete(MarketingSource))
        now = "2026-08-18T10:00:00+00:00"
        session.add(MarketingSource(key="youtube", name="YouTube", channel="video", is_active=True, created_at=now, updated_at=now))
        await session.commit()

    async def asyncTearDown(self) -> None:
        await remove_session()

    async def test_create_accepts_open_ended_period_and_zero_activity_campaign_is_reported(self) -> None:
        result = await admin_create_marketing_campaign(
            MarketingCampaignIn(source_key="youtube", name="YouTube · Карта", active_from=datetime.date(2026, 8, 18), active_to=None),
            {"sub": 1},
        )
        campaign_id = result["item"]["id"]
        report = await analytics_marketing(
            date_from=datetime.date(2026, 8, 1),
            date_to=datetime.date(2026, 8, 31),
            direction=None,
            source_key=None,
            campaign_id=None,
            campaign=None,
            _={"sub": 1},
        )
        row = next(item for item in report["rows"] if item["campaign_id"] == campaign_id)
        self.assertEqual(row["leads"], 0)
        self.assertEqual(row["spend"], 0)
        self.assertTrue(row["is_active"])

    async def test_partial_patch_does_not_clear_dates_and_can_archive(self) -> None:
        created = await admin_create_marketing_campaign(
            MarketingCampaignIn(source_key="youtube", name="Старое имя", active_from=datetime.date(2026, 8, 18)),
            {"sub": 1},
        )
        campaign_id = created["item"]["id"]
        result = await admin_patch_marketing_campaign(
            campaign_id,
            MarketingCampaignPatchIn(name="Новое имя", is_active=False),
            {"sub": 1},
        )
        self.assertEqual(result["item"]["name"], "Новое имя")
        self.assertEqual(result["item"]["active_from"], "2026-08-18")
        self.assertFalse(result["item"]["is_active"])


if __name__ == "__main__":
    unittest.main()

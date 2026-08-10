"""Additively backfill canonical contacts and opportunities.

Safe to rerun. Existing lesson/payment relationships remain unchanged during
the compatibility phase.
"""
from __future__ import annotations

import asyncio
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text

from database.connect import Base, SessionFactory, engine
from database.models import Contact, Lead, Opportunity, StudentProfile, TelegramIdentity


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


async def ensure_additive_schema() -> None:
    async with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            await conn.execute(text("ALTER TABLE student_profiles ADD COLUMN IF NOT EXISTS contact_id INTEGER"))
        else:
            columns = await conn.execute(text("PRAGMA table_info('student_profiles')"))
            if "contact_id" not in {row[1] for row in columns}:
                await conn.execute(text("ALTER TABLE student_profiles ADD COLUMN contact_id INTEGER"))
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "postgresql":
            await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_student_profiles_contact_id ON student_profiles(contact_id) WHERE contact_id IS NOT NULL"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_student_profiles_contact_id ON student_profiles(contact_id)"))
            await conn.execute(text("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'fk_student_profiles_contact_id'
                    ) THEN
                        ALTER TABLE student_profiles
                        ADD CONSTRAINT fk_student_profiles_contact_id
                        FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL;
                    END IF;
                END $$
            """))


async def migrate() -> dict[str, int]:
    await ensure_additive_schema()
    created_contacts = 0
    created_identities = 0
    created_opportunities = 0

    async with SessionFactory() as db:
        profiles = (await db.execute(select(StudentProfile).order_by(StudentProfile.telegram_id))).scalars().all()
        for profile in profiles:
            identity = (
                await db.execute(select(TelegramIdentity).where(TelegramIdentity.telegram_id == profile.telegram_id))
            ).scalar_one_or_none()
            contact = await db.get(Contact, profile.contact_id) if profile.contact_id else None
            if contact is None and identity is not None:
                contact = await db.get(Contact, identity.contact_id)
            if contact is None:
                now = utc_now()
                contact = Contact(
                    first_name=profile.first_name,
                    last_name=profile.last_name,
                    telephone=profile.telephone,
                    preferred_channel="telegram",
                    status="student" if not profile.is_deleted else "archived",
                    is_archived=bool(profile.is_deleted),
                    created_at=now,
                    updated_at=now,
                )
                db.add(contact)
                await db.flush()
                created_contacts += 1
            profile.contact_id = contact.id
            if identity is None:
                now = utc_now()
                db.add(TelegramIdentity(
                    contact_id=contact.id,
                    telegram_id=profile.telegram_id,
                    username=profile.telegram_username,
                    last_login_at=profile.last_visit_date,
                    entry_chat_id=profile.miniapp_entry_chat_id,
                    entry_message_id=profile.miniapp_entry_message_id,
                    created_at=now,
                    updated_at=now,
                ))
                created_identities += 1
        await db.commit()

        leads = (await db.execute(select(Lead).order_by(Lead.id))).scalars().all()
        for lead in leads:
            exists = (
                await db.execute(select(Opportunity.id).where(Opportunity.legacy_lead_id == lead.id))
            ).scalar_one_or_none()
            if exists is not None:
                continue
            contact = None
            if lead.telegram_id is not None:
                identity = (
                    await db.execute(select(TelegramIdentity).where(TelegramIdentity.telegram_id == lead.telegram_id))
                ).scalar_one_or_none()
                if identity:
                    contact = await db.get(Contact, identity.contact_id)
            if contact is None and lead.telephone:
                matches = (
                    await db.execute(select(Contact).where(Contact.telephone == lead.telephone).limit(2))
                ).scalars().all()
                if len(matches) == 1:
                    contact = matches[0]
            if contact is None:
                parts = [part for part in (lead.full_name or "").split() if part]
                now = utc_now()
                contact = Contact(
                    first_name=" ".join(parts[1:]) or (parts[0] if parts else None),
                    last_name=parts[0] if len(parts) > 1 else None,
                    telephone=lead.telephone,
                    preferred_channel="telegram" if lead.telegram_id else "phone",
                    status="lead",
                    is_archived=False,
                    created_at=now,
                    updated_at=now,
                )
                db.add(contact)
                await db.flush()
                created_contacts += 1
            db.add(Opportunity(
                contact_id=contact.id,
                legacy_lead_id=lead.id,
                source=lead.source,
                utm_medium=lead.utm_medium,
                utm_campaign=lead.utm_campaign,
                utm_content=lead.utm_content,
                direction=lead.direction,
                goal=lead.goal,
                stage=lead.stage,
                diagnostic_at=lead.diagnostic_at,
                offer_amount=lead.offer_amount,
                paid_amount=lead.paid_amount,
                lost_reason=lead.lost_reason,
                next_contact_at=lead.next_contact_at,
                notes=lead.notes,
                created_at=lead.created_at,
                updated_at=lead.updated_at,
            ))
            created_opportunities += 1
        await db.commit()

        counts = {
            "profiles": len(profiles),
            "contacts": len((await db.execute(select(Contact.id))).all()),
            "identities": len((await db.execute(select(TelegramIdentity.id))).all()),
            "leads": len(leads),
            "opportunities": len((await db.execute(select(Opportunity.id))).all()),
            "created_contacts": created_contacts,
            "created_identities": created_identities,
            "created_opportunities": created_opportunities,
        }
        print(" ".join(f"{key}={value}" for key, value in counts.items()))
        return counts


if __name__ == "__main__":
    asyncio.run(migrate())

# Task: Canonical contact migration

## Status

Done — deployed 2026-08-10

## Context

`student_profiles` currently combines person, Telegram identity and educational
profile. `leads` repeats contact fields. This prevents a clean single-platform
CRM and makes Telegram ID an unsafe permanent person identifier.

## Goal

Introduce canonical contacts, Telegram identities and opportunities, then
backfill all current profiles and leads without interrupting production.

## Scope

In scope:

- additive PostgreSQL schema;
- idempotent backfill script;
- `student_profiles.contact_id` compatibility link;
- row-count and orphan verification;
- rollback documentation.

Out of scope:

- removing old Telegram-ID foreign keys;
- deleting `leads`;
- redesigning the admin frontend.

## Acceptance Criteria

- every non-placeholder student profile has exactly one contact;
- every Telegram profile has exactly one Telegram identity;
- every existing lead is represented by an opportunity;
- no lesson, payment or profile count changes;
- rerunning the migration produces no duplicates;
- current API and bot remain healthy.

## Verification

- PostgreSQL backup created before migration;
- 61 profiles, 61 contacts and 61 Telegram identities;
- 0 profiles without a contact;
- 32 lesson records and 673 payments retained;
- second migration run created 0 contacts, identities and opportunities;
- foreign key `fk_student_profiles_contact_id` installed;
- API, frontend and bot are healthy after deployment.

Twenty was also removed from the operational path as a separate approved
follow-up: its final dump is retained and its containers are stopped without
removing volumes.

## Rollback / Safety

The migration only adds tables and nullable columns. The old application ignores
them. Rollback is application rollback; new tables remain inert. PostgreSQL dump
is retained for full restore if verification fails.

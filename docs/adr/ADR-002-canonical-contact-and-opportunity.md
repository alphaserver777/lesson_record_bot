# ADR-002: Canonical contact and opportunity

## Status

Accepted

## Context

The current application uses `student_profiles.telegram_id` as the identity of
a person. Marketing leads duplicate name and telephone in `leads`, while Twenty
can become a second CRM source of truth. A person may exist before Telegram and
may return with another commercial request.

## Decision

- `contacts` is the canonical person record.
- `telegram_identities` maps Telegram accounts to contacts.
- `opportunities` stores commercial funnel data and references a contact.
- `student_profiles` becomes an educational role and receives `contact_id`.
- Existing Telegram-ID foreign keys remain during a compatibility period.
- PostgreSQL is the only operational source of truth. Twenty was exported and
  stopped on 2026-08-10; its volumes remain available for a reversible rollback.

## Consequences

The first migration is additive and reversible. During the compatibility
period, old route names keep working while their implementation writes to the
new entities. No automatic
merge is performed solely from a matching name. Confirmed Telegram identity is
the strongest automatic link; telephone matches require review when ambiguous.

# Task: Unified contact directory

## Status

In progress — first read-only directory and 360° card deployed 2026-08-10

## Goal

Replace the separate student list and funnel-only view with one contact
directory backed by `contacts`, while preserving dedicated educational and
commercial views.

## Scope

- contact list API with name, phone, Telegram, lifecycle and activity filters;
- create a contact without Telegram;
- contact detail aggregation for opportunities, lessons and payments;
- safe duplicate preview before any merge;
- admin UI navigation from directory to the 360-degree contact card.

## Acceptance Criteria

- a lead-only contact and a student appear in the same searchable directory;
- opening a contact shows its opportunities, lessons and paid revenue;
- adding an opportunity never copies the contact's name or telephone;
- student booking and Telegram authentication continue to use compatibility
  links without regression;
- all admin routes remain protected and audited.

## Delivered in first increment

- `/api/admin/contacts` lists canonical contacts, Telegram identity, student
  role and number of opportunities;
- `/api/admin/contacts/{id}` returns opportunities, recent lessons and recent
  payments from the same PostgreSQL database;
- the admin UI has a separate «Контакты» tab and no longer exposes the old
  client section as a primary navigation choice.

Remaining work is contact creation/editing, filters, merge preview and a
timeline of notes/actions.

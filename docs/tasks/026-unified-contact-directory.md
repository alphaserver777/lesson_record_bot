# Task: Unified contact directory

## Status

Next

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

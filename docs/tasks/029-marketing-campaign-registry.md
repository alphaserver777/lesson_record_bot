# Task: Marketing campaign registry

## Status

Implemented; production data normalized on 18 August 2026.

## Goal

Make campaigns a first-class marketing entity instead of creating and editing
them inside the expense form.

## Behavior

- `Маркетинг → Кампании` contains creation, search and status filters;
- active and archived campaigns remain available without deleting history;
- a campaign can change its name, source, dates and target-action label;
- a campaign card combines manual top-of-funnel metrics with CRM revenue;
- the link action opens `Маркетинг → Ссылки` already filtered to the campaign;
- newly created zero-activity campaigns appear in the registry immediately;
- blank optional dates are sent as `null`, not invalid empty strings;
- PATCH updates only submitted fields and does not clear the existing period.

## Data model

`MarketingSource → MarketingCampaign → MarketingTrackingLink` remains the
canonical hierarchy. A campaign is archived with `is_active=false`; it is never
deleted merely because advertising stopped.

## Verification

- `python -m unittest tests.test_marketing_campaign_management`;
- tracked-link and redirect regression tests;
- production frontend build;
- create a campaign with only a start date, edit it, archive it and restore it.

# Task: Tracked marketing links

## Status

Implemented; production verification is required after deploy.

## Goal

Generate an opaque link for one traffic placement and attribute the complete
lead-magnet journey to that link without creating a campaign per visitor or
YouTube video.

## Implementation

- `marketing_tracking_links` belongs to one `marketing_campaigns` row;
- `web_analytics_events.tracking_link_id` connects clicks and site behavior;
- `/r/{public_token}` records the server-side open and redirects through an
  allowlist;
- the marketing site keeps `tracking_ref` through all four longread parts and
  the test-drive form;
- the Prodamus payment event inherits the tracking link from the opportunity's
  web journey;
- the former top-level `Сайты` view is available inside `Маркетинг → Поведение
  на сайте`;
- `Маркетинг → Ссылки` contains generation, comments, aggregate metrics and
  per-link reader journeys.

## Safety

- public tokens are random and do not expose names or internal IDs;
- redirect destinations are selected from a server-side allowlist;
- links are disabled instead of deleted;
- first-touch campaign attribution remains canonical;
- a link identifies traffic from a placement, not a verified individual;
- schema changes are additive and idempotent for PostgreSQL and SQLite.

## Verification

- `python -m unittest tests.test_marketing_tracking_links tests.test_tracking_redirect`;
- `npm run build` in `miniapp`;
- `npm run build` in the marketing site;
- production: create a test link, open it, read two parts, then verify one
  server-side open and one reader journey under that link.

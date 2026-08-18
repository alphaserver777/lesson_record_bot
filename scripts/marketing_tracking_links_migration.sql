BEGIN;

CREATE TABLE IF NOT EXISTS marketing_tracking_links (
  id SERIAL PRIMARY KEY,
  public_token VARCHAR(32) NOT NULL UNIQUE,
  campaign_id INTEGER NOT NULL REFERENCES marketing_campaigns(id) ON DELETE RESTRICT,
  destination_key VARCHAR(32) NOT NULL DEFAULT 'it_map',
  destination_path VARCHAR(500) NOT NULL,
  label VARCHAR(160) NOT NULL,
  note VARCHAR(1000),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  expires_at VARCHAR(50),
  created_by BIGINT,
  created_at VARCHAR(50) NOT NULL,
  updated_at VARCHAR(50) NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_marketing_tracking_links_public_token
  ON marketing_tracking_links(public_token);
CREATE INDEX IF NOT EXISTS ix_marketing_tracking_links_campaign
  ON marketing_tracking_links(campaign_id);
CREATE INDEX IF NOT EXISTS ix_marketing_tracking_links_active
  ON marketing_tracking_links(is_active);

ALTER TABLE web_analytics_events
  ADD COLUMN IF NOT EXISTS tracking_link_id INTEGER
  REFERENCES marketing_tracking_links(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_web_analytics_events_tracking_link
  ON web_analytics_events(tracking_link_id);

COMMIT;

BEGIN;

ALTER TABLE marketing_campaigns ADD COLUMN IF NOT EXISTS active_from DATE;
ALTER TABLE marketing_campaigns ADD COLUMN IF NOT EXISTS active_to DATE;

CREATE TABLE IF NOT EXISTS marketing_campaign_metrics (
  id SERIAL PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES marketing_campaigns(id) ON DELETE CASCADE,
  metric_key VARCHAR(48) NOT NULL,
  metric_value INTEGER NOT NULL DEFAULT 0 CHECK(metric_value >= 0),
  updated_at VARCHAR(50) NOT NULL,
  UNIQUE(campaign_id, metric_key)
);

CREATE INDEX IF NOT EXISTS idx_marketing_campaign_metrics_campaign ON marketing_campaign_metrics(campaign_id);

COMMIT;

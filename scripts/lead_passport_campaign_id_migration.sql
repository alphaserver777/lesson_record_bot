BEGIN;

ALTER TABLE contacts
  ADD COLUMN IF NOT EXISTS acquisition_campaign_id INTEGER
    REFERENCES marketing_campaigns(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_contacts_acquisition_campaign_id
  ON contacts(acquisition_campaign_id);

-- Only deterministic legacy matches are migrated.  Equal campaign names under
-- one source are intentionally left unlinked for manual resolution.
WITH unique_campaigns AS (
  SELECT source_key, name, MIN(id) AS id
  FROM marketing_campaigns
  GROUP BY source_key, name
  HAVING COUNT(*) = 1
)
UPDATE contacts c
SET acquisition_campaign_id = u.id
FROM unique_campaigns u
WHERE c.acquisition_campaign_id IS NULL
  AND c.acquisition_source = u.source_key
  AND c.acquisition_campaign = u.name;

ALTER TABLE opportunities
  ADD COLUMN IF NOT EXISTS qualification_status VARCHAR(24) NOT NULL DEFAULT 'new',
  ADD COLUMN IF NOT EXISTS desired_format VARCHAR(80),
  ADD COLUMN IF NOT EXISTS desired_budget INTEGER,
  ADD COLUMN IF NOT EXISTS first_response_at VARCHAR(50);
CREATE INDEX IF NOT EXISTS ix_opportunities_qualification_status
  ON opportunities(qualification_status);

COMMIT;

BEGIN;

ALTER TABLE contacts ADD COLUMN IF NOT EXISTS acquisition_source VARCHAR(80) NOT NULL DEFAULT 'unknown';
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS acquisition_campaign VARCHAR(120);
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS acquired_at DATE;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS diagnostic_scheduled_at VARCHAR(50);
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS diagnostic_held_at VARCHAR(50);
ALTER TABLE funnel_stages ADD COLUMN IF NOT EXISTS metric_role VARCHAR(32) NOT NULL DEFAULT 'new';

CREATE TABLE IF NOT EXISTS marketing_sources (
  key VARCHAR(80) PRIMARY KEY, name VARCHAR(100) NOT NULL, channel VARCHAR(40) NOT NULL DEFAULT 'other',
  is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at VARCHAR(50) NOT NULL, updated_at VARCHAR(50) NOT NULL
);
CREATE TABLE IF NOT EXISTS marketing_campaigns (
  id SERIAL PRIMARY KEY, source_key VARCHAR(80) NOT NULL REFERENCES marketing_sources(key), name VARCHAR(120) NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at VARCHAR(50) NOT NULL, updated_at VARCHAR(50) NOT NULL
);
CREATE TABLE IF NOT EXISTS marketing_expenses (
  id SERIAL PRIMARY KEY, spent_at DATE NOT NULL, amount INTEGER NOT NULL CHECK(amount > 0),
  source_key VARCHAR(80) NOT NULL REFERENCES marketing_sources(key), campaign_id INTEGER REFERENCES marketing_campaigns(id) ON DELETE SET NULL,
  category VARCHAR(32) NOT NULL CHECK(category IN ('placement','advertising','content','contractor')),
  note VARCHAR(500), created_at VARCHAR(50) NOT NULL, updated_at VARCHAR(50) NOT NULL
);
CREATE TABLE IF NOT EXISTS opportunity_stage_events (
  id SERIAL PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
  from_stage VARCHAR(48), to_stage VARCHAR(48) NOT NULL, occurred_at VARCHAR(50) NOT NULL,
  actor_id BIGINT, source VARCHAR(32) NOT NULL DEFAULT 'admin'
);

CREATE INDEX IF NOT EXISTS idx_contacts_acquisition_source ON contacts(acquisition_source);
CREATE INDEX IF NOT EXISTS idx_contacts_acquired_at ON contacts(acquired_at);
CREATE INDEX IF NOT EXISTS idx_marketing_expenses_spent_at ON marketing_expenses(spent_at);
CREATE INDEX IF NOT EXISTS idx_opportunity_stage_events_opportunity ON opportunity_stage_events(opportunity_id, occurred_at);

INSERT INTO marketing_sources(key,name,channel,is_active,created_at,updated_at) VALUES
('avito','Avito','marketplace',TRUE,NOW()::text,NOW()::text),
('youtube','YouTube','content',TRUE,NOW()::text,NOW()::text),
('telegram','Telegram','community',TRUE,NOW()::text,NOW()::text),
('referral','Рекомендация','referral',TRUE,NOW()::text,NOW()::text),
('site','Сайт / поиск','search',TRUE,NOW()::text,NOW()::text),
('direct','Прямой','direct',TRUE,NOW()::text,NOW()::text),
('other','Прочее','other',TRUE,NOW()::text,NOW()::text),
('unknown','Неизвестно','unknown',TRUE,NOW()::text,NOW()::text)
ON CONFLICT (key) DO NOTHING;

UPDATE funnel_stages SET metric_role = CASE key
  WHEN 'new' THEN 'new' WHEN 'qualified' THEN 'qualified'
  WHEN 'diagnostic_booked' THEN 'diagnostic_scheduled' WHEN 'diagnostic_done' THEN 'diagnostic_held'
  WHEN 'offer_sent' THEN 'offer' WHEN 'won' THEN 'won' WHEN 'lost' THEN 'lost' ELSE metric_role END;

WITH ranked AS (
  SELECT DISTINCT ON (contact_id) contact_id, source, utm_campaign, created_at::date AS acquired_at
  FROM opportunities ORDER BY contact_id, created_at, id
)
UPDATE contacts c SET acquisition_source = CASE
  WHEN lower(coalesce(r.source,'')) LIKE 'avito%' THEN 'avito'
  WHEN lower(coalesce(r.source,'')) LIKE 'youtube%' THEN 'youtube'
  WHEN lower(coalesce(r.source,'')) LIKE 'telegram%' THEN 'telegram'
  WHEN lower(coalesce(r.source,'')) LIKE '%recommend%' OR lower(coalesce(r.source,'')) LIKE '%referral%' THEN 'referral'
  WHEN lower(coalesce(r.source,'')) LIKE '%site%' OR lower(coalesce(r.source,'')) LIKE '%search%' THEN 'site'
  WHEN lower(coalesce(r.source,'')) IN ('direct','manual') THEN 'direct'
  WHEN coalesce(r.source,'') = '' THEN 'unknown' ELSE 'other' END,
  acquisition_campaign = NULLIF(r.utm_campaign,''), acquired_at = r.acquired_at
FROM ranked r WHERE c.id = r.contact_id;

UPDATE contacts SET acquisition_source='unknown' WHERE acquisition_source IS NULL OR acquisition_source='';

INSERT INTO opportunity_stage_events(opportunity_id,from_stage,to_stage,occurred_at,source)
SELECT o.id,NULL,o.stage,coalesce(o.created_at,NOW()::text),'migration'
FROM opportunities o WHERE NOT EXISTS (SELECT 1 FROM opportunity_stage_events e WHERE e.opportunity_id=o.id);

COMMIT;

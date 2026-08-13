BEGIN;

ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS landing_page VARCHAR(500);
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS referrer VARCHAR(500);
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS visitor_id VARCHAR(64);
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS metrica_client_id VARCHAR(64);
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS telegram_username_hint VARCHAR(100);
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS brief_json VARCHAR(4000);
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS consent_at VARCHAR(50);
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS public_token VARCHAR(64);
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(80);

CREATE INDEX IF NOT EXISTS ix_opportunities_visitor_id ON opportunities(visitor_id);
CREATE INDEX IF NOT EXISTS ix_opportunities_metrica_client_id ON opportunities(metrica_client_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_opportunities_public_token ON opportunities(public_token) WHERE public_token IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_opportunities_idempotency_key ON opportunities(idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS test_drive_enrollments (
  id SERIAL PRIMARY KEY,
  public_token VARCHAR(64) NOT NULL UNIQUE,
  idempotency_key VARCHAR(80) NOT NULL UNIQUE,
  contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
  persona VARCHAR(32) NOT NULL,
  price_amount INTEGER NOT NULL DEFAULT 1500,
  status VARCHAR(32) NOT NULL DEFAULT 'awaiting_payment',
  payment_id INTEGER REFERENCES payments(id) ON DELETE SET NULL,
  quest_url VARCHAR(500), quest_opened_at VARCHAR(50),
  submission_url VARCHAR(500), submission_note VARCHAR(1000), submitted_at VARCHAR(50), reviewed_at VARCHAR(50),
  created_at VARCHAR(50) NOT NULL, updated_at VARCHAR(50) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_test_drive_enrollments_status ON test_drive_enrollments(status, created_at);
CREATE INDEX IF NOT EXISTS ix_test_drive_enrollments_contact ON test_drive_enrollments(contact_id);

CREATE TABLE IF NOT EXISTS review_booking_requests (
  id SERIAL PRIMARY KEY,
  public_token VARCHAR(64) NOT NULL UNIQUE,
  idempotency_key VARCHAR(80) NOT NULL UNIQUE,
  contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
  enrollment_id INTEGER NOT NULL REFERENCES test_drive_enrollments(id) ON DELETE CASCADE,
  requested_date DATE NOT NULL,
  requested_hour INTEGER NOT NULL,
  requested_minute INTEGER NOT NULL,
  duration_minutes INTEGER NOT NULL DEFAULT 30,
  hold_key VARCHAR(80) UNIQUE,
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  expires_at VARCHAR(50) NOT NULL,
  admin_id BIGINT,
  decided_at VARCHAR(50),
  created_at VARCHAR(50) NOT NULL,
  updated_at VARCHAR(50) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_review_booking_requests_status ON review_booking_requests(status, requested_date);
CREATE INDEX IF NOT EXISTS ix_review_booking_requests_contact ON review_booking_requests(contact_id);
CREATE INDEX IF NOT EXISTS ix_review_booking_requests_hold_key ON review_booking_requests(hold_key);

CREATE TABLE IF NOT EXISTS web_analytics_events (
  id SERIAL PRIMARY KEY,
  event_id VARCHAR(80) NOT NULL UNIQUE,
  event_type VARCHAR(40) NOT NULL,
  visitor_id VARCHAR(64) NOT NULL,
  contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
  opportunity_id INTEGER REFERENCES opportunities(id) ON DELETE SET NULL,
  path VARCHAR(500),
  utm_source VARCHAR(80),
  utm_medium VARCHAR(80),
  utm_campaign VARCHAR(120),
  utm_content VARCHAR(120),
  campaign_id INTEGER REFERENCES marketing_campaigns(id) ON DELETE SET NULL,
  metrica_client_id VARCHAR(64),
  meta_json VARCHAR(2000),
  created_at VARCHAR(50) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_web_analytics_events_type_created ON web_analytics_events(event_type, created_at);
CREATE INDEX IF NOT EXISTS ix_web_analytics_events_visitor ON web_analytics_events(visitor_id);
CREATE INDEX IF NOT EXISTS ix_web_analytics_events_contact ON web_analytics_events(contact_id);
ALTER TABLE web_analytics_events ADD COLUMN IF NOT EXISTS campaign_id INTEGER REFERENCES marketing_campaigns(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_web_analytics_events_campaign ON web_analytics_events(campaign_id);

COMMIT;

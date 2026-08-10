-- Move operational history to the canonical client identity.
-- Telegram remains a delivery/login identity, while `contact_id` is the
-- transaction owner. Safe to rerun on PostgreSQL.
BEGIN;

ALTER TABLE record_dates ADD COLUMN IF NOT EXISTS contact_id INTEGER;
ALTER TABLE regular_lessons ADD COLUMN IF NOT EXISTS contact_id INTEGER;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS contact_id INTEGER;
ALTER TABLE analytics_events ADD COLUMN IF NOT EXISTS contact_id INTEGER;

UPDATE record_dates AS item
   SET contact_id = identity.contact_id
  FROM telegram_identities AS identity
 WHERE item.telegram_id = identity.telegram_id
   AND item.contact_id IS DISTINCT FROM identity.contact_id;

UPDATE regular_lessons AS item
   SET contact_id = identity.contact_id
  FROM telegram_identities AS identity
 WHERE item.telegram_id = identity.telegram_id
   AND item.contact_id IS DISTINCT FROM identity.contact_id;

UPDATE payments AS item
   SET contact_id = identity.contact_id
  FROM telegram_identities AS identity
 WHERE item.telegram_id = identity.telegram_id
   AND item.contact_id IS DISTINCT FROM identity.contact_id;

UPDATE analytics_events AS item
   SET contact_id = identity.contact_id
  FROM telegram_identities AS identity
 WHERE item.telegram_id = identity.telegram_id
   AND item.contact_id IS DISTINCT FROM identity.contact_id;

CREATE INDEX IF NOT EXISTS idx_record_dates_contact_id ON record_dates(contact_id);
CREATE INDEX IF NOT EXISTS idx_regular_lessons_contact_id ON regular_lessons(contact_id);
CREATE INDEX IF NOT EXISTS idx_payments_contact_id ON payments(contact_id);
CREATE INDEX IF NOT EXISTS idx_analytics_events_contact_id ON analytics_events(contact_id);

DO $$
DECLARE table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['record_dates', 'regular_lessons', 'payments', 'analytics_events']
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM pg_constraint WHERE conname = 'fk_' || table_name || '_contact_id'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL',
        table_name, 'fk_' || table_name || '_contact_id'
      );
    END IF;
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION set_transaction_contact_id()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.telegram_id IS NOT NULL THEN
    SELECT contact_id INTO NEW.contact_id
      FROM telegram_identities
     WHERE telegram_id = NEW.telegram_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS record_dates_set_contact_id ON record_dates;
CREATE TRIGGER record_dates_set_contact_id
  BEFORE INSERT OR UPDATE OF telegram_id ON record_dates
  FOR EACH ROW EXECUTE FUNCTION set_transaction_contact_id();

DROP TRIGGER IF EXISTS regular_lessons_set_contact_id ON regular_lessons;
CREATE TRIGGER regular_lessons_set_contact_id
  BEFORE INSERT OR UPDATE OF telegram_id ON regular_lessons
  FOR EACH ROW EXECUTE FUNCTION set_transaction_contact_id();

DROP TRIGGER IF EXISTS payments_set_contact_id ON payments;
CREATE TRIGGER payments_set_contact_id
  BEFORE INSERT OR UPDATE OF telegram_id ON payments
  FOR EACH ROW EXECUTE FUNCTION set_transaction_contact_id();

DROP TRIGGER IF EXISTS analytics_events_set_contact_id ON analytics_events;
CREATE TRIGGER analytics_events_set_contact_id
  BEFORE INSERT OR UPDATE OF telegram_id ON analytics_events
  FOR EACH ROW EXECUTE FUNCTION set_transaction_contact_id();

COMMIT;

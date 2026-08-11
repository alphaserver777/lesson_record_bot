BEGIN;

ALTER TABLE marketing_campaigns
  ADD COLUMN IF NOT EXISTS target_action_label VARCHAR(100) NOT NULL DEFAULT 'Целевое действие';

COMMIT;

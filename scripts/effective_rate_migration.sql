BEGIN;

CREATE TABLE IF NOT EXISTS manual_work_logs (
  id SERIAL PRIMARY KEY,
  worked_on DATE NOT NULL,
  category VARCHAR(24) NOT NULL,
  minutes INTEGER NOT NULL CHECK (minutes > 0 AND minutes <= 1440),
  note VARCHAR(500),
  created_at VARCHAR(50) NOT NULL,
  updated_at VARCHAR(50) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_manual_work_logs_worked_on ON manual_work_logs(worked_on);
CREATE INDEX IF NOT EXISTS ix_manual_work_logs_category ON manual_work_logs(category);

COMMIT;

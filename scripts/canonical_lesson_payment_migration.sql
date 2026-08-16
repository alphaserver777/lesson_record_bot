BEGIN;

ALTER TABLE payments
    ADD COLUMN IF NOT EXISTS lesson_id INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_attribute a
          ON a.attrelid = c.conrelid
         AND a.attnum = ANY(c.conkey)
        WHERE c.contype = 'f'
          AND c.conrelid = 'payments'::regclass
          AND a.attname = 'lesson_id'
    ) THEN
        ALTER TABLE payments
            ADD CONSTRAINT fk_payments_lesson_id
            FOREIGN KEY (lesson_id) REFERENCES record_dates(id)
            ON DELETE SET NULL;
    END IF;
END $$;

-- The legacy cleanup job removed lesson occurrences after seven days while
-- retaining their financial decisions. Restore identifiable occurrences once.
INSERT INTO record_dates (
    contact_id,
    telegram_id,
    record_date,
    hour,
    minute,
    duration_minutes,
    kind,
    presence_status,
    note,
    event_id,
    booking_status
)
SELECT
    (SELECT sp.contact_id
     FROM student_profiles sp
     WHERE sp.telegram_id = payments.telegram_id),
    payments.telegram_id,
    payments.lesson_date,
    payments.hour,
    payments.minute,
    payments.duration_minutes,
    CASE WHEN payments.source = 'manual' THEN 'manual' ELSE 'historical' END,
    CASE WHEN payments.status = 'canceled' THEN 'no' ELSE 'yes' END,
    'Восстановлено из истории оплат',
    NULL,
    'approved'
FROM payments
WHERE payments.lesson_id IS NULL
  AND payments.telegram_id IS NOT NULL
  AND payments.duration_minutes > 0
  AND payments.id = (
      SELECT MAX(p2.id)
      FROM payments p2
      WHERE p2.telegram_id = payments.telegram_id
        AND p2.lesson_date = payments.lesson_date
        AND p2.hour = payments.hour
        AND p2.minute = payments.minute
  )
  AND NOT EXISTS (
      SELECT 1
      FROM record_dates rd
      WHERE rd.telegram_id = payments.telegram_id
        AND rd.record_date = payments.lesson_date
        AND rd.hour = payments.hour
        AND rd.minute = payments.minute
        AND rd.kind NOT IN ('block', 'allow')
  );

-- Preserve every legacy payment row. When a slot has several decisions, only
-- the latest decision becomes canonical; older rows remain audit history.
UPDATE payments
SET lesson_id = (
    SELECT MIN(rd.id)
    FROM record_dates rd
    WHERE rd.telegram_id = payments.telegram_id
      AND rd.record_date = payments.lesson_date
      AND rd.hour = payments.hour
      AND rd.minute = payments.minute
      AND rd.kind NOT IN ('block', 'allow')
)
WHERE lesson_id IS NULL
  AND telegram_id IS NOT NULL
  AND duration_minutes > 0
  AND id = (
      SELECT MAX(p2.id)
      FROM payments p2
      WHERE p2.telegram_id = payments.telegram_id
        AND p2.lesson_date = payments.lesson_date
        AND p2.hour = payments.hour
        AND p2.minute = payments.minute
  )
  AND EXISTS (
      SELECT 1
      FROM record_dates rd
      WHERE rd.telegram_id = payments.telegram_id
        AND rd.record_date = payments.lesson_date
        AND rd.hour = payments.hour
        AND rd.minute = payments.minute
        AND rd.kind NOT IN ('block', 'allow')
  );

CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_lesson_id
    ON payments(lesson_id)
    WHERE lesson_id IS NOT NULL;

COMMIT;

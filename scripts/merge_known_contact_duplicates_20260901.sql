BEGIN;

DO $$
DECLARE
    pair integer[];
BEGIN
    FOREACH pair SLICE 1 IN ARRAY ARRAY[[2, 67], [71, 72]]::integer[][] LOOP
        IF NOT EXISTS (
            SELECT 1
              FROM contacts target
              JOIN contacts source
                ON regexp_replace(coalesce(target.telephone, ''), '[^0-9]', '', 'g') =
                   regexp_replace(coalesce(source.telephone, ''), '[^0-9]', '', 'g')
             WHERE target.id = pair[1]
               AND source.id = pair[2]
               AND target.telephone IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'Контакты % и % не прошли проверку телефона', pair[1], pair[2];
        END IF;
    END LOOP;
END $$;

UPDATE contacts target
   SET first_name = coalesce(target.first_name, source.first_name),
       last_name = coalesce(target.last_name, source.last_name),
       telephone = coalesce(target.telephone, source.telephone),
       acquisition_source = CASE
           WHEN target.acquisition_source IN ('unknown', 'direct', 'telegram')
               THEN source.acquisition_source
           ELSE target.acquisition_source
       END,
       acquisition_campaign_id = CASE
           WHEN target.acquisition_source IN ('unknown', 'direct', 'telegram')
               THEN source.acquisition_campaign_id
           ELSE target.acquisition_campaign_id
       END,
       acquisition_campaign = CASE
           WHEN target.acquisition_source IN ('unknown', 'direct', 'telegram')
               THEN source.acquisition_campaign
           ELSE target.acquisition_campaign
       END,
       acquired_at = least(target.acquired_at, source.acquired_at),
       updated_at = now()::text
  FROM contacts source
 WHERE (target.id, source.id) IN ((2, 67), (71, 72));

UPDATE telegram_identities SET contact_id = CASE contact_id WHEN 67 THEN 2 WHEN 72 THEN 71 END WHERE contact_id IN (67, 72);
UPDATE student_profiles SET contact_id = CASE contact_id WHEN 67 THEN 2 WHEN 72 THEN 71 END WHERE contact_id IN (67, 72);
UPDATE opportunities SET contact_id = CASE contact_id WHEN 67 THEN 2 WHEN 72 THEN 71 END WHERE contact_id IN (67, 72);
UPDATE payments SET contact_id = CASE contact_id WHEN 67 THEN 2 WHEN 72 THEN 71 END WHERE contact_id IN (67, 72);
UPDATE record_dates SET contact_id = CASE contact_id WHEN 67 THEN 2 WHEN 72 THEN 71 END WHERE contact_id IN (67, 72);
UPDATE regular_lessons SET contact_id = CASE contact_id WHEN 67 THEN 2 WHEN 72 THEN 71 END WHERE contact_id IN (67, 72);
UPDATE review_booking_requests SET contact_id = CASE contact_id WHEN 67 THEN 2 WHEN 72 THEN 71 END WHERE contact_id IN (67, 72);
UPDATE test_drive_enrollments SET contact_id = CASE contact_id WHEN 67 THEN 2 WHEN 72 THEN 71 END WHERE contact_id IN (67, 72);
UPDATE analytics_events SET contact_id = CASE contact_id WHEN 67 THEN 2 WHEN 72 THEN 71 END WHERE contact_id IN (67, 72);
UPDATE web_analytics_events SET contact_id = CASE contact_id WHEN 67 THEN 2 WHEN 72 THEN 71 END WHERE contact_id IN (67, 72);

DELETE FROM contacts WHERE id IN (67, 72);

COMMIT;

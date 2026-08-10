-- One-time compatibility cleanup.  `contacts` is the source of truth for a
-- client's name and phone; these legacy columns are only kept while old bot
-- code is being retired.
BEGIN;

UPDATE student_profiles AS sp
   SET first_name = c.first_name,
       last_name = c.last_name,
       full_name = concat_ws(' ', c.last_name, c.first_name),
       telephone = COALESCE(c.telephone, sp.telephone)
  FROM telegram_identities AS ti
  JOIN contacts AS c ON c.id = ti.contact_id
 WHERE sp.telegram_id = ti.telegram_id
   AND btrim(concat_ws(' ', c.last_name, c.first_name)) <> ''
   AND (
     sp.full_name IS DISTINCT FROM concat_ws(' ', c.last_name, c.first_name)
     OR sp.first_name IS DISTINCT FROM c.first_name
     OR sp.last_name IS DISTINCT FROM c.last_name
   );

UPDATE payments AS p
   SET full_name = concat_ws(' ', c.last_name, c.first_name)
  FROM telegram_identities AS ti
  JOIN contacts AS c ON c.id = ti.contact_id
 WHERE p.telegram_id = ti.telegram_id
   AND btrim(concat_ws(' ', c.last_name, c.first_name)) <> ''
   AND p.full_name IS DISTINCT FROM concat_ws(' ', c.last_name, c.first_name);

UPDATE regular_lessons AS rl
   SET full_name = concat_ws(' ', c.last_name, c.first_name)
  FROM telegram_identities AS ti
  JOIN contacts AS c ON c.id = ti.contact_id
 WHERE rl.telegram_id = ti.telegram_id
   AND btrim(concat_ws(' ', c.last_name, c.first_name)) <> ''
   AND rl.full_name IS DISTINCT FROM concat_ws(' ', c.last_name, c.first_name);

COMMIT;

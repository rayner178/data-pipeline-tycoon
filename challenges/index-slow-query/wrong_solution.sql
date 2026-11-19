SELECT
    id,
    kind,
    created_at
FROM events
WHERE CAST(user_id AS TEXT) = '42'
  AND created_at >= DATE '2026-08-01'
ORDER BY created_at ASC, id ASC;

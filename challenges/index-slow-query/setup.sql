CREATE TABLE events (
    id INT PRIMARY KEY,
    user_id INT NOT NULL,
    created_at DATE NOT NULL,
    kind TEXT NOT NULL
);
INSERT INTO events (id, user_id, created_at, kind)
SELECT
    g,
    (g % 250) + 1,
    (DATE '2026-01-01' + ((g % 360) * INTERVAL '1 day'))::date,
    CASE WHEN g % 3 = 0 THEN 'purchase' WHEN g % 2 = 0 THEN 'click' ELSE 'login' END
FROM generate_series(1, 5000) AS g;
CREATE INDEX idx_events_user_created ON events (user_id, created_at);
ANALYZE events;

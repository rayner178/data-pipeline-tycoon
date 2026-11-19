WITH ranked AS (
    SELECT
        customer_id,
        full_name,
        email,
        ROW_NUMBER() OVER (
            PARTITION BY customer_id
            ORDER BY updated_at DESC
        ) AS rn
    FROM staging_customers
)
SELECT
    customer_id,
    full_name,
    email
FROM ranked
WHERE rn = 1;

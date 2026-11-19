WITH order_totals AS (
    SELECT
        customer_id,
        SUM(total_amount) AS total_ordered
    FROM orders
    GROUP BY customer_id
),
payment_totals AS (
    SELECT
        o.customer_id,
        SUM(p.paid_amount) AS total_paid
    FROM orders o
    JOIN payments p ON p.order_id = o.id
    GROUP BY o.customer_id
)
SELECT
    c.id AS customer_id,
    c.name,
    ot.total_ordered,
    COALESCE(pt.total_paid, 0.00) AS total_paid
FROM customers c
JOIN order_totals ot ON ot.customer_id = c.id
LEFT JOIN payment_totals pt ON pt.customer_id = c.id;

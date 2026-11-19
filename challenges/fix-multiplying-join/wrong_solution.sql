SELECT
    c.id AS customer_id,
    c.name,
    SUM(o.total_amount) AS total_ordered,
    SUM(p.paid_amount) AS total_paid
FROM customers c
JOIN orders o ON o.customer_id = c.id
JOIN payments p ON p.order_id = o.id
GROUP BY c.id, c.name;

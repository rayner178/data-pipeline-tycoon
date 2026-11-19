CREATE TABLE staging_customers (
    customer_id INT NOT NULL,
    full_name TEXT NOT NULL,
    email TEXT,
    updated_at DATE NOT NULL
);
INSERT INTO staging_customers (customer_id, full_name, email, updated_at) VALUES
    (1, 'Ana Pérez', 'ana.old@example.com', '2026-01-10'),
    (1, 'Ana Pérez', 'ana@example.com', '2026-02-15'),
    (2, 'Luis Gómez', 'luis@example.com', '2026-01-20'),
    (2, 'Luis Gómez', 'luis.dup@example.com', '2026-01-05'),
    (3, 'Marta Díaz', NULL, '2026-03-01');

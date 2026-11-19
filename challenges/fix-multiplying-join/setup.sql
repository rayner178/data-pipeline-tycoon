CREATE TABLE customers (id INT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE orders (
    id INT PRIMARY KEY,
    customer_id INT NOT NULL REFERENCES customers(id),
    total_amount NUMERIC(10, 2) NOT NULL
);
CREATE TABLE payments (
    id INT PRIMARY KEY,
    order_id INT NOT NULL REFERENCES orders(id),
    paid_amount NUMERIC(10, 2) NOT NULL
);
INSERT INTO customers (id, name) VALUES
    (1, 'Comercial Norte'),
    (2, 'Distribuidora Sur');
INSERT INTO orders (id, customer_id, total_amount) VALUES
    (10, 1, 100.00),
    (11, 1, 50.00),
    (12, 2, 85.50);
INSERT INTO payments (id, order_id, paid_amount) VALUES
    (100, 10, 60.00),
    (101, 10, 40.00),
    (102, 11, 50.00),
    (103, 12, 85.50);

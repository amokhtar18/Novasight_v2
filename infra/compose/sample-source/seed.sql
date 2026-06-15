-- Sample SOURCE database for exercising the SQL-database ingestion pipeline.
--
-- This is NOT part of NovaSight's control plane. It stands in for a customer's
-- operational database: a small, realistic e-commerce schema that the
-- `sql_database` source connector can list, preview, and extract from. It lives
-- on the same Postgres container as the control plane only for dev convenience
-- (its own database, `nova_sample_source`), exactly as a real external source
-- would be a separate database the connector reaches over the network.
--
-- Idempotent: re-running drops and rebuilds the tables, so the row counts below
-- are deterministic. Run against the nova_sample_source database (see README.md).

BEGIN;

DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS customers CASCADE;

CREATE TABLE customers (
    id          integer PRIMARY KEY,
    name        text        NOT NULL,
    email       text        NOT NULL,
    country     text        NOT NULL,
    signup_date date        NOT NULL
);

CREATE TABLE products (
    id       integer PRIMARY KEY,
    name     text           NOT NULL,
    category text           NOT NULL,
    price    numeric(10, 2) NOT NULL
);

CREATE TABLE orders (
    id           integer PRIMARY KEY,
    customer_id  integer        NOT NULL REFERENCES customers (id),
    order_date   date           NOT NULL,
    status       text           NOT NULL,
    total_amount numeric(12, 2) NOT NULL DEFAULT 0
);

CREATE TABLE order_items (
    id         integer PRIMARY KEY,
    order_id   integer        NOT NULL REFERENCES orders (id),
    product_id integer        NOT NULL REFERENCES products (id),
    quantity   integer        NOT NULL,
    unit_price numeric(10, 2) NOT NULL
);

-- 200 customers across a handful of countries.
INSERT INTO customers (id, name, email, country, signup_date)
SELECT g,
       'Customer ' || g,
       'customer' || g || '@example.com',
       (ARRAY['US', 'GB', 'DE', 'FR', 'CA', 'AU', 'IN', 'BR'])[1 + (g % 8)],
       DATE '2023-01-01' + ((g * 7) % 730)
FROM generate_series(1, 200) AS g;

-- 40 products across 5 categories, deterministic prices.
INSERT INTO products (id, name, category, price)
SELECT g,
       'Product ' || g,
       (ARRAY['Electronics', 'Home', 'Apparel', 'Toys', 'Grocery'])[1 + (g % 5)],
       round((9.99 + (g % 30) * 5.5)::numeric, 2)
FROM generate_series(1, 40) AS g;

-- 1,000 orders over the last ~2 years, distributed across customers.
INSERT INTO orders (id, customer_id, order_date, status)
SELECT g,
       1 + (g * 37 % 200),
       DATE '2024-01-01' + (g % 540),
       (ARRAY['pending', 'paid', 'shipped', 'delivered', 'cancelled'])[1 + (g % 5)]
FROM generate_series(1, 1000) AS g;

-- 1–4 distinct line items per order; unit_price snapshots the product price.
INSERT INTO order_items (id, order_id, product_id, quantity, unit_price)
SELECT row_number() OVER () AS id,
       li.order_id,
       li.product_id,
       li.quantity,
       li.unit_price
FROM (
    SELECT o.id AS order_id,
           p.id AS product_id,
           1 + (o.id * p.id % 5) AS quantity,
           p.price AS unit_price
    FROM orders o
    CROSS JOIN LATERAL (
        SELECT id, price
        FROM products
        ORDER BY (o.id * 31 + products.id * 17) % 40
        LIMIT 1 + (o.id % 4)
    ) AS p
) AS li;

-- Roll the line-item totals up onto each order.
UPDATE orders o
SET total_amount = agg.total
FROM (
    SELECT order_id, SUM(quantity * unit_price) AS total
    FROM order_items
    GROUP BY order_id
) AS agg
WHERE o.id = agg.order_id;

COMMIT;

-- Quick visibility into what was loaded.
SELECT 'customers'   AS table_name, count(*) AS rows FROM customers
UNION ALL SELECT 'products',    count(*) FROM products
UNION ALL SELECT 'orders',      count(*) FROM orders
UNION ALL SELECT 'order_items', count(*) FROM order_items
ORDER BY table_name;

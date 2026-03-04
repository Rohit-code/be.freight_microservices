-- Optional: run this if orders table already exists without customer_id.
-- If the column already exists, the ALTER will fail; that is fine.

ALTER TABLE orders ADD COLUMN customer_id INTEGER;
CREATE INDEX IF NOT EXISTS ix_orders_customer_id ON orders (customer_id);

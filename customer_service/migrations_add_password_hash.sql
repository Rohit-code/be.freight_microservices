-- Add password_hash for customer portal login (nullable for existing/imported customers).
ALTER TABLE customers ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);

-- Migration: Add last_processed_history_id to users table
-- Run this manually or via Alembic

ALTER TABLE users ADD COLUMN IF NOT EXISTS last_processed_history_id VARCHAR(50) NULL;

-- Add index for faster lookups (optional)
CREATE INDEX IF NOT EXISTS idx_users_last_history_id ON users(last_processed_history_id) WHERE last_processed_history_id IS NOT NULL;

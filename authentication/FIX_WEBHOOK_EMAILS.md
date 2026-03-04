# Fix: Webhook Not Processing New Emails

## Problem

The webhook is working, but emails are being marked as "already processed" because:
1. The webhook provides the NEW historyId (after email was added)
2. The Gmail History API needs the PREVIOUS historyId to find new emails
3. Without storing the previous historyId, we can't query correctly
4. Falls back to list API which gets old emails that are already processed

## Solution

1. **Added `last_processed_history_id` field** to User model
2. **Store and use previous historyId** for Gmail History API queries
3. **Update stored historyId** after processing emails

## Database Migration Required

Run this migration to add the new field:

```sql
ALTER TABLE users ADD COLUMN last_processed_history_id VARCHAR(50) NULL;
```

Or create an Alembic migration:

```bash
cd authentication
alembic revision -m "add_last_processed_history_id"
```

Then edit the migration file to add:
```python
def upgrade():
    op.add_column('users', sa.Column('last_processed_history_id', sa.String(50), nullable=True))

def downgrade():
    op.drop_column('users', 'last_processed_history_id')
```

Run migration:
```bash
alembic upgrade head
```

## How It Works Now

1. **First webhook**: Uses `historyId - 1` as approximation
2. **Subsequent webhooks**: Uses stored `last_processed_history_id`
3. **After processing**: Updates `last_processed_history_id` to the new historyId

## Testing

After migration:
1. Send a test email
2. Check logs - should see "Found X new messages since historyId"
3. New emails should be processed, not skipped

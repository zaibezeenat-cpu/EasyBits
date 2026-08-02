-- supabase:disable-transaction
-- (ALTER TYPE ... ADD VALUE cannot run inside a transaction block; this tells the
--  Supabase CLI to apply the file outside one. Harmless in the SQL Editor.)
--
-- Add the failure categories that application code emits but the enum was
-- missing. Found by the Haier pilot (2026-07-22): a warranty_conflict escalation
-- failed with "invalid input value for enum manual_review_reason_code", leaving
-- the product stranded in QUEUED.
--
-- The application repository (manual_review.py) tolerates the gap by falling
-- back to 'other', but these should be first-class so the review queue can be
-- filtered by them and the reviewer sees the true reason without parsing detail.
--
-- ALTER TYPE ... ADD VALUE cannot run inside a transaction block, so each
-- statement stands alone. IF NOT EXISTS makes this safe to re-run.

ALTER TYPE manual_review_reason_code ADD VALUE IF NOT EXISTS 'warranty_conflict';
ALTER TYPE manual_review_reason_code ADD VALUE IF NOT EXISTS 'brand_casing_mismatch';
ALTER TYPE manual_review_reason_code ADD VALUE IF NOT EXISTS 'production_lock_violation';

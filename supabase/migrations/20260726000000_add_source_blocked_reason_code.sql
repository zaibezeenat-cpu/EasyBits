-- supabase:disable-transaction
-- (ALTER TYPE ... ADD VALUE cannot run inside a transaction block; this tells the
--  Supabase CLI to apply the file outside one. Harmless in the SQL Editor.)
--
-- Adds `source_blocked`: a source served an anti-bot / CAPTCHA challenge
-- (Cloudflare etc.) instead of the product. Kept distinct from
-- `source_unreachable` so the reviewer knows the fix is to paste the product's
-- Details, not that the product is simply unlisted. The application repository
-- (manual_review.py) already tolerates the gap by falling back to 'other'; this
-- makes it first-class so the queue can be filtered by it.
--
-- ALTER TYPE ... ADD VALUE cannot run inside a transaction block. IF NOT EXISTS
-- makes this safe to re-run.

ALTER TYPE manual_review_reason_code ADD VALUE IF NOT EXISTS 'source_blocked';

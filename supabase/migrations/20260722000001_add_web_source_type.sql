-- supabase:disable-transaction
-- (ALTER TYPE ... ADD VALUE cannot run inside a transaction block; this directive
--  makes the Supabase CLI apply it outside one. Harmless in the SQL Editor.)
--
-- Add the 'web' source type: an unvetted page discovered via broad Google
-- Programmable Search. Citations from such pages are persisted with this type
-- so the corroboration layer can weight them lowest (accepted only with
-- corroboration or under priority source-mode).
--
-- ALTER TYPE ... ADD VALUE cannot run inside a transaction block. IF NOT EXISTS
-- makes this safe to re-run.

ALTER TYPE source_type ADD VALUE IF NOT EXISTS 'web';

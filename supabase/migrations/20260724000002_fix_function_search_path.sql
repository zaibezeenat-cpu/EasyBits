-- Fixes the Supabase linter WARN `function_search_path_mutable` on the
-- update_updated_at_column trigger function (defined in complete_schema.sql).
--
-- A function with a mutable search_path can be tricked into resolving an object
-- name to an attacker-planted one. Pinning search_path to empty removes that
-- vector. The function body only calls now() (pg_catalog, always implicitly
-- searched) and the trigger's NEW record, so an empty search_path is safe.
--
-- Ref: https://supabase.com/docs/guides/database/database-linter?lint=0011
ALTER FUNCTION public.update_updated_at_column() SET search_path = '';

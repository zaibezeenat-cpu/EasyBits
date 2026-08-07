-- supabase:disable-transaction
-- (ALTER TYPE ... ADD VALUE cannot run inside a transaction block; this tells the
--  Supabase CLI to apply the file outside one. Harmless in the SQL Editor.)
--
-- Adds `inferred`: the value was DEDUCED from described features rather than
-- stated by any source. A vacuum listed with "flexible hose, extension tube, big
-- dust bag" is a canister even though no page prints the word.
--
-- Kept distinct from `confirmed` deliberately. Every guard downstream keys off
-- confirmed-ness, so folding a deduction into it would silently grant an
-- inference the standing of a verified fact -- the one thing the no-hallucination
-- design exists to prevent. `inferred` values publish, but they are visible as
-- inferences in the citation trail and in the CLI run report, and only for fields
-- the category schema marks `inferable` (never a wattage or a capacity).
--
-- ALTER TYPE ... ADD VALUE cannot run inside a transaction block. IF NOT EXISTS
-- makes this safe to re-run.

ALTER TYPE confidence_level ADD VALUE IF NOT EXISTS 'inferred';

-- The evidence an inference rests on. SourceCitation requires it whenever
-- confidence='inferred' (a deduction with nothing behind it is a guess), so the
-- table has to be able to hold it.
--
-- Nothing writes to source_citations today -- the pipeline persists citations
-- inside products.extraction_result, which is JSONB and accepts any shape -- so
-- this is not fixing a live failure. It is keeping the table in step with the
-- model, so that wiring citations_repo.create_many() later does not fail on an
-- unknown column. Nullable: only inferred citations carry a quote.
ALTER TABLE source_citations ADD COLUMN IF NOT EXISTS exact_quote TEXT;

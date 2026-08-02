-- Optional display casing for a brand, used ONLY in the product title
-- ("Haier"), while the Brands taxonomy term stays exact ("HAIER"). Nullable, so
-- brands without one fall back to the taxonomy term. Safe to re-run.
ALTER TABLE brands ADD COLUMN IF NOT EXISTS display_name TEXT;

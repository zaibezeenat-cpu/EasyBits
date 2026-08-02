-- Production hardening, verified against the supabase-performance-tuning and
-- supabase-security-basics skills.
--
-- INDEXES: Postgres indexes primary keys and UNIQUE constraints automatically,
-- but NOT plain foreign keys. These are the FK / filter columns the application
-- actually queries and that had no index yet (source_citations.product_id and
-- audit_log.product_id/batch_id already have theirs in the base schema).
--
-- Regular CREATE INDEX (not CONCURRENTLY) because these tables are small today,
-- so the build is instant with no meaningful write lock. Switch to
-- CREATE INDEX CONCURRENTLY (with -- supabase:disable-transaction) only once a
-- table grows large, per the performance skill.
-- IF NOT EXISTS keeps this safe to re-run.

-- Hottest query: products fetched by batch (BatchProcessor, batch views).
CREATE INDEX IF NOT EXISTS idx_products_batch_id ON products(batch_id);

-- Review Queue and Ready-for-QA lists filter by status.
CREATE INDEX IF NOT EXISTS idx_products_status ON products(status);

-- Warranty lookup is by brand (+ category).
CREATE INDEX IF NOT EXISTS idx_warranty_matrix_brand_id ON warranty_matrix(brand_id);

-- Category tree is assembled by parent.
CREATE INDEX IF NOT EXISTS idx_categories_parent_id ON categories(parent_id);

-- Audit log is listed newest-first.
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at DESC);

-- FK columns on a delete path from tables that DO get deleted (batches,
-- products). Without these, deleting a batch or product scans these children to
-- CASCADE / SET NULL. (Base schema already indexes source_citations.product_id,
-- audit_log.product_id/batch_id; manual_review_queue.product_id is UNIQUE.)
CREATE INDEX IF NOT EXISTS idx_manual_review_queue_batch_id ON manual_review_queue(batch_id);
CREATE INDEX IF NOT EXISTS idx_llm_usage_log_product_id ON llm_usage_log(product_id);
CREATE INDEX IF NOT EXISTS idx_scrape_cache_product_id ON scrape_cache(product_id);

-- Remaining FK columns for completeness (base-schema audit vs the postgres
-- best-practices skill): csv_exports cascades from a deleted batch; products'
-- brand/category FKs are RESTRICT-checked when a brand or category is deleted.
CREATE INDEX IF NOT EXISTS idx_csv_exports_batch_id ON csv_exports(batch_id);
CREATE INDEX IF NOT EXISTS idx_products_brand_id ON products(brand_id);
CREATE INDEX IF NOT EXISTS idx_products_category_id ON products(category_id);

-- STATEMENT TIMEOUT (defence in depth): this app is backend-only via the
-- service_role key -- the public `anon` / `authenticated` roles are never used.
-- Capping their query time means that even if the anon key were ever exposed, a
-- request could not tie up the database. service_role is deliberately left
-- unlimited so the pipeline's own operations are never cut off mid-run.
ALTER ROLE anon SET statement_timeout = '5s';
ALTER ROLE authenticated SET statement_timeout = '10s';

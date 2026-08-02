-- Migration: Add RLS policies for service_role
-- Closing security gap identified in Phase 2 audit

-- 1. Brands
CREATE POLICY "service_role_all" ON brands FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 2. Categories
CREATE POLICY "service_role_all" ON categories FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 3. Category Spec Schemas
CREATE POLICY "service_role_all" ON category_spec_schemas FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 4. Warranty Matrix
CREATE POLICY "service_role_all" ON warranty_matrix FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 5. Trusted Secondary Sources
CREATE POLICY "service_role_all" ON trusted_secondary_sources FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 6. Brand Domain Aliases
CREATE POLICY "service_role_all" ON brand_domain_aliases FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 7. Templates
CREATE POLICY "service_role_all" ON templates FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 8. Batches
CREATE POLICY "service_role_all" ON batches FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 9. Products
CREATE POLICY "service_role_all" ON products FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 10. Source Citations
CREATE POLICY "service_role_all" ON source_citations FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 11. Manual Review Queue
CREATE POLICY "service_role_all" ON manual_review_queue FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 12. Audit Log
CREATE POLICY "service_role_all" ON audit_log FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 13. CSV Exports
CREATE POLICY "service_role_all" ON csv_exports FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 14. Live SKU Snapshot
CREATE POLICY "service_role_all" ON live_sku_snapshot FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 15. LLM Model Config
CREATE POLICY "service_role_all" ON llm_model_config FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 16. LLM Usage Log
CREATE POLICY "service_role_all" ON llm_usage_log FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 17. App Settings
CREATE POLICY "service_role_all" ON app_settings FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 18. Scrape Cache
CREATE POLICY "service_role_all" ON scrape_cache FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 19. Checkpoints (from complete_schema.sql section 7)
-- Note: Checkpoints table was missed in the RLS enable list in complete_schema.sql
ALTER TABLE checkpoints ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all" ON checkpoints FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 1. Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 2. Enums
CREATE TYPE batch_status AS ENUM ('pending', 'processing', 'completed', 'completed_with_failures', 'paused_budget_exceeded');
CREATE TYPE product_status AS ENUM ('queued', 'scraping', 'extracting', 'writing', 'reviewing', 'ready_for_qa', 'manual_review', 'approved', 'exported', 'failed');
CREATE TYPE manual_review_reason_code AS ENUM (
    'source_unreachable', 'no_reliable_source_found', 'spec_conflict', 'variant_shaped', 
    'sku_collision', 'writer_reviewer_exhausted', 'preflight_score_low', 
    'missing_category_schema', 'missing_taxonomy_match', 'other'
);
CREATE TYPE source_type AS ENUM ('official', 'trusted_secondary', 'user_estimate');
CREATE TYPE confidence_level AS ENUM ('confirmed', 'conflicting', 'unreachable');

-- 3. Taxonomy Tables
CREATE TABLE brands (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT UNIQUE NOT NULL,
    casing_confirmed BOOLEAN DEFAULT false,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    parent_id UUID REFERENCES categories(id),
    is_active BOOLEAN DEFAULT true,
    needs_confirmation BOOLEAN DEFAULT true,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(name, parent_id)
);

CREATE TABLE category_spec_schemas (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    category_id UUID UNIQUE REFERENCES categories(id) ON DELETE CASCADE,
    fields JSONB NOT NULL, -- list of {key, label, required}
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE warranty_matrix (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    brand_id UUID REFERENCES brands(id) ON DELETE CASCADE,
    category_id UUID REFERENCES categories(id) ON DELETE CASCADE, -- null allowed for brand-wide default
    warranty_phrase TEXT NOT NULL,
    last_audited_at DATE DEFAULT CURRENT_DATE,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE UNIQUE INDEX idx_warranty_matrix_brand_cat ON warranty_matrix (brand_id, category_id) WHERE is_active;

CREATE TABLE trusted_secondary_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    priority INT DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE brand_domain_aliases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    brand_id UUID UNIQUE REFERENCES brands(id) ON DELETE CASCADE,
    official_domain TEXT NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 4. Templates
CREATE TABLE templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    template_type TEXT CHECK (template_type IN ('short_description', 'long_description_a', 'long_description_b', 'specs_table')),
    name TEXT NOT NULL,
    html_skeleton TEXT NOT NULL,
    is_default BOOLEAN DEFAULT false,
    is_active BOOLEAN DEFAULT true,
    version INT DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 5. Batches & Products
CREATE TABLE batches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    label TEXT NOT NULL,
    status batch_status DEFAULT 'pending',
    total_products INT DEFAULT 0,
    succeeded_count INT DEFAULT 0,
    failed_count INT DEFAULT 0,
    manual_review_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE products (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    batch_id UUID REFERENCES batches(id) ON DELETE CASCADE,
    sku TEXT NOT NULL, -- Duplicate check against snapshot, but allowed in DB for history
    model_number TEXT,
    raw_input JSONB,
    status product_status DEFAULT 'queued',
    variant_shaped BOOLEAN DEFAULT false,
    
    brand_id UUID REFERENCES brands(id),
    category_id UUID REFERENCES categories(id),
    template_long_desc_id UUID REFERENCES templates(id),
    
    image_count INT DEFAULT 0,
    scraped_image_urls JSONB DEFAULT '[]',
    
    name TEXT,
    short_description TEXT,
    description TEXT,
    specs_table_html TEXT,
    
    rank_math_focus_keyword TEXT,
    rank_math_title TEXT,
    rank_math_description TEXT,
    
    weight_kg NUMERIC(8,2) DEFAULT 0.0,
    length_cm NUMERIC(8,2) DEFAULT 0.0,
    width_cm NUMERIC(8,2) DEFAULT 0.0,
    height_cm NUMERIC(8,2) DEFAULT 0.0,
    
    regular_price NUMERIC(12,2),
    sale_price NUMERIC(12,2),
    in_stock BOOLEAN DEFAULT true,
    
    warranty_override TEXT,
    resolved_warranty_phrase TEXT,
    price_discrepancy_pct NUMERIC(5,2),
    
    extraction_result JSONB DEFAULT '{}',
    writer_result JSONB DEFAULT '{}',
    review_result JSONB DEFAULT '{}',
    
    preflight_score INT DEFAULT 0,
    retry_count INT DEFAULT 0,
    
    failure_reason TEXT,
    failure_detail JSONB DEFAULT '{}',
    
    csv_row JSONB DEFAULT '{}',
    
    queued_at TIMESTAMPTZ DEFAULT now(),
    ready_for_qa_at TIMESTAMPTZ,
    approved_at TIMESTAMPTZ,
    approved_by TEXT,
    exported_at TIMESTAMPTZ,
    
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 6. Supporting Tables
CREATE TABLE source_citations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id UUID REFERENCES products(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    value TEXT,
    source_url TEXT,
    source_type source_type NOT NULL,
    confidence confidence_level NOT NULL,
    conflicting_with_citation_id UUID REFERENCES source_citations(id),
    fetched_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_citations_product_id ON source_citations(product_id);

CREATE TABLE manual_review_queue (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id UUID UNIQUE REFERENCES products(id) ON DELETE CASCADE,
    batch_id UUID REFERENCES batches(id) ON DELETE CASCADE,
    reason_code manual_review_reason_code NOT NULL,
    reason_detail TEXT NOT NULL,
    status TEXT CHECK (status IN ('open', 'resolved', 'dismissed')) DEFAULT 'open',
    resolved_at TIMESTAMPTZ,
    resolution_note TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_manual_review_status ON manual_review_queue(status) WHERE status = 'open';

CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    product_id UUID REFERENCES products(id) ON DELETE SET NULL,
    batch_id UUID REFERENCES batches(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    actor TEXT DEFAULT 'system',
    payload JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_audit_log_product ON audit_log(product_id);
CREATE INDEX idx_audit_log_batch ON audit_log(batch_id);

CREATE TABLE csv_exports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    batch_id UUID REFERENCES batches(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    product_ids JSONB NOT NULL,
    row_count INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE live_sku_snapshot (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sku TEXT UNIQUE NOT NULL,
    wc_product_id TEXT,
    imported_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE llm_model_config (
    role TEXT PRIMARY KEY CHECK (role IN ('extractor', 'writer', 'reviewer')),
    primary_provider TEXT NOT NULL,
    primary_model_id TEXT NOT NULL,
    fallback_provider TEXT,
    fallback_model_id TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE llm_usage_log (
    id BIGSERIAL PRIMARY KEY,
    product_id UUID REFERENCES products(id) ON DELETE SET NULL,
    role TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_tokens INT DEFAULT 0,
    completion_tokens INT DEFAULT 0,
    total_tokens INT DEFAULT 0,
    estimated_cost_usd NUMERIC(10,6) DEFAULT 0.0,
    latency_ms INT,
    was_fallback BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE scrape_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_url TEXT NOT NULL,
    product_id UUID REFERENCES products(id) ON DELETE SET NULL,
    raw_content TEXT,
    status TEXT CHECK (status IN ('success', 'unreachable', 'blocked')),
    fetched_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_scrape_cache_url ON scrape_cache(source_url);

-- 7. LangGraph Checkpoints
CREATE TABLE checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    parent_id TEXT,
    checkpoint BYTEA NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (thread_id, checkpoint_id)
);

-- 8. Functions & Triggers
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_brands_updated_at BEFORE UPDATE ON brands FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();
CREATE TRIGGER update_categories_updated_at BEFORE UPDATE ON categories FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();
CREATE TRIGGER update_batches_updated_at BEFORE UPDATE ON batches FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();
CREATE TRIGGER update_products_updated_at BEFORE UPDATE ON products FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();
CREATE TRIGGER update_app_settings_updated_at BEFORE UPDATE ON app_settings FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();

-- 9. Row Level Security (RLS)
ALTER TABLE brands ENABLE ROW LEVEL SECURITY;
ALTER TABLE categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE category_spec_schemas ENABLE ROW LEVEL SECURITY;
ALTER TABLE warranty_matrix ENABLE ROW LEVEL SECURITY;
ALTER TABLE trusted_secondary_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE brand_domain_aliases ENABLE ROW LEVEL SECURITY;
ALTER TABLE templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_citations ENABLE ROW LEVEL SECURITY;
ALTER TABLE manual_review_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE csv_exports ENABLE ROW LEVEL SECURITY;
ALTER TABLE live_sku_snapshot ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_model_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_usage_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE scrape_cache ENABLE ROW LEVEL SECURITY;

-- 10. Seed Data
INSERT INTO app_settings (key, value) VALUES 
('trust_level', '"full_review"'),
('rank_math_title_format', '"{name} | Best Price"'),
('monthly_api_budget_usd', '5.00'),
('live_sku_last_synced_at', 'null');

INSERT INTO trusted_secondary_sources (domain, label, priority) VALUES
('japanelectronics.pk', 'Japan Electronics', 1),
('surmawala.pk', 'Surmawala', 2);

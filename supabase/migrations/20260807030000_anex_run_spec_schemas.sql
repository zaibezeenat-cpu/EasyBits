-- Spec schemas for the 296-product Anex run.
--
-- WITHOUT THIS, 46 products escalate at intake with missing_category_schema and
-- Hand Blender extracts against the wrong (hand-operated) schema.
--
-- Written as a migration rather than `python scripts/seed_taxonomy.py`:
-- seed_spec_schemas() upserts on category_id and REPLACES the whole `fields`
-- array for every category, destroying edits made in the Taxonomy Manager --
-- including `inferable`, which _spec() does not emit at all. Each statement
-- here touches exactly one category.
--
-- Idempotent: the UPDATE is a no-op if already applied, the INSERTs use
-- ON CONFLICT DO NOTHING. Safe to re-run.
--
-- Generated from SPEC_SCHEMAS in scripts/seed_taxonomy.py, not hand-typed.
-- Keep the two in step if either changes.
--
-- WHY SO FEW REQUIRED FIELDS: a required field is a stop sign -- no source, no
-- product. These categories hold heterogeneous items ("Hand Mixer" beside
-- "Stand Mixer 1500W 7L"; "Handy Food Processor", which is hand-cranked, beside
-- powered ones), so demanding a wattage of all of them fails the ones that have
-- no motor. Optional fields are still extracted and still published when found;
-- optional means "do not block", not "do not look".


-- Hand Blender: immersion blender -- ELECTRIC, wattage required. REPLACES the earlier hand-operated schema, which was wrong: Anex's own line reads 'With Milk Frother' / 'With Titanium Blade' / 'With Beater'.
UPDATE category_spec_schemas s
SET fields = '[{"key":"brand","label":"Brand","required":true},{"key":"model_number","label":"Model Number","required":true},{"key":"wattage","label":"Wattage","required":true},{"key":"capacity","label":"Beaker Capacity","required":false},{"key":"speeds","label":"Speeds","required":false},{"key":"blades","label":"Blades","required":false},{"key":"material","label":"Material","required":false},{"key":"features","label":"Features","required":false},{"key":"weight_kg","label":"Weight (kg)","required":false},{"key":"length_cm","label":"Length (cm)","required":false},{"key":"width_cm","label":"Width (cm)","required":false},{"key":"height_cm","label":"Height (cm)","required":false}]'::jsonb, updated_at = now()
FROM categories c
WHERE s.category_id = c.id AND c.name = 'Hand Blender'
  AND c.parent_id = (SELECT id FROM categories WHERE name = 'Kitchen Appliances' AND parent_id IS NULL);

-- Toaster: sandwich, waffle and sandwich/waffle/grill makers -- 15 Anex products. Operator-directed: the live store files these under Toaster.
INSERT INTO category_spec_schemas (category_id, fields)
SELECT c.id, '[{"key":"brand","label":"Brand","required":true},{"key":"model_number","label":"Model Number","required":true},{"key":"wattage","label":"Wattage","required":true},{"key":"slices","label":"Slices","required":false},{"key":"plate_type","label":"Plate Type","required":false},{"key":"features","label":"Features","required":false},{"key":"weight_kg","label":"Weight (kg)","required":false},{"key":"length_cm","label":"Length (cm)","required":false},{"key":"width_cm","label":"Width (cm)","required":false},{"key":"height_cm","label":"Height (cm)","required":false}]'::jsonb
FROM categories c
WHERE c.name = 'Toaster'
  AND c.parent_id = (SELECT id FROM categories WHERE name = 'Kitchen Appliances' AND parent_id IS NULL)
ON CONFLICT (category_id) DO NOTHING;

-- Garment Streamer: handheld garment steamers -- 6 products. The store spells the category 'Streamer'; every product title says 'Steamer'.
INSERT INTO category_spec_schemas (category_id, fields)
SELECT c.id, '[{"key":"brand","label":"Brand","required":true},{"key":"model_number","label":"Model Number","required":true},{"key":"wattage","label":"Wattage","required":true},{"key":"capacity","label":"Water Tank Capacity","required":false},{"key":"steam_output","label":"Steam Output","required":false},{"key":"features","label":"Features","required":false},{"key":"weight_kg","label":"Weight (kg)","required":false},{"key":"length_cm","label":"Length (cm)","required":false},{"key":"width_cm","label":"Width (cm)","required":false},{"key":"height_cm","label":"Height (cm)","required":false}]'::jsonb
FROM categories c
WHERE c.name = 'Garment Streamer'
  AND c.parent_id IS NULL
ON CONFLICT (category_id) DO NOTHING;

-- Kitchen Appliances: CATCH-ALL for products the store has no category for (kitchen robots, egg beaters, BBQ grills, slicers, multi-function combos) -- 59 products.
INSERT INTO category_spec_schemas (category_id, fields)
SELECT c.id, '[{"key":"brand","label":"Brand","required":true},{"key":"model_number","label":"Model Number","required":true},{"key":"appliance_type","label":"Appliance Type","required":true},{"key":"wattage","label":"Wattage","required":false},{"key":"capacity","label":"Capacity","required":false},{"key":"material","label":"Material","required":false},{"key":"features","label":"Features","required":false},{"key":"weight_kg","label":"Weight (kg)","required":false},{"key":"length_cm","label":"Length (cm)","required":false},{"key":"width_cm","label":"Width (cm)","required":false},{"key":"height_cm","label":"Height (cm)","required":false}]'::jsonb
FROM categories c
WHERE c.name = 'Kitchen Appliances'
  AND c.parent_id IS NULL
ON CONFLICT (category_id) DO NOTHING;

-- Grinder: 16 products.
INSERT INTO category_spec_schemas (category_id, fields)
SELECT c.id, '[{"key":"brand","label":"Brand","required":true},{"key":"model_number","label":"Model Number","required":true},{"key":"appliance_type","label":"Appliance Type","required":true},{"key":"wattage","label":"Wattage","required":false},{"key":"grinder_type","label":"Wet / Dry","required":false},{"key":"jars","label":"Jars","required":false},{"key":"material","label":"Body / Jar Material","required":false},{"key":"features","label":"Features","required":false},{"key":"weight_kg","label":"Weight (kg)","required":false},{"key":"length_cm","label":"Length (cm)","required":false},{"key":"width_cm","label":"Width (cm)","required":false},{"key":"height_cm","label":"Height (cm)","required":false}]'::jsonb
FROM categories c
WHERE c.name = 'Grinder'
  AND c.parent_id = (SELECT id FROM categories WHERE name = 'Kitchen Appliances' AND parent_id IS NULL)
ON CONFLICT (category_id) DO NOTHING;

-- Juicer: 13 products.
INSERT INTO category_spec_schemas (category_id, fields)
SELECT c.id, '[{"key":"brand","label":"Brand","required":true},{"key":"model_number","label":"Model Number","required":true},{"key":"appliance_type","label":"Appliance Type","required":true},{"key":"wattage","label":"Wattage","required":false},{"key":"capacity","label":"Jug Capacity","required":false},{"key":"speeds","label":"Speeds","required":false},{"key":"material","label":"Body Material","required":false},{"key":"features","label":"Features","required":false},{"key":"weight_kg","label":"Weight (kg)","required":false},{"key":"length_cm","label":"Length (cm)","required":false},{"key":"width_cm","label":"Width (cm)","required":false},{"key":"height_cm","label":"Height (cm)","required":false}]'::jsonb
FROM categories c
WHERE c.name = 'Juicer'
  AND c.parent_id = (SELECT id FROM categories WHERE name = 'Kitchen Appliances' AND parent_id IS NULL)
ON CONFLICT (category_id) DO NOTHING;

-- Cooker: 6 products.
INSERT INTO category_spec_schemas (category_id, fields)
SELECT c.id, '[{"key":"brand","label":"Brand","required":true},{"key":"model_number","label":"Model Number","required":true},{"key":"appliance_type","label":"Appliance Type","required":true},{"key":"capacity","label":"Capacity","required":false},{"key":"wattage","label":"Wattage","required":false},{"key":"material","label":"Inner Pot Material","required":false},{"key":"features","label":"Features","required":false},{"key":"weight_kg","label":"Weight (kg)","required":false},{"key":"length_cm","label":"Length (cm)","required":false},{"key":"width_cm","label":"Width (cm)","required":false},{"key":"height_cm","label":"Height (cm)","required":false}]'::jsonb
FROM categories c
WHERE c.name = 'Cooker'
  AND c.parent_id = (SELECT id FROM categories WHERE name = 'Kitchen Appliances' AND parent_id IS NULL)
ON CONFLICT (category_id) DO NOTHING;

-- Mixer: 5 products.
INSERT INTO category_spec_schemas (category_id, fields)
SELECT c.id, '[{"key":"brand","label":"Brand","required":true},{"key":"model_number","label":"Model Number","required":true},{"key":"appliance_type","label":"Appliance Type","required":true},{"key":"wattage","label":"Wattage","required":false},{"key":"capacity","label":"Bowl Capacity","required":false},{"key":"speeds","label":"Speeds","required":false},{"key":"material","label":"Bowl Material","required":false},{"key":"features","label":"Features","required":false},{"key":"weight_kg","label":"Weight (kg)","required":false},{"key":"length_cm","label":"Length (cm)","required":false},{"key":"width_cm","label":"Width (cm)","required":false},{"key":"height_cm","label":"Height (cm)","required":false}]'::jsonb
FROM categories c
WHERE c.name = 'Mixer'
  AND c.parent_id = (SELECT id FROM categories WHERE name = 'Kitchen Appliances' AND parent_id IS NULL)
ON CONFLICT (category_id) DO NOTHING;

-- Food Processor: 3 products.
INSERT INTO category_spec_schemas (category_id, fields)
SELECT c.id, '[{"key":"brand","label":"Brand","required":true},{"key":"model_number","label":"Model Number","required":true},{"key":"appliance_type","label":"Appliance Type","required":true},{"key":"wattage","label":"Wattage","required":false},{"key":"capacity","label":"Bowl Capacity","required":false},{"key":"attachments","label":"Attachments","required":false},{"key":"features","label":"Features","required":false},{"key":"weight_kg","label":"Weight (kg)","required":false},{"key":"length_cm","label":"Length (cm)","required":false},{"key":"width_cm","label":"Width (cm)","required":false},{"key":"height_cm","label":"Height (cm)","required":false}]'::jsonb
FROM categories c
WHERE c.name = 'Food Processor'
  AND c.parent_id = (SELECT id FROM categories WHERE name = 'Kitchen Appliances' AND parent_id IS NULL)
ON CONFLICT (category_id) DO NOTHING;

-- Roti Maker: 2 products.
INSERT INTO category_spec_schemas (category_id, fields)
SELECT c.id, '[{"key":"brand","label":"Brand","required":true},{"key":"model_number","label":"Model Number","required":true},{"key":"appliance_type","label":"Appliance Type","required":true},{"key":"wattage","label":"Wattage","required":false},{"key":"plate_size","label":"Plate Size","required":false},{"key":"material","label":"Plate Material","required":false},{"key":"features","label":"Features","required":false},{"key":"weight_kg","label":"Weight (kg)","required":false},{"key":"length_cm","label":"Length (cm)","required":false},{"key":"width_cm","label":"Width (cm)","required":false},{"key":"height_cm","label":"Height (cm)","required":false}]'::jsonb
FROM categories c
WHERE c.name = 'Roti Maker'
  AND c.parent_id = (SELECT id FROM categories WHERE name = 'Kitchen Appliances' AND parent_id IS NULL)
ON CONFLICT (category_id) DO NOTHING;

-- Pizza Pan: 1 product.
INSERT INTO category_spec_schemas (category_id, fields)
SELECT c.id, '[{"key":"brand","label":"Brand","required":true},{"key":"model_number","label":"Model Number","required":true},{"key":"appliance_type","label":"Appliance Type","required":true},{"key":"wattage","label":"Wattage","required":false},{"key":"diameter","label":"Diameter","required":false},{"key":"material","label":"Surface Material","required":false},{"key":"features","label":"Features","required":false},{"key":"weight_kg","label":"Weight (kg)","required":false},{"key":"length_cm","label":"Length (cm)","required":false},{"key":"width_cm","label":"Width (cm)","required":false},{"key":"height_cm","label":"Height (cm)","required":false}]'::jsonb
FROM categories c
WHERE c.name = 'Pizza Pan'
  AND c.parent_id = (SELECT id FROM categories WHERE name = 'Kitchen Appliances' AND parent_id IS NULL)
ON CONFLICT (category_id) DO NOTHING;


-- VERIFY -- every one of these must come back has_schema = true:
--   SELECT c.name, (s.category_id IS NOT NULL) AS has_schema
--   FROM categories c
--   LEFT JOIN category_spec_schemas s ON s.category_id = c.id
--   WHERE c.name IN ('Hand Blender','Hand Chopper','Toaster','Garment Streamer',
--                    'Kitchen Appliances','Grinder','Juicer','Cooker','Mixer',
--                    'Food Processor','Roti Maker','Pizza Pan','Beauty',
--                    'Garment Steam Iron')
--   ORDER BY c.name;

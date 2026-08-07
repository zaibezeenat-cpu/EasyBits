-- The spec schema for Hand Blender.
--
-- WHY THIS IS A MIGRATION AND NOT `python scripts/seed_taxonomy.py`
-- seed_spec_schemas() upserts on category_id and REPLACES the whole `fields`
-- array for all 30+ categories. Any edit made in the Taxonomy Manager since the
-- last seed is destroyed by it -- notably `inferable`, which _spec() does not
-- emit at all, so a field marked inferable there comes back plain. Creating one
-- missing row must not cost the operator every customisation they have made.
--
-- Mirrors SPEC_SCHEMAS["Hand Blender"] in scripts/seed_taxonomy.py exactly,
-- plus DIMENSION_FIELDS. Keep the two in step if either changes.
--
-- NO WATTAGE FIELD, deliberately: a hand blender has no motor. That absence is
-- the entire reason the category is separate from "Blender" -- the electric
-- schema marks wattage required, which sent every hand-operated product to
-- Manual Review for a fact it can never have.
--
-- Every field is required=false. Nothing about a hand blender is reliably
-- published by Pakistani retailers, and a required field with no source is a
-- guaranteed Manual Review.
--
-- Safe to re-run: does nothing if Hand Blender already has a schema.

INSERT INTO category_spec_schemas (category_id, fields)
SELECT c.id, '[
  {"key": "brand",          "label": "Brand",          "required": true},
  {"key": "model_number",   "label": "Model Number",   "required": true},
  {"key": "capacity",       "label": "Capacity",       "required": false},
  {"key": "blades",         "label": "Blades",         "required": false},
  {"key": "operation_type", "label": "Operation Type", "required": false},
  {"key": "material",       "label": "Material",       "required": false},
  {"key": "features",       "label": "Features",       "required": false},
  {"key": "weight_kg",      "label": "Weight (kg)",    "required": false},
  {"key": "length_cm",      "label": "Length (cm)",    "required": false},
  {"key": "width_cm",       "label": "Width (cm)",     "required": false},
  {"key": "height_cm",      "label": "Height (cm)",    "required": false}
]'::jsonb
FROM categories c
WHERE c.name = 'Hand Blender'
ON CONFLICT (category_id) DO NOTHING;

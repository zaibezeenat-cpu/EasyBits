-- Renames "Manual Chopper" -> "Hand Chopper" and adds "Hand Blender".
--
-- WHY THESE CATEGORIES EXIST AT ALL
-- A hand-operated chopper or blender has no motor, so it has no wattage. The
-- electric "Chopper"/"Blender" spec schemas mark wattage required, which sent
-- every hand-operated product to Manual Review for a fact it can never have.
-- Giving them their own category lets each carry its own spec schema.
--
-- They are PIPELINE categories only. csv_assembler.STORE_CATEGORY_ALIASES
-- translates them back to the live store's "Chopper"/"Blender" on export, so no
-- new category appears in WooCommerce.
--
-- Casing is exact and deliberate: WooCommerce matches taxonomy terms by exact
-- string, and the Category Casing Lock compares against these rows.
--
-- Safe to re-run: the rename is a no-op once applied, and the insert is guarded.

-- 1. Rename the existing category, preserving its id -- products, spec schemas
--    and citations all reference it by id, so nothing downstream breaks.
UPDATE categories
SET name = 'Hand Chopper'
WHERE name = 'Manual Chopper';

-- 2. Add Hand Blender under the same parent as Blender, so its breadcrumb is
--    "Kitchen Appliances > Hand Blender" and the store alias resolves.
INSERT INTO categories (name, parent_id, is_active)
SELECT 'Hand Blender', parent_id, TRUE
FROM categories
WHERE name = 'Blender'
  AND NOT EXISTS (SELECT 1 FROM categories WHERE name = 'Hand Blender');

-- After applying, seed the two spec schemas from scripts/seed_taxonomy.py
-- (Hand Chopper keeps the one Manual Chopper already had; Hand Blender needs a
-- new one). Without a schema a category routes its products to Manual Review
-- with missing_category_schema.

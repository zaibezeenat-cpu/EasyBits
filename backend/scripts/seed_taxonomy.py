"""
Seeds brands, categories (with parent mapping), and category spec schemas.

CRITICAL: this script did not exist before this pass. Without it, `brands` and
`categories` are empty on a fresh database, and every single product fails at
`intake_triage` with `missing_taxonomy_match` before Agent 1 ever runs -- the
pipeline cannot process anything at all until this has been run once.

Idempotent: safe to re-run (upserts on the unique `name` column for brands,
`(name, parent_id)` for categories).

Brand/category lists per the V3.0 Production CSV Blueprint (supersedes the
earlier phase1.md §9.1/§9.2 draft lists -- `Gaba National` is a real brand
confirmed present in the live catalog's own sample export).
"""
import asyncio

from app.db.supabase_client import get_supabase

# --- Brands (exact casing preserved, per the locked taxonomy rule) ---
BRANDS = [
    "Anex", "Boss", "DAWLANCE", "EcoStar", "ELite", "Gaba National", "GFC", "GREE",
    "HAIER", "Hanco", "Homage", "Hotline", "Kenwood", "Login", "Midea", "NASGAS",
    "ORIENT", "Panasonic", "PEL", "Philips", "Royal Fans", "SG", "Super Asia",
    "TCL", "WestPoint Pakistan",
]

# --- Official brand websites -------------------------------------------------
# Supplied by the site owner 2026-07-21. These are used for two things:
#   1. the dofollow external link in every product description (Rank Math), and
#   2. the highest-trust source tier when scraping product facts.
#
# NOT auto-discovered, and never to be guessed: probing likely domain patterns
# previously produced confident but wrong matches (royal.com.pk is a Montessori
# school, gaba.pk a rug store, elite.com.pk a printing firm). Scraping those for
# appliance specs would fabricate data with full confidence.
#
# Some entries carry a PATH, not just a host (DWP hosts EcoStar and GREE as
# sections of one site), so full URLs are stored rather than bare domains.
# A brand with no official site is simply absent -- its products get no external
# link, which costs one Rank Math test and nothing else.
BRAND_OFFICIAL_SITES: dict[str, str] = {
    "Anex": "https://www.anex.pk/",
    "Boss": "https://bosspakistan.com/",
    "DAWLANCE": "https://www.dawlance.com.pk/",
    "EcoStar": "https://dwphome.pk/ecostar",
    "ELite": "https://e-lite.com.pk/",
    "Gaba National": "https://gabanational.net/",
    "GFC": "https://gfcfans.com/",
    "GREE": "https://dwphome.pk/gree",
    "HAIER": "https://www.haier.com/pk/",
    "Hanco": "https://hanco.pk",
    "Homage": "https://homage.pk",
    # "Hotline" has no official site (owner: "N/A, available on Surmawala").
    "Kenwood": "https://kenwoodpakistan.pk",
    "Login": "https://login.com.pk/",
    "Midea": "https://mideapakistan.com",
    "NASGAS": "https://nasgas.com",
    "ORIENT": "https://orient.com.pk",
    "Panasonic": "https://panasonic.com",
    "PEL": "https://pel.com.pk",
    "Philips": "https://philipsappliances.pk",
    "Royal Fans": "https://royalfans.com",
    "SG": "https://sghomeappliance.com.pk",
    "Super Asia": "https://superasiastore.com",
    "TCL": "https://tclpakistan.com",
    "WestPoint Pakistan": "https://westpoint.pk",
}

# --- Categories -------------------------------------------------------------
# AUTHORITATIVE LIST, confirmed by the site owner as the exact live WooCommerce
# taxonomy. Updated 2026-07-26 when the owner supplied their full live tree:
# 4 top-level + 22 Home Appliance sub-categories + 6 Kitchen Appliances = 32.
#
# ONLY the owner may add to this list -- and only from their real site. Two
# entries were once INVENTED here and had to be removed after breaking real
# products: "Inverter" (collided with every "Inverter AC") and "Water Heater"
# (never existed on the live site). A category not on this list routes the
# product to Manual Review -- never created on the fly, since a stray taxonomy
# term silently creates a new term in live WooCommerce on import.
TOP_LEVEL = ["Beauty", "Garment Streamer", "Home Appliance", "Item", "Kitchen Appliances"]

HOME_APPLIANCE_CHILDREN = [
    "Air conditioner", "Air cooler", "Air Purifier", "Deep Freezer",
    "Deerma", "Fans", "Garment Steam Iron", "Geyser", "Heater", "Insect Killer",
    "Led TV", "Microwave Oven", "Refrigerator", "Vacuum Cleaner", "Washing machine",
    "Water Dispenser"
]

KITCHEN_APPLIANCE_CHILDREN = [
    "Air Fryer", "Blender", "Chopper", "Coffee Maker", "Cooker", "Electric Kettle",
    "Food Processor", "Hotplate", "Juicer", "Grinder", "Mixer", "Oven Toaster",
    "Pizza Pan", "Roti Maker", "Toaster", "Hand Chopper", "Hand Blender"
]

# --- Category spec schemas -------------------------------------------------
# V1 (2026-07-26): the owner asked to COMPLETE schemas for every real category on
# their site, done by hand here so they are correct and reviewed. (A dynamic,
# LLM-generated + owner-approved schema flow is planned as Version 2.) A category
# still missing a schema routes its products to Manual Review
# (`missing_category_schema`) rather than letting Agent 1 improvise one.
#
# `required` is used deliberately: brand + model_number are always known from the
# input row, so they never escalate; the category's DEFINING spec(s) (type,
# capacity/size, or headline wattage) are required so a listing missing them goes
# to review rather than publishing thin; everything else is optional.


def _spec(*specs: tuple[str, str, bool]) -> list[dict]:
    """brand + model_number (always known) then the category-specific fields."""
    base = [
        {"key": "brand", "label": "Brand", "required": True},
        {"key": "model_number", "label": "Model Number", "required": True},
    ]
    return base + [{"key": k, "label": label, "required": req} for k, label, req in specs]


SPEC_SCHEMAS = {
    # --- Beauty / personal care (heterogeneous, so only the type is required) ---
    "Beauty": _spec(
        ("appliance_type", "Appliance Type", True), ("wattage", "Wattage", False),
        ("voltage", "Voltage", False), ("material", "Plate / Body Material", False),
        ("temperature", "Temperature Range", False), ("features", "Features", False),
    ),
    # --- Cooling & refrigeration ---
    "Air conditioner": _spec(
        ("ac_type", "AC Type", True), ("capacity", "Capacity", True),
        ("functions", "Functions", False), ("compressor_technology", "Compressor Technology", False),
        ("smart_features", "Smart Features", False), ("refrigerant", "Refrigerant", False),
    ),
    "Refrigerator": _spec(
        ("refrigerator_type", "Refrigerator Type", True), ("capacity", "Capacity", True),
        ("exterior_finish", "Exterior Finish", False),
        ("compressor_technology", "Compressor Technology", False),
        ("refrigerant", "Refrigerant", False),
    ),
    "Deep Freezer": _spec(
        ("freezer_type", "Freezer Type", True), ("capacity", "Capacity", True),
        ("exterior_finish", "Exterior Finish", False),
        ("compressor_technology", "Compressor Technology", False), ("features", "Features", False),
    ),
    "Air cooler": _spec(
        ("capacity", "Water Tank Capacity", True), ("air_throw", "Air Throw", False),
        ("power_consumption", "Power Consumption", False), ("features", "Features", False),
    ),
    "Air Purifier": _spec(
        ("coverage_area", "Coverage Area", True), ("filter_type", "Filter Type", False),
        ("cadr", "CADR", False), ("features", "Features", False),
    ),
    "Water Dispenser": _spec(
        ("dispenser_type", "Type", True), ("taps", "Number of Taps", False),
        ("functions", "Functions", False), ("features", "Features", False),
    ),
    # --- Kitchen: cooking ---
    "Microwave Oven": _spec(
        ("appliance_type", "Appliance Type", True), ("capacity", "Capacity", True),
        ("control_panel", "Control Panel", False), ("features", "Features", False),
    ),
    "Air Fryer": _spec(
        ("capacity", "Capacity", True), ("wattage", "Wattage", True),
        ("control_type", "Control Type", False), ("features", "Features", False),
    ),
    "Oven Toaster": _spec(
        ("capacity", "Capacity", True), ("wattage", "Wattage", True),
        ("functions", "Functions", False), ("features", "Features", False),
    ),
    "Hotplate": _spec(
        ("burners", "Number of Burners", True), ("wattage", "Wattage", False),
        ("plate_type", "Plate Type", False), ("features", "Features", False),
    ),
    "Coffee Maker": _spec(
        ("coffee_maker_type", "Type", True), ("capacity", "Capacity", True),
        ("wattage", "Wattage", False), ("features", "Features", False),
    ),
    "Electric Kettle": _spec(
        ("capacity", "Capacity", True), ("wattage", "Wattage", True),
        ("body_material", "Body Material", False), ("features", "Features", False),
    ),
    # --- Kitchen: food prep ---
    "Blender": _spec(
        ("capacity", "Jar Capacity", True), ("wattage", "Wattage", True),
        ("speeds", "Speeds", False), ("jar_material", "Jar Material", False),
        ("features", "Features", False),
    ),
    "Chopper": _spec(
        ("capacity", "Bowl Capacity", True), ("wattage", "Wattage", True),
        ("blades", "Blades", False), ("features", "Features", False),
    ),
    # Hand-operated variants: no motor, so no wattage field at all. That is the
    # whole reason they are separate categories -- the electric schemas require a
    # wattage these products cannot have, which sent them to Manual Review.
    "Hand Chopper": _spec(
        ("capacity", "Bowl Capacity", False),
        ("blades", "Blades", False),
        ("operation_type", "Operation Type", False),
        ("material", "Material", False),
        ("features", "Features", False),
    ),
    # An immersion / stick blender. ELECTRIC, unlike Hand Chopper -- Anex's own
    # line reads "With Milk Frother", "With Titanium Blade", "With Beater", all
    # motorised. It is separate from Blender only because it has no jug, so a
    # jug Blender's required `capacity` cannot be demanded of it.
    "Hand Blender": _spec(
        ("wattage", "Wattage", True),
        ("capacity", "Beaker Capacity", False),
        ("speeds", "Speeds", False),
        ("blades", "Blades", False),
        ("material", "Material", False),
        ("features", "Features", False),
    ),
    # Sandwich makers, waffle makers and sandwich/waffle/grill combos. Operator-
    # directed: the live store files all of these under "Toaster".
    "Toaster": _spec(
        ("wattage", "Wattage", True),
        ("slices", "Slices", False),
        ("plate_type", "Plate Type", False),
        ("features", "Features", False),
    ),
    # Handheld garment steamers. The live store spells the category "Streamer";
    # every product title says "Steamer" (see the alias in input_adapter).
    "Garment Streamer": _spec(
        ("wattage", "Wattage", True),
        ("capacity", "Water Tank Capacity", False),
        ("steam_output", "Steam Output", False),
        ("features", "Features", False),
    ),
    # CATCH-ALL, operator-directed. Products whose real category the live store
    # does not carry (kitchen robots, egg beaters, BBQ grills, slicers) are filed
    # under the parent rather than inventing a term WooCommerce has never seen.
    #
    # Only appliance_type is required: these products have nothing else in
    # common, so demanding a wattage or a capacity of all of them would send the
    # whole group to Manual Review -- the opposite of the point.
    "Kitchen Appliances": _spec(
        ("appliance_type", "Appliance Type", True),
        ("wattage", "Wattage", False),
        ("capacity", "Capacity", False),
        ("material", "Material", False),
        ("features", "Features", False),
    ),
    # --- Categories completed for the 296-product Anex run --------------------
    # Each holds genuinely heterogeneous products, so only appliance_type is
    # required. The titles show why: Mixer covers both "Hand Mixer" and "Stand
    # Mixer 1500W 7L", Cooker covers "Rice Cooker 1.8L" and "Induction Cooker",
    # and "Handy Food Processor" (AG-12) is hand-cranked while AG-1041 is not.
    #
    # A required field is a stop sign: if no source publishes it the product goes
    # to Manual Review. Requiring a wattage across a group where a third of the
    # products have no motor would fail them for a fact that does not exist. The
    # optional fields below still PUBLISH whenever they are found -- optional
    # means "do not block", not "do not extract".
    "Grinder": _spec(
        ("appliance_type", "Appliance Type", True),
        ("wattage", "Wattage", False), ("grinder_type", "Wet / Dry", False),
        ("jars", "Jars", False), ("material", "Body / Jar Material", False),
        ("features", "Features", False),
    ),
    "Juicer": _spec(
        ("appliance_type", "Appliance Type", True),
        ("wattage", "Wattage", False), ("capacity", "Jug Capacity", False),
        ("speeds", "Speeds", False), ("material", "Body Material", False),
        ("features", "Features", False),
    ),
    "Cooker": _spec(
        ("appliance_type", "Appliance Type", True),
        ("capacity", "Capacity", False), ("wattage", "Wattage", False),
        ("material", "Inner Pot Material", False),
        ("features", "Features", False),
    ),
    "Mixer": _spec(
        ("appliance_type", "Appliance Type", True),
        ("wattage", "Wattage", False), ("capacity", "Bowl Capacity", False),
        ("speeds", "Speeds", False), ("material", "Bowl Material", False),
        ("features", "Features", False),
    ),
    "Food Processor": _spec(
        ("appliance_type", "Appliance Type", True),
        ("wattage", "Wattage", False), ("capacity", "Bowl Capacity", False),
        ("attachments", "Attachments", False), ("features", "Features", False),
    ),
    "Roti Maker": _spec(
        ("appliance_type", "Appliance Type", True),
        ("wattage", "Wattage", False), ("plate_size", "Plate Size", False),
        ("material", "Plate Material", False), ("features", "Features", False),
    ),
    "Pizza Pan": _spec(
        ("appliance_type", "Appliance Type", True),
        ("wattage", "Wattage", False), ("diameter", "Diameter", False),
        ("material", "Surface Material", False), ("features", "Features", False),
    ),
    # --- Home appliances ---
    "Fans": _spec(
        ("fan_type", "Fan Type", True), ("sweep_size", "Sweep Size", False),
        ("speeds", "Speeds", False), ("power_consumption", "Power Consumption", False),
        ("features", "Features", False),
    ),
    "Garment Steam Iron": _spec(
        ("iron_type", "Iron Type", True), ("wattage", "Wattage", True),
        ("steam_output", "Steam Output", False), ("soleplate", "Soleplate", False),
        ("features", "Features", False),
    ),
    "Geyser": _spec(
        ("geyser_type", "Geyser Type", True), ("capacity", "Capacity", True),
        ("features", "Features", False),
    ),
    "Heater": _spec(
        ("heater_type", "Heater Type", True), ("wattage", "Wattage", True),
        ("coverage_area", "Coverage Area", False), ("features", "Features", False),
    ),
    "Insect Killer": _spec(
        ("coverage_area", "Coverage Area", True), ("wattage", "Wattage", False),
        ("method", "Method", False), ("features", "Features", False),
    ),
    "Led TV": _spec(
        ("screen_size", "Screen Size", True), ("resolution", "Resolution", True),
        ("display_type", "Display Type", False), ("smart_features", "Smart Features", False),
        ("connectivity", "Connectivity", False),
    ),
    "Vacuum Cleaner": _spec(
        ("vacuum_type", "Type", True), ("capacity", "Dust Capacity", False),
        ("wattage", "Wattage", False), ("suction_power", "Suction Power", False),
        ("features", "Features", False),
    ),
    "Washing machine": _spec(
        ("washing_machine_type", "Type", True), ("capacity", "Capacity", True),
        ("wash_programs", "Wash Programs", False), ("spin_speed", "Spin Speed", False),
        ("features", "Features", False),
    ),
}

# Every schema implicitly also needs weight/length/width/height for build_dimensions()
# (phase2.md §6) -- these are requested from Agent 1 alongside the visible fields but
# rendered separately by build_dimensions(), not in the specs table.
DIMENSION_FIELDS = [
    {"key": "weight_kg", "label": "Weight (kg)", "required": False},
    {"key": "length_cm", "label": "Length (cm)", "required": False},
    {"key": "width_cm", "label": "Width (cm)", "required": False},
    {"key": "height_cm", "label": "Height (cm)", "required": False},
]


async def seed_brands() -> dict[str, str]:
    db = await get_supabase()
    name_to_id = {}
    for name in BRANDS:
        result = await db.table("brands").upsert(
            {"name": name, "is_active": True}, on_conflict="name"
        ).execute()
        name_to_id[name] = result.data[0]["id"]
        print(f"  brand: {name}")
    return name_to_id


async def _get_or_create_null_parent_category(name: str, is_active: bool = True, notes: str | None = None) -> str:
    """
    Postgres treats NULL != NULL in a UNIQUE(name, parent_id) index, so
    `.upsert(..., on_conflict="name,parent_id")` does NOT catch duplicates when
    parent_id is NULL -- re-running the seed would insert a second top-level
    row each time. Check-then-insert instead for true idempotency, since this
    schema has no partial unique index on `name WHERE parent_id IS NULL`.
    """
    db = await get_supabase()
    existing = await db.table("categories").select("id").eq("name", name).is_("parent_id", "null").execute()
    if existing.data:
        return existing.data[0]["id"]
    payload = {"name": name, "parent_id": None, "is_active": is_active, "needs_confirmation": False}
    if notes:
        payload["notes"] = notes
    result = await db.table("categories").insert(payload).execute()
    return result.data[0]["id"]


async def seed_categories() -> dict[str, str]:
    """
    Seeds exactly the authoritative taxonomy above. Every row is written with
    needs_confirmation=False because the site owner has confirmed this list
    against the live store -- nothing here is a guess awaiting verification.
    """
    name_to_id = {}

    # Pass 1: top-level categories (parent_id = null)
    for name in TOP_LEVEL:
        name_to_id[name] = await _get_or_create_null_parent_category(name)
        print(f"  category (top-level): {name}")

    # Pass 2: sub-categories, linked to their real parent id
    db = await get_supabase()

    async def seed_children(children: list[str], parent_name: str):
        parent_id = name_to_id[parent_name]
        for name in children:
            result = await db.table("categories").upsert(
                {
                    "name": name,
                    "parent_id": parent_id,
                    "is_active": True,
                    "needs_confirmation": False,
                },
                on_conflict="name,parent_id",
            ).execute()
            name_to_id[name] = result.data[0]["id"]
            print(f"  category: {parent_name} > {name}")

    await seed_children(HOME_APPLIANCE_CHILDREN, "Home Appliance")
    await seed_children(KITCHEN_APPLIANCE_CHILDREN, "Kitchen Appliances")

    return name_to_id


async def seed_spec_schemas(category_ids: dict[str, str]):
    # `category_ids` (name -> id) collapses duplicate names, but the same category
    # name can exist under two parents (e.g. "Electric Kettle" under both Home
    # Appliance and Kitchen Appliances). Query every matching row so the schema is
    # attached to ALL of them, not just whichever id won the name collision.
    db = await get_supabase()
    for category_name, fields in SPEC_SCHEMAS.items():
        rows = (await db.table("categories").select("id").eq("name", category_name).execute()).data
        if not rows:
            print(f"  SKIP schema for '{category_name}' -- category not found")
            continue
        for row in rows:
            await db.table("category_spec_schemas").upsert(
                {"category_id": row["id"], "fields": fields + DIMENSION_FIELDS},
                on_conflict="category_id",
            ).execute()
        print(f"  spec schema: {category_name} "
              f"({len(fields)} visible + 4 dimension fields; {len(rows)} category row(s))")


async def seed_brand_official_sites(brand_ids: dict[str, str]):
    """
    Records each brand's official website in `brand_domain_aliases`.

    Idempotent on brand_id (one official site per brand). Brands absent from
    BRAND_OFFICIAL_SITES are skipped rather than given a placeholder -- an empty
    row would be indistinguishable from a real one downstream.
    """
    db = await get_supabase()
    for brand_name, url in BRAND_OFFICIAL_SITES.items():
        brand_id = brand_ids.get(brand_name)
        if not brand_id:
            print(f"  SKIP {brand_name} -- brand not found in taxonomy")
            continue
        await db.table("brand_domain_aliases").upsert(
            {"brand_id": brand_id, "official_domain": url, "is_active": True},
            on_conflict="brand_id",
        ).execute()
        print(f"  official site: {brand_name} -> {url}")

    missing = sorted(set(brand_ids) - set(BRAND_OFFICIAL_SITES))
    if missing:
        print(f"  (no official site on record for: {', '.join(missing)})")


async def seed_trusted_secondary_sources():
    """
    Seeds STARTING sources so the system is not empty on day one.

    These two are defaults, NOT requirements. Nothing in the application code
    references them: `source_discovery.py` reads whatever rows exist in
    `trusted_secondary_sources`, and search URL patterns are discovered by trial
    rather than configured per site. Remove these and add your own in
    Settings -> Trusted Secondary Sources and the pipeline follows immediately,
    with no code change and no redeploy.

    (Before this existed the table was empty, so discovery returned nothing for
    every product and everything escalated before Agent 1 ever ran.)
    """
    db = await get_supabase()
    # 2026-08-09 (owner-directed): priority order corrected to Surmawala ->
    # Japan Electronics -> Pak Electronics -> (Google broad search, which is
    # its own separate tier below this one -- see GOOGLE_TIER in
    # source_discovery.py -- not something to add here). Explicitly does NOT
    # include general marketplaces like Naheed/Metro/Ary: those carry every
    # category, not specialist appliance listings, and were flagged as
    # unreliable for this catalogue -- never add them here as defaults.
    #
    # pakelectronics.pk is UNVERIFIED -- the real registered domain was not
    # confirmed at the time this was added. Check/correct it in Settings ->
    # Trusted Secondary Sources; that edit takes effect immediately with no
    # redeploy, same as every other row here (see this function's docstring).
    defaults = [
        {"domain": "surmawala.pk", "label": "Surmawala", "priority": 1},
        {"domain": "japanelectronics.pk", "label": "Japan Electronics", "priority": 2},
        {"domain": "pakelectronics.pk", "label": "Pak Electronics", "priority": 3},
    ]
    for source in defaults:
        await db.table("trusted_secondary_sources").upsert(
            {**source, "is_active": True}, on_conflict="domain"
        ).execute()
        print(f"  trusted secondary source: {source['label']} ({source['domain']})")


async def main():
    print("--- Seeding Brands ---")
    brand_ids = await seed_brands()
    print("\n--- Seeding Official Brand Websites ---")
    await seed_brand_official_sites(brand_ids)
    print("\n--- Seeding Categories ---")
    category_ids = await seed_categories()
    print("\n--- Seeding Category Spec Schemas (only where we have real evidence) ---")
    await seed_spec_schemas(category_ids)
    print("\n--- Seeding Trusted Secondary Sources ---")
    await seed_trusted_secondary_sources()
    print("\nDone. Remaining categories have NO spec schema by design -- their products")
    print("will route to Manual Review (missing_category_schema) until you define one")
    print("via the Taxonomy Manager, right before you actually process that category.")


if __name__ == "__main__":
    asyncio.run(main())

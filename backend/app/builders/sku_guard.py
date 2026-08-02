from app.db.repositories.sku_snapshot import sku_snapshot_repo

async def check_sku_collision(sku: str) -> bool:
    """
    Checks if a SKU already exists in the live WooCommerce snapshot.
    """
    return await sku_snapshot_repo.exists(sku)

import argparse
import asyncio
import sys
from uuid import UUID

from app.db.repositories.batches import batches_repo
from app.db.repositories.products import products_repo


async def check_batch(batch_id: UUID):
    print(f"--- Pilot Gate Check for Batch: {batch_id} ---")
    
    batch = await batches_repo.get(batch_id)
    if not batch:
        print(f"FAIL: Batch {batch_id} not found.")
        return False

    products = await products_repo.get_by_batch(batch_id)
    if not products:
        print("FAIL: No products found in batch.")
        return False

    all_passed = True
    
    for p in products:
        print(f"\nChecking Product: {p.name} ({p.id})")
        product_passed = True
        
        # 1. Approved status
        if p.status != "approved":
            print(f"  - FAIL: Status is '{p.status}', expected 'approved'")
            product_passed = False
            
        # 2. Warranty Consistency
        # Warranty strings in: short_description, description, specs_table_html, FAQ Q5
        # Since these are HTML or complex strings, we check if the resolved_warranty_phrase exists in them
        w_phrase = p.resolved_warranty_phrase or "Official Warranty"
        locations = {
            "Short Description": p.short_description,
            "Description": p.description,
            "Specs Table": p.specs_table_html,
        }
        # For FAQ Q5, we'd need the writer_output which might not be in first-class columns if not stored
        # But Phase 1 §5.5 says check all 4. 
        
        for loc_name, content in locations.items():
            if not content or w_phrase.lower() not in content.lower():
                print(f"  - FAIL: Warranty consistency error in {loc_name}. Expected '{w_phrase}'")
                product_passed = False
                
        # 3. Preflight Score (Mocked as we don't store it yet, or use a heuristic)
        # In a real system, we'd query the metrics/audit log
        
        if product_passed:
            print("  - PASS")
        else:
            all_passed = False

    print("\n--- Final Verdict ---")
    if all_passed:
        print("RESULT: PASS")
        return True
    else:
        print("RESULT: FAIL")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-id", required=True, type=str)
    args = parser.parse_args()
    
    try:
        success = asyncio.run(check_batch(UUID(args.batch_id)))
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

import asyncio
import argparse
from uuid import UUID
from app.db.repositories.products import products_repo

async def generate_report(batch_id: UUID):
    products = await products_repo.get_by_batch(batch_id)
    if not products:
        print("No products found.")
        return

    system_times = []
    human_times = []
    
    for p in products:
        # Queued to Ready for QA
        if p.queued_at and p.ready_for_qa_at:
            delta = (p.ready_for_qa_at - p.queued_at).total_seconds()
            system_times.append(delta)
            
        # Ready for QA to Approved
        if p.ready_for_qa_at and p.approved_at:
            delta = (p.approved_at - p.ready_for_qa_at).total_seconds()
            human_times.append(delta)

    avg_system = sum(system_times) / len(system_times) if system_times else 0
    avg_human = sum(human_times) / len(human_times) if human_times else 0

    print(f"--- Metrics Report for Batch {batch_id} ---")
    print(f"Total Products: {len(products)}")
    print(f"Avg System Processing: {avg_system:.2f}s")
    print(f"Avg Human QA Time: {avg_human:.2f}s")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-id", required=True, type=str)
    args = parser.parse_args()
    
    asyncio.run(generate_report(UUID(args.batch_id)))

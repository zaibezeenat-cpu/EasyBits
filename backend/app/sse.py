import asyncio
import json
from typing import Dict, List

class SSEManager:
    def __init__(self):
        # batch_id -> list of queues
        self.queues: Dict[str, List[asyncio.Queue]] = {}

    async def subscribe(self, batch_id: str):
        queue = asyncio.Queue()
        if batch_id not in self.queues:
            self.queues[batch_id] = []
        self.queues[batch_id].append(queue)
        try:
            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data)}\n\n"
        finally:
            self.queues[batch_id].remove(queue)
            if not self.queues[batch_id]:
                del self.queues[batch_id]

    def notify(self, batch_id: str, data: dict):
        if batch_id in self.queues:
            for queue in self.queues[batch_id]:
                queue.put_nowait(data)

sse_manager = SSEManager()

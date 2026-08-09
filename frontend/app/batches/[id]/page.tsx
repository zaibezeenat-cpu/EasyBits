"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useEffect } from "react";
import { toast } from "sonner";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Play, Download, AlertCircle, CheckCircle2, Loader2 } from "lucide-react";

export default function BatchDetailPage() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();

  const { data: batch } = useQuery({
    queryKey: ["batch", id],
    queryFn: () => api.getBatch(id),
    enabled: !!id,
  });

  const { data: products } = useQuery({
    queryKey: ["batch-products", id],
    queryFn: () => api.listProductsByBatch(id),
    enabled: !!id,
  });

  // SSE — same env var as apiClient.ts (NEXT_PUBLIC_API_URL); this was previously
  // pointed at a different, unset var name and would have silently failed to connect.
  useEffect(() => {
    if (!id) return;

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const eventSource = new EventSource(`${apiUrl}/api/events/${id}`);

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.event === "product_completed" || data.event === "product_failed") {
        queryClient.invalidateQueries({ queryKey: ["batch-products", id] });
        queryClient.invalidateQueries({ queryKey: ["batch", id] });
        queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      }
      if (data.event === "batch_completed" || data.event === "batch_paused") {
        queryClient.invalidateQueries({ queryKey: ["batch", id] });
        queryClient.invalidateQueries({ queryKey: ["batches"] });
        // batch_completed carries a plain-English tally (backend/app/graph/
        // batch_processor.py) -- e.g. "7 ready for QA, 2 need manual review,
        // 1 failed" -- so the operator sees the real outcome without opening
        // the batch. Falls back to a bare label if the payload is ever absent.
        toast.info(
          data.event === "batch_paused"
            ? "Batch paused (budget limit reached)"
            : (data.summary ? `Batch completed: ${data.summary}` : "Batch completed"),
        );
      }
    };

    return () => eventSource.close();
  }, [id, queryClient]);

  const runBatchMutation = useMutation({
    mutationFn: () => api.runBatch(id),
    onSuccess: () => {
      toast.success("Batch processing started");
      queryClient.invalidateQueries({ queryKey: ["batch", id] });
    },
    onError: () => toast.error("Failed to start batch"),
  });

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">{batch?.label || "Loading..."}</h2>
          <p className="text-muted-foreground">ID: {id}</p>
        </div>
        <div className="flex items-center gap-3">
          <Button 
            variant="outline" 
            onClick={() => runBatchMutation.mutate()}
            disabled={batch?.status === 'processing' || runBatchMutation.isPending}
          >
            {batch?.status === 'processing' ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Play className="w-4 h-4 mr-2" />}
            Run Batch
          </Button>
          <Button variant="primary" disabled={batch?.status !== 'ready_for_qa'}>
            <Download className="w-4 h-4 mr-2" />
            Export CSV
          </Button>
        </div>
      </div>

      <div className="grid gap-4">
        {products?.map((product) => (
          <Card key={product.id}>
            <CardContent className="flex items-center justify-between py-4">
              <div className="flex items-center gap-4">
                <div className={`p-2 rounded-full ${
                  product.status === 'approved' ? 'bg-green-100 text-green-600' :
                  product.status === 'manual_review' ? 'bg-red-100 text-red-600' :
                  'bg-gray-100 text-gray-400'
                }`}>
                  {product.status === 'approved' ? <CheckCircle2 className="w-5 h-5" /> : <AlertCircle className="w-5 h-5" />}
                </div>
                <div>
                  <div className="font-medium">{product.sku}</div>
                  <div className="text-sm text-muted-foreground">{product.model_number}</div>
                </div>
              </div>
              <div className="flex items-center gap-4">
                <span className="text-xs font-medium uppercase text-muted-foreground">{product.status}</span>
                <Link href={`/products/${product.id}`}>
                  <Button variant="outline" size="sm">Review</Button>
                </Link>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

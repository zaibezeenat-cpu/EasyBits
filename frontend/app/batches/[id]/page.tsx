"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Product } from "@/lib/apiClient";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useEffect } from "react";
import { toast } from "sonner";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Play, Download, AlertCircle, CheckCircle2, Loader2 } from "lucide-react";

/**
 * The real, specific reason THIS product needs a look, or null if it
 * doesn't -- the frontend mirror of backend/app/graph/batch_processor.py's
 * _issue_reason(). Owner-directed (2026-08-09): never a bare "check the
 * review queue" or "Unknown error" -- name the actual product and the
 * actual issue. Derived client-side from data already fetched for this
 * page, so it survives a refresh (unlike the completion toast, which is
 * built from the one-shot batch_completed SSE payload).
 */
function issueReason(product: Product): string | null {
  if (product.status === "manual_review" || product.status === "failed") {
    const reason = product.failure_reason || "other";
    const detail = product.failure_detail?.detail || "no further detail recorded";
    return `${reason}: ${detail}`;
  }
  if (product.status === "ready_for_qa" && product.review_result && product.review_result.passed === false) {
    const failedChecks = product.review_result.checks.filter((c) => !c.passed).map((c) => c.detail);
    const reasons = failedChecks.length > 0 ? failedChecks : [product.review_result.failure_summary || "did not pass review"];
    return `shipped without passing every SEO/fact check: ${reasons.join("; ")}`;
  }
  return null;
}

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
        queryClient.invalidateQueries({ queryKey: ["batch-products", id] });
        if (data.event === "batch_paused") {
          toast.info("Batch paused (budget limit reached)");
          return;
        }
        // batch_completed's summary (backend/app/graph/batch_processor.py) is
        // "<counts>\nIssues:\n- <sku>: <real reason>\n..." when anything
        // needs attention -- owner-directed: name the actual product and the
        // actual issue here, never a bare "check the review queue" or
        // "Unknown error". Split so the counts read as the toast title and
        // each issue as its own line in the body; a long-lived toast (issues
        // need to actually be read, not blinked past) plus the persistent
        // "Needs Attention" section below (survives after the toast is gone).
        const [title, ...rest] = (data.summary || "Batch completed").split("\n");
        const hasIssues = rest.length > 0;
        toast[hasIssues ? "warning" : "success"](title, {
          ...(hasIssues ? { description: rest.join("\n") } : {}),
          duration: hasIssues ? 15000 : 4000,
          style: { whiteSpace: "pre-line" },
        });
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

      {(() => {
        const needsAttention = (products || [])
          .map((p) => ({ product: p, reason: issueReason(p) }))
          .filter((x): x is { product: Product; reason: string } => x.reason !== null);
        if (needsAttention.length === 0) return null;
        return (
          <Card className="border-amber-500/40 bg-amber-500/10">
            <CardContent className="py-4 space-y-2">
              <p className="text-sm font-semibold text-amber-700 dark:text-amber-400">
                Needs Attention ({needsAttention.length})
              </p>
              <div className="space-y-1.5">
                {needsAttention.map(({ product, reason }) => (
                  <Link
                    key={product.id}
                    href={`/products/${product.id}`}
                    className="block text-xs p-2 border rounded-md bg-background/60 hover:bg-background"
                  >
                    <span className="font-mono font-medium">{product.sku}</span>
                    <span className="text-textSecondary"> — {reason}</span>
                  </Link>
                ))}
              </div>
            </CardContent>
          </Card>
        );
      })()}

      <div className="grid gap-4">
        {products?.map((product) => {
          const reason = issueReason(product);
          return (
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
                    {reason && <div className="text-xs text-amber-600 dark:text-amber-400 mt-0.5">{reason}</div>}
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
          );
        })}
      </div>
    </div>
  );
}

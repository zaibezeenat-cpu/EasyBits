"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";
import { useParams, useRouter } from "next/navigation";
import { Check, X, AlertCircle, Eye, EyeOff } from "lucide-react";

/**
 * Human QA Panel — Full Review Mode vs Quick Review Mode (phase1.md §5.7, §15).
 *
 * Full Review Mode: every field, with its source citation, so the reviewer is
 * verifying against real sources rather than trusting the AI blind.
 * Quick Review Mode: only the fields the Reviewer agent itself flagged as
 * failed/borderline -- available only once trust_level has been switched in
 * Settings, per the "Gradual Trust Reduction" rollout rule.
 *
 * The toggle here is a per-session override on top of the saved trust_level
 * default -- so during the trust-rebuilding period you can still spot-check
 * a specific product in Full mode without changing the global setting.
 */
export default function ProductQAPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();

  const { data: trustLevel } = useQuery({
    queryKey: ["trust-level"],
    queryFn: api.getTrustLevel,
  });

  const [modeOverride, setModeOverride] = useState<"full_review" | "quick_review" | null>(null);
  const effectiveMode = modeOverride ?? trustLevel?.mode ?? "full_review";

  const { data: product, isLoading } = useQuery({
    queryKey: ["product", id],
    queryFn: () => api.getProduct(id),
    enabled: !!id,
  });

  const { data: citations } = useQuery({
    queryKey: ["product-citations", id],
    queryFn: () => api.getProductCitations(id),
    enabled: !!id && effectiveMode === "full_review",
  });

  const updateStatusMutation = useMutation({
    mutationFn: (status: string) => api.updateProduct(id, { status }),
    onSuccess: () => {
      toast.success("Product status updated");
      queryClient.invalidateQueries({ queryKey: ["product", id] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      router.back();
    },
    onError: () => toast.error("Failed to update product"),
  });

  if (isLoading) return <p>Loading product...</p>;

  const failedChecks = (product?.review_result?.checks || []).filter((c) => !c.passed);
  const citationByField = new Map((citations || []).map((c) => [c.field_name, c]));

  // Quick mode shows only the fields the Reviewer flagged; Full mode shows everything.
  const specFieldsToShow =
    effectiveMode === "quick_review"
      ? Object.keys(product?.extraction_result || {}).filter((key) =>
          failedChecks.some((c) => c.detail.toLowerCase().includes(key.toLowerCase()))
        )
      : Object.keys(product?.extraction_result || {});

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Human QA Panel</h2>
          <p className="text-muted-foreground">Reviewing {product?.sku}</p>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setModeOverride(effectiveMode === "full_review" ? "quick_review" : "full_review")}
          >
            {effectiveMode === "full_review" ? (
              <>
                <Eye className="w-4 h-4 mr-2" /> Full Review Mode
              </>
            ) : (
              <>
                <EyeOff className="w-4 h-4 mr-2" /> Quick Review Mode
              </>
            )}
          </Button>
          <Button variant="outline" onClick={() => updateStatusMutation.mutate("manual_review")}>
            <AlertCircle className="w-4 h-4 mr-2" />
            Manual Review
          </Button>
          <Button variant="destructive" onClick={() => updateStatusMutation.mutate("failed")}>
            <X className="w-4 h-4 mr-2" />
            Reject
          </Button>
          <Button variant="primary" onClick={() => updateStatusMutation.mutate("approved")}>
            <Check className="w-4 h-4 mr-2" />
            Approve
          </Button>
        </div>
      </div>

      {effectiveMode === "quick_review" && failedChecks.length === 0 && (
        <Card className="border-success/30 bg-success/5">
          <CardContent className="py-4 text-sm text-success">
            All automated checks passed for this product — nothing flagged to review. Switch to Full Review Mode
            above if you want to see every field and source anyway.
          </CardContent>
        </Card>
      )}

      <div className="grid gap-8 lg:grid-cols-2">
        {/* Left: Extracted Facts (+ source citations in Full mode) */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>
                Extracted Facts {effectiveMode === "quick_review" && "(flagged fields only)"}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {specFieldsToShow.length === 0 ? (
                <p className="text-sm text-muted-foreground">No fields to show in this mode.</p>
              ) : (
                specFieldsToShow.map((key) => {
                  const value = (product?.extraction_result as Record<string, unknown>)?.[key];
                  const citation = citationByField.get(key);
                  return (
                    <div key={key} className="text-sm border-b pb-2 last:border-0">
                      <div className="flex justify-between">
                        <span className="font-bold capitalize">{key.replace(/_/g, " ")}:</span>
                        <span>{String(value)}</span>
                      </div>
                      {effectiveMode === "full_review" && citation && (
                        <a
                          href={citation.source_url ?? undefined}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs text-primary hover:underline"
                        >
                          Source: {citation.source_url || "unreachable"}
                        </a>
                      )}
                    </div>
                  );
                })
              )}

              {effectiveMode === "quick_review" && failedChecks.length > 0 && (
                <div className="space-y-2 pt-2">
                  <span className="text-sm font-bold">Flagged checks:</span>
                  {failedChecks.map((c) => (
                    <div key={c.check_name} className="text-xs p-2 border rounded-md bg-danger/5 text-danger">
                      <p className="font-medium">{c.check_name}</p>
                      <p>{c.detail}</p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right: Generated Content */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Generated Content</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-2">
                <label className="text-sm font-bold">Short Description</label>
                <div
                  className="w-full p-3 text-sm border rounded-md bg-muted"
                  dangerouslySetInnerHTML={{ __html: product?.short_description || "" }}
                />
              </div>

              <div className="space-y-2">
                <label className="text-sm font-bold">SEO Preview</label>
                <div className="p-4 border rounded-md bg-blue-50/30">
                  <h4 className="text-blue-700 font-medium truncate">{product?.rank_math_title}</h4>
                  <p className="text-green-700 text-xs mt-1 truncate">
                    {`https://kiachahye.pk/product/${product?.sku}`}
                  </p>
                  <p className="text-sm text-gray-600 mt-2 line-clamp-2">{product?.rank_math_description}</p>
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-bold">HTML Specs Preview</label>
                <div
                  className="p-4 border rounded-md bg-white overflow-x-auto"
                  dangerouslySetInnerHTML={{ __html: product?.specs_table_html || "" }}
                />
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

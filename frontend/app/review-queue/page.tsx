"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type Product } from "@/lib/apiClient";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import Link from "next/link";
import { ClipboardList, ExternalLink } from "lucide-react";

/**
 * Plain-language explanations of the escalation reasons the pipeline emits.
 *
 * The raw slug alone ("no_reliable_source_found") does not tell the operator
 * whether to fix a setting, fix the sheet, or accept that the product genuinely
 * has to be written by hand — which is the only decision this page exists to
 * support.
 */
const REASON_HELP: Readonly<Record<string, string>> = {
  no_reliable_source_found:
    "No configured source had this product. Add the brand's official source in Taxonomy, or a retailer under Settings.",
  source_unreachable:
    "Sources were configured but none returned a page naming this model number. It may not be listed, or the sites were down.",
  missing_taxonomy_match:
    "The brand or category in the sheet does not exist in live taxonomy. Check the exact spelling and casing.",
  brand_casing_mismatch:
    "The brand casing in the sheet differs from live taxonomy. WooCommerce would create a second brand.",
  production_lock_violation:
    "A casing or breadcrumb lock refused the row. Exporting it would have created a duplicate term.",
  warranty_conflict:
    "The sheet's warranty disagrees with the source. Both are shown on the product page — confirm which is correct.",
  variant_shaped:
    "The model number looks like a variant group rather than one product. Split it into separate rows.",
  seo_validation_failed: "The generated content did not pass every SEO check after the allowed retries.",
  other: "See the detail column.",
};

function reasonLabel(reason: string | null | undefined): string {
  if (!reason) return "Unknown";
  return reason.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export default function ReviewQueuePage() {
  const { data: products, isLoading, isError, error } = useQuery({
    queryKey: ["products", "manual_review"],
    queryFn: () => api.listProducts("manual_review"),
  });

  const rows: readonly Product[] = products ?? [];

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Review Queue</h2>
        <p className="text-muted-foreground">
          Products the pipeline refused to export. Nothing here reached a CSV — each one is waiting
          on a decision.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ClipboardList className="h-5 w-5 text-primary" aria-hidden />
            Awaiting review
            {rows.length > 0 && (
              <span className="rounded-full bg-accent/20 px-2 py-0.5 text-xs font-medium text-accent">
                {rows.length}
              </span>
            )}
          </CardTitle>
          <CardDescription>
            An escalation is the system saying it could not verify something — not that the product
            is faulty.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : isError ? (
            <p className="py-8 text-center text-sm text-destructive">
              {error instanceof Error ? error.message : "Could not load the review queue."}
            </p>
          ) : rows.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              Nothing is waiting for review.
            </p>
          ) : (
            <ul className="space-y-3">
              {rows.map((product) => {
                const detail = product.failure_detail?.detail;
                const help = product.failure_reason ? REASON_HELP[product.failure_reason] : undefined;
                return (
                  <li key={product.id} className="rounded-md border p-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="font-mono text-sm font-medium">{product.sku}</p>
                        {product.model_number && (
                          <p className="text-xs text-muted-foreground">{product.model_number}</p>
                        )}
                      </div>
                      <div className="flex shrink-0 items-center gap-3">
                        <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs font-medium text-accent">
                          {reasonLabel(product.failure_reason)}
                        </span>
                        <Link
                          href={`/products/${product.id}`}
                          className="inline-flex items-center gap-1 text-xs text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                        >
                          Open <ExternalLink className="h-3 w-3" aria-hidden />
                        </Link>
                      </div>
                    </div>

                    {help && <p className="mt-2 text-xs text-muted-foreground">{help}</p>}
                    {detail && (
                      // The raw detail is kept alongside the explanation: it
                      // names the specific provider, URL or field that failed,
                      // which the generic help text cannot.
                      <p className="mt-1 break-words font-mono text-xs text-muted-foreground/80">
                        {detail}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

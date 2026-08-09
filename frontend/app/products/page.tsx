"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import Link from "next/link";

export default function ProductsPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading...</p>}>
      <ProductsPageInner />
    </Suspense>
  );
}

function ProductsPageInner() {
  const searchParams = useSearchParams();
  const status = searchParams.get("status") || undefined;

  const { data: products, isLoading } = useQuery({
    queryKey: ["products", status],
    queryFn: () => api.listProducts(status),
  });

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Products</h2>
        <p className="text-muted-foreground">
          {status ? `Filtered: ${status.replace(/_/g, " ")}` : "All products across every batch."}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Products</CardTitle>
          <CardDescription>{products?.length ?? 0} product(s)</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : !products || products.length === 0 ? (
            <p className="text-sm text-muted-foreground">No products found.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-textSecondary border-b border-border">
                  <th className="py-2 font-medium">SKU</th>
                  <th className="py-2 font-medium">Name</th>
                  <th className="py-2 font-medium">Status</th>
                  <th className="py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {products.map((p) => {
                  // A product can reach "ready_for_qa" after exhausting every
                  // Writer/Reviewer retry without fully passing Rank Math/fact
                  // checks (backend/app/graph/router.py -- it ships rather than
                  // blocking export). review_result.passed=False plus the
                  // specific failed checks are already persisted; this is that
                  // data surfaced as a badge instead of being buried in a JSON
                  // blob nobody opens.
                  const seoFailed = p.review_result && p.review_result.passed === false;
                  return (
                    <tr key={p.id} className="border-b border-border last:border-0">
                      <td className="py-2 font-mono text-xs">{p.sku}</td>
                      <td className="py-2">{p.name || p.model_number}</td>
                      <td className="py-2 text-textSecondary uppercase text-xs">
                        <span>{p.status}</span>
                        {seoFailed && (
                          <span
                            className="ml-2 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold normal-case bg-amber-500/15 text-amber-600 dark:text-amber-400"
                            title={p.review_result?.failure_summary || "Did not pass every SEO/fact check after all retries"}
                          >
                            SEO check failed
                          </span>
                        )}
                      </td>
                      <td className="py-2">
                        <Link href={`/products/${p.id}`} className="text-accent hover:underline">
                          Review
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

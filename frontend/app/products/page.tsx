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
                {products.map((p) => (
                  <tr key={p.id} className="border-b border-border last:border-0">
                    <td className="py-2 font-mono text-xs">{p.sku}</td>
                    <td className="py-2">{p.name || p.model_number}</td>
                    <td className="py-2 text-textSecondary uppercase text-xs">{p.status}</td>
                    <td className="py-2">
                      <Link href={`/products/${p.id}`} className="text-accent hover:underline">
                        Review
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

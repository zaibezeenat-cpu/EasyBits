"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, type RawProductInput } from "@/lib/apiClient";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { toast } from "sonner";
import { useRouter } from "next/navigation";
import { Zap } from "lucide-react";

/**
 * Quick-Add (phase1.md §10, phase2.md §5.2): a single product, implemented as
 * "a batch of one" so it inherits every accuracy/escalation rule the normal
 * batch pipeline has, rather than being a separate, less-safe code path.
 *
 * Sequencing matters here: the batch is created with auto_run=false, the
 * product row is inserted, and only THEN is the batch explicitly run --
 * otherwise the pipeline could start before the product exists and process
 * zero products.
 */
export default function QuickAddPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    sku: "",
    model_number: "",
    brand_name: "",
    category_name: "",
    product_type: "",
    regular_price: "",
    sale_price: "",
    in_stock: true,
    warranty_override: "",
    template_choice: "A" as "A" | "B",
  });

  const submitMutation = useMutation({
    mutationFn: async () => {
      const rawInput: RawProductInput = {
        sku: form.sku,
        model_number: form.model_number,
        brand_name: form.brand_name,
        category_name: form.category_name,
        product_type: form.product_type,
        regular_price: form.regular_price,
        sale_price: form.sale_price,
        in_stock: form.in_stock,
        warranty_override: form.warranty_override || null,
        template_choice: form.template_choice,
      };

      const { batch_id } = await api.createBatchNoRun(`Quick-Add: ${form.sku}`);
      await api.createProduct(batch_id, rawInput);
      await api.runBatch(batch_id);
      return batch_id;
    },
    onSuccess: (batchId) => {
      toast.success("Product submitted — processing started");
      router.push(`/batches/${batchId}`);
    },
    onError: () => toast.error("Failed to submit product"),
  });

  const canSubmit =
    form.sku && form.model_number && form.brand_name && form.category_name &&
    form.product_type && form.regular_price && form.sale_price;

  return (
    <div className="space-y-8 max-w-2xl">
      <div>
        <h2 className="text-3xl font-bold tracking-tight flex items-center gap-2">
          <Zap className="w-7 h-7 text-accent" />
          Quick-Add
        </h2>
        <p className="text-muted-foreground">
          Submit one product now — same accuracy checks and safety gates as a full batch.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Product Details</CardTitle>
          <CardDescription>SKU/model, brand, and category must match your live taxonomy exactly.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-sm font-medium">SKU</label>
              <Input value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} placeholder="HDG-201S" />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Model Number</label>
              <Input
                value={form.model_number}
                onChange={(e) => setForm({ ...form, model_number: e.target.value })}
                placeholder="HDG-201S"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-sm font-medium">Brand</label>
              <Input
                value={form.brand_name}
                onChange={(e) => setForm({ ...form, brand_name: e.target.value })}
                placeholder="Must match Taxonomy Manager exactly"
              />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Category</label>
              <Input
                value={form.category_name}
                onChange={(e) => setForm({ ...form, category_name: e.target.value })}
                placeholder="Must have a defined spec schema"
              />
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-sm font-medium">Product Type</label>
            <Input
              value={form.product_type}
              onChange={(e) => setForm({ ...form, product_type: e.target.value })}
              placeholder="e.g. Grill Microwave, Split Air Conditioner"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-sm font-medium">Regular Price</label>
              <Input
                type="number"
                value={form.regular_price}
                onChange={(e) => setForm({ ...form, regular_price: e.target.value })}
              />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Sale Price</label>
              <Input
                type="number"
                value={form.sale_price}
                onChange={(e) => setForm({ ...form, sale_price: e.target.value })}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 items-end">
            <div className="space-y-1">
              <label className="text-sm font-medium">Warranty Override (optional)</label>
              <Input
                value={form.warranty_override}
                onChange={(e) => setForm({ ...form, warranty_override: e.target.value })}
                placeholder="Leave blank to use the Warranty Matrix default"
              />
            </div>
            <div className="flex items-center gap-2 pb-2">
              <input
                type="checkbox"
                id="in_stock"
                checked={form.in_stock}
                onChange={(e) => setForm({ ...form, in_stock: e.target.checked })}
              />
              <label htmlFor="in_stock" className="text-sm font-medium">In Stock</label>
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-sm font-medium">Template</label>
            <div className="flex gap-2">
              <Button
                type="button"
                variant={form.template_choice === "A" ? "primary" : "outline"}
                size="sm"
                onClick={() => setForm({ ...form, template_choice: "A" })}
              >
                A — With Images
              </Button>
              <Button
                type="button"
                variant={form.template_choice === "B" ? "primary" : "outline"}
                size="sm"
                onClick={() => setForm({ ...form, template_choice: "B" })}
              >
                B — No Images
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Automatically falls back to B if fewer than 3 images are found for this product.
            </p>
          </div>

          <Button
            className="w-full"
            disabled={!canSubmit || submitMutation.isPending}
            onClick={() => submitMutation.mutate()}
          >
            {submitMutation.isPending ? "Submitting..." : "Submit Product"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

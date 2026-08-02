"use client";

import { useMutation } from "@tanstack/react-query";
import { api, type SheetRowInput, type SheetRowPreview } from "@/lib/apiClient";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle2, FileSpreadsheet } from "lucide-react";

/**
 * Splits pasted spreadsheet text into rows.
 *
 * Tab-separated because that is what Excel and Google Sheets put on the
 * clipboard. Column ORDER is trusted (it is the owner's fixed sheet layout);
 * column MEANING is not — which of the two price cells is the regular price is
 * decided server-side from the values, since the real sheet's "Regular Price"
 * column holds the lower selling price.
 */
function parsePastedRows(text: string): readonly SheetRowInput[] {
  const rows: SheetRowInput[] = [];

  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    const cells = line.split("\t").map((c) => c.trim());

    // Tolerate a leading serial-number column, which the owner's sheet has.
    const offset = cells.length > 0 && /^\d+$/.test(cells[0] ?? "") ? 1 : 0;
    const name = cells[offset] ?? "";
    const priceA = (cells[offset + 1] ?? "").replace(/[^\d.]/g, "");
    const priceB = (cells[offset + 2] ?? "").replace(/[^\d.]/g, "");

    // A header row has no numeric prices; skipping it silently is safe because
    // a real product row always carries two.
    if (!name || !priceA || !priceB) continue;

    rows.push({
      product_name: name,
      price_a: priceA,
      price_b: priceB,
      warranty: cells[offset + 3] || undefined,
      status: cells[offset + 4] || undefined,
    });
  }

  return rows;
}

export default function NewBatchPage() {
  const [label, setLabel] = useState("");
  const [pasted, setPasted] = useState("");
  const [previews, setPreviews] = useState<readonly SheetRowPreview[] | null>(null);

  const preview = useMutation({
    mutationFn: () => api.parseSheet(parsePastedRows(pasted)),
    onSuccess: (result) => {
      setPreviews(result);
      if (result.length === 0) {
        toast.error("No product rows found. Paste the rows including both price columns.");
      }
    },
    onError: (error: Error) => toast.error(error.message || "Could not parse the rows."),
  });

  const readyRows = previews?.filter((r) => r.ready) ?? [];
  const blockedRows = previews?.filter((r) => !r.ready) ?? [];

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">New Batch</h2>
        <p className="text-muted-foreground">
          Paste rows straight from the sheet. Nothing is created until the preview below is reviewed.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileSpreadsheet className="h-5 w-5 text-primary" aria-hidden />
            Paste sheet rows
          </CardTitle>
          <CardDescription>
            Columns in sheet order: Product Name, then the two price cells, then Warranty and Status.
            A leading S.No column is ignored.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Input
            placeholder="Batch name (e.g. Kenwood ACs — 22 July)"
            aria-label="Batch name"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
          <textarea
            value={pasted}
            onChange={(e) => setPasted(e.target.value)}
            rows={8}
            aria-label="Pasted spreadsheet rows"
            placeholder={"1\tKenwood KLU-12B03S 1.0 Ton Split AC\t139999\t150000\t10 Years Compressor Warranty\timages FOUND"}
            className="w-full rounded-md border border-input bg-background p-3 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          />
          <Button
            onClick={() => preview.mutate()}
            disabled={!pasted.trim() || preview.isPending}
          >
            {preview.isPending ? "Checking..." : "Preview rows"}
          </Button>
        </CardContent>
      </Card>

      {previews && previews.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Preview</CardTitle>
            <CardDescription>
              {readyRows.length} ready, {blockedRows.length} need attention. This preview writes
              nothing — check the prices before continuing.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {previews.map((row, index) => (
              <div key={`${row.product_name}-${index}`} className="rounded-md border p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <p className="min-w-0 text-sm font-medium">{row.product_name}</p>
                  {row.ready ? (
                    <span className="flex shrink-0 items-center gap-1 text-xs text-primary">
                      <CheckCircle2 className="h-4 w-4" aria-hidden /> Ready
                    </span>
                  ) : (
                    <span className="flex shrink-0 items-center gap-1 text-xs text-accent">
                      <AlertTriangle className="h-4 w-4" aria-hidden /> Needs attention
                    </span>
                  )}
                </div>

                <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
                  <div>
                    <dt className="text-muted-foreground">SKU</dt>
                    <dd className="font-mono">{row.sku ?? "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Model</dt>
                    <dd className="font-mono">{row.model_number ?? "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Brand</dt>
                    <dd>{row.brand_name ?? "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Category</dt>
                    <dd>{row.category_path ?? row.category_name ?? "—"}</dd>
                  </div>
                  <div>
                    {/* Shown side by side deliberately: the sheet's column
                        labels are unreliable, so this is where a swapped price
                        becomes visible before it is published as a discount. */}
                    <dt className="text-muted-foreground">Regular / Sale</dt>
                    <dd className="font-mono">
                      {row.regular_price}
                      {row.sale_price ? ` / ${row.sale_price}` : " / —"}
                    </dd>
                  </div>
                </dl>

                {row.missing_required.length > 0 && (
                  <ul className="mt-2 space-y-0.5">
                    {row.missing_required.map((issue) => (
                      <li key={issue} className="text-xs text-accent">
                        {issue}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}

            {/* Deliberately not a working button. Creating a product needs a
                Full Product Type (the words that end the title, e.g. "Inverter
                Air Conditioner"), and the sheet does not contain one. Deriving
                it from the category would be a guess that lands in the product
                title and the SEO focus keyword, so it has to be supplied
                rather than invented. */}
            <p className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
              These rows are parsed and verified but not yet created. Creating them needs a Full
              Product Type per row, which the sheet does not contain and the system will not guess —
              it would go straight into the product title. Use Quick Add for single products until
              that field is added here.
            </p>
            <Button disabled title="Needs a Full Product Type per row — see the note above">
              Create batch{label ? `: ${label}` : ""}
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

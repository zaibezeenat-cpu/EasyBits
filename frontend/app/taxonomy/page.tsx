"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type TaxonomyBrand, type TaxonomyCategory } from "@/lib/apiClient";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { AlertCircle, CheckCircle, ChevronRight, Globe, Link2, Tag, X } from "lucide-react";

/**
 * Every mutation surfaces the backend's own message.
 *
 * The API answers taxonomy conflicts with a sentence that names the problem and
 * the fix ("'Kenwood' already exists as a brand. A brand and a category must
 * never share a term."). Replacing that with "Failed to add brand" throws away
 * the only part the operator can act on -- and these particular errors are the
 * guard rails that stop a stray term reaching the live store.
 */
function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

interface CategoryNode extends TaxonomyCategory {
  readonly children: readonly CategoryNode[];
}

function buildTree(categories: readonly TaxonomyCategory[]): readonly CategoryNode[] {
  const byParent = new Map<string | null, TaxonomyCategory[]>();
  for (const category of categories) {
    const siblings = byParent.get(category.parent_id) ?? [];
    siblings.push(category);
    byParent.set(category.parent_id, siblings);
  }

  const attach = (parentId: string | null): readonly CategoryNode[] =>
    (byParent.get(parentId) ?? [])
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((category) => ({ ...category, children: attach(category.id) }));

  return attach(null);
}

export default function TaxonomyPage() {
  const queryClient = useQueryClient();
  const [newBrandName, setNewBrandName] = useState("");
  const [newCategoryName, setNewCategoryName] = useState("");
  const [newCategoryParentId, setNewCategoryParentId] = useState("");
  const [editingDomainFor, setEditingDomainFor] = useState<string | null>(null);
  const [domainDraft, setDomainDraft] = useState("");

  const { data: categories, isLoading: categoriesLoading } = useQuery({
    queryKey: ["categories"],
    queryFn: api.listCategories,
  });
  const { data: brands, isLoading: brandsLoading } = useQuery({
    queryKey: ["brands"],
    queryFn: api.listBrands,
  });
  const { data: brandDomains } = useQuery({
    queryKey: ["brand-domains"],
    queryFn: api.listBrandDomains,
  });

  const tree = useMemo(() => buildTree(categories ?? []), [categories]);
  const brandsWithoutDomain = useMemo(
    () => (brands ?? []).filter((b) => b.is_active && !brandDomains?.[b.id]).length,
    [brands, brandDomains],
  );

  const invalidateBrands = () => {
    queryClient.invalidateQueries({ queryKey: ["brands"] });
    queryClient.invalidateQueries({ queryKey: ["brand-domains"] });
  };

  const addBrand = useMutation({
    mutationFn: (name: string) => api.createBrand(name),
    onSuccess: () => {
      invalidateBrands();
      setNewBrandName("");
      toast.success("Brand added");
    },
    onError: (error) => toast.error(errorMessage(error, "Could not add the brand.")),
  });

  const toggleBrandCasing = useMutation({
    mutationFn: ({ id, casing_confirmed }: { id: string; casing_confirmed: boolean }) =>
      api.updateBrand(id, { casing_confirmed }),
    onSuccess: invalidateBrands,
    onError: (error) => toast.error(errorMessage(error, "Could not update the brand.")),
  });

  const saveDisplayName = useMutation({
    mutationFn: ({ id, display_name }: { id: string; display_name: string }) =>
      api.updateBrand(id, { display_name }),
    onSuccess: () => {
      invalidateBrands();
      toast.success("Title display name saved");
    },
    onError: (error) => toast.error(errorMessage(error, "Could not save the display name.")),
  });

  const saveDomain = useMutation({
    mutationFn: ({ id, domain }: { id: string; domain: string }) => api.setBrandDomain(id, domain),
    onSuccess: (result) => {
      invalidateBrands();
      setEditingDomainFor(null);
      setDomainDraft("");
      // Show what was actually stored: the API normalises a pasted URL down to
      // a host (plus brand-section path), so the saved value often differs from
      // what was typed. Claiming plain success would hide that.
      toast.success(`Official source saved as ${result.official_domain}`);
    },
    onError: (error) => toast.error(errorMessage(error, "Could not save the official source.")),
  });

  const clearDomain = useMutation({
    mutationFn: (id: string) => api.clearBrandDomain(id),
    onSuccess: () => {
      invalidateBrands();
      toast.success("Official source removed");
    },
    onError: (error) => toast.error(errorMessage(error, "Could not remove the official source.")),
  });

  const addCategory = useMutation({
    mutationFn: () => api.createCategory(newCategoryName, newCategoryParentId || undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["categories"] });
      setNewCategoryName("");
      setNewCategoryParentId("");
      toast.success("Category added");
    },
    onError: (error) => toast.error(errorMessage(error, "Could not add the category.")),
  });

  const confirmCategory = useMutation({
    mutationFn: ({ id, needs_confirmation }: { id: string; needs_confirmation: boolean }) =>
      api.updateCategory(id, { needs_confirmation }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["categories"] }),
    onError: (error) => toast.error(errorMessage(error, "Could not update the category.")),
  });

  const renderNode = (node: CategoryNode, depth: number) => (
    <li key={node.id}>
      <div
        className="flex items-center justify-between gap-2 rounded-md border p-2 transition-colors hover:bg-muted/30"
        style={{ marginInlineStart: `${depth * 1.25}rem` }}
      >
        <span className="flex min-w-0 items-center gap-1.5">
          {depth > 0 && <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />}
          <span className="truncate text-sm font-medium">{node.name}</span>
          {!node.is_active && (
            <span className="shrink-0 text-xs text-muted-foreground">(inactive)</span>
          )}
        </span>
        <Button
          variant="outline"
          size="sm"
          className="shrink-0"
          aria-label={
            node.needs_confirmation
              ? `Confirm ${node.name} matches the live category tree`
              : `Mark ${node.name} as unconfirmed`
          }
          onClick={() =>
            confirmCategory.mutate({ id: node.id, needs_confirmation: !node.needs_confirmation })
          }
        >
          {node.needs_confirmation ? (
            <span className="flex items-center gap-1 text-accent">
              <AlertCircle className="h-4 w-4" aria-hidden /> Confirm
            </span>
          ) : (
            <span className="flex items-center gap-1 text-primary">
              <CheckCircle className="h-4 w-4" aria-hidden /> Confirmed
            </span>
          )}
        </Button>
      </div>
      {node.children.length > 0 && (
        <ul className="mt-2 space-y-2">{node.children.map((child) => renderNode(child, depth + 1))}</ul>
      )}
    </li>
  );

  const renderBrand = (brand: TaxonomyBrand) => {
    const domain = brandDomains?.[brand.id];
    const isEditing = editingDomainFor === brand.id;

    return (
      <li key={brand.id} className="rounded-md border p-2">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-sm font-medium">{brand.name}</span>
          <Button
            variant="outline"
            size="sm"
            className="shrink-0"
            title="Toggle once you have verified this casing against the live WooCommerce Brands taxonomy"
            aria-label={`${brand.casing_confirmed ? "Unconfirm" : "Confirm"} casing for ${brand.name}`}
            onClick={() =>
              toggleBrandCasing.mutate({ id: brand.id, casing_confirmed: !brand.casing_confirmed })
            }
          >
            {brand.casing_confirmed ? (
              <span className="flex items-center gap-1 text-primary">
                <CheckCircle className="h-4 w-4" aria-hidden /> Confirmed
              </span>
            ) : (
              <span className="flex items-center gap-1 text-accent">
                <AlertCircle className="h-4 w-4" aria-hidden /> Confirm
              </span>
            )}
          </Button>
        </div>

        {/* Title display casing: the Brands column keeps the exact term above
            ({brand.name}); this is only how the brand appears in the product
            TITLE (e.g. "Haier" while the column stays "HAIER"). Blank = use the
            term as-is. */}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Tag className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <span className="shrink-0 text-xs text-muted-foreground">Title as:</span>
          <Input
            defaultValue={brand.display_name ?? ""}
            placeholder={brand.name}
            aria-label={`Title display name for ${brand.name}`}
            className="h-8 min-w-0 flex-1 text-xs"
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                saveDisplayName.mutate({ id: brand.id, display_name: e.currentTarget.value });
              }
            }}
            onBlur={(e) => {
              const next = e.currentTarget.value.trim();
              if (next !== (brand.display_name ?? "")) {
                saveDisplayName.mutate({ id: brand.id, display_name: next });
              }
            }}
          />
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Link2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
          {isEditing ? (
            <>
              <Input
                autoFocus
                value={domainDraft}
                placeholder="kenwoodpakistan.pk or paste the brand's page URL"
                aria-label={`Official source for ${brand.name}`}
                className="h-8 min-w-0 flex-1 text-xs"
                onChange={(e) => setDomainDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && domainDraft.trim()) {
                    saveDomain.mutate({ id: brand.id, domain: domainDraft });
                  }
                  if (e.key === "Escape") setEditingDomainFor(null);
                }}
              />
              <Button
                size="sm"
                className="h-8"
                disabled={!domainDraft.trim() || saveDomain.isPending}
                onClick={() => saveDomain.mutate({ id: brand.id, domain: domainDraft })}
              >
                {saveDomain.isPending ? "Saving..." : "Save"}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-8"
                aria-label="Cancel editing"
                onClick={() => setEditingDomainFor(null)}
              >
                <X className="h-4 w-4" aria-hidden />
              </Button>
            </>
          ) : (
            <>
              {domain ? (
                <code className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground">
                  {domain}
                </code>
              ) : (
                // Not decoration: with no official source, tier 2 of discovery
                // never runs for this brand and its products fall back to
                // retailer sites or escalate.
                <span className="min-w-0 flex-1 text-xs text-accent">
                  No official source — brand site will not be searched
                </span>
              )}
              <Button
                variant="ghost"
                size="sm"
                className="h-8 shrink-0 text-xs"
                onClick={() => {
                  setEditingDomainFor(brand.id);
                  setDomainDraft(domain ?? "");
                }}
              >
                {domain ? "Edit" : "Add"}
              </Button>
              {domain && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 shrink-0"
                  aria-label={`Remove official source for ${brand.name}`}
                  onClick={() => clearDomain.mutate(brand.id)}
                >
                  <X className="h-4 w-4" aria-hidden />
                </Button>
              )}
            </>
          )}
        </div>
      </li>
    );
  };

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Taxonomy Manager</h2>
        <p className="text-muted-foreground">
          Brands and categories exactly as they exist in the live store. A term that differs by one
          letter is a different term to WooCommerce, so the casing here is the casing that gets exported.
        </p>
      </div>

      <div className="grid gap-8 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Tag className="h-5 w-5 text-primary" aria-hidden />
              Categories
            </CardTitle>
            <CardDescription>
              Exported as a <code className="font-mono text-xs">Parent &gt; Child</code> breadcrumb.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <Input
                placeholder="Category name (exact casing)"
                aria-label="New category name"
                className="min-w-[10rem] flex-1"
                value={newCategoryName}
                onChange={(e) => setNewCategoryName(e.target.value)}
              />
              {/* A select, not free text: the previous free-text parent field
                  matched case-insensitively, so a typo silently created a
                  top-level category instead of a child. */}
              <select
                aria-label="Parent category"
                className="h-9 min-w-[9rem] flex-1 rounded-md border border-input bg-background px-3 text-sm"
                value={newCategoryParentId}
                onChange={(e) => setNewCategoryParentId(e.target.value)}
              >
                <option value="">No parent (top level)</option>
                {(categories ?? [])
                  .slice()
                  .sort((a, b) => a.name.localeCompare(b.name))
                  .map((category) => (
                    <option key={category.id} value={category.id}>
                      {category.name}
                    </option>
                  ))}
              </select>
              <Button
                onClick={() => addCategory.mutate()}
                disabled={!newCategoryName.trim() || addCategory.isPending}
              >
                {addCategory.isPending ? "Adding..." : "Add"}
              </Button>
            </div>

            {categoriesLoading ? (
              <div className="space-y-2">
                {[0, 1, 2, 3, 4].map((i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : tree.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">No categories yet.</p>
            ) : (
              <ul className="max-h-[440px] space-y-2 overflow-y-auto pr-2">
                {tree.map((node) => renderNode(node, 0))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Globe className="h-5 w-5 text-primary" aria-hidden />
              Brands
            </CardTitle>
            <CardDescription>
              {brandsWithoutDomain > 0
                ? `${brandsWithoutDomain} active brand${brandsWithoutDomain === 1 ? "" : "s"} without an official source.`
                : "Every active brand has an official source configured."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <Input
                placeholder="Brand name (exact casing, e.g. DAWLANCE)"
                aria-label="New brand name"
                className="min-w-[12rem] flex-1"
                value={newBrandName}
                onChange={(e) => setNewBrandName(e.target.value)}
              />
              <Button
                onClick={() => addBrand.mutate(newBrandName)}
                disabled={!newBrandName.trim() || addBrand.isPending}
              >
                {addBrand.isPending ? "Adding..." : "Add"}
              </Button>
            </div>

            {brandsLoading ? (
              <div className="space-y-2">
                {[0, 1, 2, 3, 4].map((i) => (
                  <Skeleton key={i} className="h-16 w-full" />
                ))}
              </div>
            ) : (brands ?? []).length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">No brands yet.</p>
            ) : (
              <ul className="max-h-[440px] space-y-2 overflow-y-auto pr-2">
                {(brands ?? [])
                  .slice()
                  .sort((a, b) => a.name.localeCompare(b.name))
                  .map(renderBrand)}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

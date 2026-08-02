"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type SourceMode, type TrustLevelMode } from "@/lib/apiClient";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useState } from "react";
import { toast } from "sonner";
import { ShieldCheck, Database, Upload, ShieldAlert, Globe2, Type, KeyRound, CheckCircle2, XCircle, ArrowUp, ArrowDown } from "lucide-react";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [skuFile, setSkuFile] = useState<File | null>(null);
  const [newSourceDomain, setNewSourceDomain] = useState("");
  const [newSourceLabel, setNewSourceLabel] = useState("");

  const { data: trustedSources } = useQuery({
    queryKey: ["trusted-secondary-sources"],
    queryFn: api.listTrustedSecondarySources,
  });

  const addSourceMutation = useMutation({
    mutationFn: () => api.addTrustedSecondarySource(newSourceDomain, newSourceLabel),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trusted-secondary-sources"] });
      setNewSourceDomain("");
      setNewSourceLabel("");
      toast.success("Trusted secondary source added");
    },
    // The backend rejects a malformed domain with a message naming the fix
    // ("Enter it like 'kenwood.com.pk'"). "Failed to add source" would hide it.
    onError: (error: Error) => toast.error(error.message || "Could not add the source."),
  });

  const toggleSourceMutation = useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) =>
      api.toggleTrustedSecondarySource(id, isActive),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["trusted-secondary-sources"] }),
    onError: (error: Error) => toast.error(error.message || "Could not update the source."),
  });

  // Order decides which retailer is consulted first when no official brand
  // source answers, so it is a real setting, not a display preference.
  const reorderSourcesMutation = useMutation({
    mutationFn: (ids: readonly string[]) => api.reorderTrustedSecondarySources(ids),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["trusted-secondary-sources"] }),
    onError: (error: Error) => toast.error(error.message || "Could not reorder the sources."),
  });

  const { data: sourceMode } = useQuery({
    queryKey: ["source-mode"],
    queryFn: api.getSourceMode,
  });

  const setSourceModeMutation = useMutation({
    mutationFn: (mode: SourceMode) => api.setSourceMode(mode),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["source-mode"] });
      toast.success(
        result.mode === "strict"
          ? "Strict mode: only configured sources will be used."
          : "Priority mode: other sites may be used as a fallback.",
      );
    },
    onError: (error: Error) => toast.error(error.message || "Could not change the source mode."),
  });

  /**
   * Moves one source and submits the WHOLE resulting order.
   *
   * Sending just the moved item's new index would leave every other row's
   * priority stale, producing duplicate values and a final order decided by the
   * database's tiebreak rather than by what was on screen.
   */
  const moveSource = (index: number, direction: -1 | 1) => {
    if (!trustedSources) return;
    const target = index + direction;
    if (target < 0 || target >= trustedSources.length) return;
    const ordered = trustedSources.slice();
    const moved = ordered[index];
    if (!moved) return;
    ordered.splice(index, 1);
    ordered.splice(target, 0, moved);
    reorderSourcesMutation.mutate(ordered.map((s) => s.id));
  };

  const { data: seoTitleDescriptors } = useQuery({
    queryKey: ["seo-title-descriptors"],
    queryFn: api.getSeoTitleDescriptors,
  });

  const { data: apiKeyStatus } = useQuery({
    queryKey: ["api-key-status"],
    queryFn: api.getApiKeyStatus,
  });

  const { data: trustLevel } = useQuery({
    queryKey: ["trust-level"],
    queryFn: api.getTrustLevel,
  });

  const setTrustLevelMutation = useMutation({
    mutationFn: (mode: TrustLevelMode) => api.setTrustLevel(mode),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["trust-level"] });
      toast.success(`Trust level set to ${data.mode === "full_review" ? "Full Review" : "Quick Review"} Mode`);
    },
    onError: () => toast.error("Failed to update trust level"),
  });

  const { data: warranties } = useQuery({
    queryKey: ["warranties"],
    queryFn: api.listWarrantyMatrix,
  });

  // Real status from the database, so the card reports what is actually stored
  // rather than assuming an upload happened.
  const { data: snapshotStatus } = useQuery({
    queryKey: ["sku-snapshot-status"],
    queryFn: api.getSkuSnapshotStatus,
  });

  const uploadSkuSnapshotMutation = useMutation({
    // This previously slept 1.5s and returned {success:true} without uploading
    // anything, so the operator saw a green "updated successfully" while the
    // table stayed empty and the duplicate-SKU guard stayed switched off.
    mutationFn: (file: File) => api.uploadSkuSnapshot(file),
    onSuccess: (result) => {
      setSkuFile(null);
      queryClient.invalidateQueries({ queryKey: ["sku-snapshot-status"] });
      toast.success(`Imported ${result.count.toLocaleString()} SKUs`);
      // Surface skipped rows: a silently partial snapshot looks like protection
      // while leaving most products exposed.
      for (const warning of result.warnings) {
        toast.warning(warning);
      }
    },
    onError: (error: Error) => {
      toast.error(error.message || "Upload failed. The previous snapshot is unchanged.");
    },
  });

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Settings</h2>
        <p className="text-muted-foreground">Configure system rules and reference data.</p>
      </div>

      <div className="grid gap-8 lg:grid-cols-2">
        {/* Trust Level */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldAlert className="w-5 h-5 text-primary" />
              Trust Level
            </CardTitle>
            <CardDescription>
              Full Review Mode shows every field with its source citation. Quick Review Mode shows only
              flagged fields — switch only after the pilot has proven a stable low error rate (phase1.md §15).
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between p-3 border rounded-md">
              <div>
                <p className="text-sm font-medium">
                  Current mode: {trustLevel?.mode === "quick_review" ? "Quick Review" : "Full Review"}
                </p>
                <p className="text-xs text-muted-foreground">This is a one-way decision per your own rollout plan.</p>
              </div>
              <Button
                variant="outline"
                disabled={setTrustLevelMutation.isPending}
                onClick={() => {
                  const next: TrustLevelMode =
                    trustLevel?.mode === "quick_review" ? "full_review" : "quick_review";
                  if (
                    next === "quick_review" &&
                    !window.confirm(
                      "Switching to Quick Review Mode hides unflagged fields from every future review. Only do this once the pilot has shown a stable low error rate. Continue?"
                    )
                  ) {
                    return;
                  }
                  setTrustLevelMutation.mutate(next);
                }}
              >
                Switch to {trustLevel?.mode === "quick_review" ? "Full" : "Quick"} Review
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Warranty Matrix */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="w-5 h-5 text-primary" />
              Warranty Matrix
            </CardTitle>
            <CardDescription>Official brand/category warranty durations.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="text-sm font-medium border-b pb-2 flex justify-between">
                <span>Brand / Category</span>
                <span>Duration</span>
              </div>
              <div className="space-y-2 max-h-[400px] overflow-y-auto">
                {warranties?.map((w) => (
                  <div key={w.id} className="flex justify-between items-center p-2 text-sm border-b border-dashed">
                    <div>
                      <span className="font-bold">{w.brand_name}</span>
                      <span className="text-muted-foreground mx-2">/</span>
                      <span>{w.category_name}</span>
                      {w.is_stale && (
                        <span className="ml-2 text-[10px] bg-danger/10 text-danger px-1.5 py-0.5 rounded uppercase">
                          Stale (&gt;90 days)
                        </span>
                      )}
                    </div>
                    <span className="bg-primary/10 text-primary px-2 py-0.5 rounded font-medium">
                      {w.warranty_phrase}
                    </span>
                  </div>
                ))}
              </div>
              <Button variant="outline" className="w-full mt-4">Add Rule</Button>
            </div>
          </CardContent>
        </Card>

        {/* Trusted Secondary Sources */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Globe2 className="w-5 h-5 text-primary" />
              Trusted Secondary Sources
            </CardTitle>
            <CardDescription>
              Fallback sources used only when Agent 1 can&apos;t find an official-domain match (phase1.md §5.3).
              Seeded with Japan Electronics/Surmawala, fully editable here.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex gap-2">
              <Input
                placeholder="domain (e.g. japanelectronics.pk)"
                value={newSourceDomain}
                onChange={(e) => setNewSourceDomain(e.target.value)}
              />
              <Input
                placeholder="label (e.g. Japan Electronics)"
                value={newSourceLabel}
                onChange={(e) => setNewSourceLabel(e.target.value)}
              />
              <Button
                onClick={() => addSourceMutation.mutate()}
                disabled={!newSourceDomain || !newSourceLabel || addSourceMutation.isPending}
              >
                Add
              </Button>
            </div>
            {/* Source mode. Defaults to strict, matching the rest of the
                system's no-guess principle: a product that cannot be verified
                from an approved source goes to Manual Review rather than being
                built from an unknown site. */}
            <fieldset className="rounded-md border p-3">
              <legend className="px-1 text-xs font-medium text-muted-foreground">
                When no configured source has the product
              </legend>
              <div className="flex flex-col gap-2 sm:flex-row">
                {(
                  [
                    {
                      mode: "strict" as const,
                      title: "Strict",
                      detail: "Send it to Manual Review. Nothing outside this list is ever read.",
                    },
                    {
                      mode: "priority" as const,
                      title: "Priority",
                      detail: "Try other sites as a fallback. Faster, but the source is unvetted.",
                    },
                  ]
                ).map(({ mode, title, detail }) => {
                  const active = sourceMode?.mode === mode;
                  return (
                    <button
                      key={mode}
                      type="button"
                      aria-pressed={active}
                      disabled={setSourceModeMutation.isPending}
                      onClick={() => setSourceModeMutation.mutate(mode)}
                      className={`flex-1 rounded-md border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:opacity-50 ${
                        active ? "border-primary bg-primary/10" : "hover:bg-muted/50"
                      }`}
                    >
                      <span className="block text-sm font-medium">{title}</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">{detail}</span>
                    </button>
                  );
                })}
              </div>
            </fieldset>

            <ol className="max-h-[300px] space-y-2 overflow-y-auto">
              {trustedSources?.map((s, index) => (
                <li
                  key={s.id}
                  className={`flex flex-wrap items-center justify-between gap-2 rounded-md border p-2 text-sm ${
                    s.is_active ? "" : "opacity-60"
                  }`}
                >
                  <div className="flex min-w-0 items-center gap-2">
                    {/* Position, not the raw priority value: after a reorder the
                        stored numbers are 0-based, and showing "p0" for the
                        first source reads like an error. */}
                    <span
                      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium"
                      aria-hidden
                    >
                      {index + 1}
                    </span>
                    <span className="min-w-0">
                      <span className="font-medium">{s.label}</span>
                      <span className="ml-2 font-mono text-xs text-muted-foreground">{s.domain}</span>
                    </span>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Move ${s.label} earlier`}
                      disabled={index === 0 || reorderSourcesMutation.isPending}
                      onClick={() => moveSource(index, -1)}
                    >
                      <ArrowUp className="h-4 w-4" aria-hidden />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Move ${s.label} later`}
                      disabled={
                        index === (trustedSources?.length ?? 0) - 1 || reorderSourcesMutation.isPending
                      }
                      onClick={() => moveSource(index, 1)}
                    >
                      <ArrowDown className="h-4 w-4" aria-hidden />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => toggleSourceMutation.mutate({ id: s.id, isActive: !s.is_active })}
                    >
                      {s.is_active ? "Deactivate" : "Activate"}
                    </Button>
                  </div>
                </li>
              ))}
            </ol>

            {trustedSources?.length === 0 && (
              // Clearing the list does not fall back to a built-in default --
              // discovery escalates instead. Saying so prevents an empty list
              // being mistaken for "use anything".
              <p className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
                No secondary sources configured. Products without an official brand source will go
                straight to Manual Review.
              </p>
            )}
          </CardContent>
        </Card>

        {/* SEO Title Descriptors */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Type className="w-5 h-5 text-primary" />
              SEO Title Descriptors
            </CardTitle>
            <CardDescription>
              The &quot;Boss Title Rule&quot; registry (`seo_title_builder.py`). Read-only here — adding a new
              category&apos;s literal descriptor is a one-line code change, not a database edit, since the
              title format is deterministic logic, not user data.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {seoTitleDescriptors && (
              <>
                {Object.entries(seoTitleDescriptors.category_descriptors).map(([category, descriptor]) => (
                  <div key={category} className="p-2 border rounded-md text-sm">
                    <div className="font-bold">{category}</div>
                    <div className="text-xs text-muted-foreground font-mono">{descriptor}</div>
                  </div>
                ))}
                <div className="p-2 border rounded-md text-sm bg-muted/30">
                  <div className="font-bold">All other categories</div>
                  <div className="text-xs text-muted-foreground font-mono">
                    [Focus Keyword] | {seoTitleDescriptors.fallback_power_word}
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* API Key Status */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <KeyRound className="w-5 h-5 text-primary" />
              API Key Status
            </CardTitle>
            <CardDescription>
              Presence only — values live only in the server&apos;s environment, never fetched or shown here.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {apiKeyStatus &&
              Object.entries(apiKeyStatus).map(([key, present]) => (
                <div key={key} className="flex items-center justify-between p-2 border rounded-md text-sm">
                  <span className="font-mono">{key}</span>
                  {present ? (
                    <CheckCircle2 className="w-4 h-4 text-success" />
                  ) : (
                    <XCircle className="w-4 h-4 text-danger" />
                  )}
                </div>
              ))}
          </CardContent>
        </Card>

        {/* SKU Snapshot */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="w-5 h-5 text-primary" />
              Live SKU Snapshot
            </CardTitle>
            <CardDescription>Upload current WooCommerce SKUs to prevent collisions.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="p-8 border-2 border-dashed rounded-lg flex flex-col items-center justify-center text-center space-y-4">
              <Upload className="w-10 h-10 text-muted-foreground" />
              <div>
                <p className="text-sm font-medium">Click to upload or drag and drop</p>
                <p className="text-xs text-muted-foreground">CSV file from WooCommerce Export</p>
              </div>
              <Input 
                type="file" 
                accept=".csv" 
                onChange={(e) => setSkuFile(e.target.files?.[0] || null)}
                className="hidden" 
                id="sku-upload"
              />
              <label htmlFor="sku-upload" className="cursor-pointer bg-secondary text-secondary-foreground px-4 py-2 rounded-md text-sm hover:bg-secondary/80">
                Select File
              </label>
              {skuFile && <p className="text-xs font-mono text-primary">{skuFile.name}</p>}
            </div>
            
            <Button 
              className="w-full" 
              disabled={!skuFile || uploadSkuSnapshotMutation.isPending}
              onClick={() => uploadSkuSnapshotMutation.mutate(skuFile!)}
            >
              {uploadSkuSnapshotMutation.isPending ? "Uploading..." : "Sync SKUs"}
            </Button>
            
            {/* Both values below were previously hardcoded: "last synced" printed
                today's date on every render, and the count was a literal 1,245.
                An operator who had never uploaded anything still saw a healthy,
                current-looking snapshot. */}
            <div className="p-4 bg-muted/50 rounded-md">
              <p className="text-xs text-muted-foreground">
                <strong>Last synced:</strong>{" "}
                {snapshotStatus?.last_imported_at
                  ? new Date(snapshotStatus.last_imported_at).toLocaleString()
                  : "Never"}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                <strong>Total SKUs indexed:</strong>{" "}
                {snapshotStatus ? snapshotStatus.sku_count.toLocaleString() : "—"}
              </p>
              {snapshotStatus?.sku_count === 0 && (
                <p className="text-xs text-destructive mt-2 font-medium">
                  No SKUs indexed — the duplicate-SKU guard cannot block anything.
                  Upload your WooCommerce export before exporting any batch.
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

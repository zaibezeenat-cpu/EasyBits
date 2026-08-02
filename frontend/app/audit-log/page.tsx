"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type AuditEvent } from "@/lib/apiClient";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollText } from "lucide-react";

/**
 * Plain-language labels for the events actually written by the backend.
 *
 * An unknown type falls back to its raw slug rather than being hidden: a new
 * event appearing untranslated is a cosmetic gap, but an event silently
 * dropped from the trail defeats the point of having one.
 */
const EVENT_LABELS: Readonly<Record<string, string>> = {
  brand_created: "Brand created",
  category_created: "Category created",
  brand_domain_set: "Brand official source set",
  brand_domain_cleared: "Brand official source removed",
  sources_reordered: "Secondary sources reordered",
  source_mode_changed: "Source mode changed",
  sku_snapshot_replaced: "Live SKU snapshot replaced",
};

function summarise(event: AuditEvent): string {
  const p = event.payload;
  switch (event.event_type) {
    case "brand_created":
    case "category_created":
      return typeof p.name === "string" ? p.name : "";
    case "brand_domain_set":
      return typeof p.official_domain === "string" ? p.official_domain : "";
    case "source_mode_changed":
      return typeof p.mode === "string" ? p.mode : "";
    case "sku_snapshot_replaced":
      return typeof p.count === "number" ? `${p.count.toLocaleString()} SKUs` : "";
    case "sources_reordered":
      return Array.isArray(p.order) ? `${p.order.length} sources` : "";
    default:
      return "";
  }
}

export default function AuditLogPage() {
  const { data: events, isLoading, isError, error } = useQuery({
    queryKey: ["audit-events"],
    queryFn: () => api.listAuditEvents(200),
  });

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Audit Log</h2>
        <p className="text-muted-foreground">
          Every change that affects what future exports contain — taxonomy edits, source changes and
          snapshot replacements — newest first.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ScrollText className="h-5 w-5 text-primary" aria-hidden />
            Recent activity
          </CardTitle>
          <CardDescription>
            Written by the operations themselves; entries cannot be submitted or edited from here.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : isError ? (
            <p className="py-8 text-center text-sm text-destructive">
              {error instanceof Error ? error.message : "Could not load the audit log."}
            </p>
          ) : (events ?? []).length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No activity recorded yet. Entries appear here as soon as taxonomy, sources or the SKU
              snapshot are changed.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="sr-only">Audit events, newest first</caption>
                <thead>
                  <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th scope="col" className="py-2 pr-4 font-medium">When</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Event</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Detail</th>
                    <th scope="col" className="py-2 font-medium">Actor</th>
                  </tr>
                </thead>
                <tbody>
                  {(events ?? []).map((event) => (
                    <tr key={event.id} className="border-b last:border-0">
                      <td className="whitespace-nowrap py-2 pr-4 text-muted-foreground">
                        {new Date(event.created_at).toLocaleString()}
                      </td>
                      <td className="py-2 pr-4 font-medium">
                        {EVENT_LABELS[event.event_type] ?? event.event_type}
                      </td>
                      <td className="py-2 pr-4 font-mono text-xs text-muted-foreground">
                        {summarise(event)}
                      </td>
                      <td className="whitespace-nowrap py-2 text-muted-foreground">{event.actor}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Package,
  Layers,
  AlertTriangle,
  Clock,
  TrendingUp,
  Plus,
  Zap
} from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/apiClient";

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  const minutes = Math.round(seconds / 60);
  return `${minutes} min`;
}

export default function Dashboard() {
  // All 5 cards are real data from the backend — no hardcoded/mock values
  // (phase2.md §5.2: "5 stat cards ... not vanity metrics").
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: api.getDashboardStats,
  });

  const { data: batches, isLoading: batchesLoading } = useQuery({
    queryKey: ["batches"],
    queryFn: api.listBatches,
  });

  const recentBatches = (batches || []).slice(0, 10);

  const cards = [
    {
      label: "Manual Review Queue",
      value: statsLoading ? "…" : String(stats?.manual_review_count ?? 0),
      icon: AlertTriangle,
      color: "text-danger",
      href: "/review-queue",
    },
    {
      label: "Ready for QA",
      value: statsLoading ? "…" : String(stats?.ready_for_qa_count ?? 0),
      icon: Package,
      color: "text-accent",
      href: "/products?status=ready_for_qa",
    },
    {
      label: "Batches In Progress",
      value: statsLoading ? "…" : String(stats?.batches_in_progress_count ?? 0),
      icon: Layers,
      color: "text-accent",
      href: "/batches",
    },
    {
      label: "Approved This Week",
      value: statsLoading ? "…" : String(stats?.week_approved_count ?? 0),
      icon: TrendingUp,
      color: "text-success",
      href: "/batches",
    },
    {
      label: "Avg QA Time / Product (7d)",
      value: statsLoading ? "…" : formatDuration(stats?.avg_qa_seconds ?? null),
      icon: Clock,
      color: "text-accent",
      href: undefined,
    },
  ];

  return (
    <div className="p-8 space-y-8 bg-background min-h-screen">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-textPrimary">Product Dashboard</h1>
          <p className="text-textSecondary">Welcome to kiachahye.pk automation engine</p>
        </div>
        <div className="flex gap-4">
          <Link href="/products/quick-add">
            <Button variant="outline" className="flex gap-2">
              <Zap className="w-4 h-4" /> Quick Add
            </Button>
          </Link>
          <Link href="/batches/new">
            <Button className="bg-accent hover:bg-accent/90 flex gap-2">
              <Plus className="w-4 h-4" /> New Batch
            </Button>
          </Link>
        </div>
      </div>

      {/* Exactly 5 stat cards, no charts, no extra widgets (phase2.md §5.2) */}
      <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-6">
        {cards.map((stat) => {
          const CardBody = (
            <Card key={stat.label} className="border-border shadow-sm h-full">
              <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                <CardTitle className="text-sm font-medium text-textSecondary">
                  {stat.label}
                </CardTitle>
                <stat.icon className={`w-4 h-4 ${stat.color}`} />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-textPrimary">{stat.value}</div>
              </CardContent>
            </Card>
          );
          return stat.href ? (
            <Link key={stat.label} href={stat.href}>{CardBody}</Link>
          ) : (
            CardBody
          );
        })}
      </div>

      <Card className="border-border">
        <CardHeader>
          <CardTitle>Recent Batches</CardTitle>
          <CardDescription>Monitor live processing status</CardDescription>
        </CardHeader>
        <CardContent>
          {batchesLoading ? (
            <div className="text-sm text-textSecondary">Loading…</div>
          ) : recentBatches.length === 0 ? (
            <div className="text-sm text-textSecondary">No active batches. Create one to begin.</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-textSecondary border-b border-border">
                  <th className="py-2 font-medium">Label</th>
                  <th className="py-2 font-medium">Status</th>
                  <th className="py-2 font-medium">Succeeded</th>
                  <th className="py-2 font-medium">Failed</th>
                  <th className="py-2 font-medium">Manual Review</th>
                  <th className="py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {recentBatches.map((batch) => (
                  <tr key={batch.id} className="border-b border-border last:border-0">
                    <td className="py-2 text-textPrimary">{batch.label}</td>
                    <td className="py-2 text-textSecondary">{batch.status}</td>
                    <td className="py-2 text-textSecondary">{batch.succeeded_count}</td>
                    <td className="py-2 text-textSecondary">{batch.failed_count}</td>
                    <td className="py-2 text-textSecondary">{batch.manual_review_count}</td>
                    <td className="py-2">
                      <Link href={`/batches/${batch.id}`} className="text-accent hover:underline">
                        Open
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

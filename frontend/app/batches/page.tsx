"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useState } from "react";
import { toast } from "sonner";
import Link from "next/link";
import { Plus, ExternalLink } from "lucide-react";

export default function BatchesPage() {
  const queryClient = useQueryClient();
  const [newBatchName, setNewBatchName] = useState("");

  const { data: batches, isLoading } = useQuery({
    queryKey: ["batches"],
    queryFn: api.listBatches,
  });

  const createBatchMutation = useMutation({
    mutationFn: (label: string) => api.createBatch(label),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["batches"] });
      setNewBatchName("");
      toast.success("Batch created successfully");
    }
  });

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Batches</h2>
          <p className="text-muted-foreground">Manage and run product automation batches.</p>
        </div>
        <div className="flex items-center gap-3">
          <Input 
            placeholder="New Batch Name..." 
            value={newBatchName}
            onChange={(e) => setNewBatchName(e.target.value)}
            className="w-64"
          />
          <Button 
            onClick={() => createBatchMutation.mutate(newBatchName)}
            disabled={!newBatchName || createBatchMutation.isPending}
          >
            <Plus className="w-4 h-4 mr-2" />
            Create Batch
          </Button>
        </div>
      </div>

      <div className="grid gap-6">
        {isLoading ? (
          <p>Loading batches...</p>
        ) : batches?.map((batch) => (
          <Card key={batch.id}>
            <CardHeader className="flex flex-row items-center justify-between py-4">
              <div>
                <CardTitle className="text-lg">{batch.label}</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Created {new Date(batch.created_at).toLocaleDateString()}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                  batch.status === 'completed' ? 'bg-green-100 text-green-700' :
                  batch.status === 'processing' ? 'bg-blue-100 text-blue-700' :
                  'bg-gray-100 text-gray-700'
                }`}>
                  {batch.status.toUpperCase()}
                </span>
                <Link href={`/batches/${batch.id}`}>
                  <Button variant="outline" size="sm">
                    <ExternalLink className="w-4 h-4 mr-2" />
                    Details
                  </Button>
                </Link>
              </div>
            </CardHeader>
          </Card>
        ))}
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type TemplateRecord } from "@/lib/apiClient";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { FileCode, Eye, EyeOff } from "lucide-react";

const TEMPLATE_TYPES = ["short_description", "long_description_a", "long_description_b", "specs_table"] as const;

/**
 * Template Manager (phase1.md §7.5, phase2.md §5.2): edit any template's HTML
 * skeleton without a code change or redeploy. Live preview renders the raw
 * skeleton with its {{PLACEHOLDER}} tokens visible (not filled with fake sample
 * data) so you can see exactly what markup will merge with the AI's content --
 * an honest preview of the code, not a simulation of the output.
 */
export default function TemplatesPage() {
  const queryClient = useQueryClient();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftHtml, setDraftHtml] = useState("");
  const [previewOn, setPreviewOn] = useState<Record<string, boolean>>({});

  const [newTemplate, setNewTemplate] = useState({
    name: "",
    template_type: "long_description_a" as (typeof TEMPLATE_TYPES)[number],
    html_skeleton: "",
  });

  const { data: templates, isLoading } = useQuery({
    queryKey: ["templates"],
    queryFn: api.listTemplates,
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, html_skeleton }: { id: string; html_skeleton: string }) =>
      api.updateTemplate(id, { html_skeleton }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates"] });
      setEditingId(null);
      toast.success("Template saved");
    },
    onError: () => toast.error("Failed to save template"),
  });

  const toggleActiveMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) => api.updateTemplate(id, { is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["templates"] }),
  });

  const createMutation = useMutation({
    mutationFn: () => api.createTemplate(newTemplate),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates"] });
      setNewTemplate({ name: "", template_type: "long_description_a", html_skeleton: "" });
      toast.success("Template created");
    },
    onError: () => toast.error("Failed to create template"),
  });

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Template Manager</h2>
        <p className="text-muted-foreground">
          Edit the HTML skeletons the Writer Agent's content is merged into — no code change needed.
        </p>
      </div>

      <div className="grid gap-6">
        {isLoading && <p className="text-sm text-muted-foreground">Loading templates...</p>}

        {templates?.map((tpl: TemplateRecord) => (
          <Card key={tpl.id}>
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <FileCode className="w-5 h-5 text-primary" />
                  {tpl.name}
                </CardTitle>
                <CardDescription>
                  {tpl.template_type} · v{tpl.version} · {tpl.is_active ? "active" : "inactive"}
                  {tpl.is_default && " · default"}
                </CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPreviewOn({ ...previewOn, [tpl.id]: !previewOn[tpl.id] })}
                >
                  {previewOn[tpl.id] ? <EyeOff className="w-4 h-4 mr-1" /> : <Eye className="w-4 h-4 mr-1" />}
                  Preview
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => toggleActiveMutation.mutate({ id: tpl.id, is_active: !tpl.is_active })}
                >
                  {tpl.is_active ? "Deactivate" : "Activate"}
                </Button>
                {editingId === tpl.id ? (
                  <Button
                    size="sm"
                    onClick={() => updateMutation.mutate({ id: tpl.id, html_skeleton: draftHtml })}
                    disabled={updateMutation.isPending}
                  >
                    Save
                  </Button>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setEditingId(tpl.id);
                      setDraftHtml(tpl.html_skeleton);
                    }}
                  >
                    Edit
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent>
              {editingId === tpl.id ? (
                <textarea
                  className="w-full h-64 p-3 text-xs font-mono border rounded-md"
                  value={draftHtml}
                  onChange={(e) => setDraftHtml(e.target.value)}
                />
              ) : previewOn[tpl.id] ? (
                <div
                  className="p-4 border rounded-md bg-white overflow-x-auto"
                  dangerouslySetInnerHTML={{ __html: tpl.html_skeleton }}
                />
              ) : (
                <pre className="text-xs font-mono bg-muted p-3 rounded-md overflow-x-auto max-h-40">
                  {tpl.html_skeleton}
                </pre>
              )}
            </CardContent>
          </Card>
        ))}

        <Card>
          <CardHeader>
            <CardTitle>New Template</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input
              placeholder="Name"
              value={newTemplate.name}
              onChange={(e) => setNewTemplate({ ...newTemplate, name: e.target.value })}
            />
            <select
              className="w-full h-10 rounded-md border border-input bg-background px-3 text-sm"
              value={newTemplate.template_type}
              onChange={(e) =>
                setNewTemplate({ ...newTemplate, template_type: e.target.value as typeof newTemplate.template_type })
              }
            >
              {TEMPLATE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <textarea
              className="w-full h-32 p-3 text-xs font-mono border rounded-md"
              placeholder="<h2>{{HERO_HEADING}}</h2>..."
              value={newTemplate.html_skeleton}
              onChange={(e) => setNewTemplate({ ...newTemplate, html_skeleton: e.target.value })}
            />
            <Button
              onClick={() => createMutation.mutate()}
              disabled={!newTemplate.name || !newTemplate.html_skeleton || createMutation.isPending}
            >
              Create Template
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

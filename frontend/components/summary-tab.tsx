"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { listTemplates, summarize } from "@/lib/api/orchestration";
import { createTemplate, deleteTemplate, patchTemplate, saveSummary } from "@/lib/api/storage";
import type { Meeting, Segment, Summary, TemplateSpec } from "@/lib/api/types";

interface SummaryTabProps {
  meeting: Meeting;
  segments: Segment[];
  segmentsPending: boolean;
  summary: Summary | null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function TemplateEditDialog({
  template,
  open,
  onOpenChange,
}: {
  template: TemplateSpec | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(template?.name ?? "");
  const [systemPrompt, setSystemPrompt] = useState(template?.system_prompt ?? "");
  const [focusInstructions, setFocusInstructions] = useState(template?.focus_instructions ?? "");

  const save = useMutation({
    mutationFn: () => {
      const data = {
        name: name.trim(),
        system_prompt: systemPrompt.trim(),
        focus_instructions: focusInstructions.trim() || null,
      };
      return template !== null ? patchTemplate(template.id as string, data) : createTemplate(data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates"] });
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{template === null ? "New template" : "Edit template"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <label className="text-muted-foreground text-sm" htmlFor="template-name">
              Name
            </label>
            <Input id="template-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-2">
            <label className="text-muted-foreground text-sm" htmlFor="template-system-prompt">
              System prompt
            </label>
            <Textarea
              id="template-system-prompt"
              rows={5}
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <label className="text-muted-foreground text-sm" htmlFor="template-focus">
              Focus instructions (optional)
            </label>
            <Textarea
              id="template-focus"
              rows={3}
              value={focusInstructions}
              onChange={(e) => setFocusInstructions(e.target.value)}
            />
          </div>
        </div>
        {save.isError && (
          <DialogFooter>
            <p className="text-destructive text-sm">Something went wrong. Try again.</p>
          </DialogFooter>
        )}
        <DialogFooter>
          <Button
            onClick={() => save.mutate()}
            disabled={save.isPending || name.trim() === "" || systemPrompt.trim() === ""}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function SummaryTab({ meeting, segments, segmentsPending, summary }: SummaryTabProps) {
  const queryClient = useQueryClient();
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [provider, setProvider] = useState("ollama");
  const [model, setModel] = useState("llama3");
  const [editDialog, setEditDialog] = useState<{ open: boolean; template: TemplateSpec | null }>({
    open: false,
    template: null,
  });

  const {
    data: templates,
    isPending: templatesPending,
    isError: templatesError,
  } = useQuery({
    queryKey: ["templates"],
    queryFn: listTemplates,
    enabled: summary === null,
  });

  const selectedTemplate = (() => {
    if (templates === undefined) return null;
    if (templateId !== null) {
      const match = templates.find((template) => template.id === templateId);
      if (match !== undefined) return match;
    }
    return templates[0] ?? null;
  })();

  const generate = useMutation({
    mutationFn: async (template: TemplateSpec) => {
      const response = await summarize(segments, template, provider, model);
      await saveSummary(meeting.id, {
        title: response.summary.title,
        overview: response.summary.overview,
        key_points: response.summary.key_points,
        action_items: response.summary.action_items,
        quotes: response.summary.quotes,
        provider: response.provider,
        model: response.model,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["summary", meeting.id] });
    },
  });

  const removeTemplate = useMutation({
    mutationFn: (id: string) => deleteTemplate(id),
    onSuccess: () => {
      setTemplateId(null);
      queryClient.invalidateQueries({ queryKey: ["templates"] });
    },
  });

  if (summary) {
    return (
      <div className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-medium">{summary.title}</h2>
          <p className="text-muted-foreground text-sm">
            {summary.provider} / {summary.model}
          </p>
        </div>
        <p>{summary.overview}</p>
        {summary.key_points.length > 0 && (
          <div className="space-y-2">
            <h3 className="eyebrow text-muted-foreground">Key points</h3>
            <ul className="list-disc space-y-1 pl-5">
              {summary.key_points.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
          </div>
        )}
        {summary.action_items.length > 0 && (
          <div className="space-y-2">
            <h3 className="eyebrow text-muted-foreground">Action items</h3>
            <ul className="list-disc space-y-1 pl-5">
              {summary.action_items.map((item, index) => {
                const description = stringValue(item.description);
                const owner = stringValue(item.owner);
                return (
                  <li key={index}>
                    {description ?? "Untitled action"}
                    {owner !== null && <span className="text-muted-foreground"> ({owner})</span>}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        {summary.quotes.length > 0 && (
          <div className="space-y-2">
            <h3 className="eyebrow text-muted-foreground">Quotes</h3>
            <ul className="space-y-1">
              {summary.quotes.map((quote, index) => {
                const speaker = stringValue(quote.speaker);
                const text = stringValue(quote.text);
                return (
                  <li key={index}>
                    {speaker !== null && <span className="font-medium">{speaker}: </span>}
                    <span className="text-muted-foreground">{text ?? ""}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="max-w-xl space-y-4">
      <h2 className="text-lg font-medium">Generate summary</h2>
      <div className="space-y-2">
        <label className="text-muted-foreground text-sm" htmlFor="template-select">
          Template
        </label>
        {templatesPending ? (
          <Skeleton className="h-9 w-full" />
        ) : templatesError ? (
          <p className="text-destructive text-sm">Failed to load templates</p>
        ) : (
          <div className="flex items-center gap-2">
            <Select value={selectedTemplate?.id ?? ""} onValueChange={setTemplateId}>
              <SelectTrigger id="template-select" className="w-full">
                <SelectValue placeholder="Choose a template" />
              </SelectTrigger>
              <SelectContent>
                {templates?.map((template) => (
                  <SelectItem key={template.id} value={template.id as string}>
                    <span className="flex items-center gap-2">
                      <span>{template.name}</span>
                      <Badge variant="outline" className="text-xs">
                        {template.source === "custom" ? "Custom" : "Built-in"}
                      </Badge>
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setEditDialog({ open: true, template: null })}
            >
              New
            </Button>
            {selectedTemplate?.source === "custom" && (
              <>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setEditDialog({ open: true, template: selectedTemplate })}
                >
                  Edit
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  disabled={removeTemplate.isPending}
                  onClick={() => removeTemplate.mutate(selectedTemplate.id as string)}
                >
                  Delete
                </Button>
              </>
            )}
          </div>
        )}
      </div>
      {editDialog.open && (
        <TemplateEditDialog
          template={editDialog.template}
          open
          onOpenChange={(open) => setEditDialog((previous) => ({ ...previous, open }))}
        />
      )}
      <div className="space-y-2">
        <label className="text-muted-foreground text-sm" htmlFor="provider">
          Provider
        </label>
        <Input
          id="provider"
          value={provider}
          onChange={(event) => setProvider(event.target.value)}
        />
      </div>
      <div className="space-y-2">
        <label className="text-muted-foreground text-sm" htmlFor="model">
          Model
        </label>
        <Input id="model" value={model} onChange={(event) => setModel(event.target.value)} />
      </div>
      {segmentsPending === false && segments.length === 0 && (
        <p className="text-muted-foreground text-sm">No transcript available to summarize yet</p>
      )}
      {generate.isError && <p className="text-destructive text-sm">Failed to generate summary</p>}
      <Button
        onClick={() => {
          if (selectedTemplate !== null && segments.length > 0) {
            generate.mutate(selectedTemplate);
          }
        }}
        disabled={
          generate.isPending ||
          selectedTemplate === null ||
          segmentsPending ||
          segments.length === 0
        }
      >
        {generate.isPending ? "Generating…" : "Generate"}
      </Button>
    </div>
  );
}

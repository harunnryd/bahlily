"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { listTemplates, summarize } from "@/lib/api/orchestration";
import { listSegments, saveSummary } from "@/lib/api/storage";
import type { Meeting, Summary, TemplateSpec } from "@/lib/api/types";

interface SummaryTabProps {
  meeting: Meeting;
  summary: Summary | null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function SummaryTab({ meeting, summary }: SummaryTabProps) {
  const queryClient = useQueryClient();
  const [templateName, setTemplateName] = useState<string | null>(null);
  const [provider, setProvider] = useState("ollama");
  const [model, setModel] = useState("llama3");

  const {
    data: templates,
    isPending: templatesPending,
    isError: templatesError,
  } = useQuery({
    queryKey: ["templates"],
    queryFn: listTemplates,
    enabled: summary === null,
  });

  const selectedTemplate =
    templates?.find((template) => template.name === templateName) ??
    templates?.[0] ??
    null;

  const generate = useMutation({
    mutationFn: async (template: TemplateSpec) => {
      const segments = await listSegments(meeting.id);
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

  if (summary) {
    return (
      <div className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold">{summary.title}</h2>
          <p className="text-muted-foreground text-sm">
            {summary.provider} / {summary.model}
          </p>
        </div>
        <p>{summary.overview}</p>
        {summary.key_points.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-muted-foreground text-sm font-medium">
              Key points
            </h3>
            <ul className="list-disc space-y-1 pl-5">
              {summary.key_points.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
          </div>
        )}
        {summary.action_items.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-muted-foreground text-sm font-medium">
              Action items
            </h3>
            <ul className="list-disc space-y-1 pl-5">
              {summary.action_items.map((item, index) => {
                const description = stringValue(item.description);
                const owner = stringValue(item.owner);
                return (
                  <li key={index}>
                    {description ?? "Untitled action"}
                    {owner !== null && (
                      <span className="text-muted-foreground"> ({owner})</span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        {summary.quotes.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-muted-foreground text-sm font-medium">
              Quotes
            </h3>
            <ul className="space-y-1">
              {summary.quotes.map((quote, index) => {
                const speaker = stringValue(quote.speaker);
                const text = stringValue(quote.text);
                return (
                  <li key={index}>
                    {speaker !== null && (
                      <span className="font-medium">{speaker}: </span>
                    )}
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
      <h2 className="text-lg font-semibold">Generate summary</h2>
      <div className="space-y-2">
        <label
          className="text-muted-foreground text-sm"
          htmlFor="template-select"
        >
          Template
        </label>
        {templatesPending ? (
          <Skeleton className="h-9 w-full" />
        ) : templatesError ? (
          <p className="text-sm text-red-300">Failed to load templates</p>
        ) : (
          <Select
            value={selectedTemplate?.name ?? ""}
            onValueChange={setTemplateName}
          >
            <SelectTrigger id="template-select" className="w-full">
              <SelectValue placeholder="Choose a template" />
            </SelectTrigger>
            <SelectContent>
              {templates?.map((template) => (
                <SelectItem key={template.name} value={template.name}>
                  {template.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>
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
        <Input
          id="model"
          value={model}
          onChange={(event) => setModel(event.target.value)}
        />
      </div>
      {generate.isError && (
        <p className="text-sm text-red-300">Failed to generate summary</p>
      )}
      <Button
        onClick={() => {
          if (selectedTemplate !== null) {
            generate.mutate(selectedTemplate);
          }
        }}
        disabled={generate.isPending || selectedTemplate === null}
      >
        {generate.isPending ? "Generating…" : "Generate"}
      </Button>
    </div>
  );
}

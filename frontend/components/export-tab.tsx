"use client";

import { useState } from "react";

import { exportSummary } from "@/lib/api/export";
import type { Summary } from "@/lib/api/types";
import { Button } from "@/components/ui/button";

type ExportFormat = "markdown" | "docx" | "pdf";

const EXTENSIONS: Record<ExportFormat, string> = {
  markdown: "md",
  docx: "docx",
  pdf: "pdf",
};

function sanitizeFilename(title: string): string {
  const slug = title.replace(/[^a-z0-9-_]+/gi, "_").toLowerCase();
  return slug === "" ? "summary" : slug;
}

export function ExportTab({ disabled, summary }: { disabled: boolean; summary: Summary | null }) {
  const [pendingFormat, setPendingFormat] = useState<ExportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleExport = async (format: ExportFormat) => {
    if (summary === null) return;
    setPendingFormat(format);
    setError(null);
    try {
      const blob = await exportSummary(format, summary);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${sanitizeFilename(summary.title)}-${format}.${EXTENSIONS[format]}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setPendingFormat(null);
    }
  };

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-medium">Export summary</h2>
      {disabled && <p className="text-muted-foreground text-sm">Generate a summary first</p>}
      <div className="flex flex-wrap gap-2">
        {(["markdown", "docx", "pdf"] as const).map((format) => (
          <Button
            key={format}
            variant="outline"
            disabled={disabled || pendingFormat !== null}
            onClick={() => handleExport(format)}
          >
            {pendingFormat === format ? "Exporting\u2026" : format.toUpperCase()}
          </Button>
        ))}
      </div>
      {error !== null && <p className="text-destructive text-sm">{error}</p>}
    </div>
  );
}

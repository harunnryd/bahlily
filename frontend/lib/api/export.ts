import { ApiError } from "./client";
import { SERVICES } from "./config";
import type { Summary } from "./types";

const base = SERVICES.export;

export async function exportSummary(
  format: "markdown" | "docx" | "pdf",
  summary: Summary,
): Promise<Blob> {
  const resp = await fetch(`${base}/export?format=${format}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      title: summary.title,
      overview: summary.overview,
      key_points: summary.key_points,
      action_items: summary.action_items,
      quotes: summary.quotes,
      created_at: summary.created_at,
    }),
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, null, resp.statusText);
  }
  return resp.blob();
}

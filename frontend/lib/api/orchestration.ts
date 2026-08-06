import { request } from "./client";
import { SERVICES } from "./config";
import { parseSummarizeResponse, parseTemplates } from "./guards";
import type { Segment, SummarizeResponse, TemplateSpec } from "./types";

const base = SERVICES.orchestration;

export function listTemplates(): Promise<TemplateSpec[]> {
  return request<TemplateSpec[]>(`${base}/templates`, undefined, parseTemplates);
}

export function summarize(
  segments: Segment[],
  template: TemplateSpec,
  provider: string,
  model: string,
): Promise<SummarizeResponse> {
  const payload = {
    segments: segments.map((s) => ({
      text: s.text,
      segment_id: s.segment_id,
      speaker: s.speaker_cluster_label,
      start_time: s.audio_start_time,
      end_time: s.audio_end_time,
      language: s.language,
    })),
    template,
    provider,
    model,
  };
  return request<SummarizeResponse>(
    `${base}/summarize`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    parseSummarizeResponse,
  );
}

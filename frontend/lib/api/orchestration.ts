import { request } from "./client";
import { SERVICES } from "./config";
import type {
  Segment,
  SummarizeResponse,
  Template,
  TemplateSpec,
} from "./types";

const base = SERVICES.orchestration;

export function listTemplates(): Promise<TemplateSpec[]> {
  return request<TemplateSpec[]>(`${base}/templates`);
}

export function summarize(
  segments: Segment[],
  template: Template,
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
    template: {
      name: template.name,
      version: template.version,
      system_prompt: template.system_prompt,
      focus_instructions: template.focus_instructions,
      few_shot_examples: template.few_shot_examples,
    },
    provider,
    model,
  };
  return request<SummarizeResponse>(`${base}/summarize`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

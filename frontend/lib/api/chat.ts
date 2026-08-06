import { request } from "./client";
import { SERVICES } from "./config";
import type { ChatAnswer, Segment } from "./types";

const base = SERVICES.chat;

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export function ingestMeeting(
  meetingId: string,
  segments: Segment[],
): Promise<{ meeting_id: string; segments_indexed: number }> {
  const payload = {
    segments: segments.map((s) => ({
      text: s.text,
      segment_id: s.segment_id,
      speaker: s.speaker_cluster_label,
      start_time: s.audio_start_time,
      end_time: s.audio_end_time,
    })),
  };
  return request<{ meeting_id: string; segments_indexed: number }>(
    `${base}/meetings/${meetingId}/ingest`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function askChat(
  question: string,
  meetingId: string,
  history: ChatTurn[],
  provider: string,
  model: string,
): Promise<ChatAnswer> {
  return request<ChatAnswer>(`${base}/chat`, {
    method: "POST",
    body: JSON.stringify({
      question,
      meeting_id: meetingId,
      history,
      provider,
      model,
    }),
  });
}

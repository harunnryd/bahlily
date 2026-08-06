export interface Meeting {
  id: string;
  title: string | null;
  status: string;
  language: string | null;
  engine: string | null;
  model_name: string | null;
  started_at: string;
  ended_at: string | null;
  segments_count: number;
  recording_path: string | null;
  diarization_status: string;
  has_summary: boolean;
}

export interface Segment {
  segment_id: number;
  text: string;
  confidence: number | null;
  engine: string;
  model_name: string;
  audio_start_time: number;
  audio_end_time: number;
  language: string | null;
  is_partial: boolean;
  trace_id: string;
  speaker_cluster_label: string | null;
  speaker_profile_id: string | null;
}

export interface SpeakerProfile {
  id: string;
  name: string;
  voice_embedding: number[];
  created_at: string;
  updated_at: string;
}

export interface Summary {
  id: string;
  meeting_id: string;
  title: string;
  overview: string;
  key_points: string[];
  action_items: Array<Record<string, unknown>>;
  quotes: Array<Record<string, unknown>>;
  provider: string;
  model: string;
  created_at: string;
}

export interface Template {
  id: string;
  name: string;
  version: string;
  system_prompt: string;
  focus_instructions: string | null;
  few_shot_examples: Array<{ input: string; output: string }>;
  created_at: string;
  updated_at: string;
}

export interface SummarizeResponse {
  summary: {
    title: string;
    overview: string;
    key_points: string[];
    action_items: Array<Record<string, unknown>>;
    quotes: Array<Record<string, unknown>>;
  };
  attempts: number;
  provider: string;
  model: string;
}

export interface ChatAnswer {
  answer: string;
  citations: Array<{
    meeting_id: string;
    segment_id: number;
    text: string;
    start_time: number | null;
    end_time: number | null;
  }>;
}

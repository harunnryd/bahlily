import type {
  ChatAnswer,
  Meeting,
  Segment,
  SpeakerProfile,
  SummarizeResponse,
  Summary,
  Template,
  TemplateSpec,
} from "./types";
import { ApiError } from "./client";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean";
}

function isStringOrNull(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

function isNumberOrNull(value: unknown): value is number | null {
  return (typeof value === "number" && Number.isFinite(value)) || value === null;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString);
}

function isFewShotArray(value: unknown): value is Array<{ input: string; output: string }> {
  return (
    Array.isArray(value) &&
    value.every((item) => isObject(item) && isString(item.input) && isString(item.output))
  );
}

function fail(message: string): never {
  throw new ApiError(0, "INVALID_PAYLOAD", message);
}

function requireField<T>(
  record: Record<string, unknown>,
  key: string,
  check: (value: unknown) => value is T,
  context: string,
): T {
  if (!(key in record)) fail(`${context}: missing field "${key}"`);
  const value = record[key];
  if (!check(value)) fail(`${context}: field "${key}" has wrong type`);
  return value;
}

function parseMeeting(value: unknown, context = "meeting"): Meeting {
  if (!isObject(value)) fail(`${context}: expected object`);
  return {
    id: requireField(value, "id", isString, context),
    title: requireField(value, "title", isStringOrNull, context),
    status: requireField(value, "status", isString, context),
    language: requireField(value, "language", isStringOrNull, context),
    engine: requireField(value, "engine", isStringOrNull, context),
    model_name: requireField(value, "model_name", isStringOrNull, context),
    started_at: requireField(value, "started_at", isString, context),
    ended_at: requireField(value, "ended_at", isStringOrNull, context),
    segments_count: requireField(value, "segments_count", isNumber, context),
    recording_path: requireField(value, "recording_path", isStringOrNull, context),
    diarization_status: requireField(value, "diarization_status", isString, context),
    has_summary: requireField(value, "has_summary", isBoolean, context),
  };
}

function parseMeetings(value: unknown): Meeting[] {
  if (!Array.isArray(value)) fail("meetings: expected array");
  return value.map((item, index) => parseMeeting(item, `meetings[${index}]`));
}

function parseSegment(value: unknown, context: string): Segment {
  if (!isObject(value)) fail(`${context}: expected object`);
  return {
    segment_id: requireField(value, "segment_id", isNumber, context),
    text: requireField(value, "text", isString, context),
    confidence: requireField(value, "confidence", isNumberOrNull, context),
    engine: requireField(value, "engine", isString, context),
    model_name: requireField(value, "model_name", isString, context),
    audio_start_time: requireField(value, "audio_start_time", isNumber, context),
    audio_end_time: requireField(value, "audio_end_time", isNumber, context),
    language: requireField(value, "language", isStringOrNull, context),
    is_partial: requireField(value, "is_partial", isBoolean, context),
    trace_id: requireField(value, "trace_id", isString, context),
    speaker_cluster_label: requireField(value, "speaker_cluster_label", isStringOrNull, context),
    speaker_profile_id: requireField(value, "speaker_profile_id", isStringOrNull, context),
  };
}

function parseSegments(value: unknown): Segment[] {
  if (!Array.isArray(value)) fail("segments: expected array");
  return value.map((item, index) => parseSegment(item, `segments[${index}]`));
}

function parseSummary(value: unknown, context = "summary"): Summary {
  if (!isObject(value)) fail(`${context}: expected object`);
  return {
    id: requireField(value, "id", isString, context),
    meeting_id: requireField(value, "meeting_id", isString, context),
    title: requireField(value, "title", isString, context),
    overview: requireField(value, "overview", isString, context),
    key_points: requireField(value, "key_points", isStringArray, context),
    action_items: requireField(
      value,
      "action_items",
      (v): v is Array<Record<string, unknown>> => Array.isArray(v) && v.every(isObject),
      context,
    ),
    quotes: requireField(
      value,
      "quotes",
      (v): v is Array<Record<string, unknown>> => Array.isArray(v) && v.every(isObject),
      context,
    ),
    provider: requireField(value, "provider", isString, context),
    model: requireField(value, "model", isString, context),
    created_at: requireField(value, "created_at", isString, context),
  };
}

function parseSpeakerProfile(value: unknown, context: string): SpeakerProfile {
  if (!isObject(value)) fail(`${context}: expected object`);
  return {
    id: requireField(value, "id", isString, context),
    name: requireField(value, "name", isString, context),
    voice_embedding: requireField(
      value,
      "voice_embedding",
      (v): v is number[] => Array.isArray(v) && v.every(isNumber),
      context,
    ),
    created_at: requireField(value, "created_at", isString, context),
    updated_at: requireField(value, "updated_at", isString, context),
  };
}

function parseSpeakerProfiles(value: unknown): SpeakerProfile[] {
  if (!Array.isArray(value)) fail("speakerProfiles: expected array");
  return value.map((item, index) => parseSpeakerProfile(item, `speakerProfiles[${index}]`));
}

function isTemplateSource(value: unknown): value is "bundled" | "custom" | null {
  return value === "bundled" || value === "custom" || value === null;
}

function parseTemplateSpec(value: unknown, context: string): TemplateSpec {
  if (!isObject(value)) fail(`${context}: expected object`);
  return {
    name: requireField(value, "name", isString, context),
    version: requireField(value, "version", isString, context),
    system_prompt: requireField(value, "system_prompt", isString, context),
    focus_instructions: requireField(value, "focus_instructions", isStringOrNull, context),
    few_shot_examples: requireField(value, "few_shot_examples", isFewShotArray, context),
    id: requireField(value, "id", isStringOrNull, context),
    source: requireField(value, "source", isTemplateSource, context),
  };
}

function parseTemplates(value: unknown): TemplateSpec[] {
  if (!Array.isArray(value)) fail("templates: expected array");
  return value.map((item, index) => parseTemplateSpec(item, `templates[${index}]`));
}

function parseTemplate(value: unknown, context: string): Template {
  if (!isObject(value)) fail(`${context}: expected object`);
  return {
    id: requireField(value, "id", isString, context),
    name: requireField(value, "name", isString, context),
    version: requireField(value, "version", isString, context),
    system_prompt: requireField(value, "system_prompt", isString, context),
    focus_instructions: requireField(value, "focus_instructions", isStringOrNull, context),
    few_shot_examples: requireField(value, "few_shot_examples", isFewShotArray, context),
    created_at: requireField(value, "created_at", isString, context),
    updated_at: requireField(value, "updated_at", isString, context),
  };
}

function parseSummarizeResponse(value: unknown, context = "summarizeResponse"): SummarizeResponse {
  if (!isObject(value)) fail(`${context}: expected object`);
  const summary = requireField(value, "summary", isObject, context);
  if (!isObject(summary)) fail(`${context}.summary: expected object`);
  return {
    summary: {
      title: requireField(summary, "title", isString, `${context}.summary`),
      overview: requireField(summary, "overview", isString, `${context}.summary`),
      key_points: requireField(summary, "key_points", isStringArray, `${context}.summary`),
      action_items: requireField(
        summary,
        "action_items",
        (v): v is Array<Record<string, unknown>> => Array.isArray(v) && v.every(isObject),
        `${context}.summary`,
      ),
      quotes: requireField(
        summary,
        "quotes",
        (v): v is Array<Record<string, unknown>> => Array.isArray(v) && v.every(isObject),
        `${context}.summary`,
      ),
    },
    attempts: requireField(value, "attempts", isNumber, context),
    provider: requireField(value, "provider", isString, context),
    model: requireField(value, "model", isString, context),
  };
}

function parseChatAnswer(value: unknown, context = "chatAnswer"): ChatAnswer {
  if (!isObject(value)) fail(`${context}: expected object`);
  return {
    answer: requireField(value, "answer", isString, context),
    citations: requireField(
      value,
      "citations",
      (v): v is ChatAnswer["citations"] => {
        if (!Array.isArray(v)) return false;
        return v.every(
          (item) =>
            isObject(item) &&
            isString(item.meeting_id) &&
            isNumber(item.segment_id) &&
            isString(item.text) &&
            isNumberOrNull(item.start_time) &&
            isNumberOrNull(item.end_time),
        );
      },
      context,
    ),
  };
}

function parseIngestResponse(
  value: unknown,
  context = "ingestResponse",
): { meeting_id: string; segments_indexed: number } {
  if (!isObject(value)) fail(`${context}: expected object`);
  return {
    meeting_id: requireField(value, "meeting_id", isString, context),
    segments_indexed: requireField(value, "segments_indexed", isNumber, context),
  };
}

export {
  parseChatAnswer,
  parseIngestResponse,
  parseMeeting,
  parseMeetings,
  parseSegment,
  parseSegments,
  parseSpeakerProfile,
  parseSpeakerProfiles,
  parseSummarizeResponse,
  parseSummary,
  parseTemplate,
  parseTemplateSpec,
  parseTemplates,
};

import { request } from "./client";
import { SERVICES } from "./config";
import {
  parseMeeting,
  parseMeetings,
  parseSegments,
  parseSpeakerProfile,
  parseSpeakerProfiles,
  parseSummary,
} from "./guards";
import type { Meeting, Segment, SpeakerProfile, Summary } from "./types";

const base = SERVICES.storage;

export function listMeetings(limit = 20, offset = 0): Promise<Meeting[]> {
  return request<unknown>(`${base}/meetings?limit=${limit}&offset=${offset}`).then(parseMeetings);
}

export function getMeeting(meetingId: string): Promise<Meeting> {
  return request<unknown>(`${base}/meetings/${meetingId}`).then(parseMeeting);
}

export function deleteMeeting(meetingId: string): Promise<void> {
  return request<void>(`${base}/meetings/${meetingId}`, { method: "DELETE" });
}

export function listSegments(meetingId: string): Promise<Segment[]> {
  return request<unknown>(`${base}/meetings/${meetingId}/segments`).then(parseSegments);
}

export function getSummary(meetingId: string): Promise<Summary> {
  return request<unknown>(`${base}/meetings/${meetingId}/summary`).then(parseSummary);
}

export function listSpeakerProfiles(): Promise<SpeakerProfile[]> {
  return request<unknown>(`${base}/speaker-profiles`).then(parseSpeakerProfiles);
}

export function labelSpeaker(
  meetingId: string,
  clusterLabel: string,
  name: string,
): Promise<SpeakerProfile> {
  return request<unknown>(`${base}/meetings/${meetingId}/speakers/${clusterLabel}/label`, {
    method: "POST",
    body: JSON.stringify({ name }),
  }).then((value) => parseSpeakerProfile(value, "labelSpeaker"));
}

export function saveSummary(
  meetingId: string,
  data: {
    title: string;
    overview: string;
    key_points: string[];
    action_items: Array<Record<string, unknown>>;
    quotes: Array<Record<string, unknown>>;
    provider: string;
    model: string;
  },
): Promise<Summary> {
  return request<unknown>(`${base}/meetings/${meetingId}/summary`, {
    method: "POST",
    body: JSON.stringify(data),
  }).then(parseSummary);
}

import { request } from "./client";
import { SERVICES } from "./config";
import type { Meeting, Segment, SpeakerProfile, Summary } from "./types";

const base = SERVICES.storage;

export function listMeetings(limit = 20, offset = 0): Promise<Meeting[]> {
  return request<Meeting[]>(`${base}/meetings?limit=${limit}&offset=${offset}`);
}

export function getMeeting(meetingId: string): Promise<Meeting> {
  return request<Meeting>(`${base}/meetings/${meetingId}`);
}

export function deleteMeeting(meetingId: string): Promise<void> {
  return request<void>(`${base}/meetings/${meetingId}`, { method: "DELETE" });
}

export function listSegments(meetingId: string): Promise<Segment[]> {
  return request<Segment[]>(`${base}/meetings/${meetingId}/segments`);
}

export function getSummary(meetingId: string): Promise<Summary> {
  return request<Summary>(`${base}/meetings/${meetingId}/summary`);
}

export function listSpeakerProfiles(): Promise<SpeakerProfile[]> {
  return request<SpeakerProfile[]>(`${base}/speaker-profiles`);
}

export function labelSpeaker(
  meetingId: string,
  clusterLabel: string,
  name: string,
): Promise<SpeakerProfile> {
  return request<SpeakerProfile>(
    `${base}/meetings/${meetingId}/speakers/${clusterLabel}/label`,
    { method: "POST", body: JSON.stringify({ name }) },
  );
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
  return request<Summary>(`${base}/meetings/${meetingId}/summary`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

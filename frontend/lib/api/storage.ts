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
  return request<Meeting[]>(
    `${base}/meetings?limit=${limit}&offset=${offset}`,
    undefined,
    parseMeetings,
  );
}

export function getMeeting(meetingId: string): Promise<Meeting> {
  return request<Meeting>(`${base}/meetings/${meetingId}`, undefined, parseMeeting);
}

export function deleteMeeting(meetingId: string): Promise<void> {
  return request<void>(`${base}/meetings/${meetingId}`, { method: "DELETE" });
}

export function listSegments(meetingId: string): Promise<Segment[]> {
  return request<Segment[]>(`${base}/meetings/${meetingId}/segments`, undefined, parseSegments);
}

export function getSummary(meetingId: string): Promise<Summary> {
  return request<Summary>(`${base}/meetings/${meetingId}/summary`, undefined, parseSummary);
}

export function listSpeakerProfiles(): Promise<SpeakerProfile[]> {
  return request<SpeakerProfile[]>(`${base}/speaker-profiles`, undefined, parseSpeakerProfiles);
}

export function labelSpeaker(
  meetingId: string,
  clusterLabel: string,
  name: string,
): Promise<SpeakerProfile> {
  return request<SpeakerProfile>(
    `${base}/meetings/${meetingId}/speakers/${clusterLabel}/label`,
    {
      method: "POST",
      body: JSON.stringify({ name }),
    },
    (value) => parseSpeakerProfile(value, "labelSpeaker"),
  );
}

export function patchSpeakerProfile(profileId: string, name: string): Promise<SpeakerProfile> {
  return request<SpeakerProfile>(
    `${base}/speaker-profiles/${profileId}`,
    {
      method: "PATCH",
      body: JSON.stringify({ name }),
    },
    (value) => parseSpeakerProfile(value, "patchSpeakerProfile"),
  );
}

export function mergeSpeakerProfiles(
  profileId: string,
  otherProfileId: string,
): Promise<SpeakerProfile> {
  return request<SpeakerProfile>(
    `${base}/speaker-profiles/${profileId}/merge`,
    {
      method: "POST",
      body: JSON.stringify({ other_profile_id: otherProfileId }),
    },
    (value) => parseSpeakerProfile(value, "mergeSpeakerProfiles"),
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
  return request<Summary>(
    `${base}/meetings/${meetingId}/summary`,
    {
      method: "POST",
      body: JSON.stringify(data),
    },
    parseSummary,
  );
}

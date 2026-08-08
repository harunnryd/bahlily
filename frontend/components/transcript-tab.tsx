"use client";

import { useQuery } from "@tanstack/react-query";

import { SpeakerLegend, type SpeakerLegendCluster } from "@/components/speaker-legend";
import { listSpeakerProfiles } from "@/lib/api/storage";
import type { Meeting, Segment } from "@/lib/api/types";

interface TranscriptTabProps {
  meeting: Meeting;
  segments: Segment[];
}

function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  return `[${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}]`;
}

export function TranscriptTab({ meeting, segments }: TranscriptTabProps) {
  const { data: profiles } = useQuery({
    queryKey: ["speakerProfiles"],
    queryFn: listSpeakerProfiles,
  });

  const groups: Array<{ label: string; segments: Segment[] }> = [];
  const groupIndex = new Map<string, number>();
  for (const segment of segments) {
    const label = segment.speaker_cluster_label ?? "Unknown";
    const index = groupIndex.get(label);
    if (index === undefined) {
      groupIndex.set(label, groups.length);
      groups.push({ label, segments: [segment] });
    } else {
      groups[index].segments.push(segment);
    }
  }

  const clusters: SpeakerLegendCluster[] = groups.map((group) => {
    const speakerProfileId = group.segments[0]?.speaker_profile_id ?? null;
    const profile =
      speakerProfileId === null
        ? undefined
        : profiles?.find((item) => item.id === speakerProfileId);
    return {
      label: group.label,
      name: profile?.name ?? null,
      profileId: speakerProfileId,
    };
  });

  if (segments.length === 0) {
    return <p className="text-muted-foreground py-8 text-center">No transcripts yet</p>;
  }

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <h2 className="eyebrow text-muted-foreground">Speakers</h2>
        <SpeakerLegend meetingId={meeting.id} clusters={clusters} />
      </div>
      <div className="space-y-3">
        <h2 className="eyebrow text-muted-foreground">Transcript</h2>
        <div className="bg-graphite text-graphite-foreground divide-graphite-foreground/10 max-h-[32rem] divide-y overflow-y-auto rounded-xl p-4">
          {groups.map((group) =>
            group.segments.map((segment) => (
              <p key={segment.segment_id} className="flex gap-3 py-1.5 first:pt-0 last:pb-0">
                <span className="text-primary-on-graphite shrink-0 font-mono text-sm">
                  {formatTimestamp(segment.audio_start_time)}
                </span>
                <span>{segment.text}</span>
              </p>
            )),
          )}
        </div>
      </div>
    </div>
  );
}

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  SpeakerLegend,
  type SpeakerLegendCluster,
} from "@/components/speaker-legend";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { labelSpeaker, listSpeakerProfiles } from "@/lib/api/storage";
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

function RelabelForm({
  initialName,
  pending,
  onSave,
}: {
  initialName: string;
  pending: boolean;
  onSave: (name: string) => void;
}) {
  const [name, setName] = useState(initialName);

  return (
    <form
      className="flex gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        const trimmed = name.trim();
        if (trimmed) {
          onSave(trimmed);
        }
      }}
    >
      <Input
        value={name}
        onChange={(event) => setName(event.target.value)}
        placeholder="Speaker name"
        aria-label="Speaker name"
        className="h-8 w-48"
      />
      <Button type="submit" size="sm" disabled={pending}>
        Save
      </Button>
    </form>
  );
}

export function TranscriptTab({ meeting, segments }: TranscriptTabProps) {
  const queryClient = useQueryClient();
  const [names, setNames] = useState<Record<string, string>>({});

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
      name: profile?.name ?? names[group.label] ?? null,
    };
  });

  const relabel = useMutation({
    mutationFn: ({ label, name }: { label: string; name: string }) =>
      labelSpeaker(meeting.id, label, name),
    onSuccess: (_profile, { label, name }) => {
      setNames((previous) => ({ ...previous, [label]: name }));
      queryClient.invalidateQueries({ queryKey: ["segments", meeting.id] });
      queryClient.invalidateQueries({ queryKey: ["speakerProfiles"] });
    },
  });

  if (segments.length === 0) {
    return (
      <p className="text-muted-foreground py-8 text-center">
        No transcripts yet
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <h2 className="text-muted-foreground text-sm font-medium">Speakers</h2>
        <div className="space-y-2">
          {clusters.map((cluster) => (
            <div
              key={cluster.label}
              className="flex flex-wrap items-center gap-2"
            >
              <SpeakerLegend clusters={[cluster]} />
              <RelabelForm
                initialName={cluster.name ?? ""}
                pending={relabel.isPending}
                onSave={(name) =>
                  relabel.mutate({ label: cluster.label, name })
                }
              />
            </div>
          ))}
        </div>
      </div>
      <div className="space-y-3">
        <h2 className="text-muted-foreground text-sm font-medium">
          Transcript
        </h2>
        <div className="space-y-1">
          {groups.map((group) =>
            group.segments.map((segment) => (
              <p key={segment.segment_id} className="flex gap-2">
                <span className="text-muted-foreground shrink-0 font-mono text-sm">
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

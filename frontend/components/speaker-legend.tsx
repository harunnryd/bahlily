"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  labelSpeaker,
  listSpeakerProfiles,
  mergeSpeakerProfiles,
  patchSpeakerProfile,
} from "@/lib/api/storage";
import type { SpeakerProfile } from "@/lib/api/types";

export interface SpeakerLegendCluster {
  label: string;
  name: string | null;
  profileId: string | null;
}

function SpeakerEditDialog({
  meetingId,
  cluster,
  displayName,
  otherProfiles,
  open,
  onOpenChange,
  onResolved,
}: {
  meetingId: string;
  cluster: SpeakerLegendCluster;
  displayName: string | null;
  otherProfiles: SpeakerProfile[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onResolved: (name: string) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(displayName ?? "");
  const [reassignTarget, setReassignTarget] = useState("");
  const [mergeTarget, setMergeTarget] = useState("");

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["segments", meetingId] });
    queryClient.invalidateQueries({ queryKey: ["speakerProfiles"] });
  };

  const rename = useMutation({
    mutationFn: (newName: string) =>
      cluster.profileId
        ? patchSpeakerProfile(cluster.profileId, newName)
        : labelSpeaker(meetingId, cluster.label, newName),
    onSuccess: (profile) => {
      onResolved(profile.name);
      invalidate();
      onOpenChange(false);
    },
  });

  const reassign = useMutation({
    mutationFn: (targetName: string) => labelSpeaker(meetingId, cluster.label, targetName),
    onSuccess: (profile) => {
      onResolved(profile.name);
      invalidate();
      onOpenChange(false);
    },
  });

  const merge = useMutation({
    mutationFn: (otherProfileId: string) =>
      // The URL's profile_id survives and other_profile_id is absorbed into
      // it, so the target the user picked ("merge into") must be the survivor.
      mergeSpeakerProfiles(otherProfileId, cluster.profileId as string),
    onSuccess: (profile) => {
      onResolved(profile.name);
      invalidate();
      onOpenChange(false);
    },
  });

  const isMutating = rename.isPending || reassign.isPending || merge.isPending;
  const failed = rename.isError || reassign.isError || merge.isError;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{displayName ?? cluster.label}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              const trimmed = name.trim();
              if (!isMutating && trimmed) rename.mutate(trimmed);
            }}
          >
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Speaker name"
              aria-label="Speaker name"
            />
            <Button type="submit" size="sm" disabled={isMutating}>
              Rename
            </Button>
          </form>

          {otherProfiles.length > 0 && (
            <div className="flex gap-2">
              <Select value={reassignTarget} onValueChange={setReassignTarget}>
                <SelectTrigger className="w-full" aria-label="Reassign to existing speaker">
                  <SelectValue placeholder="Reassign to existing speaker" />
                </SelectTrigger>
                <SelectContent>
                  {otherProfiles.map((profile) => (
                    <SelectItem key={profile.id} value={profile.name}>
                      {profile.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                size="sm"
                variant="outline"
                disabled={!reassignTarget || isMutating}
                onClick={() => reassign.mutate(reassignTarget)}
              >
                Reassign
              </Button>
            </div>
          )}

          {cluster.profileId && otherProfiles.length > 0 && (
            <div className="flex gap-2">
              <Select value={mergeTarget} onValueChange={setMergeTarget}>
                <SelectTrigger className="w-full" aria-label="Merge into another speaker">
                  <SelectValue placeholder="Merge into another speaker" />
                </SelectTrigger>
                <SelectContent>
                  {otherProfiles.map((profile) => (
                    <SelectItem key={profile.id} value={profile.id}>
                      {profile.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                size="sm"
                variant="destructive"
                disabled={!mergeTarget || isMutating}
                onClick={() => merge.mutate(mergeTarget)}
              >
                Merge
              </Button>
            </div>
          )}
        </div>

        {failed && (
          <DialogFooter>
            <p className="text-destructive text-sm">Something went wrong. Try again.</p>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function SpeakerLegend({
  meetingId,
  clusters,
}: {
  meetingId: string;
  clusters: SpeakerLegendCluster[];
}) {
  const [openLabel, setOpenLabel] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const { data: profiles } = useQuery({
    queryKey: ["speakerProfiles"],
    queryFn: listSpeakerProfiles,
  });

  return (
    <div className="flex flex-wrap items-center gap-2">
      {clusters.map((cluster) => {
        const otherProfiles = (profiles ?? []).filter(
          (profile) => profile.id !== cluster.profileId,
        );
        const displayName = overrides[cluster.label] ?? cluster.name;
        return (
          <div key={cluster.label}>
            <Badge asChild variant="outline">
              <button
                type="button"
                className="cursor-pointer"
                aria-haspopup="dialog"
                onClick={() => setOpenLabel(cluster.label)}
              >
                {displayName ?? cluster.label}
              </button>
            </Badge>
            {openLabel === cluster.label && (
              <SpeakerEditDialog
                meetingId={meetingId}
                cluster={cluster}
                displayName={displayName}
                otherProfiles={otherProfiles}
                onResolved={(name) =>
                  setOverrides((previous) => ({ ...previous, [cluster.label]: name }))
                }
                open
                onOpenChange={(open) => setOpenLabel(open ? cluster.label : null)}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

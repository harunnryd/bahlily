"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { MeetingsTable } from "@/components/meetings-table";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import { deleteMeeting, listMeetings } from "@/lib/api/storage";

const PAGE_SIZE = 20;

export default function HomePage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const { data, isPending, isError, error, refetch, isPlaceholderData } = useQuery({
    queryKey: ["meetings", offset],
    queryFn: () => listMeetings(PAGE_SIZE, offset),
    placeholderData: keepPreviousData,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteMeeting,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["meetings"] });
      setPendingDelete(null);
    },
  });

  const filteredMeetings = (data ?? []).filter((meeting) =>
    (meeting.title ?? "").toLowerCase().includes(search.toLowerCase()),
  );

  const hasNextPage = (data?.length ?? 0) === PAGE_SIZE;

  return (
    <main className="p-8">
      <div className="mx-auto max-w-5xl space-y-6">
        <h1 className="text-2xl font-semibold">Meetings</h1>

        <div className="relative">
          <Search className="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-zinc-500" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search meetings"
            className="pl-9"
          />
        </div>

        {isError && (
          <div className="flex items-center justify-between rounded-md border border-red-500/30 bg-red-500/10 p-4">
            <div className="text-sm text-red-300">
              <p className="font-medium">Failed to load meetings</p>
              <p>
                {error instanceof ApiError && error.offline
                  ? "Storage service unreachable"
                  : error.message}
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              Retry
            </Button>
          </div>
        )}

        {isPending ? (
          <div className="space-y-2">
            {Array.from({ length: 6 }, (_, index) => (
              <Skeleton key={index} className="h-10 w-full" />
            ))}
          </div>
        ) : (
          <MeetingsTable
            meetings={filteredMeetings}
            onOpen={(id) => router.push(`/meetings?id=${id}`)}
            onDelete={(id) => setPendingDelete(id)}
          />
        )}

        <div className="flex items-center justify-between">
          <p className="text-sm text-zinc-500">{data?.length ?? 0} meetings on this page</p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
              disabled={offset === 0}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setOffset((current) => current + PAGE_SIZE)}
              disabled={!hasNextPage || isPlaceholderData}
            >
              Next
            </Button>
          </div>
        </div>

        <Dialog
          open={pendingDelete !== null}
          onOpenChange={(open) => {
            if (!open) setPendingDelete(null);
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete meeting?</DialogTitle>
              <DialogDescription>
                This permanently removes the meeting, its segments, and its summary.
              </DialogDescription>
            </DialogHeader>
            {deleteMutation.isError && (
              <p className="text-sm text-red-400">
                Failed to delete the meeting. Please try again.
              </p>
            )}
            <DialogFooter>
              <Button variant="ghost" onClick={() => setPendingDelete(null)}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                disabled={deleteMutation.isPending}
                onClick={() => {
                  if (pendingDelete) deleteMutation.mutate(pendingDelete);
                }}
              >
                {deleteMutation.isPending ? "Deleting..." : "Delete"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </main>
  );
}

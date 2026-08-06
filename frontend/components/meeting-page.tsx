"use client";

import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";

import { MeetingDetail } from "@/components/meeting-detail";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import { getMeeting, getSummary, listSegments } from "@/lib/api/storage";

export function MeetingDetailSkeleton() {
  return (
    <main className="p-8">
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="space-y-2">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-4 w-40" />
        </div>
        <Skeleton className="h-10 w-96" />
      </div>
    </main>
  );
}

function QueryErrorBanner({
  title,
  error,
  onRetry,
}: {
  title: string;
  error: unknown;
  onRetry: () => void;
}) {
  const message =
    error instanceof ApiError && error.offline
      ? "Storage service unreachable"
      : String(error instanceof Error ? error.message : error);
  return (
    <div className="flex items-center justify-between rounded-md border border-red-500/30 bg-red-500/10 p-4">
      <div className="text-sm text-red-300">
        <p className="font-medium">{title}</p>
        <p>{message}</p>
      </div>
      <Button variant="outline" size="sm" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}

export function MeetingPage() {
  const searchParams = useSearchParams();
  const id = searchParams.get("id");

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ["meeting", id],
    queryFn: () => getMeeting(id as string),
    enabled: id !== null,
  });

  const {
    data: dataSegments,
    isPending: segmentsPending,
    isError: segmentsIsError,
    error: segmentsError,
    refetch: refetchSegments,
  } = useQuery({
    queryKey: ["segments", id],
    queryFn: () => listSegments(id as string),
    enabled: id !== null,
  });

  const {
    data: dataSummary,
    isError: summaryIsError,
    error: summaryError,
    refetch: refetchSummary,
  } = useQuery({
    queryKey: ["summary", id],
    queryFn: () =>
      getSummary(id as string).catch((e) => {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }),
    enabled: id !== null,
  });

  if (id === null) {
    return (
      <main className="p-8">
        <div className="mx-auto max-w-5xl">
          <p className="text-muted-foreground">No meeting selected</p>
        </div>
      </main>
    );
  }

  if (isPending) {
    return <MeetingDetailSkeleton />;
  }

  if (isError) {
    return (
      <main className="p-8">
        <div className="mx-auto max-w-5xl">
          <QueryErrorBanner
            title="Failed to load meeting"
            error={error}
            onRetry={() => refetch()}
          />
        </div>
      </main>
    );
  }

  return (
    <main className="p-8">
      <div className="mx-auto max-w-5xl space-y-4">
        {segmentsIsError && (
          <QueryErrorBanner
            title="Failed to load transcript"
            error={segmentsError}
            onRetry={() => refetchSegments()}
          />
        )}
        {summaryIsError && (
          <QueryErrorBanner
            title="Failed to load summary"
            error={summaryError}
            onRetry={() => refetchSummary()}
          />
        )}
        <MeetingDetail
          meeting={data}
          segments={dataSegments ?? []}
          segmentsPending={segmentsPending}
          summary={dataSummary ?? null}
        />
      </div>
    </main>
  );
}

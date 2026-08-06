"use client";

import { ChatTab } from "@/components/chat-tab";
import { ExportTab } from "@/components/export-tab";
import { SummaryTab } from "@/components/summary-tab";
import { TranscriptTab } from "@/components/transcript-tab";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Meeting, Segment, Summary } from "@/lib/api/types";

const STATUS_CLASSES: Record<string, string> = {
  recording: "border-amber-500/30 bg-amber-500/10 text-amber-400",
  completed: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400",
};

const FALLBACK_STATUS_CLASSES = "border-zinc-500/30 bg-zinc-500/10 text-zinc-300";

export function MeetingDetail({
  meeting,
  segments,
  segmentsPending,
  summary,
}: {
  meeting: Meeting;
  segments: Segment[];
  segmentsPending: boolean;
  summary: Summary | null;
}) {
  return (
    <div className="p-8">
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold">{meeting.title ?? "Untitled"}</h1>
          <div className="flex items-center gap-3">
            <Badge
              variant="outline"
              className={STATUS_CLASSES[meeting.status] ?? FALLBACK_STATUS_CLASSES}
            >
              {meeting.status}
            </Badge>
            <p className="text-muted-foreground text-sm">
              {new Date(meeting.started_at).toLocaleDateString()}
            </p>
          </div>
        </div>

        <Tabs defaultValue="transcript">
          <TabsList>
            <TabsTrigger value="transcript">Transcript</TabsTrigger>
            <TabsTrigger value="summary">Summary</TabsTrigger>
            <TabsTrigger value="chat">Chat</TabsTrigger>
            <TabsTrigger value="export">Export</TabsTrigger>
          </TabsList>
          <TabsContent value="transcript">
            <TranscriptTab meeting={meeting} segments={segments} />
          </TabsContent>
          <TabsContent value="summary">
            <SummaryTab
              meeting={meeting}
              segments={segments}
              segmentsPending={segmentsPending}
              summary={summary}
            />
          </TabsContent>
          <TabsContent value="chat" forceMount>
            <ChatTab
              key={meeting.id}
              meeting={meeting}
              segments={segments}
              segmentsPending={segmentsPending}
              ingested={false}
            />
          </TabsContent>
          <TabsContent value="export">
            <ExportTab disabled={summary === null} summary={summary} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

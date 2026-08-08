"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { ChatTab } from "@/components/chat-tab";
import { ExportTab } from "@/components/export-tab";
import { SummaryTab } from "@/components/summary-tab";
import { TranscriptTab } from "@/components/transcript-tab";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { FALLBACK_STATUS_CLASSES, STATUS_CLASSES } from "@/lib/status-badge";
import { cn } from "@/lib/utils";
import type { Meeting, Segment, Summary } from "@/lib/api/types";

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
        <Link
          href="/"
          className="text-muted-foreground hover:text-foreground eyebrow inline-flex items-center gap-1.5 transition-colors"
        >
          <ArrowLeft className="size-3" />
          Meetings
        </Link>

        <div className="space-y-2">
          <h1 className="text-2xl font-medium">{meeting.title ?? "Untitled"}</h1>
          <div className="flex items-center gap-3">
            <Badge
              variant="outline"
              className={cn("eyebrow", STATUS_CLASSES[meeting.status] ?? FALLBACK_STATUS_CLASSES)}
            >
              {meeting.status}
            </Badge>
            <p className="text-muted-foreground font-mono text-sm">
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
          <TabsContent value="transcript" className="border-border rounded-xl border p-6">
            <TranscriptTab meeting={meeting} segments={segments} />
          </TabsContent>
          <TabsContent value="summary" className="border-border rounded-xl border p-6">
            <SummaryTab
              meeting={meeting}
              segments={segments}
              segmentsPending={segmentsPending}
              summary={summary}
            />
          </TabsContent>
          <TabsContent
            value="chat"
            forceMount
            className="border-border rounded-xl border p-6 data-[state=inactive]:hidden"
          >
            <ChatTab
              key={meeting.id}
              meeting={meeting}
              segments={segments}
              segmentsPending={segmentsPending}
              ingested={false}
            />
          </TabsContent>
          <TabsContent value="export" className="border-border rounded-xl border p-6">
            <ExportTab disabled={summary === null} summary={summary} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

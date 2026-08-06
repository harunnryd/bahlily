"use client";

import { Eye, FileDown, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Meeting } from "@/lib/api/types";

const STATUS_CLASSES: Record<string, string> = {
  recording: "border-amber-500/30 bg-amber-500/10 text-amber-400",
  completed: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400",
};

const FALLBACK_STATUS_CLASSES =
  "border-zinc-500/30 bg-zinc-500/10 text-zinc-300";

interface MeetingsTableProps {
  meetings: Meeting[];
  onOpen?: (id: string) => void;
  onDelete?: (id: string) => void;
  onExport?: (id: string) => void;
}

export function MeetingsTable({
  meetings,
  onOpen,
  onDelete,
  onExport,
}: MeetingsTableProps) {
  if (meetings.length === 0) {
    return (
      <p className="text-muted-foreground py-8 text-center">No meetings yet</p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Title</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Started</TableHead>
          <TableHead>Segments</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {meetings.map((meeting) => (
          <TableRow key={meeting.id}>
            <TableCell className="font-medium">
              {meeting.title ?? "Untitled"}
            </TableCell>
            <TableCell>
              <Badge
                variant="outline"
                className={
                  STATUS_CLASSES[meeting.status] ?? FALLBACK_STATUS_CLASSES
                }
              >
                {meeting.status}
              </Badge>
            </TableCell>
            <TableCell className="text-muted-foreground">
              {new Date(meeting.started_at).toLocaleDateString()}
            </TableCell>
            <TableCell className="text-muted-foreground">
              {meeting.segments_count}
            </TableCell>
            <TableCell>
              <div className="flex justify-end gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onOpen?.(meeting.id)}
                >
                  <Eye />
                  Open
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onExport?.(meeting.id)}
                >
                  <FileDown />
                  Export
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onDelete?.(meeting.id)}
                >
                  <Trash2 />
                  Delete
                </Button>
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

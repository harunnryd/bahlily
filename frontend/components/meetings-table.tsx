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
import { FALLBACK_STATUS_CLASSES, STATUS_CLASSES } from "@/lib/status-badge";
import { cn } from "@/lib/utils";
import type { Meeting } from "@/lib/api/types";

interface MeetingsTableProps {
  meetings: Meeting[];
  onOpen?: (id: string) => void;
  onDelete?: (id: string) => void;
  onExport?: (id: string) => void;
}

export function MeetingsTable({ meetings, onOpen, onDelete, onExport }: MeetingsTableProps) {
  if (meetings.length === 0) {
    return <p className="text-muted-foreground py-8 text-center">No meetings yet</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="eyebrow">Title</TableHead>
          <TableHead className="eyebrow">Status</TableHead>
          <TableHead className="eyebrow">Started</TableHead>
          <TableHead className="eyebrow">Segments</TableHead>
          <TableHead className="eyebrow text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {meetings.map((meeting) => (
          <TableRow key={meeting.id}>
            <TableCell className="font-medium">{meeting.title ?? "Untitled"}</TableCell>
            <TableCell>
              <Badge
                variant="outline"
                className={cn("eyebrow", STATUS_CLASSES[meeting.status] ?? FALLBACK_STATUS_CLASSES)}
              >
                {meeting.status}
              </Badge>
            </TableCell>
            <TableCell className="text-muted-foreground font-mono text-sm">
              {new Date(meeting.started_at).toLocaleDateString()}
            </TableCell>
            <TableCell className="text-muted-foreground font-mono text-sm">
              {meeting.segments_count}
            </TableCell>
            <TableCell>
              <div className="flex justify-end gap-1">
                <Button variant="ghost" size="sm" onClick={() => onOpen?.(meeting.id)}>
                  <Eye />
                  Open
                </Button>
                {onExport !== undefined && (
                  <Button variant="ghost" size="sm" onClick={() => onExport(meeting.id)}>
                    <FileDown />
                    Export
                  </Button>
                )}
                <Button variant="ghost" size="sm" onClick={() => onDelete?.(meeting.id)}>
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

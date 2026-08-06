import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MeetingsTable } from "@/components/meetings-table";
import type { Meeting } from "@/lib/api/types";

const meetings: Meeting[] = [
  {
    id: "m1",
    title: "Sprint planning",
    status: "completed",
    language: "en",
    engine: "whisper",
    model_name: "small",
    started_at: "2026-08-01T10:00:00Z",
    ended_at: "2026-08-01T11:00:00Z",
    segments_count: 42,
    recording_path: null,
    diarization_status: "completed",
    has_summary: true,
  },
];

describe("MeetingsTable", () => {
  it("renders a row per meeting with title and status", () => {
    render(<MeetingsTable meetings={meetings} />);
    expect(screen.getByText("Sprint planning")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
  });

  it("shows empty state when there are no meetings", () => {
    render(<MeetingsTable meetings={[]} />);
    expect(screen.getByText("No meetings yet")).toBeInTheDocument();
  });
});

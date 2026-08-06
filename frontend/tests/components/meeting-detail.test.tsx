import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MeetingDetail } from "@/components/meeting-detail";
import type { Meeting } from "@/lib/api/types";

vi.mock("@/lib/api/storage", () => ({
  getMeeting: vi.fn(),
}));

const meeting: Meeting = {
  id: "m1",
  title: "Sprint planning",
  status: "completed",
  language: "en",
  engine: "whisper",
  model_name: "small",
  started_at: "2026-08-01T10:00:00Z",
  ended_at: null,
  segments_count: 0,
  recording_path: null,
  diarization_status: "completed",
  has_summary: false,
};

describe("MeetingDetail", () => {
  it("renders the meeting title and four tabs", () => {
    render(<MeetingDetail meeting={meeting} />);
    expect(screen.getByText("Sprint planning")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /transcript/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /summary/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /chat/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /export/i })).toBeInTheDocument();
  });
});

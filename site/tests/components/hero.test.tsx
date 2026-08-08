import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Hero } from "@/components/hero";

afterEach(cleanup);

describe("Hero", () => {
  it("renders the headline and the shipped-only subhead", () => {
    render(<Hero />);
    expect(
      screen.getByRole("heading", {
        name: "Meeting intelligence that runs on your machine.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Transcribe, diarize, summarize, and chat with every meeting — all running locally.",
      ),
    ).toBeInTheDocument();
  });

  it("links the primary CTA to the waitlist anchor and the secondary CTA to GitHub", () => {
    render(<Hero />);
    expect(screen.getByRole("link", { name: "Join the waitlist" })).toHaveAttribute(
      "href",
      "#waitlist",
    );
    expect(screen.getByRole("link", { name: "View source on GitHub →" })).toHaveAttribute(
      "href",
      "https://github.com/harunnryd/bahlily",
    );
  });

  it("never mentions translation — that's an unshipped feature and stays out of the hero", () => {
    render(<Hero />);
    expect(screen.queryByText(/translation/i)).not.toBeInTheDocument();
  });
});

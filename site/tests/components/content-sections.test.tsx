import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FeatureRows } from "@/components/feature-rows";
import { PositioningStatement } from "@/components/positioning-statement";

afterEach(cleanup);

describe("PositioningStatement", () => {
  it("frames multi-language support as a direction, not a shipped guarantee", () => {
    render(<PositioningStatement />);
    expect(screen.getByText(/a direction we're building toward/i)).toBeInTheDocument();
  });
});

describe("FeatureRows", () => {
  it("has the #features anchor the nav links to", () => {
    render(<FeatureRows />);
    expect(document.getElementById("features")).not.toBeNull();
  });

  it("lists shipped features under 'Shipped today'", () => {
    render(<FeatureRows />);
    expect(screen.getByText("Shipped today")).toBeInTheDocument();
    expect(screen.getByText("Transcript & Speakers")).toBeInTheDocument();
    expect(screen.getByText("Summarize")).toBeInTheDocument();
    expect(screen.getByText("Chat with your meeting")).toBeInTheDocument();
    expect(screen.getByText("Export")).toBeInTheDocument();
  });

  it("lists live translation and trackable action items only under 'Exploring next'", () => {
    render(<FeatureRows />);
    expect(screen.getByText("Exploring next")).toBeInTheDocument();
    expect(screen.getByText("Live translation")).toBeInTheDocument();
    expect(screen.getByText("Trackable action items")).toBeInTheDocument();
  });
});

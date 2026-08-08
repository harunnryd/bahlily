import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LandingPage from "@/app/page";

describe("LandingPage", () => {
  it("renders every section in order", () => {
    render(<LandingPage />);
    expect(
      screen.getByRole("heading", {
        name: "Meeting intelligence that runs on your machine.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Why Bahlily")).toBeInTheDocument();
    expect(screen.getByText("Shipped today")).toBeInTheDocument();
    expect(screen.getByText("Exploring next")).toBeInTheDocument();
    expect(screen.getByText("Open source")).toBeInTheDocument();
    expect(screen.getByText("What's next")).toBeInTheDocument();
  });
});

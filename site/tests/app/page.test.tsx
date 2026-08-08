import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import LandingPage from "@/app/page";

afterEach(cleanup);

describe("LandingPage", () => {
  it("renders every required section", () => {
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

  it("renders the sections in the required order", () => {
    render(<LandingPage />);
    const elements = [
      screen.getByRole("heading", {
        name: "Meeting intelligence that runs on your machine.",
      }),
      screen.getByText("Why Bahlily"),
      screen.getByText("Shipped today"),
      screen.getByText("Exploring next"),
      screen.getByText("Open source"),
      screen.getByText("What's next"),
    ];

    for (let i = 0; i < elements.length - 1; i += 1) {
      const position = elements[i].compareDocumentPosition(elements[i + 1]);
      expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  });
});

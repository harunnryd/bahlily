import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LandingPage from "@/app/page";

describe("LandingPage", () => {
  it("renders a heading", () => {
    render(<LandingPage />);
    expect(
      screen.getByRole("heading", { name: "Bahlily" }),
    ).toBeInTheDocument();
  });
});

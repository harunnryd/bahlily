import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OssBand } from "@/components/oss-band";

describe("OssBand", () => {
  it("links to GitHub and claims no fabricated metrics", () => {
    render(<OssBand />);
    expect(
      screen.getByRole("link", { name: "View on GitHub" }),
    ).toHaveAttribute("href", "https://github.com/harunnryd/bahlily");
    expect(
      screen.queryByText(/\d+[,.]?\d*\s*(stars|users)/i),
    ).not.toBeInTheDocument();
  });
});

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Footer } from "@/components/footer";
import { Nav } from "@/components/nav";

afterEach(cleanup);

describe("Nav", () => {
  it("renders the wordmark and links to GitHub and the waitlist anchor", () => {
    render(<Nav />);
    expect(screen.getByText("bahlily")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/harunnryd/bahlily",
    );
    expect(screen.getByRole("link", { name: "Join waitlist" })).toHaveAttribute(
      "href",
      "#waitlist",
    );
  });
});

describe("Footer", () => {
  it("renders the license line and a GitHub link", () => {
    render(<Footer />);
    expect(screen.getByText("MIT licensed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/harunnryd/bahlily",
    );
  });
});

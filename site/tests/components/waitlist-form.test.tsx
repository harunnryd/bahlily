import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { WaitlistForm } from "@/components/waitlist-form";

afterEach(cleanup);

describe("WaitlistForm", () => {
  it("shows an inline error for an invalid email and does not submit", async () => {
    const user = userEvent.setup();
    render(<WaitlistForm />);

    await user.type(screen.getByLabelText("Email address"), "not-an-email");
    await user.click(screen.getByRole("button", { name: "Join waitlist" }));

    await waitFor(() => {
      expect(
        screen.getByText("Enter a valid email address."),
      ).toBeInTheDocument();
    });
  });

  it("moves idle -> submitting -> success for a valid email", async () => {
    const user = userEvent.setup();
    render(<WaitlistForm />);

    await user.type(screen.getByLabelText("Email address"), "dev@example.com");
    await user.click(screen.getByRole("button", { name: "Join waitlist" }));

    expect(screen.getByRole("button", { name: "Joining…" })).toBeDisabled();

    await waitFor(() => {
      expect(screen.getByText("You're on the list.")).toBeInTheDocument();
    });
  });
});

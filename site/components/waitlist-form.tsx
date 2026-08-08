"use client";

import { useState } from "react";

type FormState = "idle" | "submitting" | "success" | "error";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function WaitlistForm() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<FormState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!EMAIL_PATTERN.test(email)) {
      setState("error");
      setErrorMessage("Enter a valid email address.");
      return;
    }

    setState("submitting");
    setErrorMessage(null);

    try {
      // TODO(backend): wire to a real waitlist endpoint. For now this
      // simulates a network round-trip and always succeeds.
      await new Promise((resolve) => setTimeout(resolve, 600));
      setState("success");
    } catch {
      setState("error");
      setErrorMessage("Something went wrong — try again.");
    }
  };

  if (state === "success") {
    return (
      <p className="text-foreground text-sm font-medium">
        You&apos;re on the list.
      </p>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      className="flex flex-col gap-3 sm:flex-row sm:items-start"
    >
      <div className="flex-1">
        <input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@example.com"
          aria-label="Email address"
          disabled={state === "submitting"}
          className="border-border focus-visible:ring-ring/50 w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-[3px] disabled:opacity-50"
        />
        {state === "error" && errorMessage !== null && (
          <p className="text-destructive mt-2 text-sm">{errorMessage}</p>
        )}
      </div>
      <button
        type="submit"
        disabled={state === "submitting"}
        className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-md px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50"
      >
        {state === "submitting" ? "Joining…" : "Join waitlist"}
      </button>
    </form>
  );
}

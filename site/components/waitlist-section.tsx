import { WaitlistForm } from "@/components/waitlist-form";

export function WaitlistSection() {
  return (
    <section
      id="waitlist"
      className="border-border mx-auto max-w-6xl border-t px-6 py-16"
    >
      <div className="max-w-xl space-y-4">
        <p className="eyebrow text-muted-foreground">What&apos;s next</p>
        <h2 className="text-2xl font-medium">
          A hosted sync tier is being explored.
        </h2>
        <p className="text-muted-foreground">
          Local-first stays free and default. If a hosted option ships, waitlist
          members hear first.
        </p>
        <WaitlistForm />
      </div>
    </section>
  );
}

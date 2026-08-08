const DEMO_LINES = [
  {
    time: "00:00",
    speaker: "Alex",
    text: "Let's walk through the Q3 roadmap.",
  },
  {
    time: "00:04",
    speaker: "Priya",
    text: "Sure — starting with the transcription service.",
  },
  {
    time: "00:09",
    speaker: "Alex",
    text: "Can we prioritize speaker diarization first?",
  },
];

export function Hero() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-16 sm:py-24">
      <div className="grid gap-12 lg:grid-cols-2 lg:items-center">
        <div className="space-y-6">
          <h1 className="text-3xl font-medium sm:text-4xl">
            Meeting intelligence that runs on your machine.
          </h1>
          <p className="text-muted-foreground text-lg">
            Transcribe, diarize, summarize, and chat with every meeting — all
            running locally.
          </p>
          <div className="flex flex-wrap items-center gap-4">
            <a
              href="#waitlist"
              className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-md px-4 py-2 text-sm font-medium transition-colors"
            >
              Join the waitlist
            </a>
            <a
              href="https://github.com/harunnryd/bahlily"
              className="text-foreground text-sm font-medium underline-offset-4 hover:underline"
            >
              View source on GitHub →
            </a>
          </div>
          <div className="eyebrow text-muted-foreground flex flex-wrap gap-4">
            <span>Local-first</span>
            <span>Local Whisper</span>
            <span>MIT licensed</span>
          </div>
        </div>
        <div className="bg-graphite text-graphite-foreground rounded-xl p-4">
          <p className="eyebrow text-graphite-foreground/60 mb-3">
            transcript.live
          </p>
          <div className="divide-graphite-foreground/10 divide-y">
            {DEMO_LINES.map((line) => (
              <p
                key={line.time}
                className="flex gap-3 py-2 text-sm first:pt-0 last:pb-0"
              >
                <span className="text-primary shrink-0 font-mono">
                  [{line.time}]
                </span>
                <span className="text-graphite-foreground/60 shrink-0">
                  {line.speaker}:
                </span>
                <span>{line.text}</span>
              </p>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

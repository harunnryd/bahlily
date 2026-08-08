export function OssBand() {
  return (
    <section className="bg-graphite text-graphite-foreground">
      <div className="mx-auto max-w-6xl px-6 py-16">
        <div className="max-w-xl space-y-4">
          <p className="eyebrow text-graphite-foreground/60">Open source</p>
          <h2 className="text-2xl font-medium">
            Local-first, MIT-licensed, built on Whisper and your choice of LLM provider.
          </h2>
          <a
            href="https://github.com/harunnryd/bahlily"
            className="bg-primary text-primary-foreground hover:bg-primary/90 inline-block rounded-md px-4 py-2 text-sm font-medium transition-colors"
          >
            View on GitHub
          </a>
        </div>
      </div>
    </section>
  );
}

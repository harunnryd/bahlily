interface Feature {
  title: string;
  description: string;
  wide: boolean;
}

const SHIPPED: Feature[] = [
  {
    title: "Transcript & Speakers",
    description: "Automatic diarization, with speaker profiles that carry across meetings.",
    wide: true,
  },
  {
    title: "Summarize",
    description:
      "Key points, quotes, and action items extracted automatically. Templates are fully customizable.",
    wide: false,
  },
  {
    title: "Chat with your meeting",
    description: "Ask questions, get answers with citations back to the transcript.",
    wide: false,
  },
  {
    title: "Export",
    description: "Markdown, DOCX, PDF.",
    wide: true,
  },
];

const EXPLORING: Feature[] = [
  {
    title: "Live translation",
    description: "Real-time captions in your language during the call.",
    wide: false,
  },
  {
    title: "Trackable action items",
    description:
      "Turn extracted action items into assignable, completable tasks instead of a static list.",
    wide: false,
  },
];

function FeatureCard({ feature }: { feature: Feature }) {
  return (
    <div className={`border-border space-y-2 border-l pl-4 ${feature.wide ? "lg:col-span-2" : ""}`}>
      <h3 className="font-medium">{feature.title}</h3>
      <p className="text-muted-foreground text-sm">{feature.description}</p>
    </div>
  );
}

export function FeatureRows() {
  return (
    <section id="features" className="border-border mx-auto max-w-6xl border-t px-6 py-16">
      <div className="space-y-10">
        <div className="space-y-4">
          <p className="eyebrow text-muted-foreground">Shipped today</p>
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {SHIPPED.map((feature) => (
              <FeatureCard key={feature.title} feature={feature} />
            ))}
          </div>
        </div>
        <div className="space-y-4">
          <p className="eyebrow text-muted-foreground">Exploring next</p>
          <div className="grid gap-6 sm:grid-cols-2">
            {EXPLORING.map((feature) => (
              <FeatureCard key={feature.title} feature={feature} />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

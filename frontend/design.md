# Design — Bahlily

A locked design system for this app. Every page redesign reads this file before
emitting code. Do not regenerate per page — extend or amend this file when the
system needs to grow.

## Genre

modern-minimal

## Macrostructure family

Bahlily is a functioning tool (meeting review, transcripts, chat, export), not a
marketing site — it has no landing/pricing pages. Every route is an **app page**,
so there is one family:

- App pages: **Workbench** — small functional headings, frame-based content
  blocks (cards as "frames"), hairline dividers instead of drop-shadows, a
  sticky/settled action row rather than marketing CTAs. Data (tables,
  transcripts, chat turns) is the primary content; chrome stays quiet.

## Theme — Cobalt

- `--color-paper` oklch(98.5% 0.004 250)
- `--color-ink` oklch(24% 0.02 258)
- `--color-rule` oklch(84% 0.008 250)
- `--color-accent` oklch(50% 0.20 256)
- `--color-accent-ink` oklch(98.5% 0.004 250)
- `--color-focus` oklch(58% 0.20 256)
- `--color-graphite` oklch(22% 0.016 260) — the one dark band (transcript / code-like surfaces)
- `--color-primary-on-graphite` oklch(72% 0.15 256) — accent text/labels on the graphite band, since the paper-background accent is too dark to read there
- `--color-success` oklch(50% 0.13 155)
- `--color-warning` oklch(48% 0.14 75)
- `--color-danger` oklch(50% 0.19 25)

## Typography

- Display: Space Grotesk, weight 500/600, style normal
- Body: Inter, weight 400/500
- Mono: JetBrains Mono, weight 400/500 — eyebrows, meta, timestamps, status chips, UPPERCASE, tracking 0.06em
- Display tracking: -0.02em
- Type scale: plain Tailwind text-size utilities (text-2xl, text-lg, etc.) applied directly — no semantic type-scale token exists.

## Spacing

No semantic spacing tokens exist yet. Pages use raw Tailwind utility spacing
(`p-4`, `gap-6`, etc.) directly.

## Motion

- Easing: none defined — this is a motion-cut build with no easing tokens.
- Reveal pattern: none — this is a working tool, not a marketing page. Data appears instantly.
- Reduced-motion fallback: n/a (no reveals to begin with)

## Microinteractions stance

- Silent success (query invalidation + updated UI), never celebratory toasts
- Errors render inline as a bordered banner in `--color-danger`, never a modal interrupt
- Focus rings: 3px `ring-ring/50` box-shadow, shown instantly via `focus-visible`, never animated in

## CTA voice

- Primary action: solid `--color-accent` fill, 6px radius, `--color-accent-ink` text
- Secondary/outline: hairline `--color-rule` border, transparent fill
- Destructive: `--color-danger` fill only on the confirming action, never on the trigger

## Per-page allowances

- All pages are app pages: no enrichment, no hero imagery, no decorative treatments.
- Typography and hairline structure carry the page.

## What pages MUST share

- Cobalt palette + Space Grotesk/Inter/JetBrains Mono pairing.
- Hairline borders (`--color-rule`) instead of drop-shadows on cards/panels.
- Mono-uppercase micro-labels for status, timestamps, section eyebrows.
- 6px radius on buttons/inputs, 12px on cards.
- CTA voice above.

## What pages MAY differ on

- Layout density (the dashboard is table-led; meeting detail is tab-led).
- Whether a section uses the graphite dark band — used on the transcript panel and
  the chat log (both are log-like content, matching Cobalt's "code is the hero"
  signature move). Not used anywhere else.

## Navigation

A single edge-aligned minimal bar (N9) in `components/app-shell.tsx`, wired
through `app/layout.tsx` so every route shares it: wordmark left, a quiet
static label right, hairline bottom border. Meeting detail additionally
carries a `← Meetings` breadcrumb above its own heading — there is no nav
destination for it otherwise.

## Exports

### tokens.css

See `app/globals.css` — tokens are declared directly in the project's existing
Tailwind v4 `@theme inline` block rather than a separate file, to avoid a second
source of truth alongside the pre-existing shadcn/ui token names this app already
uses (`--background`, `--foreground`, `--primary`, etc). The Cobalt values above
are mapped onto those existing semantic names one-to-one.

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
- `--color-paper`      oklch(98.5% 0.004 250)
- `--color-paper-2`    oklch(96% 0.006 250)
- `--color-ink`        oklch(24% 0.02 258)
- `--color-ink-2`      oklch(34% 0.018 257)
- `--color-rule`       oklch(90% 0.006 250)
- `--color-rule-2`     oklch(84% 0.008 250)
- `--color-accent`     oklch(58% 0.20 256)
- `--color-accent-ink` oklch(98.5% 0.004 250)
- `--color-focus`      oklch(58% 0.20 256)
- `--color-graphite`   oklch(22% 0.016 260)  — the one dark band (transcript / code-like surfaces)
- `--color-success`    oklch(62% 0.13 155)
- `--color-warning`    oklch(70% 0.14 75)
- `--color-danger`     oklch(58% 0.19 25)

## Typography
- Display: Space Grotesk, weight 500/600, style normal
- Body:    Inter, weight 400/500
- Mono:    JetBrains Mono, weight 400/500 — eyebrows, meta, timestamps, status chips, UPPERCASE, tracking 0.06em
- Display tracking: -0.02em
- Type scale anchor: `--text-display` = clamp(1.5rem, 1.1rem + 1.2vw, 2rem) — app headings stay small and functional, never marketing-scale

## Spacing
4-point named scale in `app/globals.css` `@theme inline`. Pages use named
tokens (`--space-*`), never raw Tailwind spacing where a semantic token exists.

## Motion
- Easing: `--ease-out` = cubic-bezier(0.16, 1, 0.3, 1)
- Reveal pattern: none — this is a working tool, not a marketing page. Data appears instantly.
- Reduced-motion fallback: n/a (no reveals to begin with)

## Microinteractions stance
- Silent success (query invalidation + updated UI), never celebratory toasts
- Errors render inline as a bordered banner in `--color-danger`, never a modal interrupt
- Focus rings: 2px solid `--color-focus`, shown instantly, never animated in

## CTA voice
- Primary action: solid `--color-accent` fill, 6px radius, `--color-accent-ink` text
- Secondary/outline: hairline `--color-rule-2` border, transparent fill
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

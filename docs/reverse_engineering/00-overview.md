# Reverse Engineering Meetily — Overview

## Why this folder exists

Meetily's public positioning splits the product into a free "Community Edition" (this repo) and a "Meetily PRO" tier advertised in `README.md` as a **separate, unreleased codebase** (enhanced accuracy, custom summary templates, advanced export, auto-join meetings, speaker diarization, chat-with-meetings, calendar integration, self-hosted enterprise deployment). **The project owner's explicit goal for the rewrite is to fully open-source every one of these Pro-tier capabilities** — not just match the free Community Edition, but eliminate the paywall entirely by shipping diarization, advanced export, custom templates, chat-with-meetings, and calendar integration as first-class open-source features. See the update below: as of mid-2026, `meetily.ai`'s live site (not just the repo README) confirms Pro ($10/user/month) already ships speaker diarization as a working feature, not a "Coming Soon" placeholder — this is the concrete bar the rewrite needs to clear and open-source.

We want to build an equivalent — and eventually better — product from scratch, with a different technology bias: heavy on Python/TypeScript (to use LangChain, LangGraph, DeepEval) and Rust only where Rust is actually load-bearing (most likely native OS audio capture). Before designing that, we need an accurate picture of:

1. What the current Community Edition actually does (not what the README claims).
2. What "Pro" would need to do, reconstructed from README claims plus competitor products, since no Pro code exists to inspect.
3. Where the current Rust-monolith-in-Tauri architecture should and shouldn't carry over.

## Methodology

- **01, 02**: static analysis of this repository — Rust source under `frontend/src-tauri/src`, TypeScript under `frontend/src`, the archived `backend/`, and root docs (`README.md`, `LICENSE.md`, `PRIVACY_POLICY.md`, `CONTRIBUTING.md`). No external research; these are direct findings from a full-repo grep/read pass.
- **03**: external research on competitor meeting-assistant products (Otter.ai, Fireflies.ai, Fathom, Grain) for how they implement the not-yet-built Pro-track features, cross-referenced against the specific open-source libraries already scouted (pyannote-audio, whisper-diarization, docx-rs/printpdf, comrak, icalendar/caldav, screenpipe/pynput, LangChain/LangGraph).
- **04**: architecture research — for each subsystem, whether it has a hard technical requirement for Rust (native OS APIs, real-time constraints) or can move to Python/TS without losing capability.
- **05, 06**: synthesis — no new research, just architecture design built on 01-04.

## Scope boundaries

| Question | Where it's answered |
|---|---|
| What does Community Edition actually implement today? | `01-current-architecture.md`, `02-feature-inventory.md` |
| What is "Pro" actually claimed to include, and what's real vs. marketing? | `02-feature-inventory.md` |
| How would we build the Pro-track features as open source, using what libraries? | `03-pro-feature-research.md` |
| What must stay Rust vs. what can move to Python/TS? | `04-rust-vs-python-ts-boundary.md` |
| What does the new microservice architecture look like? | `05-proposed-architecture.md` |
| How do we get there incrementally? | `06-migration-roadmap.md` |

## Key finding up front

There is **no license-check, paywall, or feature-gating code anywhere in this repository**. The only runtime feature flag is an unrelated Beta system (`frontend/src/types/betaFeatures.ts`) gating a single feature (`importAndRetranscribe`). "Meetily PRO" is 100% marketing copy in `README.md`/`meetily.ai` pointing to a paid tier ($10/user/month, confirmed live on the marketing site) — none of it exists as code in this open-source repo. This means the Pro feature set below is **reconstructed**, not reverse-engineered from code — treat `03-pro-feature-research.md` as a design proposal, not a spec extracted from a real system. Note also that the live marketing site is a moving target: it already contradicts the repo's own `README.md` on at least one point (diarization is marketed as shipped/live on the site, but still "Coming Soon" per the README) — re-check `meetily.ai` periodically rather than treating `02-feature-inventory.md`'s Pro-status column as permanently current.

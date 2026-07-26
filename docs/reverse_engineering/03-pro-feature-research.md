# Pro-Track Feature Research: Competitors + Open-Source Building Blocks

## Context

Meetily's README markets a "Meetily PRO" tier with eight capabilities, several explicitly labeled "Coming Soon" by the vendor itself: enhanced transcription accuracy, custom/expanded summary templates, advanced export (PDF/DOCX/Markdown), auto-detect and auto-join meetings, speaker identification/diarization, chat-with-meetings, calendar integration, and self-hosted/enterprise deployment. None of this exists in the open-source repo (see `02-feature-inventory.md`) — it has to be designed from zero. Self-hosted/enterprise deployment is a packaging/ops decision, not a feature with its own pipeline, so it is out of scope for this file; the other seven are covered below, one H2 per feature.

For each feature: how Otter.ai, Fireflies.ai, Fathom, and Grain actually behave (what's free vs. paywalled, and any pipeline details they disclose), then a recommendation for an open-source, Python/TS-biased implementation, drawing on the libraries the team already scouted and checking each against current GitHub health and license compatibility.

A cross-cutting finding worth flagging up front: **all four competitors implement calendar integration and auto-join as one combined feature**, via a **bot that joins the call as a visible virtual participant** (named "Otter Notetaker," "Fathom Notetaker," etc.), triggered off a calendar-synced meeting link — not via OS-level UI automation on the user's own machine. That's a materially different architecture than the scouted `pynput`/`screenpipe`/accessibility-API approach, and it changes the licensing and platform calculus (see the Auto-Join section).

---

## 1. Speaker Identification / Diarization

### Competitor approach
- **Otter.ai**: Diarization is a post-processing pass, not real-time — live transcription shows no speaker labels; after the recording stops, Otter re-analyzes the full audio with complete context to separate speakers. It maintains a persistent "voiceprint" per named speaker at the account/workspace level: once a user labels "Speaker 1" as a real name, Otter reuses that voiceprint to auto-identify the same person in future meetings, and retroactively relabels the current transcript.
- **Fireflies.ai**: Markets a proprietary multi-stage pipeline (audio preprocessing → feature extraction → speaker clustering → refinement) with claimed 95%+ accuracy and support for up to 50 speakers. For Zoom/Google Meet it pulls actual participant display names from the meeting platform's participant list rather than relying purely on acoustic clustering; for other sources it falls back to generic "Speaker 1/2" labels, which is a strong signal that platform metadata (not just audio ML) is doing a lot of the identification work in-meeting.
- **Fathom / Grain**: Both similarly join as meeting-platform bots and inherit the participant roster from the platform's API/UI, use that to pre-label speakers, and only fall back to acoustic diarization for audio-only imports or uploaded files without platform metadata.

### Recommended OSS approach
Use **pyannote-audio** (`pyannote/speaker-diarization-3.1` or the newer community pipeline) as the acoustic fallback, but architect the system so that **platform-provided participant metadata is the primary signal whenever available** (Tauri app already knows which audio device is "system" vs "mic"; if/when a bot-join capability exists, the calling platform's participant list should populate speaker labels directly, same as competitors do). Prefer `MahmoudAshraf97/whisper-diarization` over the originally scouted `snakers4/whisper-diarization` — the snakers4 repo is not the actively maintained project in this space (that name is more associated with Silero VAD); `MahmoudAshraf97/whisper-diarization` (~5.6k stars, MIT) is the actively maintained Whisper+pyannote combinator and matches the "diarize → transcribe → link" workflow the team scouted.

### Sketch
Run pyannote's segmentation+clustering pipeline on the full recorded audio (mic+system pre-mix, not the VAD-filtered stream used for live transcription) as a background job after recording stops, mirroring Otter's "second pass" model. Store per-utterance speaker-cluster IDs and timestamps in the local DB, then merge with Whisper's word-level timestamps to produce "Speaker N: text" segments (the `whisper-diarization` project's linking approach). Expose a one-time UI affordance to name a cluster, and persist a lightweight voice embedding (pyannote already extracts embeddings) keyed to that name so future sessions can auto-match without re-labeling — essentially Otter's voiceprint model, built on data pyannote already computes for free.

### Gotchas
- **HuggingFace gating**: pyannote's pipelines are MIT-licensed but gated behind HuggingFace's per-model click-through terms and an auth token; both `pyannote/segmentation-3.0` and `pyannote/speaker-diarization-3.1` require separate acceptance, which means first-run setup needs a token-provisioning flow (or bundling a mirrored/self-hosted copy, which the license permits since it's MIT, just not with HF's gate).
- **Accuracy under real conditions**: published DER for pyannote 3.x is ~11–19% on clean benchmark audio; noisy multi-speaker meetings with cross-talk, laptop mics, and system-audio bleed (exactly Meetily's target scenario) will do meaningfully worse, and overlapping speech is still the hardest case even with pyannote 3's powerset classification.
- **Diarization is a second, separate model from Whisper** — it roughly doubles inference cost/time per meeting and needs its own GPU/CPU budget, which competes with the existing VAD-filtered live-transcription path for compute.
- **Bot-vs-local mismatch**: competitors' most accurate speaker labels come from platform participant metadata (bot joins the call), not acoustics. If Meetily stays a local-capture app without a virtual meeting-bot participant, it will structurally lag competitor accuracy unless local diarization quality is heavily invested in.

---

## 2. Chat with Meetings

### Competitor approach
- **Otter.ai**: "Otter AI Chat" lets users ask questions about a single meeting or across meeting history conversationally — effectively RAG over the transcript corpus scoped per-user/workspace.
- **Fireflies.ai**: "AskFred" is gated behind an **AI-credit system** even on paid tiers (20 credits/month on Pro, 30 on Business) — each chat query consumes credits priced by estimated compute cost, meaning chat is functionally metered/rationed rather than unlimited even for paying customers.
- **Fathom**: "Ask Fathom" is presented as a ChatGPT-like interface over one's meeting library; on the free tier it's capped (bundled with the "5 AI summaries/month" cap), unlimited on paid tiers.
- **Grain**: "Ask Anything" plus a documented **MCP server and API** for querying transcripts externally, and one-click export of transcript context into ChatGPT/Claude — notably the most "open substrate" approach of the four, treating transcript-chat as an integration surface rather than only an in-app widget.

### Recommended OSS approach
**LangChain (Python) + Ollama**, exactly as already scouted, with a RAG layer rather than raw context-stuffing: chunk transcripts (Whisper's segment boundaries are natural chunk points), embed with a local embedding model (e.g., `nomic-embed-text` via Ollama, or `sentence-transformers`), store in a lightweight local vector store (`chromadb` or `sqlite-vec`, both permissive-licensed and already Python-native), and retrieve top-k chunks per query for the LLM. Skip "LangChain Rust" for this — it is materially less mature than the Python library, and chat-with-meetings has no hard real-time/native constraint that would justify paying that immaturity cost; this is squarely in the Python/TS-biased half of the new architecture.

### Sketch
On meeting-save, chunk the final transcript + diarization labels into overlapping windows, embed each chunk, and upsert into a per-meeting (and optionally cross-meeting) vector collection. A chat endpoint takes a user query, embeds it, retrieves top-k chunks (plus the meeting summary as a standing system-context item), and calls the local Ollama model (or a remote provider, matching Meetily's existing multi-provider LLM pattern) via a LangChain conversational-retrieval chain. Grain's "MCP server + API" idea is worth borrowing regardless of chat UI — exposing transcript search as an MCP tool costs little extra once RAG infrastructure exists and gives Meetily a distribution edge (agents/other tools can query meetings directly).

### Gotchas
- Fireflies' credit-metering shows that "chat with meetings" is one of the more expensive Pro features to run at scale — for a local-first, self-hosted product this cost shifts to the user's own compute/API bill, which is actually favorable, but batch/embedding jobs still need to not compete with live transcription for GPU time.
- RAG quality degrades on long, rambling meeting transcripts without decent chunking; naive fixed-size chunking will split mid-sentence and hurt retrieval — chunk on diarization/utterance boundaries instead.
- If exposing an MCP/API surface (Grain's model), that's a new attack surface requiring auth even in a local-first app (e.g., binding to localhost only, or requiring a token) — don't repeat the archived FastAPI backend's unauthenticated-CORS mistake called out in `02-feature-inventory.md`.

---

## 3. Calendar Integration + Auto-Detect/Auto-Join Meetings

### Competitor approach
All four vendors implement this as a **single combined feature**, and all four use the same architecture: connect Google Calendar or Outlook/Microsoft 365 → the service reads upcoming calendar events → detects a Zoom/Google Meet/Microsoft Teams link in the event body → a cloud-hosted **bot joins the call as a named virtual participant** ("Otter Notetaker," "Fathom Notetaker," Fireflies' "Fred") at the scheduled time, with no user action needed. Otter and Fireflies both let users scope this (all meetings / external-only / manual-approval-only). Zoom requires an explicit app authorization via the Zoom Marketplace; Google Meet and Microsoft Teams typically let the bot join via the invite URL directly with no separate app install. Critically, **none of the four rely on local OS automation** (no clicking a "Join" button via `pynput` or an accessibility API) — the bot is a server-side service account that joins over the network, which sidesteps OS permission prompts and works headlessly, but requires operating a fleet of bot workers (a real infrastructure cost) and inherently sends meeting audio to the vendor's cloud.

### Recommended OSS approach
This is the one feature where the originally scouted OSS building blocks (`screenpipe`, `pynput`, native accessibility APIs) solve a **different problem than what competitors actually built**. Competitors' approach is a cloud-bot-joins-the-call model; the scouted tools are for **local UI automation to auto-click "Join" inside apps already open on the user's own machine** — appropriate only if Meetily stays local-first and avoids operating a bot fleet. Recommend: **`icalendar` (Python, MIT) + provider APIs** (Google Calendar API, Microsoft Graph API — both have official, actively maintained Python SDKs and are the licensing-safe path, ahead of the scouted `caldav` which is GPL-2.0+ and would taint a permissively-licensed codebase if statically/tightly linked) for calendar reading and meeting-link detection, paired with **native OS notification/auto-launch** (trigger Meetily's own local recording a configurable number of minutes before a detected meeting) rather than reproducing competitors' bot-join model. Treat `pynput` as a fallback only, and be aware of its license.

### Sketch
Use Google Calendar API / Microsoft Graph API OAuth to pull the user's upcoming events, parse each event body/location for a Zoom/Meet/Teams URL via regex (competitors do exactly this — it's the same signal, just detected locally instead of server-side), and surface a "meeting starting in N minutes — start recording?" prompt (or fully automatic start, per user preference) that kicks off Meetily's existing local audio-capture pipeline. This preserves the local-first, no-bot-in-the-call privacy story that differentiates Meetily from the four cloud competitors, at the cost of not automatically getting participant-name metadata (see diarization section) the way a true meeting bot would.

### Gotchas
- **`caldav` (GPL 2.0+)** is a licensing risk for a project stated to prefer permissive licensing; if CalDAV support (non-Google/Microsoft calendars, e.g. iCloud, self-hosted) is wanted, isolate it as an optional/pluggable component invoked via subprocess or a separate service boundary, not linked into the core, or find a permissively-licensed CalDAV client instead.
- **`pynput` is LGPL-3** — for a Python module invoked as a separate process this is usually fine (LGPL's dynamic-linking exception broadly maps to "import as a library"), but bundling it into a compiled/frozen desktop binary can create a stricter linking situation; legal review advisable before shipping it in a bundled app, and it should be scoped narrowly (auto-click "Join" only) rather than general automation.
- **`screenpipe` (MIT, ~19k stars, actively developed as of mid-2026)** is healthy and broad (24/7 screen/audio recording + OCR + agent integrations) but is a much heavier dependency than this feature needs — it is arguably overkill for "detect a video-call window and click Join"; a narrower accessibility-API-based detector is likely lower-risk than embedding a general always-on recording platform.
- True bot-join (matching competitor UX) requires either a headless browser/meeting-SDK client per platform (Zoom SDK, Google Meet, Teams) plus server infrastructure to host bot workers — a materially larger engineering and hosting commitment than local calendar-triggered auto-start, and a privacy trade-off (audio leaves the user's machine) that cuts against Meetily's stated "entirely on local infrastructure" positioning.

---

## 4. Advanced Export (PDF, DOCX, Markdown)

### Competitor approach
None of the four competitors publish much about their export pipeline internals — this is treated as a commodity feature by all of them (present in paid tiers, rarely discussed in blogs/docs beyond "export your notes"). The interesting signal is *what* gets exported: structured summaries (headers, bullet action items, speaker-attributed quotes), not just raw transcript text, meaning the export layer needs to consume the same structured summary/template data model as the chat and template features, not just flatten a transcript to text.

### Recommended OSS approach
Given the project's stated Python/TS-heavy bias, prefer the **Python-side equivalents** over the originally scouted Rust crates for this feature specifically: **`python-docx`** (MIT, mature, most widely used DOCX-from-Python library) for DOCX, and **`weasyprint`** (BSD/LGPL dual depending on version — verify current license — HTML/CSS-to-PDF) or **`reportlab`** (BSD-ish "commercial-friendly" open edition) for PDF, since export generation is naturally driven by the same structured summary object the LLM produces (JSON/Markdown) and doing HTML→PDF or template→DOCX in the same language as the summarization service avoids an extra Rust FFI boundary for a non-performance-critical, infrequent (per-export, not per-frame) operation. Markdown export needs no library at all beyond a templating engine, since a well-structured summary can be serialized to Markdown directly — but if HTML rendering of that Markdown is also needed (e.g., in-app preview before export), **comrak** (Rust, MIT, ~1k+ stars, actively maintained) remains a solid choice if there's already a case for calling into Rust from the export path, otherwise Python's `markdown-it-py` or `mistune` (both MIT) avoids a cross-language call for a small feature.
The originally scouted `docx-rs` and `printpdf` remain reasonable if export generation ends up living in the Rust/Tauri core for some other reason (e.g., wanting it fully offline/bundled with zero Python runtime dependency) — the choice is really "which side of the Python/TS-vs-Rust boundary does export live on," which `04-rust-vs-python-ts-boundary.md` should resolve; this file recommends Python primarily because export consumes the same structured summary object the (Python-side) LLM summarization step already produces.

### Sketch
Define one canonical structured-summary schema (title, sections, bullet action items with owners/dates, speaker-attributed key quotes) produced once by the summarization step; write three renderers off that single schema — Markdown (direct template), DOCX (`python-docx`, populate a template document with headings/tables), and PDF (render the same content to HTML via a small Jinja2 template, then `weasyprint`/`reportlab` to PDF) — so all three formats stay in sync automatically when the schema changes, rather than three independent hand-rolled generators.

### Gotchas
- `weasyprint`'s license has shifted across versions (some releases moved between BSD-3 and LGPL-ish terms) — pin and verify the exact version's license before adoption; `reportlab`'s fully-open feature set is narrower than its commercial "Plus" tier, so check that required features (tables, styling) are in the open edition.
- DOCX/PDF templates that try to visually mimic Word/Acrobat output exactly are a maintenance sink; keep the initial template intentionally simple (headings + bullets + a table) rather than chasing pixel-perfect competitor-parity layouts.
- If export ever needs to run fully offline with zero Python dependency (e.g., a minimal Rust-only build variant), the Rust crates (`docx-rs`, `printpdf`) are the fallback — worth keeping in mind as an alternate path, not a wasted evaluation.

---

## 5. Custom / Expanded Summary Templates

### Competitor approach
- **Otter.ai**: "Custom Meeting Type Templates" — users pick a built-in template (Team Meeting, Sales Call, 1:1) or author their own, and it changes what the summary tab extracts/generates (available across all tiers, gated more by usage limits than by feature access).
- **Fireflies.ai**: Ships "AI Skills," 100+ built-in templates (BANT, MEDDIC, interview feedback, etc.) — essentially a template *library* as a product differentiator, not just a single custom-template editor.
- **Fathom**: 14+ built-in templates including sales-specific frameworks (SPICED, MEDDPICC, BANT) plus org-level custom call/deal summary templates; free tier caps advanced templates to 5 uses/month before falling back to one basic chronological template only.

### Recommended OSS approach
No new OSS library needed here — this is fundamentally a **prompt-engineering and structured-output problem**, well served by the already-scouted **LangChain (Python)** prompt-template abstractions plus a validated output schema (e.g., Pydantic models + LangChain's structured-output/function-calling support, or a JSON-schema-constrained decoding path if using a local Ollama model that supports it). The "value" competitors sell here is really a curated library of good prompts per use case (sales call, 1:1, interview), which is a content/curation investment more than a technical one.

### Sketch
Model each template as a stored prompt (system instructions + the canonical structured-summary schema from the Export section, with template-specific extra fields — e.g., a sales template adds a "framework fields" section for BANT/MEDDIC) plus optional few-shot examples; let users pick a template before/after a meeting, and store custom templates as user-authored prompt+schema pairs in the local DB so "create your own template" (Otter's model) falls out for free once the schema-driven prompt system exists. Ship a handful of built-in templates at launch (generic meeting, 1:1, sales call, interview) and treat growing the library as an ongoing content task, not a v1 blocker.

### Gotchas
- Structured-output reliability from local/smaller Ollama models is weaker than from frontier hosted models — validate the chosen schema-constraint approach (Pydantic + retries, or grammar-constrained decoding) actually holds up on the local models Meetily ships by default, or templates will silently produce malformed summaries.
- Competitors gate template usage by *volume* (5/month on free tiers), not by template *complexity* — if there's ever a hosted/paid tier, metering summary generations (not template access) is closer to how the market prices this.
- A large template library (Fireflies' 100+) is a curation/QA burden — better to launch with fewer, well-tested templates than to copy the sheer count.

---

## 6. Enhanced Transcription Accuracy

### Competitor approach
None of the four disclose real pipeline internals publicly beyond marketing claims ("industry-leading accuracy," etc.); this is the least-documented feature across all four vendors' public docs/blogs. What is observable: all four support multiple audio sources (live meeting-platform bot audio, which is typically clean single-or-few-speaker VoIP audio, vs. uploaded files of unknown quality), and several (Fireflies) explicitly separate "meeting platform" transcripts (higher quality, participant-name-tagged) from generic upload transcripts — implying their accuracy advantage partly comes from cleaner input (VoIP-quality bot audio) rather than purely from a better ASR model.

### Recommended OSS approach
This isn't a new-library question — Meetily already uses whisper.cpp/whisper-rs, which is the right foundation. "Enhanced accuracy" as a Pro feature most realistically decomposes into: (a) offering larger Whisper model tiers (`medium`/`large-v3`) as a Pro-tier default vs. `base`/`small` on free, matching Meetily's own documented dev-vs-prod model guidance in `whisper_engine.rs`; (b) domain/vocabulary adaptation (custom vocabulary/prompt biasing, which whisper.cpp already supports via initial prompt injection) for jargon-heavy meetings; and (c) better pre-processing (the existing VAD + professional audio mixing in `pipeline.rs` already does more real signal-quality work than most competitors disclose doing). Parakeet (already referenced in the CLAUDE.md tech stack) is worth benchmarking against whisper-large-v3 as an alternative ASR backend, since NVIDIA's Parakeet models have published competitive WER on some benchmarks with faster inference.

### Sketch
Expose model-tier selection (base/small/medium/large-v3, or Parakeet variants) as a user- or tier-gated setting rather than building new transcription infrastructure; add a custom-vocabulary/initial-prompt field per meeting or per user (feeds Whisper's existing prompt-biasing mechanism) so domain jargon (product names, acronyms) transcribes correctly; and treat "accuracy" partly as a diarization/speaker-labeling quality question (see Feature 1) since garbled speaker attribution reads to end users as "bad transcription" even when word-level ASR is fine.
### Gotchas
- Larger models cost proportionally more compute/memory/time — "enhanced accuracy" as a Pro gate is easy to implement technically but has real hardware implications for users without a capable GPU (this is a support-burden and UX-messaging problem, not just an engineering one).
- Whisper hallucination (fabricating plausible-sounding text during silence/noise) is a known failure mode that model-tier upgrades don't fully fix — pair larger models with the existing VAD filtering, since VAD reduces exactly the silence/noise segments most prone to hallucination.
- Benchmarking Parakeet vs. whisper-large-v3 needs to happen on Meetily's actual target audio (mixed mic+system, multi-speaker, imperfect real-world meetings), not published clean-benchmark WER numbers, since real-world ranking between ASR models often differs from benchmark leaderboards.

---

## Summary Table

| Feature | Recommended library/approach | License | Confidence (High/Medium/Low) |
|---|---|---|---|
| Speaker diarization | pyannote-audio (`speaker-diarization-3.1`) + `MahmoudAshraf97/whisper-diarization` combinator, platform-metadata-first when available | MIT (HF-gated distribution) | High |
| Chat with meetings | LangChain (Python) + Ollama + local vector store (Chroma/sqlite-vec), RAG over transcript chunks | MIT / Apache-2.0 | High |
| Calendar integration | Google Calendar API + Microsoft Graph API (official SDKs) + `icalendar` for parsing/generation | MIT / permissive | Medium |
| Auto-detect/auto-join | Local calendar-triggered auto-start of Meetily's own recorder (no cloud bot); `pynput`/accessibility APIs only as a narrow, isolated fallback for local "click Join" automation | LGPL-3 (`pynput`, isolate) / MIT (`screenpipe`, likely unnecessary) | Medium |
| Advanced export | `python-docx` (DOCX) + `weasyprint`/`reportlab` (PDF) + direct Markdown templating, all driven by one structured-summary schema | MIT / BSD-LGPL (verify per version) | Medium |
| Custom summary templates | LangChain prompt templates + Pydantic-validated structured output, curated built-in template library | MIT | High |
| Enhanced transcription accuracy | Existing whisper.cpp/whisper-rs with tiered model selection + custom-vocabulary prompt biasing; benchmark Parakeet as alternative backend | MIT (whisper.cpp) | Medium |

**Note on `caldav`**: excluded from the recommended calendar stack above due to its GPL-2.0+ license conflicting with the project's stated permissive-licensing preference; keep it only as an optional, isolated plugin if non-Google/Microsoft (CalDAV-only) calendar support is required, or find a permissively-licensed alternative before committing to it in the core.

---

## Sources

- [Speaker Identification Overview – Otter Help Center](https://help.otter.ai/hc/en-us/articles/21665587209367-Speaker-Identification-Overview)
- [Custom Meeting Type Templates – Otter Help Center](https://help.otter.ai/hc/en-us/articles/31402572907415-Custom-Meeting-Type-Templates)
- [Otter Meeting Types blog post](https://otter.ai/blog/otter-meeting-types-get-smarter-tailored-summaries-for-every-meeting)
- [Automatically add Otter Notetaker to your meetings](https://help.otter.ai/hc/en-us/articles/13674910923671-Automatically-add-Otter-Notetaker-to-your-meetings)
- [Otter.ai Integrations – Calendar](https://otter.ai/integrations/calendar)
- [Otter.ai Pricing (Claap)](https://www.claap.io/blog/otter-pricing)
- [Fireflies Speaker Diarization Technical Deep Dive](https://workgpt.com/en/faq/fireflies-speaker-diarization-how-it-works)
- [Best Speaker Diarization Tools 2026 (VexaScribe)](https://vexascribe.com/compare/best-speaker-diarization-tools)
- [Fireflies Pricing & Plans](https://fireflies.ai/pricing)
- [AI Credits Pricing and Overview – Fireflies](https://guide.fireflies.ai/articles/2114151875-learn-about-ai-credits)
- [How Fireflies joins and records your meetings – FAQs](https://guide.fireflies.ai/articles/9554534786-how-fireflies-joins-and-records-your-meetings-faqs)
- [How to Invite Fireflies to Meetings](https://guide.fireflies.ai/articles/4335268657-how-to-invite-fireflies-to-meetings)
- [Fathom Quick Start Guide](https://help.fathom.video/en/articles/276608)
- [Fathom Integrations](https://www.fathom.ai/integrations)
- [Fathom Pricing](https://www.fathom.ai/pricing)
- [Fathom Pricing 2026 (get-alfred.ai)](https://get-alfred.ai/blog/fathom-pricing)
- [Grain Bot Capture](https://support.grain.com/en/articles/13467724-bot-capture)
- [Grain AI](https://grain.com/ai)
- [Grain Meeting Recorder Review 2026](https://workgpt.com/en/app-reviews/grain-meeting-recorder)
- [pyannote/speaker-diarization-3.1 – Hugging Face](https://huggingface.co/pyannote/speaker-diarization-3.1)
- [pyannote-community/speaker-diarization-community-1 README](https://huggingface.co/pyannote-community/speaker-diarization-community-1/blob/main/README.md)
- [pyannote.audio Guide 2026 (VexaScribe)](https://vexascribe.com/pyannote-audio)
- [Speaker Diarization With Pyannote In Production (ForaSoft)](https://www.forasoft.com/learn/ai-for-video-engineering/articles-ai/pyannote-speaker-diarization-production)
- [MahmoudAshraf97/whisper-diarization – GitHub](https://github.com/MahmoudAshraf97/whisper-diarization)
- [mediar-ai/screenpipe – GitHub](https://github.com/mediar-ai/screenpipe)
- [The Dispatch Report: mediar-ai/screenpipe analysis](https://thedispatch.ai/reports/2495/)

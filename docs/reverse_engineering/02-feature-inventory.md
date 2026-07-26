# Feature Inventory — Implemented vs. Stub vs. Not Present

Legend: **Implemented** = working code path in this repo · **Stub** = UI/config/type exists but no working behavior · **Not present** = zero code, README/marketing claim only.

| Feature | Status | Source module | Tier (per README) | Notes |
|---|---|---|---|---|
| Mic + system audio capture, mixing, ducking | Implemented | `audio/`, `audio_v2/` | Community | Two parallel implementations mid-migration |
| Voice Activity Detection (VAD) | Implemented | `audio/pipeline.rs` | Community | Filters ~70% of audio before Whisper |
| Whisper transcription (local, GPU-accel) | Implemented | `whisper_engine/` | Community | Metal/CoreML/CUDA/Vulkan/HIP |
| Parakeet transcription (ONNX, alt. engine) | Implemented | `parakeet_engine/` | Community | User-selectable vs. Whisper |
| Import audio + retranscription | Implemented (Beta flag) | `audio/import.rs`, `audio/retranscription.rs` | Community | Gated by `betaFeatures.importAndRetranscribe`, default ON |
| Summarization w/ prompt templates | Implemented | `summary/`, `summary/templates/` | Community | Only 2 built-in templates: daily standup, standard meeting |
| Multi-LLM support (Ollama/Claude/Groq/OpenRouter/OpenAI) | Implemented | `ollama/` `anthropic/` `groq/` `openrouter/` `openai/` | Community | All optional, user-configured |
| Local meeting/transcript storage | Implemented | `database/` (SQLite) | Community | No sync/remote DB |
| Rich text notes editor (BlockNote) | Implemented | `components/BlockNoteEditor/` | Community | Legacy Remirror/TipTap deps still present |
| System notifications / reminders | Implemented | `notifications/settings.rs` | Community | "meeting_reminders" setting exists but has no calendar to read from |
| Product analytics (PostHog) | Implemented | `analytics/analytics.rs` | Community | Sanitizes sensitive fields, opt-out available |
| Onboarding flow | Implemented | `onboarding.rs`, `components/onboarding/` | Community | |
| Auto-update | Implemented | `tauri-plugin-updater` | Community | Against GitHub Releases |
| Enhanced transcription accuracy | Not present | — | **Pro** ($10/user/mo, live per `meetily.ai`) | No concrete differentiator found in code; likely refers to model/pipeline tuning not in this repo |
| Custom summary templates (expanded library) | Stub / partial | `summary/templates/loader.rs` | **Pro** ($10/user/mo, live per `meetily.ai`) | Loader supports user-authored custom templates already; Pro ships a bigger curated library |
| Advanced export (PDF, DOCX) | Not present | — | **Pro** ($10/user/mo, live per `meetily.ai`) | Frontend only does markdown; no `docx`/`pdf` generation library in `frontend/package.json` |
| Auto-detect & join meetings | Not present | — | **Pro** ($10/user/mo, live per `meetily.ai`) | Zero code hits for window detection / auto-join |
| Speaker identification / diarization | Not present | — | **Pro** ($10/user/mo, live per `meetily.ai`) | Marked "Coming Soon" in repo `README.md`, but `meetily.ai`'s current marketing site advertises it as shipped and live ("labels every voice in your transcript — live as you record and on imported audio") — the README is stale on this point. Only local trace of prior diarization work is the archived `backend/whisper-custom/server/README.md` (legacy, unsupported). |
| Chat with meetings | Not present | — | **Pro** (README, "Coming Soon"; not confirmed live on `meetily.ai`) | No RAG/chat code over transcripts anywhere |
| Calendar integration | Not present | — | **Pro** (README, "Coming Soon"; not confirmed live on `meetily.ai`) | Only a decorative `Calendar` icon in Sidebar/notes UI |
| Self-hosted / enterprise deployment, GDPR tooling, priority support | Not present (business terms) | — | **Enterprise** (separate tier per `meetily.ai`: admin dashboard, centralized storage, compliance frameworks) | Not a code feature — licensing/support-contract language |

## Reading this table

Everything under "Community" is real and can be treated as ground truth for `01-current-architecture.md`. The "Pro" column no longer reflects only the repo's `README.md` — cross-checking the live `meetily.ai` marketing site (mid-2026) shows the commercial Pro tier ($10/user/month) is further along than the README lets on: **speaker diarization is now marketed as shipped and live**, not "Coming Soon." Chat-with-meetings and calendar integration remain unconfirmed as live (still "Coming Soon" per README, and the site content checked didn't confirm otherwise). Advanced export and auto-detect/join have no code in this repo either way. Custom summary templates are only partially unbuilt — the underlying loader already supports user-authored templates, so "Pro" there most likely means a bigger *curated library*, not new capability.

**This does not change the rewrite's approach, only its ambition**: none of these six features exist as working implementations *in this open-source codebase* to reverse-engineer against, so all six remain greenfield designs informed by competitors (`03-pro-feature-research.md`) rather than extractions from an existing system. What changes is the goal stated in `00-overview.md`: the project isn't just replicating Community Edition — it's building and **open-sourcing the entire Pro feature set** (including the now-confirmed-live diarization), removing Meetily's paywall on all of it rather than leaving any feature commercial-only.

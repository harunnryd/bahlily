# Feature Notes

Target feature set, informed by general research into how meeting-assistant products (Otter.ai, Fireflies.ai, Fathom, Grain) approach the same problems, and the open-source building blocks we plan to build on.

## Speaker diarization

Products in this space typically run diarization as a post-processing pass rather than live: transcribe, then re-analyze the full audio with complete context to separate speakers, and let users label a speaker once, then auto-recognize them in future recordings via a persistent voice embedding. Several also lean on meeting-platform participant metadata (pulling real names from the call roster) as the primary signal, falling back to pure acoustic clustering only for audio-only sources.

**Approach**: `pyannote.audio` (segmentation + clustering) as the acoustic method, run on the full pre-mixed recording after it ends. Store per-utterance speaker-cluster IDs and timestamps, merge with word-level ASR timestamps to produce "Speaker N: text" segments, and persist a lightweight voice embedding per named speaker so future sessions can auto-match without re-labeling.

**Known limitations**: pyannote's pretrained pipelines require accepting per-model terms via Hugging Face before first use. Real-world accuracy (noisy multi-speaker audio, cross-talk, laptop mics, system-audio bleed) will be meaningfully worse than clean-benchmark numbers. It's a second model pass, roughly doubling inference cost/time per meeting.

## Chat with meetings

The common pattern is retrieval-augmented chat over a transcript corpus — ask questions about one meeting or across meeting history conversationally.

**Approach**: LangChain + a local embedding model (Ollama-hosted or `sentence-transformers`) + a lightweight local vector store (`chromadb` or `sqlite-vec`). Chunk on utterance/diarization boundaries rather than fixed-size windows (naive chunking splits mid-sentence and hurts retrieval). Worth considering an MCP tool surface for transcript search alongside the chat UI, since the same RAG infrastructure serves both — bound to localhost with auth if exposed.

**Known limitations**: this is one of the more compute-expensive features to run continuously; for a local-first product that cost lands on the user's own hardware rather than a vendor's margin, which is a reasonable trade.

## Calendar integration and auto-start

The common industry pattern is a cloud-hosted bot that joins the call as a visible participant, triggered off a calendar-synced meeting link, and inherits the platform's participant roster for speaker labeling. That's a materially different, more centralized architecture than a local-first product should adopt — it requires operating bot infrastructure and sends meeting audio off the user's machine.

**Approach**: read the user's calendar (Google Calendar API / Microsoft Graph API), detect a meeting-platform link in the event body, and prompt (or auto-start, per user preference) the app's own local recorder a configurable number of minutes before the meeting — no bot joins the call, audio never leaves the device. The trade-off is not automatically getting participant-name metadata the way a true meeting bot would; diarization quality has to carry more of that weight.

**Known limitations**: CalDAV support (for non-Google/Microsoft calendars) needs a permissively-licensed client — some popular CalDAV libraries are GPL-licensed, which doesn't fit a permissive-licensing goal; isolate or avoid as needed.

## Advanced export (PDF, DOCX, Markdown)

What matters most is exporting *structured* summaries (headings, action items, speaker-attributed quotes) rather than flattened transcript text — the export layer should consume the same structured-summary schema the LLM produces, not a separate flattening step.

**Approach**: one canonical structured-summary schema (validated, e.g. via Pydantic), three renderers off it — Markdown (direct template), DOCX (`python-docx`), PDF (render to HTML via a small template, then convert with `weasyprint` or `reportlab`). Keeping all three in sync automatically when the schema changes beats maintaining three independent generators.

**Known limitations**: verify the exact license of whichever HTML-to-PDF library is chosen (some have shifted terms across versions); keep templates intentionally simple rather than chasing pixel-perfect parity with word processors.

## Custom summary templates

Fundamentally a prompt-engineering and structured-output problem, not a new-library problem. Products differentiate here mostly through a curated library of good prompts per use case (sales call, 1:1, interview) rather than novel technology.

**Approach**: model each template as a stored prompt (system instructions + the structured-summary schema, plus template-specific extra fields) with optional few-shot examples, using LangChain's prompt-template abstractions and a validated structured-output path (Pydantic + retries, or grammar-constrained decoding for local models). User-authored custom templates fall out for free once this exists. Ship a handful of well-tested built-in templates rather than a large, thin library.

## Enhanced transcription accuracy

Decomposes into a few concrete levers rather than one new capability: offering larger model tiers as a default (`medium`/`large-v3` vs `base`/`small`), custom-vocabulary/prompt-biasing for domain jargon, and treating diarization/speaker-labeling quality as part of what users perceive as "accuracy" — garbled speaker attribution reads as bad transcription even when word-level ASR is fine.

**Known limitations**: larger models cost proportionally more compute; pair any model-tier increase with VAD filtering, since VAD reduces the silence/noise segments most prone to Whisper's known hallucination failure mode.

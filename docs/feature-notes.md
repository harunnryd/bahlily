# Feature Notes

Target feature set, informed by general research into how meeting-assistant products (Otter.ai, Fireflies.ai, Fathom, Grain) approach the same problems, and the open-source building blocks we plan to build on.

## Speaker diarization

Products in this space typically run diarization as a post-processing pass rather than live. They transcribe first, then re-analyze the full audio with complete context to separate speakers, and let users label a speaker once so future recordings auto-recognize them via a persistent voice embedding. Several also lean on meeting-platform participant metadata, pulling real names from the call roster, falling back to pure acoustic clustering only for audio-only sources.

Our approach: `pyannote.audio` for segmentation and clustering, run on the full pre-mixed recording after it ends. Store per-utterance speaker-cluster IDs and timestamps, merge with word-level ASR timestamps to produce "Speaker N: text" segments, and keep a lightweight voice embedding per named speaker so future sessions can auto-match without re-labeling.

Worth knowing going in: pyannote's pretrained pipelines require accepting per-model terms on Hugging Face before first use. Real-world accuracy on noisy multi-speaker audio, cross-talk, laptop mics, system-audio bleed will be meaningfully worse than clean-benchmark numbers suggest. It's also a second model pass, roughly doubling inference cost and time per meeting.

## Chat with meetings

The common pattern is retrieval-augmented chat over a transcript corpus: ask questions about one meeting or across meeting history, conversationally.

Our approach: LangChain plus a local embedding model (Ollama-hosted, or `sentence-transformers`) plus a lightweight local vector store (`chromadb` or `sqlite-vec`). Chunk on utterance/diarization boundaries rather than fixed-size windows, since naive chunking splits mid-sentence and hurts retrieval. Also worth considering an MCP tool surface for transcript search alongside the chat UI, since the same RAG infrastructure serves both; bind it to localhost with auth if it's exposed at all.

This is one of the more compute-expensive features to run continuously. For a local-first product that cost lands on the user's own hardware rather than a vendor's margin, which is a reasonable trade.

## Calendar integration and auto-start

The common industry pattern here is a cloud-hosted bot that joins the call as a visible participant, triggered off a calendar-synced meeting link, and inherits the platform's participant roster for speaker labeling. That's a materially different, more centralized architecture than a local-first product should adopt. It requires operating bot infrastructure and sends meeting audio off the user's machine.

Our approach: read the user's calendar through the Google Calendar API or Microsoft Graph API, detect a meeting-platform link in the event body, and prompt (or auto-start, per user preference) the app's own local recorder some configurable number of minutes before the meeting starts. No bot joins the call, and audio never leaves the device. The trade-off is not getting participant-name metadata automatically the way a true meeting bot would, so diarization quality has to carry more of that weight.

CalDAV support for non-Google/Microsoft calendars needs a permissively-licensed client. Some popular CalDAV libraries are GPL-licensed, which doesn't fit a permissive-licensing goal, so we'd isolate or avoid that dependency as needed.

## Advanced export (PDF, DOCX, Markdown)

What matters most is exporting structured summaries (headings, action items, speaker-attributed quotes) rather than flattened transcript text. The export layer should consume the same structured-summary schema the LLM produces, not run a separate flattening step.

Our approach: one canonical structured-summary schema, validated with Pydantic, and three renderers off it. Markdown is a direct template. DOCX goes through `python-docx`. PDF renders to HTML via a small template, then converts with `weasyprint` or `reportlab`. Keeping all three in sync automatically when the schema changes beats maintaining three independent generators.

Check the exact license of whichever HTML-to-PDF library gets chosen, since some have shifted terms across versions. Keep templates intentionally simple rather than chasing pixel-perfect parity with word processors.

## Custom summary templates

This is fundamentally a prompt-engineering and structured-output problem, not a new-library problem. Products differentiate here mostly through a curated library of good prompts per use case (sales call, one-on-one, interview) rather than novel technology.

Our approach: model each template as a stored prompt (system instructions plus the structured-summary schema, plus template-specific extra fields) with optional few-shot examples, using LangChain's prompt-template abstractions and a validated structured-output path (Pydantic with retries, or grammar-constrained decoding for local models). User-authored custom templates fall out for free once this exists. Ship a handful of well-tested built-in templates rather than a large, thin library.

## Enhanced transcription accuracy

This decomposes into a few concrete levers rather than one new capability: offering larger model tiers as a default (medium/large-v3 instead of base/small), custom-vocabulary or prompt-biasing for domain jargon, and treating diarization/speaker-labeling quality as part of what users perceive as "accuracy." Garbled speaker attribution reads as bad transcription even when the word-level ASR is fine.

Larger models cost proportionally more compute, so pair any model-tier increase with VAD filtering. VAD reduces the silence and noise segments most prone to Whisper's known hallucination failure mode.

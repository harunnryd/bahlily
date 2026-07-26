# Build Roadmap

Ordered by leverage (value delivered) against risk, not strict dependency order.

## Phase 0: audio core and desktop shell

Build simultaneous mic and system capture, real-time mixing/ducking, and inline VAD gating in Rust (`shell/audio-core/`), plus the minimal Tauri shell: window, tray, single-instance enforcement, updater. This is the highest-risk, most platform-specific piece, so get it working and stable on macOS and Windows before building anything downstream of it.

## Phase 1: orchestration service (summarization)

Stand up the Python orchestration service. LangChain/LangGraph-based prompt templating, structured-output summaries, a multi-provider LLM client (Ollama, Anthropic, Groq, OpenRouter, OpenAI), with DeepEval wired in for automated summary-quality evaluation. No OS dependency, no real-time constraint. This is the safest first service to get right, and it's where LangGraph and DeepEval deliver value immediately.

## Phase 2: transcription service

Stand up Whisper (`faster-whisper`, or whisper.cpp/MLX on Apple Silicon) and Parakeet (`onnxruntime`/`onnx-asr`), fed by the audio core over local IPC. Validate WER and latency on real recorded meetings, per platform, since Apple Silicon needs its own path separate from CUDA.

## Phase 3: storage

Pick a single authoritative SQLite owner and get meeting/transcript/summary persistence solid before building features on top of it. Every other service depends on this being correct.

## Phase 4: feature build-out

Roughly in this order:

1. Custom summary templates. No new infrastructure needed once Phase 1 exists, so this ships value fast.
2. Advanced export (Markdown/DOCX/PDF), which depends on Phase 1's structured-summary schema.
3. Chat with meetings, which depends on Phases 1 through 3 (the LLM service, transcripts, and stable storage). Add the RAG/vector-store layer here.
4. Speaker diarization, which depends on Phase 2's segment timestamps. Budget real GPU/compute headroom, since it roughly doubles inference cost per meeting.
5. Calendar integration and local auto-start, mostly independent of the other services and fine to build in parallel with 1 through 4. It's sequenced last here mainly because it needs its own UX pass around permission prompts and auto-start opt-in.

## What stays out of scope until Phase 4 is done

No sync, multi-device, or self-hosted-server component until the full local pipeline works end-to-end for a single user. Building a sync layer before the local data model is stable means designing conflict resolution against a schema that's still changing underneath it.

## Suggested repo layout

```
bahlily/
├── shell/
│   └── audio-core/
├── services/
│   ├── transcription/
│   ├── orchestration/
│   ├── chat/
│   ├── calendar/
│   ├── export/
│   └── storage/
└── frontend/
```

`shell/` is the Tauri Rust shell (window, tray, updater, notifications); `audio-core/` is the one Rust business-logic module, handling capture, mixing, and VAD. Under `services/`: `transcription` wraps `faster-whisper`, `onnx-asr`, and `pyannote`; `orchestration` wraps LangChain/LangGraph and the multi-provider LLM client, with DeepEval; `chat` is RAG plus an optional MCP surface; `calendar` wraps the Google Calendar/MS Graph APIs and `icalendar`; `export` wraps `python-docx` and `weasyprint`/`reportlab`; `storage` is the single SQLite owner. `frontend/` is the Next.js/React UI.

Each `services/*` directory should be independently runnable, with its own `pyproject.toml`/entrypoint and its own tests. Someone should be able to work on one service without standing up the rest of the stack.

## Verification per phase

Phase 0: capture and mix a real meeting on each target platform, checking for dropped samples, drift, and clipping under load.

Phase 1: compare summarization output across providers on the same transcript, and once DeepEval is wired in, run it automatically.

Phase 2: run a WER and latency benchmark on a fixed set of real recorded meetings, per platform (macOS Metal, NVIDIA CUDA, CPU-only).

Phase 3: spot-check data integrity on a realistic dataset before treating storage as stable, and have a rollback path ready for any future schema change.

Phase 4 features: ship each behind its own settings toggle, so newer, less-proven features can be disabled independently of the stable core.

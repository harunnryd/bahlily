# Security

Bahlily processes meeting audio, transcripts, and summaries locally by default. That local-first design is a security property worth protecting, not just a performance choice, so treat anything that could leak recorded audio or transcript data off-device without explicit user consent as a high-severity issue.

## Reporting a vulnerability

Don't open a public issue for a security problem. Instead, open a private security advisory on this repository (GitHub's "Report a vulnerability" under the Security tab) or email the maintainers directly once a contact address is published. Include what you found, how to reproduce it, and what you think the impact is.

## Scope

In scope: anything in this repo, including the desktop shell, the audio-core crate, all Python services, and the frontend once it exists. Particular areas of concern:

- Any code path that sends audio, transcript, or summary content to a network destination the user didn't explicitly configure (an LLM provider, a calendar API, a future sync service).
- Local service endpoints (the Python sidecars) that aren't bound to localhost, or that accept requests without the intended auth.
- Dependencies with known CVEs, especially anything handling untrusted input (imported audio files, calendar event data, downloaded models).

Out of scope: issues in third-party services a user explicitly configures (an LLM provider's own infrastructure, for instance) that aren't caused by how this project talks to them.

## Response

We'll acknowledge a report as soon as we can and aim to have a fix or mitigation plan before any public disclosure.

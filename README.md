# AI Moderator

A semantic content moderation pipeline for AI-powered chat, built with React and Vite.

Every message passes through a 3-stage pipeline:

```
User input → [Classifier] → AI assistant → [Classifier] → Response
```

1. **Input classifier** — checks the user's message before the AI sees it
2. **AI assistant** — generates a response under a constrained system prompt
3. **Output classifier** — checks the response before the user sees it

The classifier understands meaning, not just keywords — it catches jailbreak attempts, hypothetical framings, topic pivoting, and indirect references.

## Modes

- **Whitelist** — school assistant mode; only allows configured academic topics
- **Blacklist** — general mode; blocks specific topics

Switch between modes using `VITE_MODE` in `.env`:
- `teacher` — full config panel (topic lists, custom rules, audit log, forum checker)
- `student` — chat only, no configuration exposed

## Features

- **Chat moderation** — 3-stage pipeline with per-message audit trail, exportable as CSV
- **Forum checker** — paste or load `.txt`/`.json` forum posts for batch classification, exportable as CSV
- **Per-classroom config** — whitelist, blacklist, and custom instructions set via environment variables at deploy time

## Getting started

### Prerequisites

- Node.js 18+
- An [Anthropic API key](https://console.anthropic.com)

### Setup

```bash
npm install
cp .env.example .env
# Fill in your API key and classroom config in .env
npm run dev
```

The API key is injected server-side by the Vite proxy and never exposed to the browser.

## Project structure

```
src/
└── App.jsx          # Full application — pipeline logic + UI
test-forums/         # Sample forum posts for testing (.txt and .json)
```

All moderation logic lives in `App.jsx`. The `callClaude()` function is the only model-specific code — swap the endpoint and headers to use any OpenAI-compatible API.

## Planned: backend extension

The current setup requires the teacher to run the server locally. A backend is planned to enable:

- **Persistent session logging** — every message and classifier verdict stored in a database, accessible to the teacher
- **Multi-student support** — logs filterable by student, date, and session
- **Always-on deployment** — no local server required, deployable to Render, Railway, or a cheap VPS (~€4/month)
- **LLM benchmarking** — structured logs to compare moderation accuracy across different models

Stack: Express + SQLite (with a path to Postgres/Turso for hosted deployments).

## Roadmap

- [x] Teacher/student mode switching
- [x] Per-classroom configuration via environment variables
- [x] Forum post batch classifier with CSV export
- [x] Chat audit log with CSV export
- [ ] Additional LLM backends (GPT-4, Mistral, etc.)
- [ ] Moderation accuracy benchmarking across models
- [ ] Backend with persistent logging and teacher dashboard

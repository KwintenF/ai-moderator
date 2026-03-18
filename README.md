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

Both the topic lists and custom moderation rules are configurable from the sidebar.

## Getting started

### Prerequisites

- Node.js 18+
- An [Anthropic API key](https://console.anthropic.com)

### Setup

```bash
npm install
cp .env.example .env
# Add your API key to .env
npm run dev
```

## Project structure

```
src/
└── App.jsx          # Full application — pipeline logic + UI
```

All moderation logic lives in `App.jsx`. The `callClaude()` function is the only model-specific code — swap the endpoint and headers to use any OpenAI-compatible API.

## Roadmap

- [ ] Student-facing view (chat only, no config panel)
- [ ] Per-classroom configuration via environment variables
- [ ] Support for additional LLM backends (GPT-4, Mistral, etc.)
- [ ] Moderation accuracy benchmarking across models

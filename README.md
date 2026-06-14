# Chat + Ollama + A1111 WebUI

An Open WebUI–style chat interface that wires together a local **Ollama** LLM and
**A1111 (Stable Diffusion WebUI)**. The model decides on its own when to generate an
image (via native function-calling, a directive protocol on the Claude engine, or
structured output on the Codex engine), and the result is rendered inline in the
conversation. You can also switch the AI engine between **Ollama**, your logged-in
**Claude CLI**, and your logged-in **OpenAI Codex CLI**.

![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)
![chat: ollama](https://img.shields.io/badge/chat-ollama-blue)
![chat: claude--cli](https://img.shields.io/badge/chat-claude--cli-orange)
![chat: codex--cli](https://img.shields.io/badge/chat-codex--cli-black)
![image: A1111](https://img.shields.io/badge/image-A1111-green)

> **Built by a human and AI, together.** This project was designed and implemented
> collaboratively by a human developer and **Anthropic's Claude (via Claude Code)** —
> from architecture and code to end-to-end testing. See [Development](#development).

---

## Features

- 🔀 **Switchable AI engine** — toggle in the top bar between **Ollama** (local models),
  **Claude CLI** (your logged-in Claude Code), and **OpenAI Codex CLI** (your logged-in
  `codex`). All three can generate images on their own (Ollama via native tools, Claude via
  a directive protocol, Codex via structured output) and see images (vision).
- 💬 **Multi-conversation chat** — streaming replies, Markdown / code highlighting,
  collapsible reasoning (thinking) blocks.
- 🎨 **Autonomous image generation** — the model calls `generate_image` (txt2img) →
  A1111 renders → the image is embedded inline (zoom / download / view parameters).
- 🖼️ **Image upload (vision)** — attach or paste an image and ask a vision model about it.
- 🖌️ **img2img redraw** — attach an image and ask the model to restyle/modify it
  (`edit_image`); any generated image also has a "redraw from this" button.
- 🌐 **Web search** — when enabled, the model can call `web_search` / `fetch_url` to
  look things up and read pages, with clickable sources (DuckDuckGo by default, no key;
  SearXNG optional). *(Ollama engine.)*
- 🧠 **Context management** — adjustable `num_ctx` (unlock a model's full context), a
  live **usage meter** (used / limit) in the top bar, and one-click **compact** that
  summarizes older messages while keeping the latest exchange.
- 👁/🔧 The model dropdown marks which models can **see images** (vision) and **use tools**.
- 📄 **PNG Info (generation parameters)** — read the embedded SD parameters
  (prompt / negative / seed / sampler / size / model) from a generated **or uploaded**
  image, with one-click **"apply to settings"** to reproduce it. The model can also call
  `read_png_info` to answer "how was this image made?". *(Only works on images that still
  carry A1111/ComfyUI metadata — screenshots or recompressed images won't have any.)*
- 📊 **Live progress bar** — percentage, step count, and a live preview during generation.
- 📂 **Selectable image storage location** — pick the output folder with a server-side
  directory picker (browse / type a path / create a folder); old images still resolve
  after you switch.
- 🔌 **Configurable service sources** — point Ollama / A1111 at an "API URL" or a
  "Docker container", with a "Test connection" button (auto-lists containers when the
  docker socket is reachable).
- 🌐 **Multilingual UI** — Traditional Chinese / Simplified Chinese / English / 日本語 /
  한국어, switchable live.
- ⚙️ **Settings panel** — SD checkpoint, sampler, width/height, steps, CFG, seed,
  denoising strength, default negative prompt, system prompt.
- 💾 **Server-side persistence** — conversations (SQLite) and settings are stored on the
  backend for cross-device, long-term history, with a `localStorage` cache for speed;
  images live on the backend and only their URLs are stored.
- ⌨️ `/image <prompt>` generates directly, skipping the LLM (a manual fallback).

## Requirements

- **Ollama** at `localhost:11434` with at least one **tool-capable** model
  (e.g. `qwen3.5:35b`, the `qwen3` family).
- **A1111** at `localhost:7860`, started with `--api`.
- For the **Claude CLI engine** (optional): the `claude` CLI installed and logged in.
  The Docker image installs it for you; you only mount your credentials (see below).
- For the **Codex CLI engine** (optional): the `codex` CLI logged in on the host. Its whole
  `~/.codex` (static binary + credentials + model cache) is mounted into the container — no
  in-image install needed (see below).
- Python 3.10+ and Node 18+ for local development.

> Ollama and A1111 can run anywhere as long as their ports are reachable; this WebUI
> connects out to them.

## Quick start (Docker Compose, recommended)

Ollama and A1111 run in their **own** containers with ports published to the host
(11434 / 7860). This compose file runs only the WebUI itself (backend + nginx frontend)
and reaches those two services via `host.docker.internal`:

```bash
docker compose up -d --build
```

Open **http://localhost:5273**. Generated images are bind-mounted to `backend/data/`
on the host, so they survive restarts.

```bash
docker compose logs -f      # follow logs
docker compose down         # stop
```

Optional: copy `.env.example` → `.env` to set `WEBUI_PORT`, override
`OLLAMA_URL` / `A1111_URL`, or enable the Claude (`CLAUDE_CREDS_DIR`) / Codex
(`CODEX_CREDS_DIR`) engines.

> **Linux note:** the backend uses `extra_hosts: host.docker.internal:host-gateway`
> to reach the host (requires Docker 20.10+). To instead put this WebUI on the same
> docker network as Ollama/A1111 and use service names, see [Advanced](#advanced-same-docker-network).

## Local development (without Docker)

```bash
./run.sh
```

The first run creates a Python venv, installs dependencies, runs `npm install`, then starts:

- Frontend → http://127.0.0.1:5273 (Vite dev with HMR)
- Backend → http://127.0.0.1:8000

### Manual start

```bash
# Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

## Usage

1. Pick a model marked 🔧 (tool-capable) from the top dropdown.
2. Chat normally; when you want a picture, say e.g. *"draw a shiba inu wearing sunglasses"*
   and the model generates it automatically.
3. **See an image:** attach (or paste) an image with the 🖼️ button, then ask
   "what's in this image?" → a vision model answers.
4. **Redraw:** attach an image and say *"make this watercolor"* → the model runs img2img;
   or click 🖌️ "redraw from this" on any generated image.
5. **Web search:** turn on 🌐 "Web search" in the top bar, then ask something current →
   the model searches, reads pages, and cites clickable sources. *(Ollama engine.)*
6. **PNG Info:** click 📄 on a generated image, or on an uploaded thumbnail, to read its
   embedded generation parameters; "apply to settings" reproduces them. You can also just
   ask the model "what prompt made this?".
7. Generation shows a **progress bar** with a live preview; click an image to zoom, or use
   the top-right buttons to download / view parameters.
8. The ⚙️ gear opens settings: SD model & parameters, denoising strength, system prompt,
   image storage location, service sources, web provider, and language.
9. You can also type `/image 1girl, solar punk city, masterpiece` to generate directly.

> **Storage location in Docker mode:** the picker browses the **backend container's**
> filesystem. By default images go to the bind-mounted `backend/data/images`. To store
> them elsewhere persistently, mount another volume into the container and select it.

> **vision vs img2img:** with an attached image the model can both *see* it (if it
> supports vision) and *redraw* it (img2img) — it decides based on what you ask.
> Non-vision models can still redraw (img2img is handled by A1111 and doesn't require the
> model to see the image).

> **Tip:** these are SDXL / Pony / Illustrious anime checkpoints — comma-separated English
> danbooru-style tags work best. The system prompt already nudges the model to write them.

## AI engines: Ollama / Claude CLI / Codex CLI

The top-bar selector switches the **AI engine**:

- **Ollama** — local models with native function-calling for image generation (default).
- **Claude CLI** — uses your **already-logged-in `claude` (Claude Code)**. Because the CLI
  is launched with `--tools ""` (all built-in tools disabled, so Claude never touches the
  backend filesystem), image generation uses a **directive protocol** instead: the system
  prompt asks Claude to emit a `[[GENIMG]]{…}[[/GENIMG]]` marker in its text; the backend
  parses it out of the stream, runs A1111, and replaces it with the rendered image (the
  marker is never shown to you). Vision (base64 image input) and img2img redraw are
  supported too.

### Enabling Claude CLI (Docker)

The CLI binary is installed into the image by `backend/Dockerfile`; you only need to mount
your **logged-in credentials**:

1. Make sure `claude` is logged in on the host (run `claude` once and complete login).
2. Copy `.env.example` → `.env` and set an **absolute path** (under `sudo`, `$HOME`
   becomes `/root`, so always use an absolute path):
   ```bash
   CLAUDE_CREDS_DIR=/home/youruser/.claude
   ```
3. `docker compose up -d --build`, then switch the engine to **Claude CLI** in the top bar.

> Without `CLAUDE_CREDS_DIR`, an empty directory is mounted and the Claude engine shows as
> "unavailable" (Ollama is unaffected). The credentials directory is mounted **read-write**
> so the CLI can refresh its token. Use `CLAUDE_MODELS` to customize the model aliases in
> the dropdown (default `sonnet,opus,haiku`).

### Enabling Claude CLI (local dev, no Docker)

If the backend runs directly on the host and `claude` is on `PATH` and logged in,
**no configuration is needed** — `/api/engines` auto-detects it and the option appears.

### OpenAI Codex CLI

Uses your **logged-in `codex` (OpenAI Codex CLI)**. It's launched with
`codex exec --json -s read-only --ephemeral`, the assistant message is parsed from the
JSONL stream, and attachments are passed via `-i` (vision). For image generation, Codex
(a coding agent that won't reliably emit a free-text marker) is driven with **structured
output** (`--output-schema`): when the image tool is on, the model returns
`{reply, image_prompt, edit_attached_image}`, and a non-empty `image_prompt` triggers
A1111 (txt2img, or img2img when an image is attached). The model dropdown is populated
automatically from the models your Codex account supports (read from
`~/.codex/models_cache.json`). You can also type `/image <prompt>` on any engine.

**Docker:** the `codex` binary is a static executable, so the whole `~/.codex` (binary +
auth + model cache) is mounted into the container — set an **absolute path** in `.env`:

```bash
CODEX_CREDS_DIR=/home/youruser/.codex
```

Then `docker compose up -d --build` and pick **Codex CLI** in the top bar. If Codex errors
about sandbox/landlock inside the container, set `CODEX_SANDBOX_MODE=bypass` in `.env`
(the container is already the isolation boundary). **Local dev:** if `codex` is on `PATH`
and logged in, it's auto-detected — no config needed.

## Architecture

```
Frontend (React/Vite)  ──/api proxy──▶  Backend (FastAPI)
                                         ├─▶ Ollama      /api/chat (stream + tools + vision)
                                         ├─▶ Claude CLI  claude -p (stream-json subprocess)
                                         ├─▶ Codex CLI   codex exec --json (subprocess)
                                         └─▶ A1111       /sdapi/v1/{txt2img,img2img,progress,png-info}
Images are saved to backend/data/images/ and served by the backend at /images/
```

**Agentic loop** (`backend/chat.py`): stream the engine → detect `tool_calls`
(`generate_image`=txt2img / `edit_image`=img2img) — or, on Claude, parse `[[GENIMG]]`
directives — → poll `/progress` while generating → feed the result back → the model
continues its text reply, all pushed to the frontend over SSE. With an attached image,
the last user message's image is used as the img2img init image; non-vision models have
their `images` stripped automatically.

### Key files

| Path | Description |
|------|-------------|
| `backend/main.py` | FastAPI routes, SSE, static images, engine selection |
| `backend/chat.py` | agentic tool loop + Claude directive parser |
| `backend/tools.py` | tool schemas: `generate_image` / `edit_image` / `read_png_info` / `web_search` / `fetch_url` |
| `backend/ollama_client.py` | Ollama engine (chat stream, models, capabilities, context length) |
| `backend/claude_client.py` | Claude CLI engine (subprocess `claude -p` stream-json; images via directives) |
| `backend/codex_client.py` | OpenAI Codex CLI engine (subprocess `codex exec --json`; chat + vision via `-i`) |
| `backend/a1111_client.py` | A1111: txt2img / img2img / progress / models / samplers / png-info |
| `backend/web_tools.py` | web search (DuckDuckGo/SearXNG) + page extraction (with SSRF guard) |
| `backend/settings_store.py` | persisted settings: image dir + service sources + web provider |
| `backend/docker_probe.py` | best-effort container listing via the docker socket |
| `frontend/src/store/chat.js` | zustand state + streaming coordination + persistence |
| `frontend/src/lib/api.js` | SSE parsing, storage/browse/sources/engine calls |
| `frontend/src/i18n.js` | 5-language dictionary + `useT()` hook |
| `frontend/src/components/` | UI components (TopBar, Composer, Message, ImageBlock, PngInfoModal, pickers, panels) |

## Configuration

Copy `.env.example` and override via environment variables (addresses, default model,
timeouts, Claude / Codex credentials). In dev mode the frontend proxy target is in
`frontend/vite.config.js` (`BACKEND_URL`, default `127.0.0.1:8000`); in Docker mode
`frontend/nginx.conf` proxies `/api` and `/images` to `backend:8000`.

### Advanced: same docker network

To put this WebUI on the same docker network as Ollama/A1111 and use service names
(instead of `host.docker.internal`), add the matching `networks:` to the `backend`
service in `docker-compose.yml` and set `OLLAMA_URL` / `A1111_URL` to the containers'
names and **in-container** ports:

```yaml
  backend:
    environment:
      OLLAMA_URL: http://ollama:11434
      A1111_URL: http://a1111:7860
    networks: [default, ai_net]
networks:
  ai_net:
    external: true            # the existing network where ollama/A1111 live
```

## Docker files

| Path | Description |
|------|-------------|
| `docker-compose.yml` | two services: backend (uvicorn) + frontend (nginx) |
| `backend/Dockerfile` | python:3.12-slim, installs the `claude` CLI, runs uvicorn |
| `frontend/Dockerfile` | multi-stage: node build → nginx serves static files |
| `frontend/nginx.conf` | SPA + proxy `/api` (buffering off for SSE) + `/images` |

## Notes

- Technical parameters (steps / sampler / cfg / checkpoint / seed) are controlled by the
  settings panel and are **not exposed to the model** — the model only provides
  prompt / negative / size. A checkpoint set in settings is switched in via
  `override_settings` and restored after generation.
- Some models don't support tools; when selected, the tool toggles disable automatically
  and plain chat (or `/image`) still works.
- On the Claude engine, the web-search tools are not available (built-in tools are disabled).

## Development

This project is a **human + AI collaboration**. The human developer drove the goals,
product decisions, the local Ollama / A1111 / Claude setup, and review; **Anthropic's
Claude (via Claude Code)** contributed the architecture, the implementation across the
backend and frontend, and end-to-end verification. Treat the AI-written code the same as
any other contribution — review it before relying on it.

## License

Licensed under the **GNU General Public License v3.0** — see [LICENSE](LICENSE).

This program is free software: you can redistribute it and/or modify it under the terms of
the GNU GPL as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version. It is distributed in the hope that it will be
useful, but **WITHOUT ANY WARRANTY**; without even the implied warranty of MERCHANTABILITY
or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# Chat + Ollama + A1111 WebUI

An Open WebUI–style chat interface that wires together a local **Ollama** LLM and
**A1111 (Stable Diffusion WebUI)**. The model decides on its own when to generate an
image (every engine calls its tools through MCP: native function calling on Ollama / Strata,
native MCP on the Claude and Codex CLIs), and the result is rendered inline in the
conversation. You can also switch the AI engine between **Ollama**, your logged-in
**Claude CLI**, your logged-in **OpenAI Codex CLI**, and a local **Strata** server.

![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)
![chat: ollama](https://img.shields.io/badge/chat-ollama-blue)
![chat: claude--cli](https://img.shields.io/badge/chat-claude--cli-orange)
![chat: codex--cli](https://img.shields.io/badge/chat-codex--cli-black)
![chat: strata](https://img.shields.io/badge/chat-strata-purple)
![image: A1111](https://img.shields.io/badge/image-A1111-green)

> **Built by a human and AI, together.** This project was designed and implemented
> collaboratively by a human developer and **Anthropic's Claude (via Claude Code)** —
> from architecture and code to end-to-end testing. See [Development](#development).

---

## Features

- 🔀 **Switchable AI engine** — toggle in the top bar between **Ollama** (local models),
  **Claude CLI** (your logged-in Claude Code), **OpenAI Codex CLI** (your logged-in
  `codex`) and **Strata** (a local LLM server with an OpenAI-compatible API, see
  [Strata](https://github.com/sss22213/Strata)). All of them can generate images on their own
  (Ollama and Strata via native tools, Claude and Codex via native MCP — see
  [Tools and MCP](#tools-and-mcp)); Ollama, Claude and Codex also see images (vision). Strata uses the same tool loop as
  Ollama (image tools, web search, skill tools), streams its thinking, maps the thinking
  switch and effort to `reasoning_effort` (none / low / medium / high) and shows its server's
  context in the usage meter. Its API key is entered in **Settings → Service sources**; it is
  stored only in the backend's settings file and never sent back to the browser.
- 💬 **Multi-conversation chat** — streaming replies, Markdown / code highlighting,
  collapsible reasoning (thinking) blocks.
- 🎨 **Autonomous image generation** — the model calls `generate_image` (txt2img) →
  A1111 renders → the image is embedded inline (zoom / download / view parameters), right
  under the text that was written before it, so a reply with several images reads
  text → image → text → image. There is no limit on tool calls per reply. A vision-capable
  model **sees the images A1111 generated**: the newest one is attached to the tool result in
  the same reply (Ollama / Strata), and the images of the previous reply are attached to your
  next message on every engine, so "is anything wrong with that picture?" gets a real look.
- 📚 **Illustrated stories in chat** — with the `story-illustrator` skill the model plans the
  whole story first (cast sheet + numbered scenes, each with a one-sentence picture line),
  then writes each scene and generates its image one at a time, so every picture sits under
  its own scene; ask for "keywords only" to get one prompt per scene instead. If the model
  writes the next scene and stops without its image, the backend reminds it to draw that
  scene and finish the story.
- 🖼️ **Image upload (vision)** — attach or paste an image and ask a vision model about it.
- 📖 **Comic Studio** (`#/comic`) — describe a story, let the LLM break it into panels
  (8–15 scene tags led by subject-count tags, a per-panel **expression** picked from a
  danbooru whitelist with off-list words mapped to the closest tag, dialogue in the
  premise's language, captions), regenerate one panel's tags on demand (with an
  optional direction such as "from above, add rain", and an undo), keep characters consistent
  with character cards + LoRA, render every panel through A1111, lay them out as a page
  with draggable speech bubbles, and export a PNG. Bubbles come in six styles (speech,
  box, shout burst, whisper, thought, caption) with a selectable tail direction (eight
  directions or none); the page preview and the exported PNG share the same geometry.
  **Storyboard skills**: tick skills in the script panel (e.g. *SD Prompt Guide (Anima)*) and
  their instructions are added to the storyboard and tag-regeneration prompts, with a
  Comic Studio adapter note (JSON only, no tools; style, LoRA and the card looks are added by
  the app). **Prompt format** *Auto / Tags only / English sentences + tags*: for checkpoints
  that read English (Anima; Auto checks the checkpoint in the comic's image settings, or
  Forge's current one when empty) every panel also gets 2–4 English sentences describing the
  picture, with characters referred to by their look instead of their names. The sentences
  go into the image prompt as a whole, after the style and before the tags.
  A **Thinking mode** switch (Ollama) decides whether thinking-capable models reason
  before writing the storyboard; if a model gets stuck thinking and returns no answer (or the
  answer is cut off), the request is retried once without thinking and the page shows a
  notice saying the result was produced without thinking. The same switch exists on the
  Image Story page, and the chat's conversation summary shows the same notice.
  Comics are **saved on the server automatically** (title, premise, cards, panels, bubbles,
  render settings) into `DATA_DIR/comics.db`, with the rendered panels in the image folder;
  the 📂 **Library** button lists them with thumbnails to reopen, delete or start a new
  one, and "Export page PNG" also stores the page image in the image folder. The browser's
  localStorage is only a cache, so container rebuilds, another browser or another device
  all see the same comics.
  Each comic also keeps **storyboard versions**: before a new AI storyboard, a script
  import or a restore, the current panels (rendered images included) are snapshotted; the
  "Storyboard versions" section in the script panel lists them with previews to restore or
  delete. Versions live on the server (`comic_versions` table, no limit, identical content
  stored once); the browser caches only the latest five and fetches older ones on demand.
  Character cards are matched to the storyboard by name, leniently (case, spaces and
  suffixes like "Mia (heroine)" are ignored), anyone who speaks in a panel is listed as
  present, unnamed cards are auto-named before generation, and renaming a card renames its
  references in the panels.
  Storyboard replies are parsed leniently (code fences, chatter around the JSON, trailing
  commas, `<think>` blocks) and a reply that still is not JSON is retried up to three times
  with a reminder; a reply cut off mid-JSON is reported as truncated with a hint to raise
  `num_ctx`, lower the panel count or switch thinking off.
- 🖼️➡️📖 **Image Story** (`#/story`) — upload any number of images and let a vision model
  write a **short story** or a complete **comic script** (cast with appearance tags, art
  style, premise, panels) from them; one click opens it in Comic Studio and renders it.
  A third mode, **Image panels**, treats each uploaded image as one panel (in upload
  order) and writes a scene note, dialogue and caption for every panel; open it in Comic
  Studio with the images already in place to position bubbles and export. Panels are
  handled in two passes — every image is described on its own (one image per request,
  so a panel can never be matched to the wrong image, even with a dozen of them), then
  the numbered descriptions are written up as one coherent script.
  For the story / comic-script modes the page estimates context usage (~2k tokens per
  image) against the model's window and warns you to drop images or raise `num_ctx`
  when it won't fit.
- 📱 **Mobile / tablet friendly** — the chat, Comic Studio and Image Story pages adapt to
  iPhone / iPad sizes (two-row toolbars, drawer sidebar, single-column layouts, iOS
  safe-area and input-zoom handling). Copy buttons also work when the page is opened over
  plain HTTP on the LAN (e.g. `http://192.168.x.x:5273`), where browsers hide the clipboard API.
- 🖌️ **img2img redraw** — attach an image and ask the model to restyle/modify it
  (`edit_image`); any generated image also has a "redraw from this" button.
- 🌐 **Web search** — when enabled, the model can call `web_search` / `fetch_url` to
  look things up and read pages, with clickable sources (DuckDuckGo by default, no key;
  SearXNG optional). *(Ollama engine.)*
- 🧠 **Context management** — adjustable `num_ctx` (unlock a model's full context), a
  live **usage meter** (used / limit) in the top bar, one-click **compact** that
  summarizes older messages while keeping the latest exchange, and an optional
  **auto compact** (Settings) that does it for you once usage crosses a threshold.
- 👁/🔧 The model dropdown marks which models can **see images** (vision) and **use tools**;
  the ⟳ button next to it refreshes the Ollama model list and reloads the selected model.
- 📄 **PNG Info (generation parameters)** — read the embedded SD parameters
  (prompt / negative / seed / sampler / size / model) from a generated **or uploaded**
  image, with one-click **"apply to settings"** to reproduce it. The model can also call
  `read_png_info` to answer "how was this image made?". *(Only works on images that still
  carry A1111/ComfyUI metadata — screenshots or recompressed images won't have any.)*
- 🕘 **Prompt history** — if you run the A1111 `sd-webui-prompt-history` extension, browse
  its recorded generations right here: a searchable, paginated thumbnail grid (read straight
  from the extension's `data.json`), and one click to **apply to settings** or **generate
  now** (re-render with the original seed/params). *(Optional — point it at the extension's
  data folder; see [Prompt history](#prompt-history-sd-webui-prompt-history).)*
- 👥 **Character keyword search (WAI / Illustrious)** — the 👥 button opens a searchable
  picker of **20,000+** anime characters whose danbooru tags work directly with WAI /
  Illustrious / NoobAI / Pony checkpoints. Romanization-tolerant, multi-word search; insert
  into the composer or generate immediately. Most entries carry a **full curated appearance
  prompt** for accurate results. *(See [Character search](#character-search-wai--illustrious)
  for data sources.)*
- 📊 **Live progress bar** — percentage, step count, and a live preview during generation.
- 📂 **Selectable image storage location** — pick the output folder with a server-side
  directory picker (browse / type a path / create a folder); old images still resolve
  after you switch.
- 🔌 **Configurable service sources** — point Ollama / A1111 / Strata at an "API URL" or a
  "Docker container", with a "Test connection" button that shows why a test failed
  (auto-lists containers when the docker socket is reachable). Strata also has an API key
  field: it shows only whether a key is set, keeps the saved key when left empty, and
  "Test connection" can try a newly typed key before you save it.
- 🌐 **Multilingual UI** — Traditional Chinese / Simplified Chinese / English / 日本語 /
  한국어, switchable live.
- ⚙️ **Settings panel** — SD checkpoint, sampler, width/height, steps, CFG, seed,
  denoising strength, default negative prompt, system prompt.
- 💾 **Server-side persistence** — conversations (SQLite) and settings are stored on the
  backend for cross-device, long-term history, with a `localStorage` cache for speed;
  images live on the backend and only their URLs are stored. Open tabs re-sync the
  conversation list when they regain focus and every 30 s, so a chat continued on your
  phone shows up on the desktop without a reload.
- 🧩 **Skills (Agent Skills plugin)** — drop community `SKILL.md` folders into the skills
  directory and enable any number of them (or let the model pick) from the ✨ button. Skills can declare
  HTTP API tools (`tools.json`) and, once you enable it in Settings, the model can run the
  skill's bundled Python scripts on the server. *(See [Skills](#skills-agent-skills-plugin).)*
- 🕸️ **LangGraph workflows** (`#/workflows`) — drop in an official LangGraph project
  (`langgraph.json` + Python), install its dependencies into its own venv with one click and
  run any of its graphs, watching every node, LLM call, generated image and log line live —
  on a **flowchart** of the graph that lights up the running node and the path taken.
  Graphs use the app's engines, A1111 and web search through `import webui_app` (no API
  keys), can show A1111's images to a vision model, and can be started from the chat with
  `/workflow project:graph input`. Projects live in a workflows folder you can switch (or mount
  from the host) and are managed on the page — search, rename, duplicate, export as zip, delete —
  with a saved **run history** per project. *(See [LangGraph workflows](#langgraph-workflows).)*
- ✏️ **Instruction-based image editing** *(optional)* — with a local
  **stable-diffusion.cpp** server running an editing model (e.g. Qwen-Image 2.1), the
  `sdcpp-image-edit` skill edits the latest image in the chat ("make her hair red", "remove
  the background") through the server's MCP tools, shows progress while it runs and the result
  inline, and lets a vision model check the result.
- 🔎 **Civitai search & model examples** — search civitai.com from the chat and get result
  **cards** (example images, base model, trigger words, a **Download this** button that hands
  the model to A1111's Civitai Helper; a base-model filter shows the matching version), or
  browse an installed model's example images as a **gallery** that vision models can also
  look at. Images that people posted on civitai (by user, by LoRA / model, or both) show up
  as a gallery with their prompts, and the ones you pick can be saved as extra example images
  of an installed LoRA.
- 🗂️ **LoRA browser** — the layers button next to the chat input lists every installed LoRA
  with its preview and trigger words. Filter by **base model** (Illustrious, NoobAI, Pony,
  SDXL, SD 1.5, Anima …, from Civitai or inferred from the file's training info) and by
  **content category** (character, clothing, poses, style, concept, background …, from the
  model's Civitai tags). Categories are fetched only when you ask: **Update categories**
  (all LoRAs, in the background) or **Update** in a LoRA's details (just that one). The
  details show the Civitai source (model / version / creator, link to the page), the example
  images with their prompts (copy button), **Download all example images**, and **Delete**
  (removes the LoRA and every file that belongs to it). The chat model searches the same way:
  its LoRA inventory tool filters by category and base model and reports how many LoRAs each
  category holds.
- 🎛️ **Anima checkpoints** — when the selected checkpoint is an Anima model (WAI-ANIMA,
  One Obsession Anima 2.9B, Anima base), the app loads the Qwen3 text encoder and Qwen-Image
  VAE that Forge Neo needs for it by itself, also when the app follows the checkpoint
  selected in Forge. The **SD Prompt Guide (Anima)** skill teaches the model Anima's prompt
  style. Errors from A1111 now show Forge's own reason (for example a missing file) instead
  of a bare "HTTP 500".
- 🎬 **MMD animation** *(optional)* — with the separate **anime-render** service (Blender +
  mmd_tools + TTS, port 5280), the `mmd-animation` skill turns a story into a storyboard and
  renders it as a short mp4 acted out by a 3D MMD character (through the service's MCP tools,
  with render progress in the chat).
- ⌨️ `/image <prompt>` generates directly, skipping the LLM (a manual fallback).

## Requirements

- **Ollama** at `localhost:11434` with at least one **tool-capable** model
  (e.g. `qwen3.5:35b`, the `qwen3` family).
- **A1111** at `localhost:7860`, started with `--api`, with **MCP**: every A1111 and Civitai Helper
  tool of this app (image generation, model / sampler / LoRA lists, PNG info, the Civitai Helper
  skill, the LoRA browser …) is called through their MCP servers (see [Tools and MCP](#tools-and-mcp)).
  **Required: [sd-webui-forge-neo-chino](https://github.com/sss22213/sd-webui-forge-neo-chino)**
  (its built-in `sd_forge_mcp` extension serves `/mcp`) with the
  [Civitai Helper (sss22213 fork)](https://github.com/sss22213/Stable-Diffusion-Webui-Civitai-Helper)
  1.16.0+ (serves `/civitai-helper/mcp`). Put both tokens (Forge **Settings → MCP Server** and
  **Settings → Civitai Helper**) into this app's **Settings → Service sources → A1111**, or into
  `.env` as `A1111_MCP_TOKEN` / `CIVITAI_HELPER_MCP_TOKEN`. This combination also brings:
  - `a1111-memory-manager` needs its extended unload API: `unload-checkpoint?full=false|true`
    (VRAM only, or RAM too) and the new `reload-checkpoint`. Upstream Forge Neo has no reload
    endpoint and always unloads fully.
  - The LoRA browser (examples, download, delete) and the `civitai-helper` skill use the
    Civitai Helper fork's MCP tools.
  - It is based on a Forge Neo that supports Anima 2.9B (One Obsession) and ships a Docker image
    with every package pre-installed and fixes for mobile browsers.

  Other A1111 / Forge builds have no MCP server, so this app cannot generate images with them.
- For the **Claude CLI engine** (optional): the `claude` CLI installed and logged in.
  The Docker image installs it for you; you only mount your credentials (see below).
- For the **Codex CLI engine** (optional): the `codex` CLI logged in on the host. Its whole
  `~/.codex` (static binary + credentials + model cache) is mounted into the container — no
  in-image install needed (see below).
- For **Prompt history** (optional): the A1111 `sd-webui-prompt-history` extension; mount its
  `data` folder into the container (read-only) so the WebUI can read your past generations.
- For **image editing** (optional): the stable-diffusion.cpp server with its A1111 bridge and MCP
  server (`bridge.py` with `/mcp`) at `localhost:7861` (`SDCPP_URL`) with an editing model loaded;
  URL and token in **Settings → Service sources → sd.cpp**. Everything else works without it.
- For **MMD animation** (optional): the anime-render service with its MCP server at
  `localhost:5280` (`MMD_URL`); URL and token in **Settings → Service sources → MMD**.
- For **Civitai search** (`civitai-api` skill): Civitai Helper with the `/civitai/models` and
  `/civitai/images` routes (its MCP tools `civitai_search_models` / `civitai_search_images`).
- For the **Strata engine** (optional): a running Strata server at `localhost:8081` (`STRATA_URL`;
  Docker: `host.docker.internal:8081`). Put its API key in **Settings → Service sources → Strata**.
  The engine is enabled in the top bar once the server answers with that key and its model is
  loaded. Strata and A1111 share the GPU: a large Strata model can leave too little VRAM for
  image generation.
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
`OLLAMA_URL` / `A1111_URL` / `SDCPP_URL` / `MMD_URL` and the MCP tokens, or enable the Claude (`CLAUDE_CREDS_DIR`) / Codex
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
10. **Prompt history:** if enabled, the 🕘 button (top bar, left of ⚙️) opens a searchable
    grid of your past A1111 generations — click one to apply it to settings or re-generate.
11. **Character search:** the 👥 button (composer) opens a searchable list of 20k+ anime
    characters — **insert** one into your prompt or **generate** it directly. See
    [Character search](#character-search-wai--illustrious).
12. **Reload model (Ollama):** the ⟳ button next to the model dropdown refreshes the model
    list (models added with `ollama pull` / `ollama create` appear without reloading the
    page), then unloads the selected model and loads it again with the chat's `num_ctx`,
    so the next message does not trigger another load. Use it after overwriting a model
    with `ollama create`, or when a model starts behaving oddly.
13. **Comic Studio:** the 📖 button opens `#/comic`. Write a premise, add character cards
    (fixed appearance tags + optional LoRA; unnamed cards are auto-named), optionally tick
    **Thinking mode** for thinking-capable Ollama models, pick **Storyboard skills** and the
    **Prompt format** if you like, press **AI storyboard** to get panels with scene tags
    (plus English sentences for Anima), a per-panel **Face** (expression) field, dialogue
    and captions, then **Generate all**. Each panel has **Regenerate tags** (type a direction such as
    "from above, add rain", Enter; **Undo** brings the previous tags back). Switch to page
    view to drag bubbles around, hover one to change its style and tail direction (also
    editable per bubble in the storyboard cards), and export a PNG. Everything is saved
    to the server as you work: 📂 **Library** reopens earlier comics, and **Storyboard
    versions** (script panel) keeps every storyboard that was replaced, with preview and
    restore.
14. **Image Story:** the 🖼️ button opens `#/story`. Upload / paste as many images as you
    like (the page shows an estimated token count against the context window), pick
    **Story**, **Comic script** or **Image panels** (your images are the panels; reorder
    them with ◀ ▶), optionally add direction ("heartwarming, twist ending"),
    and press **Generate**. A story can be sent to Comic Studio as the premise; a comic
    script can be opened there directly — **Open & render all** imports the cast and
    panels and starts rendering. Needs a vision-capable model (👁 in the dropdown).
15. **Illustrated story in chat:** enable **Story Illustrator** (and **SD Prompt Guide (Illustrious)**)
    with the ✨ button, then ask e.g. *"tell a story in 8 pictures: a little fox lost in a
    snowstorm finds its way home by the stars"*. The model writes the outline, then each
    scene's text followed by its image; say *"keywords only"* to get the prompts without
    rendering. Put a LoRA and its trigger words in your request to use it for the heroine.
16. **LangGraph workflows:** the 🕸️ button opens `#/workflows`. Press **Allow running** once,
    create the **example** project (or upload your own folder / zip, or drop a project folder
    into the workflows folder and press **Rescan**), press **Install dependencies**, pick a
    graph, type the input (JSON or plain text) and **Run**. **Runs** keeps every run; open one
    to see its steps and output, or **Run again with this input**. In the chat, `/workflow`
    lists the workflows and `/workflow example:chat your question` runs one.

> **Keyboard:** **Enter** sends a message and **Shift + Enter** inserts a newline by default;
> ⚙️ Settings → *Send key* swaps the two. Enter never sends while an IME is still composing
> (e.g. picking characters in a Chinese/Japanese input method).

> **Storage location in Docker mode:** the picker browses the **backend container's**
> filesystem. By default images go to the bind-mounted `backend/data/images` (stored in
> `app_settings.json` as an empty `image_dir`, so the same settings file works for the
> container and for a backend started on the host). To store them elsewhere persistently,
> mount another volume into the container and select it; a folder outside a mounted
> volume lives only inside the container and is lost when it is rebuilt.

> **vision vs img2img:** with an attached image the model can both *see* it (if it
> supports vision) and *redraw* it (img2img) — it decides based on what you ask.
> Non-vision models can still redraw (img2img is handled by A1111 and doesn't require the
> model to see the image).

> **Tip:** these are SDXL / Pony / Illustrious anime checkpoints — comma-separated English
> danbooru-style tags work best. The system prompt already nudges the model to write them.

## AI engines: Ollama / Claude CLI / Codex CLI / Strata

The top-bar selector switches the **AI engine**:

- **Ollama** — local models with native function-calling for image generation (default).
- **Claude CLI** — uses your **already-logged-in `claude` (Claude Code)**. The CLI is launched
  with `--tools ""` (all built-in tools disabled, so Claude never touches the backend
  filesystem) and with the app's MCP gateway attached for this conversation only
  (`--mcp-config … --strict-mcp-config --allowedTools mcp__webui`): Claude calls
  `generate_image`, `edit_image`, web search and the enabled skills' tools natively, the chat shows
  progress and images live, and Claude sees the picture it made. Vision (base64 image input)
  is supported too.
- **Codex CLI** — your logged-in `codex`, with the same MCP gateway (see below).
- **Strata** — a local [Strata](https://github.com/sss22213/Strata) server through its
  OpenAI-compatible API, with the same native tool calling as Ollama (see below).

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
> so the CLI can refresh its token. Use `CLAUDE_MODELS` to customize the models in the
> dropdown (default `sonnet,opus,fable,haiku`) — see [Supported models](#supported-models).

### Enabling Claude CLI (local dev, no Docker)

If the backend runs directly on the host and `claude` is on `PATH` and logged in,
**no configuration is needed** — `/api/engines` auto-detects it and the option appears.

### OpenAI Codex CLI

Uses your **logged-in `codex` (OpenAI Codex CLI)**. It's launched with
`codex exec --json -s read-only --ephemeral`, the assistant message is parsed from the
JSONL stream, and attachments are passed via `-i` (vision). Tools come from the app's MCP
gateway (`-c mcp_servers.webui.url=…`, its tools approved automatically because `codex exec`
never asks): Codex calls `generate_image`, web search and the skills' tools itself. Codex's own
built-in tools are switched off for these chats (`image_generation`, which would draw with
OpenAI instead of A1111, `shell_tool`, `unified_exec`, browser and computer use, apps, plugins,
`view_image`). The model dropdown is populated
automatically from the models your Codex account supports (read from
`~/.codex/models_cache.json`, see [Supported models](#supported-models)). You can also type
`/image <prompt>` on any engine.

**Docker:** the `codex` binary is a static executable, so the whole `~/.codex` (binary +
auth + model cache) is mounted into the container — set an **absolute path** in `.env`:

```bash
CODEX_CREDS_DIR=/home/youruser/.codex
```

Then `docker compose up -d --build` and pick **Codex CLI** in the top bar. If Codex errors
about sandbox/landlock inside the container, set `CODEX_SANDBOX_MODE=bypass` in `.env`
(the container is already the isolation boundary). **Local dev:** if `codex` is on `PATH`
and logged in, it's auto-detected — no config needed.

### Strata

Talks to a [Strata](https://github.com/sss22213/Strata) server (a local llama.cpp-based LLM
server) over its OpenAI-compatible API: `/v1/chat/completions` with streaming, tool calls and
`reasoning_content`, and `/v1/models` for the model list and context size. The app's
Ollama-format messages are converted on the way out, so Strata runs the **same agentic loop
as Ollama**: `generate_image` / `edit_image`, web search, skill tools and the no-retry guard.

1. Start Strata (default `localhost:8081`). In Docker the backend reaches it at
   `host.docker.internal:8081`; change it with `STRATA_URL` or in Settings.
2. Open **⚙️ Settings → Service sources → Strata**, paste the server's API key, press
   **Test connection** (shows the loaded model and its context), then **Save**.
3. Pick **Strata** in the top bar. It stays greyed out until the server answers with that key
   and its model is loaded.

- **API key.** Sent as `Authorization: Bearer …` from the backend only. It is kept in the
  backend's settings file, never returned by `/api/sources`, `/api/engines` or
  `/api/models`; the field shows "set" / "not set". Saving with the field empty keeps the
  key, **Clear key** + Save removes it. `STRATA_API_KEY` in `.env` is only the initial value.
- **Thinking.** The thinking switch and the effort in ⚙️ Settings map to `reasoning_effort`
  (`none` / `low` / `medium` / `high`, default `medium`); thinking streams into the
  collapsible reasoning block.
- **Context.** Fixed by the server's `--max-context` start option, so ⚙️ Settings shows it read-only
  instead of the Ollama `num_ctx` field; change it in Strata (run its setup again, or edit
  `--max-context` in its config and restart). The usage meter and Comic Studio use that value
  (`meta.n_ctx` from `/v1/models`).
- **Vision.** Images are sent only when the model lists `image` in its input modalities;
  a text-only model has attachments stripped like a non-vision Ollama model.
- **Comic Studio / Image Story / Compact** work on Strata too, one request at a time.
- **VRAM.** Strata and A1111 usually share one GPU. A model that fills the card leaves no
  room for SDXL, so image generation can fail until you free memory.

### Supported models

**Claude CLI.** The dropdown shows whatever `CLAUDE_MODELS` contains (default
`sonnet,opus,fable,haiku`). Aliases are resolved by the installed Claude Code CLI to the
newest model of that family, so they never go stale; full IDs pin a specific version. The
table reflects Claude Code 2.1.281 (catalog read from the binary on 2026-09-25):

| Entry in `CLAUDE_MODELS` | Resolves to | Context | Reasoning effort |
|---|---|---|---|
| `fable` | Claude Fable 5.1 (`claude-fable-5-1`) | 1M | low · medium · high · xhigh · max (default high) |
| `opus` | Claude Opus 5.5 (`claude-opus-5-5`) | 1M | low · medium · high · xhigh · max (default medium) |
| `sonnet` | Claude Sonnet 5 (`claude-sonnet-5`) | 1M | low · medium · high · xhigh · max (default high) |
| `haiku` | Claude Haiku 4.5 (`claude-haiku-4-5`) | 200K | — |

Full IDs accepted as well:

| Full ID | Context | Reasoning effort |
|---|---|---|
| `claude-opus-5-5` | 1M | low · medium · high · xhigh · max (default medium) |
| `claude-fable-5-1`, `claude-fable-5`, `claude-opus-5`, `claude-opus-4-8`, `claude-sonnet-5` | 1M | low · medium · high · xhigh · max (default high) |
| `claude-opus-4-7` | 1M | low · medium · high · xhigh · max (default xhigh) |
| `claude-opus-4-6`, `claude-sonnet-4-6` | 200K | low · medium · high · max (no xhigh) |
| `claude-haiku-4-5`, `claude-opus-4-5`, `claude-sonnet-4-5` | 200K | — |

Fable / Opus 5.5 / Opus 5 / Opus 4.7+ / Sonnet 5 use a native 1M window; the 200K models accept a
`[1m]` suffix (e.g. `sonnet-4-6[1m]`, `claude-opus-4-6[1m]`, `haiku[1m]`) to turn on the
CLI's 1M window. The dropdown shows the resolved name next to each entry (e.g.
`opus · Opus 5.5`); set `CLAUDE_CONTEXT_LENGTH` to force one context size for every Claude
model. The effort selector in ⚙️ Settings only offers the levels the selected model
declares, and `--effort` is not sent for models that do not support it. `claude-mythos-5-1`
/ `claude-mythos-5` are in the CLI catalog too but only for approved organizations, so they
are not in the default list.

**Codex CLI.** The dropdown is built from `~/.codex/models_cache.json` — the models your
account can actually use — so it updates whenever the `codex` CLI refreshes its catalog
(run `codex debug models` or any `codex` session on the host; Docker sees the mounted
cache). Hidden / non-chat entries (`gpt-reserve`, `codex-auto-review`) are filtered out.
Catalog as of 2026-09-25 (codex 0.155.1; `gpt-6-sol` and `gpt-6-luna` are new):

| Model | Reasoning effort | Context |
|---|---|---|
| `gpt-6-astra` | low · medium · high · xhigh · max · ultra (default low) | 272K |
| `gpt-6-sol` | low · medium · high · xhigh · max · ultra (default medium) | 272K |
| `gpt-6-luna` | low · medium · high · xhigh · max (default medium) | 272K |
| `gpt-5.6-sol` | low · medium · high · xhigh · max · ultra (default low) | 272K |
| `gpt-5.6-terra` | low · medium · high · xhigh · max · ultra (default medium) | 272K |
| `gpt-5.6-luna` | low · medium · high · xhigh · max (default medium) | 272K |
| `gpt-5.5` | low · medium · high · xhigh (default medium) | 272K |

The effort selector in ⚙️ Settings only offers the levels the selected model declares. Set
`CODEX_MODELS=gpt-6-astra,gpt-5.5` to pin the dropdown; the same list above is the built-in
fallback when no cache exists yet.

## Tools and MCP

Every tool call goes through MCP (Model Context Protocol):

- **A1111 (Forge Neo)** serves its tools at `<A1111>/mcp` (built-in `sd_forge_mcp` extension of
  [sd-webui-forge-neo-chino](https://github.com/sss22213/sd-webui-forge-neo-chino)): `txt2img`,
  `img2img`, `get_progress`, `png_info`, `list_checkpoints`, `list_samplers`, `list_loras`,
  `list_modules`, `refresh_*`, memory, unload / reload. **Civitai Helper** serves its tools at
  `<A1111>/civitai-helper/mcp`. The backend talks to both with the official MCP Python SDK
  (`backend/mcp_client.py`), so image generation (chat, Comic Studio, stories, workflows), the
  model / sampler / LoRA lists, PNG info, the LoRA browser and the memory skill all use MCP; only
  LoRA preview images (static files) are fetched over plain HTTP.
- **stable-diffusion.cpp** serves `sdcpp_edit_image`, `sdcpp_img2img` and `sdcpp_status` at
  `<sd.cpp>/mcp` (its `bridge.py`), and **anime-render** serves `mmd_animation_catalog`,
  `make_mmd_animation` and `mmd_animation_status` at `<MMD>/mcp`. Both wait for the job and send
  progress (sd.cpp steps; MMD queue / TTS / render / encode), which the chat shows on the tool row.
  The civitai.com searches (`civitai_search_models`, `civitai_search_images`) are Civitai Helper
  MCP tools, so they use the civitai domain, API key and proxy set there.
- **The app itself is an MCP server too — the tool gateway** (`backend/tool_gateway.py`). Each chat
  and workflow run asks it which tools exist (`tools/list`: `generate_image`, `edit_image`,
  `read_png_info`, `web_search`, `fetch_url` and the enabled skills' tools) and calls them with
  `tools/call`. The gateway runs its own tools (web search, HTTP / script skill tools), forwards MCP
  skill tools to Forge / Civitai Helper / sd.cpp / anime-render, and streams progress, images,
  sources and skill cards to the chat while the model only gets the result (and, for vision models,
  the generated or edited image). Servers that cannot be reached are skipped for 20 seconds, so
  `tools="auto"` does not wait for a service that is off.
- **Claude CLI and Codex use MCP natively**: for each conversation (and each workflow call with
  tools) the gateway opens a one-time endpoint `http://127.0.0.1:<port>/mcp/session/<token>` and
  the CLI is started with it; the CLI runs its own tool loop against the gateway while the chat
  shows progress and images live. The endpoint closes when the reply ends. `MCP_GATEWAY_URL`
  overrides the address the CLIs use if the backend is not reachable on `127.0.0.1`.
- Tokens: Forge shows its token under **Settings → MCP Server**, Civitai Helper under **Settings →
  Civitai Helper**; sd.cpp and anime-render read `MCP_TOKEN` from their own `.env` (empty = no
  token). Enter them in **Settings → Service sources** (A1111, sd.cpp, MMD; stored only on the
  server; **Test connection** checks the MCP endpoints and lists their tool counts) or set
  `A1111_MCP_TOKEN` / `CIVITAI_HELPER_MCP_TOKEN` / `SDCPP_MCP_TOKEN` / `MMD_MCP_TOKEN` in `.env`;
  the settings page wins. A wrong or missing token, or a service without MCP, is reported in plain
  words where the call fails.
- These MCP servers are open to other clients as well (Claude Code, Claude Desktop, Codex …)
  with the same tokens; see each project's README for the commands.

## Skills (Agent Skills plugin)

A skill is a folder under the skills directory (default `backend/skills/`, changeable in
⚙️ Settings → Skills) with a `SKILL.md` (YAML `name` / `description` + Markdown
instructions), optional `references/*.md`, optional `scripts/*.py`, and an optional
`tools.json`. The format is the same one Anthropic / Codex / ClawHub skills use, so
community skills can be dropped in as-is. Enable skills from the ✨ button in the chat top
bar, or choose **Auto** to let the model decide per request. Skills dropped into the folder
while the app is running appear after **Rescan** in that dialog (no restart or reload needed). Skills work on every engine
(Ollama / Claude CLI / Codex CLI / Strata) because they are injected into the system prompt, and a
runtime-adapter note maps a skill's assumed `image_gen` to the app's A1111 generation.
Several skills can be enabled at once: their instructions are injected together (each gets a
share of the skill length limit when one is set) and their tools are all available. The selection is
saved with the other settings on the backend, so it survives reloads and follows you across
devices. Comic Studio has its own skill selection per comic (instructions only, no tools; see
[Comic Studio](#features)).

**How a skill can act**

| Mechanism | Declared in | What the model gets |
|---|---|---|
| Instructions | `SKILL.md`, `references/` | Injected into the system prompt in full by default. ⚙️ Settings → Skills → **Skill prompt length limit** caps it (0 = unlimited, the default; with a limit, several enabled skills split it, at least 3000 characters each). |
| MCP tools | `tools.json` with a top-level `"mcp_server"` (or `"server"` per tool): `a1111`, `civitai-helper`, `sdcpp` or `mmd` | A function per tool, called on that MCP server (Forge's `/mcp`, Civitai Helper's `/civitai-helper/mcp`, sd.cpp's and anime-render's `/mcp`; `"tool"` names it when it differs). `parameters`, `defaults`, `result_note`, `max_chars`, `postprocess` and `vision_max` work as for HTTP tools: the server's structured result is the same JSON its REST API returns. `"attach_image": {"field": "image"}` puts the most recent image of the conversation into that argument. Images in the result are saved, shown in the chat and attached for vision models; progress notifications show on the tool row. Used by `civitai-helper`, `a1111-memory-manager`, `civitai-api`, `sdcpp-image-edit` and `mmd-animation`. |
| HTTP API tools | `tools.json` (`kind` omitted or `"http"`) | A function per tool; the backend performs the request. `base_url` may use `{a1111_url}` / `{ollama_url}`. |
| WebUI-local images | automatic for tools whose `base_url` uses `{a1111_url}` | A1111-relative image links such as Civitai Helper's `local_url` (`./sd_extra_networks/thumb?filename=…`) are rewritten to the app's `/api/a1111-thumb` proxy (resized to 1024 px and cached), and the chat renderer rewrites them too if the model copies the raw link. |
| Images for the model to see | `tools.json` HTTP tool with `"postprocess": "civitai_examples"` (and `"vision_max"`) | The backend shows a `gallery` in the chat and attaches up to `vision_max` downscaled images to the tool message. Vision-capable Ollama models see them; other models are told they cannot. |
| Query parameters on POST | `tools.json` HTTP tool with `"query_params": ["full"]` | Those arguments go into the URL query string instead of the JSON body (e.g. A1111's `unload-checkpoint?full=true`). |
| Attached image | `tools.json` HTTP or MCP tool with `"attach_image": {"field": …, "as": "list" or "single"}` | The most recent image in the conversation (the user's attachment or the last generated / edited image, whichever is newer) is added to the request as a data URL, so the model never handles image bytes. `base_url` may also use `{sdcpp_url}` / `{mmd_url}`. |
| Result cards | `tools.json` script tool with `"postprocess"` (currently `civitai_models`) | The backend turns the script's JSON into a compact summary for the model and a `candidates` event the chat renders as cards (thumbnails cached under `DATA_DIR/civitai-cache/`). |
| Python scripts | `scripts/*.py`, and optionally `tools.json` entries with `"kind": "script"` | A `run_skill_script(script, args[])` function (plus any declared fixed-script tools). Off by default: enable **Allow skills to run scripts** in Settings → Skills. |

Tools are available on every engine through the MCP gateway (Ollama / Strata: native function
calling; Claude CLI / Codex: native MCP). The chat shows each tool call while it runs.

**How scripts run.** The backend executes the file with its own Python interpreter (no
shell, arguments passed as a list), inside a persistent per-skill work folder at
`DATA_DIR/skill-work/<skill>/` (a Docker volume path, so files a skill writes survive
restarts). The script only sees a minimal environment: `PATH`, `HOME` set to the work
folder (so mounted CLI credentials are not exposed), `PYTHONPATH` pointing at the skill
folder, proxy variables, plus the variables named in `SKILL_SCRIPT_ENV` and any
`KEY=VALUE` lines in `<work folder>/.env`. Those values are masked as `***` in the output
the model sees. Runs are killed after `SKILL_SCRIPT_TIMEOUT` seconds (default 300) and
output is truncated to a few thousand characters. Only the standard library and the
backend's own dependencies are importable; there is no `pip install`. Review third-party
skills before enabling scripts for them.

**Installing a ClawHub skill.** Either paste the folder into the skills directory, or:

```bash
npx -y clawhub install civitai-api          # downloads to ./skills/civitai-api
cp -r skills/civitai-api backend/skills/    # or into the folder chosen in Settings
```

Bundled skills:

| Skill | What it does |
|---|---|
| `generate-manga-page` | agent-mangaka-forge's consistency workflow adapted to A1111 LoRA / seed reuse. |
| `story-illustrator` | Illustrated stories in chat: the model first writes an outline (a cast sheet with each character's fixed **Core** look and **Outfit** tags, then numbered scenes forming a full arc, each with a one-sentence *picture line* of what the image shows), then writes each `## Scene N` and generates its image before the next one, so pictures sit under their scenes — or, when you only want keywords, gives one ready-to-paste prompt per scene. Scene prompts put the count of everyone visible, the character's core look and the scene's action / key objects / other people first (the defining action weighted), then expression, setting, a shot that can show the action, the outfit and the quality tags; `solo` only when the character is alone. |
| `sdcpp-image-edit` | Instruction-based editing of an attached image through the MCP server of a local **stable-diffusion.cpp** bridge (Settings → Service sources → sd.cpp, default port 7861) running an editing model such as Qwen-Image 2.1: the app passes the most recent image in the conversation (your attachment, or the last image generated with A1111 or edited here, so "edit the picture you just made" works without re-attaching), the server uses it as the reference image, reports progress and returns the result, which is shown inline like a generated image and attached for vision models. Also has an img2img tool and a status tool that reports whether the loaded model can edit (an edit on a plain SD checkpoint comes back with a warning). |
| `a1111-memory-manager` | Memory tools for the A1111 / Forge image generator: show RAM / VRAM (`/sdapi/v1/memory`, summarized in GB), unload the checkpoint from VRAM only or fully (`/sdapi/v1/unload-checkpoint[?full=true]`), and load it back (`/sdapi/v1/reload-checkpoint`). Handy when Ollama, A1111 and sd.cpp share one GPU. |
| `sd-prompt-guide` | **SD Prompt Guide (Illustrious)** — prompt-writing rules for the local SD backend, tuned for **WAI-illustrious-SDXL**: danbooru tag order, weights, negative prompt, sizes, no tag-count limit, and the WAI author's quality tags `masterpiece, best quality, amazing quality` at the end with no extra quality / aesthetic tags (they blur the image). How to apply a LoRA (`<lora:filename:0.6–1>` plus its trigger words in the prompt); points to Civitai Helper for the installed-LoRA inventory, prefers Illustrious / NoobAI LoRAs by base model, and stops after two lookups instead of searching on and on. |
| `sd-prompt-guide-anima` | **SD Prompt Guide (Anima)** — prompt-writing rules for **Anima** checkpoints (default WAI-ANIMA; also One Obsession Anima 2.9B and Anima base): a short head (quality prefix, LoRA trigger word, safety tag), then an English description of the character, outfit, action and place, then a full danbooru tag list of the same picture with the LoRA tag at the end, `@artist` tags, heavier weights, each checkpoint's own quality prefix and negative prompt, Anima-only LoRAs (`civitai_lora_inventory` with `base: "Anima"`). Enable only the guide that matches the selected checkpoint. When the selected checkpoint — or, with no checkpoint set in the app, the one currently selected in Forge — is Anima (Civitai Helper base model, or `anima` in the file name), the app loads Forge Neo's `qwen_3_06b_base` text encoder and `qwen_image_vae` by itself; Anima 2.9B needs Forge Neo from August 2026 or later. |
| `civitai-helper` | MCP tools of the A1111 **Civitai Helper** extension ([sss22213 fork](https://github.com/sss22213/Stable-Diffusion-Webui-Civitai-Helper)): local LoRA / checkpoint inventory with trigger words (the LoRA inventory is filtered by the app by `category` and `base` model, with per-category counts, the same data as the LoRA browser), model lookup by URL or id, download into the WebUI, scan, check for new versions, refresh lists, save civitai users' images as extra examples of an installed model, rename an installed model with all its files, optionally changing the file extension (Civitai Helper 1.15.0+). Example images of an installed model are shown as a **gallery** (local copies first, with prompts and a copy button), and the first 4 are also attached to the tool result so a vision-capable Ollama model can actually see and describe them. |
| `civitai-api` | [stanestane/civitai-api](https://clawhub.ai/stanestane/skills/civitai-api) (MIT-0) plus app-specific search tools that run as Civitai Helper MCP tools (so they use its civitai domain, API key and proxy): `civitai_search_models` searches civitai.com (LoRA by default) and the chat shows the results as **cards** with server-cached example images, base model, trigger words and a **Download this** button that hands the model page to Civitai Helper (`base_model` shows the version made for that base model). `civitai_search_images` shows images people posted (by user, by model, or both) as a gallery with their prompts, and the picked ones can be saved as examples with Civitai Helper. Other commands (by-hash, tags, creators…) run the skill's script through `run_skill_script` (needs scripts enabled; `CIVITAI_API_KEY=…` in `backend/data/skill-work/civitai-api/.env` for authenticated calls). |
| `mmd-animation` | Turns a story into a short mp4 acted out by a 3D MMD character: the model writes a storyboard (narration, voiced and lip-synced lines, motions, expressions, camera) and the separate **anime-render** service (Blender + mmd_tools + TTS, Settings → Service sources → MMD, default `http://host.docker.internal:5280`) renders it through its MCP server, with queue and render progress in the chat. Optional; needs that service running. |

## LangGraph workflows

Runs **official LangGraph projects** — the same layout `langgraph dev` / LangGraph Platform
use — on the app's server. A project is a subfolder of the **workflows folder** with a
`langgraph.json`:

```json
{
  "dependencies": ["."],
  "graphs": { "illustrate": "./illustrate.py:graph", "chat": "./chat_agent.py:graph" },
  "env": ".env"
}
```

- **graphs** — `"./file.py:variable"` or `"package.module:variable"`; the variable is a compiled
  graph, an uncompiled `StateGraph`, or a factory function that takes the config (may be
  async). Python only (JS / TS graphs are listed as unsupported).
- **dependencies** — `langgraph` is always installed; `"."` / `"./sub"` install that folder
  (`pip install -e` when it has `pyproject.toml` / `setup.py`, `-r requirements.txt` plus
  `sys.path` otherwise); other strings are package names. Each project gets its own venv in
  `backend/data/langgraph-envs/<project>/` (pip cache shared); changing the dependency files
  marks it **needs reinstall**.
- **env** — a `.env` path or a `{name: value}` map. `.env` files are write-only in the page
  (never sent back to the browser) and their values are masked as `***` in logs and outputs.

**Using the app from a graph.** `import webui_app` (provided by the runner, nothing to install):

| Function | What it does |
|---|---|
| `chat(prompt, *, messages=None, system=None, engine=None, model=None, think=None, images=None, tools=None, skill=None, max_rounds=8, details=False, exclude_tools=None, read_only=False)` | Asks the engine / model selected in the page (or the chat), or the one you name. `images` takes `generate_image` results, `/images/…` URLs, data URLs or base64 — the model looks at them (Claude / Codex always; Ollama / Strata vision models). `tools` / `skill` let it call tools (see *Tool calling* below) |
| `app_tools(names=None, *, skill=None)` | App and skill tools as LangChain tools, for `ToolNode` / `create_react_agent` |
| `generate_image(prompt, *, negative_prompt, width, height, seed, steps, cfg_scale, checkpoint)` | A1111 txt2img with the app's image settings (Anima modules included); returns `{"url", "info", "params"}` |
| `list_checkpoints()` | A1111's checkpoints with their base model: `{"current", "checkpoints": [{"name", "title", "base"}]}` — `base` (Illustrious / NoobAI / Pony / SDXL / SD 1.5 / Flux / Anima …) comes from Civitai Helper's records, else the file name; `name` goes straight into `generate_image(checkpoint=…)` |
| `web_search(query, max_results=5)` | The app's web search |
| `ask(title, fields=None, *, message="", images=None)` | Pauses the run and shows a form on the workflows page; returns `{field name: value}` (see *Human input* below) |
| `emit(message)` | A progress line in the run log |
| `get_chat_model()` | A LangChain `BaseChatModel` for `llm.invoke(state["messages"])`; `.bind_tools(tools)` returns messages with `tool_calls` for `ToolNode` |

Each has an async twin (`achat`, `agenerate_image`, `alist_checkpoints`, `aweb_search`). The calls travel over the
runner's stdin / stdout to the backend, so a project never needs the Strata key or CLI
credentials. Plain LangChain models (`ChatOllama`, `ChatOpenAI` …) work too if the project
lists them in `dependencies`.

**Tool calling.** `chat(..., tools=[...])` lets the model call tools until it stops asking (at
most `max_rounds` rounds, then one last answer without tools) and returns its final text.
`tools` mixes:

- **app tools by name** — `generate_image`, `web_search`, `fetch_url`, or any skill tool's name
  (e.g. Civitai Helper's `civitai_list_local_models`; script tools need *Allow skill scripts*).
  The backend runs them exactly like the chat does: generation progress, images and search
  sources appear in the run log, and a vision model gets to look at the picture it just made;
- **Python functions** (type hints, the docstring's first line as the description) and
  **LangChain tools**, run inside the workflow.

`skill="civitai-helper"` (comma-separated slugs, or `"__auto__"`) puts the skill's SKILL.md in the
system prompt, as choosing a skill in the chat does, and offers all of its tools (`tools=False`
for the instructions only). `details=True` returns `{"text", "calls": [{"name", "args", "result",
"images"}], "images"}`. **`tools="auto"`** hands the choice to the model: it gets every MCP tool —
`generate_image`, web search, all skills' tools and the other tools of the A1111 / Civitai Helper
servers (`list_checkpoints`, `set_checkpoint`, `list_loras`, `png_info`, `txt2img` with full
control over checkpoint / seed / steps …; images it makes this way are saved and shown like
`generate_image`'s) — except destructive ones (e.g. `civitai_delete_model`) and internal ones
(`get_progress`, `interrupt`, `skip`), which must be named. `["auto", my_function]` adds your own
functions. `read_only=True` keeps only tools that just look things up (MCP `readOnlyHint`, web
search, PNG info, `tools.json` entries with `"read_only": true`; named tools and your functions stay),
and `exclude_tools=[…]` drops tools by name — for steps that should research but not generate. Ollama / Strata models with tool support use native tool calling (the workflow runs the
loop); Claude CLI and Codex use native MCP (the CLI runs the loop and calls your Python functions
back in the workflow through the gateway). Ollama models without tool support fall back to the
`[[CALL]]` marker protocol. Identical repeated calls are not run twice. The LangGraph way works
as well:

```python
tools = [my_function, *webui_app.app_tools(["web_search"], skill="civitai-helper")]
llm = webui_app.get_chat_model().bind_tools(tools)
# agent node: {"messages": [llm.invoke(state["messages"])]}; then ToolNode(tools) + tools_condition
```

`app_tools()` and `list_checkpoints()` may also be called at module level (the page answers them
while loading the graph); every other `webui_app` call belongs inside a node.

**Workflows folder.** Default `backend/data/langgraph/` (`LANGGRAPH_DIR`). The card at the top of
the project list shows it; **Change folder** picks another one (inside `BROWSE_ROOTS`, created if
missing) and **Default** goes back. Every subfolder with a `langgraph.json` is a project, so you
can copy project folders in (or keep them in git) and press **Rescan**. In Docker the folder is
`/data/langgraph`; set `LANGGRAPH_HOST_DIR=/home/you/langgraph-projects` in `.env` to mount a host
folder there, and edits made on the host show up right away. Environments, work folders and
run records are kept per workflows folder, so two folders can have projects with the same name.

`docker-compose.yml` mounts each LangGraph folder on its own (all under `backend/data/` by default):

| Host (default) | Container | Holds | Override |
|---|---|---|---|
| `backend/data/langgraph/` | `/data/langgraph` | projects | `LANGGRAPH_HOST_DIR` |
| `backend/data/langgraph-envs/` | `/data/langgraph-envs` | per-project venvs (~90 MB each) and the pip cache | `LANGGRAPH_ENVS_HOST_DIR` |
| `backend/data/langgraph-runs/` | `/data/langgraph-runs` | run history | — |
| `backend/data/langgraph-work/` | `/data/langgraph-work` | each run's working folder (`HOME`) | — |

In Docker, **Change folder** only sees paths inside the container, so a host folder you want to
switch to has to be mounted in `docker-compose.yml` first (anything not mounted is lost when the
container is rebuilt).

**Managing projects.** The list shows each project's dependency state, number of graphs, the
first line of its README and when it last ran; a search box filters by name, description or
graph id. A project can be **renamed** (its run history moves with it), **duplicated** (files
and `.env`, not the history), **exported as zip** (without `.env`, venv and caches — the zip
can be uploaded again) or **deleted** (with its environment and history). After a rename or a
duplicate the dependencies have to be installed again, because editable installs remember the
old path.

**Run history.** Every run — from the page or from the chat's `/workflow` — is saved in
`backend/data/langgraph-runs/` (the last 100 per project): graph, input, engine / model,
source, status, duration, the run's events, output, error and generated images. The **Runs** tab
lists them with thumbnails; opening one replays its steps, path on the flowchart and output, **Run again with this
input** fills the Run tab, and single records or the whole history can be deleted (images
stay). A run that was going when the backend restarted is shown as *interrupted*.

**Flowchart.** The loaded graph is drawn top to bottom (loops route around the side, conditional
edges are dashed and carry their branch names). During a run the running node pulses — parallel
branches light up together — finished nodes turn green with a run count, failed ones red, and
the edges taken are highlighted with how often each was used. Clicking a node lists its events
(updates, LLM replies, images); **Mermaid** copies LangGraph's own Mermaid source. The node-start
signal needs a langgraph with the `tasks` stream mode (any recent release); older ones still
mark nodes as they finish.

**Running.** The page loads the graph (nodes, edges, input / output JSON schema), fills an input
template from the input schema and streams the run: node updates, LLM calls (and how many
images the model looked at), generation progress and images, `emit` notes, custom stream events,
streamed LLM text, `print` output and stderr. The final output follows the graph's output
schema, like `invoke`. Plain text as input goes into `messages` (for `MessagesState` graphs) or
the first text field. **Stop** kills the run with its child processes; runs time out after
`LANGGRAPH_RUN_TIMEOUT` (1800 s), installs after `LANGGRAPH_INSTALL_TIMEOUT` (1200 s).

**Human input (interrupts).** A node can stop and wait for a person with LangGraph's
`interrupt()` — most easily through `webui_app.ask`, which shows a form under the Run button:

```python
answer = webui_app.ask(
    "Check the prompt",
    [{"name": "decision", "label": "Looks right?", "type": "choice", "required": True,
      "options": [{"value": "ok", "label": "Yes"}, {"value": "redo", "label": "No"}]},
     {"name": "feedback", "label": "What to change", "type": "textarea"}],
    message=f"```\n{state['prompt']}\n```", images=[state["image"]],
)
```

Field types are `text`, `textarea`, `select`, `choice` (a row of buttons) and `checkbox`;
options are strings or `{"value", "label"}`, and fields can have `default`, `required`,
`placeholder` and `help`. `message` is Markdown, `images` take `generate_image` results or
`/images/…` URLs. A plain `interrupt(value)` works too: the page shows the value and sends back
the typed text (parsed as JSON when it looks like JSON). The runner gives every graph an
in-memory checkpointer for the run (a graph's own checkpointer is kept), so after the answer the
interrupted node **runs again from the top** and `ask` returns the answer — keep slow or
side-effecting work out of the node before `ask`. The flowchart shows the waiting node in amber,
the run log records each question and answer, and the waiting time does not count towards
`LANGGRAPH_RUN_TIMEOUT` (it is capped at 12 hours; the page keeps the connection open with pings,
so leave it open — closing or reloading it stops the run). Runs started from the chat's
`/workflow` cannot be answered and stop at the first question with a hint to use the page.

**In the chat.** `/workflow` lists the workflows; `/workflow project:graph input` (or just the
graph id when it is unique) runs one with the chat's engine and model: the steps go into the
collapsible process block, generated images show as usual and the output becomes the reply
(for `MessagesState` graphs, the last AI message).

**Safety.** Installing and running execute the project's Python on the server, so both are off
until **Allow running** is pressed on the page (persisted, can be turned off again). The runner
gets a minimal environment with its own `HOME` (the mounted `~/.claude` / `~/.codex` are not
visible), the project's `.env`, and no app secrets. Paths in uploads and the file editor are
confined to the project folder.

The **example** project (`backend/langgraph_examples/example`) has two graphs: `illustrate`
(idea → English scene → danbooru tags → A1111 → the LLM looks at the image and asks for a
redraw with fixed tags when it does not match, at most two pictures) and `chat` (a
`MessagesState` chat graph built on `get_chat_model()`).

The **text2image** template (`backend/langgraph_examples/text2image`, "文字轉圖片workflow") is a
human-in-the-loop text-to-image flow: list A1111's base model families → *you* enter the
keywords and pick a family (optionally a checkpoint) → *you* paste an optional reference
character prompt → the LLM splits the reference into character / clothing / scene and adjusts
them to your keywords → combines everything into a prompt written for that family (Illustrious /
NoobAI tags with `masterpiece, best quality, amazing quality`, Pony `score_9…`, SD 1.5,
SDXL, Anima sentences plus tags, Flux prose) with a negative prompt and the reasons → *you*
review or edit the prompt → A1111 → the LLM checks the image → *you* confirm it. While combining the
prompt the LLM picks read-only MCP tools on its own (`tools="auto", read_only=True`) — e.g. finds an
installed LoRA for the named character made for that base model, reads its trigger words and example
prompts, and adds `<lora:file:0.8>` — and the review form lists what it looked up. Every
"doesn't match" goes back to the splitting step with the feedback. Pick it under **New project**.

## Prompt history (sd-webui-prompt-history)

If you use the A1111 **`sd-webui-prompt-history`** extension, the WebUI can browse and reuse
the generations it has recorded — even though that extension exposes no API. It reads the
extension's data folder directly (`data.json` + per-record `<id>.jpg`), parses each record's
embedded parameters (the **same A1111 format as PNG Info**), and shows a searchable,
paginated thumbnail grid (the 🕘 button in the top bar). Click any record to:

- **Apply to settings** — load its parameters (negative / steps / sampler / seed / size /
  checkpoint) and drop the prompt into the composer as `/image …` for review/editing; or
- **Generate now** — one-click re-render with the record's original prompt and parameters.

Checkpoints not currently loaded in A1111 are skipped automatically. Thumbnails are
downscaled on the fly and cached under `backend/data/history_thumbs/`.

**Enable it** by pointing the backend at that `data` folder — either way works:

- **`PROMPT_HISTORY_DIR`** (env) — set it to the extension's `data` folder. In Docker it is
  bind-mounted **read-only** to a fixed in-container path:
  ```bash
  PROMPT_HISTORY_DIR=/home/youruser/.../extensions/sd-webui-prompt-history/data
  ```
- **Settings panel** — ⚙️ → *Prompt history* → choose the folder. This overrides the env
  default and is persisted server-side. The 🕘 button appears as soon as a folder containing
  `data.json` is detected.

> **Docker note:** the folder picker (and the backend) can only see paths **mounted into the
> container**. Your history lives on the host, so it must be mounted in first — which is
> exactly what setting `PROMPT_HISTORY_DIR` in `.env` does. The in-UI override is mainly for
> local dev, or for switching between several already-mounted folders.

## Character search (WAI / Illustrious)

The 👥 button in the composer opens a searchable picker of anime characters whose danbooru
tags work directly with WAI / Illustrious / NoobAI / Pony checkpoints. Search by name,
series, tag, or nickname — matching is **romanization-tolerant** (long vowels are collapsed,
so `yuko` finds `yuuko`) and **multi-word AND** (`ganyu genshin` works). Then **insert** the
character into the composer or **generate** an image immediately. Most entries carry a full
curated **appearance prompt** (clothing, hair, eyes) for more accurate results.

### Data sources

The list is the **union of three sources, kept without de-duplication** (the searchable
keywords and prompts differ between sources, so the same character may appear more than
once — the richer entry is marked 📝):

| Source | What | License / origin |
|--------|------|------------------|
| **Drawing Spells** | ~14,000 characters **with full appearance prompts**, bundled at `backend/drawingspells_characters.json` | **MIT** © 2025 深海異音 — <https://github.com/hbl917070/DrawingSpells> |
| **danbooru** | up to ~20,000 popular character tags (`category:character`, ordered by post count), fetched in the background on first run and cached at `backend/data/booru_characters_cache.json` | tag data from <https://danbooru.donmai.us> |
| **Built-in seed** | ~120 hand-curated popular characters with series + nickname aliases, at `backend/booru_characters_seed.json` | this project |

The danbooru fetch is **best-effort**: if the site is unreachable, the bundled Drawing
Spells list and the seed still work fully offline. The cache is versioned and refreshes
after 30 days. See `backend/booru_characters.py`.

## Architecture

```
Frontend (React/Vite)  ──/api proxy──▶  Backend (FastAPI)
                                         ├─▶ Ollama      /api/chat (stream + tools + vision)
                                         ├─▶ Claude CLI  claude -p (stream-json subprocess)
                                         ├─▶ Codex CLI   codex exec --json (subprocess)
                                         ├─▶ Strata      /v1/chat/completions (stream + tools, Bearer key)
                                         ├─▶ A1111       /sdapi/v1/{txt2img,img2img,progress,png-info}
                                         ├─▶ MCP tools   Forge /mcp, Civitai Helper /civitai-helper/mcp,
                                         │               sd.cpp /mcp, anime-render /mcp (via the tool gateway)
                                         └─▶ LangGraph   runner.py in each project's venv (stdin/stdout JSON;
                                                         webui_app calls answered with the engines above)
Images are saved to backend/data/images/ and served by the backend at /images/
```

**Agentic loop** (`backend/chat.py`): stream the engine → detect `tool_calls`
(`generate_image`=txt2img / `edit_image`=img2img, called through the MCP gateway; on Claude /
Codex the CLI calls the gateway itself) → poll progress while generating → feed the result back → the model
continues its text reply, all pushed to the frontend over SSE. With an attached image,
the last user message's image is used as the img2img init image; non-vision models have
their `images` stripped automatically.

There is no cap on tool rounds per reply. The only guard is stuck detection: a non-image
tool called again with identical arguments is not re-run (the model is told to use the
earlier result), and three rounds in a row of only such repeats end the tool loop with a
text answer. Image tools are exempt, since "four images from the same prompt" is a valid
request. When a multi-image reply opens the next numbered section (`## Scene N`) and ends
without generating its image, the model is reminded to draw it and continue (again only
after each new image, so a model that refuses cannot loop). Every `image` event is stored
with the length of the text streamed so far (`at`), and the chat renders each image under
that paragraph; older messages without `at` show their images at the end as before.

### Key files

| Path | Description |
|------|-------------|
| `backend/main.py` | FastAPI routes, SSE, static images, engine selection |
| `backend/errors.py` | turns httpx/engine exceptions into readable error messages (which host timed out, HTTP status + body) |
| `backend/chat.py` | agentic tool loop (no round cap; stuck detection; "draw the scene you just wrote" reminder); Claude / Codex runs with the MCP gateway attached, merging the CLI stream with the gateway's UI events |
| `backend/tools.py` | tool schemas: `generate_image` / `edit_image` / `read_png_info` / `web_search` / `fetch_url`; model-written tags are de-duplicated (no count or length cap) |
| `backend/ollama_client.py` | Ollama engine (chat stream, models, capabilities, context length, thinking switch with automatic no-thinking retry + user notices, unload / reload a model with the chat's `num_ctx`) |
| `backend/claude_client.py` | Claude CLI engine (subprocess `claude -p` stream-json; tools via native MCP: `--mcp-config` with the gateway session) |
| `backend/codex_client.py` | OpenAI Codex CLI engine (subprocess `codex exec --json`; chat + vision via `-i`; tools via native MCP, built-in tools off) |
| `backend/comics_store.py` | Comic projects + storyboard versions persisted in SQLite (`DATA_DIR/comics.db`) for the Comic Studio library |
| `backend/comic.py` | Comic storyboard: premise + cast → panels (scene tags, English sentences for Anima, expression, dialogue, caption) as strict JSON; the comic's skills plus a Comic Studio adapter note; lenient JSON parsing with retries; per-panel tag regeneration; character-name matching |
| `backend/story.py` | Image Story: uploaded image(s) → short story, a full comic script (cast, style, premise, panels), or per-image panel text (describe each image, then write the script) |
| `backend/expression_tags.py` | danbooru expression-tag whitelist (+ synonym map for off-list words) shared by the storyboard prompt and the LoRA trigger filter |
| `frontend/src/comic/` | Comic Studio page (script panel, character cards, panel cards, page layout, PNG export, library modal, storyboard versions); `bubbleShape.js` = bubble geometry shared by the page preview and the PNG export, `names.js` = lenient character-name matching, `notices.js` = backend notice texts |
| `frontend/src/store/comic.js` | Comic Studio state: storyboard, cards, panels, bubbles, autosave to the server, versions cache, per-panel tag regeneration |
| `frontend/src/story/` | Image Story page (upload, mode/options, result view, hand-off to Comic Studio); state in `frontend/src/store/story.js`, API in `frontend/src/lib/storyApi.js`, client-side downscaling in `frontend/src/lib/image.js` |
| `backend/a1111_client.py` | A1111 over its MCP tools: txt2img / img2img / progress / models / samplers / LoRAs / png-info; adds the Forge extra modules (text encoder / VAE) an Anima checkpoint needs, and puts Forge's error reason into the exception |
| `backend/mcp_client.py` | MCP client (official SDK) for Forge's `/mcp`, Civitai Helper's `/civitai-helper/mcp`, sd.cpp's and anime-render's `/mcp`: tool lists (cached; unreachable servers skipped for 20 s), calls with progress, plain-language errors (wrong token, no MCP, unreachable), connection test |
| `backend/tool_gateway.py` | The app's MCP tool gateway: per-conversation tool list and calls for chat and workflows; streams UI events, returns text and images for the model |
| `backend/mcp_lite.py` | Small MCP server (Streamable HTTP, no dependencies) — the same implementation as Forge's and Civitai Helper's — used by the gateway |
| `backend/strata_client.py` | Strata engine: OpenAI-compatible `/v1/chat/completions` (streaming, tool calls, `reasoning_content`), messages converted from the app's Ollama format, Bearer API key from the settings, model list / context from `/v1/models` |
| `backend/web_tools.py` | web search (DuckDuckGo/SearXNG) + page extraction (with SSRF guard) |
| `backend/langgraph_store.py` | LangGraph projects in the (switchable) workflows folder: `langgraph.json` parsing, files (write-only `.env`), folder / zip upload, rename / duplicate / zip export, per-project venv install from `dependencies` |
| `backend/langgraph_history.py` | LangGraph run history: one JSON record per run (input, events, output, images), last 100 per project, interrupted runs detected after a restart |
| `backend/langgraph_exec.py` | Runs / inspects a graph in the project's venv, turns runner events into SSE, answers `webui_app` calls (LLM with images, A1111, web search), masks `.env` values, cancel / timeout |
| `backend/langgraph_runtime/` | `runner.py` (loads the graph from `langgraph.json`, streams updates / tasks / custom / values / messages, adds an in-memory checkpointer and waits for interrupt answers) and `webui_app.py` (the module graphs import) — run inside the project's venv |
| `backend/langgraph_examples/example/` | Bundled example project (`illustrate` with a visual check loop, `chat`) |
| `frontend/src/workflow/` | LangGraph workflows page (projects, upload, install log, graph inspect, input, live run view, file editor); state in `frontend/src/store/workflow.js`, API in `frontend/src/lib/workflowApi.js` |
| `backend/settings_store.py` | persisted settings: image dir (default stored as empty so the host and the container resolve their own path) + service sources + web provider + prompt-history dir + skill prompt length limit + the LangGraph "Allow running" switch and workflows folder |
| `backend/prompt_history_store.py` | reads the `sd-webui-prompt-history` extension's `data.json` + thumbnails (cached, paginated, searchable) |
| `backend/booru_characters.py` | character keyword search (Drawing Spells + danbooru + seed; fuzzy/alias matching) |
| `backend/docker_probe.py` | best-effort container listing via the docker socket |
| `backend/skills_store.py` | skill discovery / SKILL.md parsing / prompt injection (pinned or Auto) + runtime-adapter note |
| `backend/skill_tools.py` | skill tools: `tools.json` MCP tools (Forge / Civitai Helper / sd.cpp / anime-render; attached image in, result images and progress out), HTTP tools, fixed-script tools, and the `run_skill_script` runner (sandboxed env, work folder, timeout, secret masking) |
| `backend/civitai_cards.py` | `civitai_models` postprocess: Civitai search results → model summary + result cards (thumbnails cached in `DATA_DIR/civitai-cache/`) |
| `backend/civitai_examples.py` | `civitai_examples` postprocess: Civitai Helper example images → chat gallery + downscaled vision images for the model |
| `backend/civitai_images.py` | `civitai_images` postprocess: civitai image search → chat gallery (prompts, parameters, author, LoRAs used) + numbered summary with image ids |
| `backend/loras.py` | LoRA list for the browser (A1111 + Civitai Helper source), thumbnails, examples, download / delete, and the `lora_inventory` postprocess that filters the model's LoRA inventory by category / base |
| `backend/lora_meta.py` | LoRA base-model grouping / inference, Civitai source, content categories (Civitai model tags, fetched only on request, cached in `DATA_DIR/civitai-cache/model_tags.json`) |
| `backend/a1111_memory.py` | `a1111_memory` postprocess: A1111 RAM / VRAM figures → readable GB summary |
| `frontend/src/store/chat.js` | zustand state + streaming coordination + persistence |
| `frontend/src/lib/api.js` | SSE parsing, storage/browse/sources/engine calls |
| `frontend/src/lib/clipboard.js` | copy to clipboard with a fallback for plain-HTTP LAN pages |
| `frontend/src/i18n.js` | 5-language dictionary + `useT()` hook |
| `frontend/src/components/` | UI components (TopBar, Composer, Message, ImageBlock, PngInfoModal, HistoryModal, CandidateCards, ExampleGallery, pickers, panels) |

## Configuration

Copy `.env.example` and override via environment variables (addresses incl. the optional
`SDCPP_URL`, `MMD_URL` and `STRATA_URL`, the MCP tokens, default model,
timeouts, Claude / Codex credentials and model lists (`CLAUDE_MODELS`, `CODEX_MODELS`),
prompt-history folder, skills folder and script settings `SKILLS_DIR` / `SKILL_MAX_CHARS` /
`SKILL_SCRIPT_ENV` / `SKILL_SCRIPT_TIMEOUT`, LangGraph folders and limits `LANGGRAPH_DIR` /
`LANGGRAPH_ENV_DIR` / `LANGGRAPH_RUNS_DIR` / `LANGGRAPH_WORK_DIR` / `LANGGRAPH_RUN_TIMEOUT` /
`LANGGRAPH_INSTALL_TIMEOUT`, host mounts `LANGGRAPH_HOST_DIR` / `LANGGRAPH_ENVS_HOST_DIR`, pip
source `PIP_INDEX_URL` / `PIP_EXTRA_INDEX_URL`). In dev mode the frontend proxy target is in
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
- On the CLI engines (Claude and Codex), the web-search tools are not available — they are
  only wired to the Ollama engine.

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

### Third-party data

The bundled character list `backend/drawingspells_characters.json` is derived from
**[Drawing Spells](https://github.com/hbl917070/DrawingSpells)** — **MIT License**,
© 2025 深海異音 — used here under the terms of the MIT License. Character tags fetched at
runtime come from **[danbooru](https://danbooru.donmai.us)**. See
[Character search](#character-search-wai--illustrious).

---
name: Civitai Helper
description: "Manage the local Stable Diffusion model library through the Civitai Helper extension API: list installed LoRAs / checkpoints / embeddings with their trigger words, look up a civitai model by URL or id, download a model version into the WebUI, scan for missing civitai info and preview images, and check which installed models have newer versions. Use when the user mentions civitai, pastes a civitai link, asks to download or install a LoRA / model, asks for trigger words, or asks what models are installed."
---

# Civitai Helper

You manage the models of the app's LOCAL Stable Diffusion WebUI (Forge / A1111) through the **Civitai Helper** extension. This skill comes with real API tools (see the tool list the app gives you); the app performs the HTTP calls and hands you the results. You never touch files yourself.

Model types used by every tool: `lora` (LoRA), `ckp` (checkpoint), `ti` (textual-inversion embedding), `hyper` (hypernetwork).

## What each tool is for

- `civitai_lora_inventory` — every installed LoRA with its `prompt_tag`, civitai name / version / base model / trigger words, and training metadata from the file (base model version, top training tags). Use `q` to search by name, trigger word or training tag; results are paged (`limit`, `offset`).
- `civitai_list_local_models` — what is installed for the other types (checkpoints, embeddings, hypernetworks), with trigger words. Use `q` to search by name or trigger word.
- `civitai_local_model_info` — full civitai details of ONE installed model (by file name).
- `civitai_lookup_model` — inspect a civitai model by id or page URL before downloading (versions newest first).
- `civitai_download_model` — download a version into the right model folder (+ info file + preview).
- `civitai_scan_models` — fetch missing civitai info / previews for models already on disk (SHA256 match).
- `civitai_check_new_versions` — find installed models that have a newer version on civitai.
- `civitai_task_status` — poll a long-running download / scan / check by task id.
- `refresh_loras` / `refresh_checkpoints` — make the WebUI see newly downloaded files.

## Workflows

**"What LoRAs do I have?" / "trigger words for X" / "which LoRA for X?"** → `civitai_lora_inventory` (optional `q`; use it for anything more specific than "list everything"). Answer with a short list: file name, model name, base model, trigger words, and the `prompt_tag` (suggest a weight like `:0.8`). If a LoRA has no civitai record, use `training.base_model_version` and `training.top_tags` to describe it. If `total` is larger than what you received, say how many there are and offer to narrow with `q`.

**"What checkpoints / embeddings do I have?"** → `civitai_list_local_models` with the type.

**User pastes a civitai link or asks about a model** → `civitai_lookup_model`. Summarize: name, type, newest version + base model, trigger words, file size, creator, and say if it is NSFW. If they did not ask to install it, stop there and offer to download.

**"Download / install this"** →
1. `civitai_lookup_model` first (unless you already looked it up this conversation).
2. Confirm the choice only when it is ambiguous: several versions with different base models, or a subfolder was mentioned. Otherwise take the newest version and the folder root (`subfolder: "/"`).
3. `civitai_download_model` with `url_or_id` (+ `version_id` / `subfolder` if chosen).
4. Read `status`:
   - `done` → report `result.file`, trigger words, then call `refresh_loras` (LoRA) or `refresh_checkpoints` (checkpoint). Finish with a ready-to-use prompt snippet that includes the LoRA tag + trigger words.
   - `running` → the download continues in the background; tell the user, remember the task `id`, and use `civitai_task_status` when they ask (or when you need the file for the next step).
   - `error` → relay the message. A login / API-key error means the civitai API key must be set in the WebUI: Settings → Civitai Helper → "Civitai API Key". "already existed" means it is installed already.

**"Fill in missing info / previews" or "I copied some models manually"** → `civitai_scan_models` with the types. Report the counts.

**"Any updates for my models?"** → `civitai_check_new_versions`. List model → new version; offer to download (use `model_id` + `new_version_id`).

## Rules

- Never download without an explicit user request to download / install / get the model. Looking up is always fine.
- One tool call at a time; wait for the result before deciding the next step. Do not invent results.
- Keep replies short and in the user's language. Do not paste raw JSON; extract what matters (names, versions, trigger words, file names, errors).
- Model files can be large; do not repeat a download that is already `running` or `done`.
- If a tool reports it cannot reach the API, tell the user the WebUI must be running with the Civitai Helper extension (its API lives at `/civitai-helper/v1` on the WebUI) and stop.
- When the user then wants an image with the new LoRA, generate it with the app's image capability using the LoRA tag + trigger words in the prompt.

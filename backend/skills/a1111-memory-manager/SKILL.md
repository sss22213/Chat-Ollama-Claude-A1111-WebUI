---
name: A1111 Memory Manager
description: "Check and free the memory used by the A1111 / Forge WebUI image generator: show RAM / VRAM usage, unload the checkpoint from VRAM (keeps it in RAM for a fast restart) or fully (frees RAM too), and load it back. Use when the user asks about memory, VRAM, GPU usage, out-of-memory errors, wants to free the GPU for another model (Ollama, sd.cpp image editing, games), or wants the checkpoint reloaded."
---

# A1111 Memory Manager

The app's image generator is an A1111 / Forge WebUI. It shares one GPU with Ollama (the chat model) and the stable-diffusion.cpp server (image editing). These tools let you inspect and free A1111's share.

## Tools

- `a1111_memory` — current state: system RAM, the whole GPU (all programs), A1111's own VRAM, whether the checkpoint is on the GPU, OOM count.
- `a1111_unload_checkpoint` — free memory.
  - `full: false` (default) — frees **VRAM only**; the model stays in RAM, so the next generation starts fastest. Use this to make room on the GPU.
  - `full: true` — frees **VRAM and RAM**; the next generation re-reads the model file automatically (slower). Use only when the user wants RAM back too, or asks for a full unload.
- `a1111_reload_checkpoint` — load the checkpoint back into memory now (useful after a full unload, so the next generation skips reading the file). On Forge the weights go onto the GPU only when the next image is generated, so VRAM does not rise right after a reload — that is normal, not a failure.

## How to act

- "How much memory / VRAM is used?" → `a1111_memory`, then answer in a few lines: GPU used / free, how much of it is A1111's, whether the checkpoint is loaded. Note that the GPU total includes Ollama and sd.cpp, so A1111 unloading may not free everything.
- "Free the GPU / VRAM", "image editing ran out of memory", "make room for another model" → `a1111_unload_checkpoint` with `full: false`, then report how much VRAM is free now. A1111 only holds VRAM after it has generated something (about 7 GB for an SDXL checkpoint); if `a1111_memory` shows it already holds ~0 GB, unloading will not free more — the rest of the GPU belongs to Ollama / sd.cpp.
- "Free everything / RAM too / full unload" → `a1111_unload_checkpoint` with `full: true`.
- "Load the model back / warm it up" → `a1111_reload_checkpoint`; tell the user the model is ready in memory and will move to the GPU at the next generation.
- Generating an image after an unload is fine: A1111 loads the model again by itself (a few seconds for a VRAM-only unload, longer after a full unload). You do not need to reload before generating unless the user asks.

## Rules

- Only unload or reload when the user asks for it, or when they report an out-of-memory problem and agree to free memory. Checking memory is always fine.
- One call at a time; report numbers from the tool result, never invent them.
- Keep replies short and in the user's language; round to one decimal GB.
- If a tool cannot reach A1111, say the WebUI is not reachable and stop.

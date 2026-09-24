# A1111 / Forge prompt syntax cheat sheet

| Syntax | Effect |
|---|---|
| `tag1, tag2, tag3` | comma-separated tags; earlier = stronger |
| `(tag)` / `((tag))` | ×1.1 / ×1.21 |
| `(tag:1.3)` | explicit weight (0.5–1.5 sensible) |
| `[tag]` | ×0.9 |
| `[from:to:0.5]` | switch from `from` to `to` at 50 % of the steps |
| `[a|b]` | alternate a / b every step |
| `BREAK` | starts a new 75-token chunk (separate concepts, e.g. two characters) |
| `\(` `\)` | literal parentheses inside a tag name |
| `<lora:file:0.8>` | apply LoRA `file.safetensors` at weight 0.8 (models/Lora) |
| `<lyco:file:0.8>` | same for LyCORIS files in the LyCORIS folder (older WebUIs) |
| `<hypernet:file:0.8>` | hypernetwork |
| `embedding_name` | textual-inversion embedding: just write its file name as a tag (often used in the negative prompt) |

Checkpoint families and what they expect:

| Family | Quality tags | Notes |
|---|---|---|
| Illustrious / NoobAI / WAI | `masterpiece, best quality, very aesthetic, absurdres` | danbooru tags, character names as `name \(series\)` work well |
| Pony Diffusion V6 | `score_9, score_8_up, score_7_up` first, then `source_anime` / `rating_safe` | needs the score tags |
| Animagine XL | `masterpiece, best quality, very aesthetic` | year tags like `newest` |
| SD 1.5 anime | `masterpiece, best quality` | 512–768 px; SD1.5 LoRAs only |

LoRA weight guide: style 0.6–0.8 · character / costume 0.8–1.0 · concept / pose 0.7–1.0 · detail / slider LoRAs as documented (can be negative) · when stacking, keep the total ≈1.5.

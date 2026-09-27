---
name: SD Prompt Guide (Anima)
description: "How to write prompts for this app's local Stable Diffusion WebUI (Forge Neo) when the checkpoint is an Anima model — by default WAI-ANIMA (waiANIMA_v10Base10); also One Obsession Anima 2.9B and Anima base. Anima uses a Qwen3 text encoder, not SDXL: danbooru tags mixed with natural language, quality and safety tags first, @artist tags, stronger weights, the checkpoint's own negative prompt, and Anima-only LoRAs. Use whenever the user wants an image generated with an Anima checkpoint, asks to use a LoRA on Anima, or asks how to write or improve an Anima prompt."
---

# SD Prompt Guide (Anima)

The images are rendered by a LOCAL Stable Diffusion WebUI (Forge Neo) with an **Anima** checkpoint. Unless the user says otherwise it is **WAI-ANIMA** (`waiANIMA_v10Base10`), a fine-tune of the Anima base model. Anima is **not** SDXL: it has a Qwen3 language-model text encoder, reads danbooru tags **and** plain English, and puts quality and safety tags first. SDXL / Illustrious / Pony habits (quality tags at the end, `score_9, score_8_up`, small weights, `BREAK`, embeddings) do not carry over.

The image tool takes a `prompt` (and optional `negative_prompt`, `width`, `height`); the app controls steps, sampler, CFG and seed, and loads Anima's text encoder and VAE by itself. This skill tells you what to put in `prompt` and `negative_prompt`. The image tool's own description says "tags, not sentences" — with Anima, a sentence or two after the tags is fine and often better.

## Checkpoint presets

| Checkpoint | Quality prefix (start of `prompt`) | `negative_prompt` |
|---|---|---|
| **WAI-ANIMA** (`waiANIMA_v10Base10`, default) | `masterpiece, best quality, score_7` | `worst quality, low quality, score_1, score_2, score_3, artist name, blurry, jpeg artifacts, lowres, censor` |
| One Obsession Anima 2.9B (`oneObsession_anima29BV1`) | `masterpiece, best quality, amazing quality, very awa, absurdres, newest, very aesthetic, depth of field, highres` | `worst quality, normal quality, anatomical nonsense, bad anatomy, interlocked fingers, extra fingers, watermark, simple background, transparent, low quality, logo, text, signature, face backlighting` |
| Anima base (`anima-base-…`) | `masterpiece, best quality, score_7` | `worst quality, low quality, score_1, score_2, score_3, artist name, blurry, jpeg artifacts, chromatic aberration` |

Use the row of the checkpoint the user named; otherwise WAI-ANIMA. Drop `depth of field` from the One Obsession prefix when the background has to stay sharp (landscapes, detailed rooms, groups spread across the picture). Do not add other quality or "detail" tags (`8k`, `ultra detailed`, `hyperrealistic`, more `score_*`).

## Tag format

- Tags are lowercase with **spaces, not underscores** (`long hair`, `school uniform`). Score tags are the only exception: `score_7`.
- Use this order:
  1. **quality prefix** from the table, then one **safety tag**, then optional meta / time tags: `official art`, `anime screenshot` (looks like a frame from an anime episode), `newest`, `recent`, `mid`, `early`, `old`, `year 2025` (the One Obsession prefix already has `newest`).
  2. **count**: `1girl`, `1boy`, `1other`, `2girls`, `1girl, 1boy`, `no humans`; add `solo` when alone.
  3. LoRA tag(s) + their trigger words (see below).
  4. **character**, then **series**, as two separate tags: `hatsune miku, vocaloid`.
  5. **artist**, written with `@` in front: `@artist name`. Without the `@` the model does not read it as an artist. Only use an artist the user named.
  6. **general tags**: appearance (hair, eyes, body), clothing and accessories, expression, pose / action, other people and animals, objects, place, time of day, weather, lighting, composition / camera (`upper body`, `full body`, `from above`).
- **Natural language**: after the tags you may add one or two plain English sentences for what the tags cannot say well — who does what, where things are, the mood. Use normal capitalization for names in sentences ("Hatsune Miku waves at the crowd"). With several characters, name each one and describe their look right after the name, so features do not mix. Write the sentence fresh from the user's request every time. A prompt in pure natural language should be at least two descriptive sentences; short vague prompts give random results.
- Every visible thing that matters goes into the **tags**, not only into the sentence, e.g. the outfit (`cardigan, long skirt`). What the tags leave open, the model fills with its own defaults — an unspecified girl's outfit often becomes a school uniform.
- Never repeat a tag. No names of real people.
- **Weights** work but need more than on SDXL: `(tag:1.5)` to `(tag:2)` for the one or two things that must win (`(chibi:2)`); `1.1`–`1.3` barely changes anything. Parentheses that belong to a tag are escaped: `\(`, `\)`.
- Do not use `BREAK` or SDXL / SD 1.5 embedding names.
- Anima is an anime model and cannot render text beyond a single word: keep dialogue and titles out of the prompt. One Obsession leans a little towards a 2.5D look; add `anime coloring` or `anime screenshot` when the user wants flat anime. For photorealism, tell the user to switch to another checkpoint.
- The anime training data ends in **September 2025**: characters from later series are unknown to it — describe their look with tags, or use a LoRA.

## Negative prompt

The app adds its own negative prompt from the image settings, and your `negative_prompt` is appended to it. Always pass the `negative_prompt` of the checkpoint from the table. When the user wants something specific excluded, add only those few tags.

## Size

WAI-ANIMA: portrait 832×1216, 896×1152 or 1024×1344 (the size of the author's examples); landscape 1216×832, 1152×896 or 1344×1024; square 1024×1024. Anima works up to about 1536 on the long side; One Obsession also lists 768×1344, 1024×1536 and 640×1536. Portrait for one standing character, landscape for scenery and groups.

## Using a LoRA (IMPORTANT)

A LoRA is only applied when its tag is **inside the prompt**: `<lora:FILENAME:WEIGHT>`.

- **Only Anima LoRAs work on Anima.** LoRAs made for Illustrious, NoobAI, Pony, SDXL or SD 1.5 are a different architecture and do nothing on it. Never use one as a fallback.
- `FILENAME` = the LoRA file name **without** `.safetensors`, exactly as the user, the LoRA browser or a tool result gives it. Never guess or "prettify" a file name.
- `WEIGHT` = `0.6` to `1` (`0.8` is a good default; `0.5`–`0.6` when mixing several LoRAs). Keep the sum of weights around `1.5` or lower. Anima LoRAs are trained on the Anima base model, so on a fine-tune like WAI-ANIMA or One Obsession start at `0.8` and raise it if the character does not come through.
- Put the tag right after the count tag, then the LoRA's **trigger words**, each part separated by commas: `..., 1girl, solo, <lora:file:0.8>, trigger word, ...`. A missing comma glues the tag to the next word.
- `trained_words` often holds several groups: the first is usually the character itself (name, hair, eyes), the others are alternative outfits. Use the first group plus at most one outfit group that fits the request. Keep tags such as `anime screencap` that the LoRA was trained with.
- The LoRA tag goes in `prompt` only, never in `negative_prompt`.
- Characters that were popular before September 2025 often work with only their character and series tags, no LoRA needed.
- If the user asks "why did the LoRA not work": check that it is an Anima LoRA (base `Anima`), the file name is exact, the tag is in the prompt with commas around it, the trigger words are present and the weight is not too low.

Example for WAI-ANIMA with an Anima LoRA `my_oc_anima` (trigger words `mira, short hair, black hair, red eyes`) in a scene the user described:

```
masterpiece, best quality, score_7, newest, 1girl, solo, <lora:my_oc_anima:0.8>, mira, short hair, black hair, red eyes, white sweater, long skirt, sitting, reading book, cup of coffee, smile, cafe, window, rain, indoors, warm lighting, upper body. Mira sits by the rainy window of a small cafe, reading a book with a cup of coffee in front of her.
```

Without a LoRA the prompt is written the same way, only without the LoRA tag and trigger words.

## Finding LoRAs

- If the user pasted a `<lora:...>` tag or trigger words, use them as-is (check it is an Anima LoRA when you can).
- If the **Civitai Helper** skill is active, call `civitai_lora_inventory` with `base: "Anima"` (plus `category` and a short `q` when needed). Anima LoRAs are few, so one call with `base: "Anima"` and no `q` usually lists them all; pick from that list. Do not search other bases.
- A `character` LoRA draws that one character: use it only when the user asks for that character, never as a stand-in for a generic subject ("a knight", "a maid").
- If no Anima LoRA fits, generate without one and say so. If the **civitai-api** skill is active, you can search civitai.com for Anima LoRAs (base model "Anima"), but a LoRA must be installed before its tag works; offer to download it with Civitai Helper.
- Otherwise ask the user for the file name and trigger words (they can copy both from the app's LoRA browser, the **LoRA** button with the layers icon next to the chat input; filter it by the base model Anima). Do not invent a LoRA.

## Reply style

Write one short sentence, then call the image tool (with the checkpoint's negative prompt). When the user asks for the prompt text itself, give the full prompt and the negative prompt in code blocks and say which Anima checkpoint they are for. Answer in the user's language; keep tags and the natural-language part in English.

If the image tool fails with an error from the image server (HTTP 500, "Failed to load …", a missing text encoder or VAE), the prompt is not the cause: do not retry with a shorter or changed prompt. Tell the user the error in one or two sentences and stop.

## Settings the app cannot set from here

Anima wants different sampler settings than SDXL. WAI-ANIMA: sampler **Euler a**, **20–30** steps, CFG **4–5**; hires fix at most 1.5× (20 steps, R-ESRGAN 4x+ Anime6B, denoising 0.35–0.5). One Obsession: Euler a, 25–35 steps, CFG 3–6. Anima base: 30–50 steps, CFG 4–5. These live in the app's image settings, not in the prompt; if images come out burnt, over-saturated or noisy, tell the user to check them there.

If One Obsession (Anima 2.9B) returns pure noise whatever the prompt, the WebUI is too old for Anima 2.9B: Forge Neo before August 2026 loads only 28 of its 40 blocks. The user has to update Forge Neo (2.9B support also remaps 2B Anima LoRAs onto it); until then use WAI-ANIMA or Anima base.

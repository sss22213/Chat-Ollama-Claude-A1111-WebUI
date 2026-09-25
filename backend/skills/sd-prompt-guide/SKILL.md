---
name: SD Prompt Guide
description: "How to write prompts for this app's local Stable Diffusion (A1111 / Forge, SDXL / Pony / Illustrious anime checkpoints): danbooru tag format and ordering, tag weights, negative prompt, and how to use LoRA — put <lora:filename:weight> (weight 0.6–1) together with the LoRA's trigger words in the prompt. Use whenever the user wants an image generated, asks to use / apply / add a LoRA, mentions trigger words, asks why a LoRA did not take effect, or asks how to write or improve a prompt."
---

# SD Prompt Guide

Every image in this app is rendered by a LOCAL Stable Diffusion WebUI (A1111 / Forge) with SDXL-family anime checkpoints (Illustrious / NoobAI / Pony / WAI). The image tool takes a `prompt` (and optional `negative_prompt`, `width`, `height`); the app controls steps, sampler, CFG and seed. This skill tells you what to put in `prompt`.

## Tag format

- Comma-separated English **danbooru-style tags**, not sentences: `1girl, solo, silver hair, long hair, blue eyes, school uniform, cherry blossoms, outdoors, looking at viewer, smile`.
- Spaces inside a tag are fine (`school uniform`); do not use underscores unless it is a trigger word given with underscores.
- Order matters (earlier tags weigh more). Use this order:
  1. subject count: `1girl`, `2girls`, `1boy`, `1girl, 1boy`, `no humans`
  2. LoRA tag(s) + their trigger words (see below)
  3. character / appearance: hair, eyes, body, age words
  4. clothing and accessories
  5. pose, expression, action, gaze (`looking at viewer`, `sitting`, `smile`)
  6. scene / background / lighting / time (`night, city lights, rain`)
  7. composition / camera (`upper body`, `full body`, `from above`, `dutch angle`)
  8. quality tags, exactly `masterpiece, best quality, amazing quality` (the WAI-illustrious author's recommendation)
- There is no limit on the number of tags: use as many as the image needs to describe the subject, clothing, pose and scene. Never repeat a tag. No names of real people.
- Do not add more quality / aesthetic tags than the three above (`very aesthetic`, `absurdres`, `highres`, `ultra detailed`, `8k`, …): piling them on makes the image blurrier, not better.
- Weight a tag with `(tag:1.2)` (1.1–1.4 to strengthen, 0.6–0.9 to weaken). Parentheses inside a tag must be escaped: `\(`, `\)` — e.g. `hatsune miku \(vocaloid\)`.
- Pony-based checkpoints like the leading `score_9, score_8_up, score_7_up`; Illustrious / NoobAI do not need them. Only add them when the user says the checkpoint is Pony.
- Negative prompt: the app already applies a curated one. Only pass `negative_prompt` when the user wants something specific excluded (e.g. `text, watermark, extra fingers`), at most 15 tags. A long negative prompt also makes the image blurrier.
- Size: 1024×1024 square, 832×1216 portrait, 1216×832 landscape (multiples of 64). Pick by subject (portrait for one standing character, landscape for scenery / groups).

## Using a LoRA (IMPORTANT)

A LoRA is only applied when its tag is **inside the prompt**. The syntax is

```
<lora:FILENAME:WEIGHT>
```

- `FILENAME` = the LoRA file name **without** `.safetensors`, exactly as the user, the LoRA browser, or a tool result gives it (case, hyphens and underscores included). Never guess or "prettify" a file name; if you only know a Civitai model name, find the installed file first (see "Finding LoRAs").
- `WEIGHT` = `0.6` to `1` for normal use (`0.8` is a good default; `1` when the user wants the full effect; `0.5–0.6` when mixing several LoRAs or when it overpowers the image). Style LoRAs usually take `0.6–0.8`, character / costume LoRAs `0.8–1`.
- Put the tag near the front of the prompt, right after the subject count, then a comma, then the LoRA's **trigger words** as their own comma-separated tags (the words the LoRA was trained on). Without trigger words many LoRAs do nothing.

Example, user has `jp_school_uniform` with trigger words `school uniform, jp_school_uniform`:

```
1girl, solo, <lora:jp_school_uniform:0.8>, school uniform, jp_school_uniform, brown hair, twintails, smile, classroom, window light, upper body, masterpiece, best quality, amazing quality
```

- Several LoRAs: one tag each, keep the sum of weights around `1.5` or lower (`<lora:styleA:0.6>, <lora:charB:0.8>`), and include each one's trigger words.
- **The LoRA tag is one tag like any other**, so it is separated from its neighbours by commas on both sides: `..., <lora:file:0.8>, trigger word, ...`. A missing comma glues the tag to the next word and the WebUI misreads both.
  - correct: `1girl, <lora:jp_school_uniform:0.8>, school uniform, brown hair`
  - wrong: `1girl <lora:jp_school_uniform:0.8> school uniform, brown hair` / `1girl, <lora:jp_school_uniform:0.8> school uniform, brown hair`
- The LoRA tag goes in `prompt` only, never in `negative_prompt`. Do not wrap it in quotes, brackets or parentheses.
- If the user asks "why did the LoRA not work": check the file name is exact, the tag is in the prompt (not just mentioned), the trigger words are present, the weight is not too low, and the LoRA matches the checkpoint family (an SD1.5 LoRA does nothing on SDXL / Illustrious; a Pony LoRA works poorly on Illustrious and vice versa).

## Finding LoRAs

- If the user pasted a `<lora:...>` tag or trigger words, use them as-is.
- If the **Civitai Helper** skill is active, call `civitai_lora_inventory` (with `q` to search) — it returns the exact `prompt_tag`, trigger words and base model of every installed LoRA. Use `civitai_model_examples` for an example prompt from Civitai.
- Pick by base model. The checkpoint is Illustrious-based (WAI-illustrious-SDXL), so prefer LoRAs whose `civitai.base_model` is **Illustrious** or **NoobAI**. A **Pony** LoRA works poorly on it, and an **SD 1.5** LoRA does nothing. If a LoRA has no civitai record, check `training.base_model_version`: SD 1.5 there means it will not work; plain SDXL usually does not tell Illustrious from Pony, so treat it as uncertain. If the only match is a Pony or uncertain LoRA, say so when you use it.
- Do not keep re-searching: call `civitai_lora_inventory` **at most twice** per request (one specific `q`, then at most one broader `q`; never page through the whole list hoping to spot one). If those find no suitable LoRA, stop searching: ask the user which LoRA to use, or generate without a LoRA and say that none was found.
- If the **civitai-api** skill is active, you can search civitai.com for candidates, but a LoRA must be installed in the WebUI before its tag works; offer to download it with Civitai Helper.
- Otherwise ask the user for the file name and trigger words (they can copy both from the app's LoRA browser, the **LoRA** button with the layers icon next to the chat input). Do not invent a LoRA.

## Reply style

Write one short sentence, then call the image tool. When the user asks for the prompt text itself, give the full comma-separated prompt in a code block (LoRA tag + trigger words included) and say which checkpoint family it targets. Answer in the user's language; keep tags in English.

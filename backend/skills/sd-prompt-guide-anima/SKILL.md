---
name: SD Prompt Guide (Anima)
description: "How to write prompts for this app's local Stable Diffusion WebUI (Forge Neo) when the checkpoint is an Anima model — by default WAI-ANIMA (waiANIMA_v10Base10); also One Obsession Anima 2.9B and Anima base. Anima uses a Qwen3 text encoder, not SDXL, and understands English sentences: a short head (quality prefix, trigger word or character, safety tag), then a natural-language description of the character, outfit, action and place, then a full danbooru tag list of the same picture, with the LoRA tag at the end. Covers @artist tags, stronger weights, the checkpoint's own negative prompt and Anima-only LoRAs. Use whenever the user wants an image generated with an Anima checkpoint, asks to use a LoRA on Anima, or asks how to write or improve an Anima prompt."
---

# SD Prompt Guide (Anima)

The images are rendered by a LOCAL Stable Diffusion WebUI (Forge Neo) with an **Anima** checkpoint. Unless the user says otherwise it is **WAI-ANIMA** (`waiANIMA_v10Base10`), a fine-tune of the Anima base model. Anima is **not** SDXL: its text encoder is the Qwen3 language model, so it reads **plain English sentences as well as danbooru tags**, and it was trained on captions that combine both. SDXL / Illustrious / Pony habits (tags only, quality tags at the end, `score_9, score_8_up`, small weights, `BREAK`, embeddings) do not carry over.

The image tool takes a `prompt` (and optional `negative_prompt`, `width`, `height`); the app controls steps, sampler, CFG and seed, and loads Anima's text encoder and VAE by itself. This skill tells you what to put in `prompt` and `negative_prompt`. The image tool's own description says "tags, not sentences" — for Anima, ignore that and follow this skill.

## Prompt structure

Write every prompt in this order, all in one line:

1. **Head** — the quality prefix of the checkpoint (table below); if a LoRA is used, its **trigger word** exactly as trained (underscores and all); otherwise the character's name when it is a known character; then the safety tag (e.g. `safe`).
2. **Description** — 2 to 5 English sentences about the picture: who it is (use the trigger word or the character's name as the subject, or "a woman with …" for an original character), the **appearance** (hair length, colour and style, eyes, notable features), the **outfit** piece by piece, the **action and pose**, the **expression**, the **place and background** with its notable objects, the **time of day, weather and light**, and the **framing** ("Full body.", "Upper body, seen from below."). Concrete and visual, present tense, third person.
3. **Tag list** — the same picture again as lowercase danbooru tags with spaces (`long hair`, not `long_hair`): the count first (`1girl`, `1boy`, `2girls`, `1girl, 1boy`, `no humans`, plus `solo` when alone), then the expression, the character and series tags, hair and eyes, every clothing item, the pose and action, the objects, the place, time and weather, the lighting and the camera tag (`full body`, `cowboy shot`, `upper body`, `close-up`, `from above` …). Typically 20–40 tags.
4. **LoRA tag(s)** at the very end: `<lora:FILENAME:WEIGHT>`.

Both the description and the tag list describe the character, the outfit, the action and the place. That repetition is intended: the sentences say how things relate (who does what, where things are, what is behind whom), the tags pin down each detail with the exact danbooru word. Anything left out of both is filled in by the model's defaults — an unspecified girl's outfit often turns into a school uniform.

Example with an Anima LoRA `my_oc_anima` (trigger word `my_oc_mira`):

```
masterpiece, best quality, score_7, my_oc_mira, safe, my_oc_mira sits by the window of a small cafe on a rainy afternoon. She has short black hair with a side part and red eyes, and wears a white knit sweater with a long brown skirt. Raindrops run down the glass behind her and a cup of coffee steams on the wooden table. She reads a paperback with a gentle smile. Upper body. 1girl, solo, smile, short hair, black hair, swept bangs, red eyes, sweater, white sweater, knit sweater, long skirt, brown skirt, sitting, holding book, reading, cup, coffee, steam, table, indoors, cafe, window, rain, water drop, day, warm lighting, upper body <lora:my_oc_anima:0.8>
```

Example without a LoRA, two original characters:

```
masterpiece, best quality, score_7, safe, Two friends walk home along a riverside path at sunset. On the left, a tall woman with long wavy red hair and green eyes wears a beige trench coat over a white blouse and carries a paper grocery bag. On the right, a man with short black hair and round glasses wears a grey hoodie and jeans and points at the orange sky. Cherry blossom petals drift over the water behind them. Wide shot. 1girl, 1boy, walking, smile, long hair, wavy hair, red hair, green eyes, trench coat, white shirt, holding bag, paper bag, short hair, black hair, round eyewear, hoodie, grey hoodie, jeans, pointing, outdoors, river, path, cherry blossoms, petals, sunset, orange sky, wide shot
```

These examples show the form only. Write the description and the tags fresh from what the user asked for every image — never copy an example's scene.

## Checkpoint presets

| Checkpoint | Quality prefix (start of `prompt`) | `negative_prompt` |
|---|---|---|
| **WAI-ANIMA** (`waiANIMA_v10Base10`, default) | `masterpiece, best quality, score_7` | `worst quality, low quality, score_1, score_2, score_3, artist name, blurry, jpeg artifacts, lowres, censor` |
| One Obsession Anima 2.9B (`oneObsession_anima29BV1`) | `masterpiece, best quality, amazing quality, very awa, absurdres, newest, very aesthetic, depth of field, highres` | `worst quality, normal quality, anatomical nonsense, bad anatomy, interlocked fingers, extra fingers, watermark, simple background, transparent, low quality, logo, text, signature, face backlighting` |
| Anima base (`anima-base-…`) | `masterpiece, best quality, score_7` | `worst quality, low quality, score_1, score_2, score_3, artist name, blurry, jpeg artifacts, chromatic aberration` |

Use the row of the checkpoint the user named; otherwise WAI-ANIMA. Drop `depth of field` from the One Obsession prefix when the background has to stay sharp (landscapes, detailed rooms, groups spread across the picture). Do not add other quality or "detail" words (`8k`, `ultra detailed`, `hyperrealistic`, more `score_*`), and do not write quality wishes into the sentences ("a beautiful high-quality picture") — quality comes from the prefix.

## Writing the description

- Name each character, then describe them right after the name: "Hatsune Miku from Vocaloid, with long turquoise twintails and turquoise eyes, wears …". Use normal English capitalization for names and series in sentences; in the tag list they are lowercase tags (`hatsune miku, vocaloid`).
- With several characters, give each one their own sentence and say where they are ("On the left …", "Behind her …", "In the foreground …"), so hair colours and outfits do not get mixed up. Listing names without describing them confuses the model.
- Turn feelings and story into something visible: not "she is sad about the exam" but "tears in her eyes, she stares down at the test paper on her desk". Keep dialogue, titles and other text out — Anima cannot render text beyond a single word.
- Say what is there, not what is missing: things to avoid belong in `negative_prompt`.
- Very short prompts give random results. Even a quick request gets at least two full sentences plus the tag list.

## Tags, weights and artists

- Danbooru tags are lowercase with spaces; score tags (`score_7`) and trigger words keep their underscores.
- Never repeat the same tag. No names of real people.
- **Artist**: only when the user names one, as a tag with `@` in front (`@artist name`) in the head or the tag list; without the `@` it is not read as an artist.
- **Weights** work on tags but need more than on SDXL: `(tag:1.5)` to `(tag:2)` for the one or two things that must win (`(chibi:2)`); `1.1`–`1.3` barely changes anything. Do not weight sentences — make the important part come early and describe it precisely. Parentheses that belong to a tag are escaped: `\(`, `\)`.
- Do not use `BREAK` or SDXL / SD 1.5 embedding names.
- Optional meta tags in the tag list: `official art`, `anime screenshot` (a frame from an anime episode), `newest`, `recent`, `mid`, `early`, `old`, `year 2025` (the One Obsession prefix already has `newest`). One Obsession leans a little towards a 2.5D look; add `anime coloring` or `anime screenshot` when the user wants flat anime. For photorealism, tell the user to switch to another checkpoint.
- The anime training data ends in **September 2025**: characters from later series are unknown — describe their look in the sentences and tags, or use a LoRA.

## Negative prompt

The app adds its own negative prompt from the image settings, and your `negative_prompt` is appended to it. Always pass the `negative_prompt` of the checkpoint from the table. When the user wants something specific excluded, add only those few tags.

## Size

WAI-ANIMA: portrait 832×1216, 896×1152 or 1024×1344 (the size of the author's examples); landscape 1216×832, 1152×896 or 1344×1024; square 1024×1024. Anima works up to about 1536 on the long side; One Obsession also lists 768×1344, 1024×1536 and 640×1536. Portrait for one standing character, landscape for scenery and groups.

## Using a LoRA (IMPORTANT)

A LoRA is only applied when its tag `<lora:FILENAME:WEIGHT>` is **inside the prompt** (put it at the end).

- **Only Anima LoRAs work on Anima.** LoRAs made for Illustrious, NoobAI, Pony, SDXL or SD 1.5 are a different architecture and do nothing on it. Never use one as a fallback.
- `FILENAME` = the LoRA file name **without** `.safetensors`, exactly as the user, the LoRA browser or a tool result gives it. Never guess or "prettify" a file name.
- `WEIGHT` = `0.6` to `1` (`0.8` is a good default; `0.5`–`0.6` when mixing several LoRAs). Keep the sum of weights around `1.5` or lower. Anima LoRAs are trained on the Anima base model, so on a fine-tune like WAI-ANIMA or One Obsession start at `0.8` and raise it if the character does not come through.
- **Trigger word**: put it in the head and use it as the character's name in the first sentence, exactly as trained (`my_oc_mira sits …`). `trained_words` often holds several groups: the first is usually the trigger plus the character's look, the others are alternative outfits — describe the look from the first group in the sentences and tags, and add at most one outfit group that fits the request. Keep tags such as `anime screencap` that the LoRA was trained with.
- The LoRA tag goes in `prompt` only, never in `negative_prompt`. Separate it from the tag before it with a space or a comma.
- Characters that were popular before September 2025 often work with only their name in the sentences and their character and series tags, no LoRA needed.
- If the user asks "why did the LoRA not work": check that it is an Anima LoRA (base `Anima`), the file name is exact, the tag is in the prompt, the trigger word is in the head and the first sentence, and the weight is not too low.

## Finding LoRAs

- If the user pasted a `<lora:...>` tag or trigger words, use them as-is (check it is an Anima LoRA when you can).
- If the **Civitai Helper** skill is active, call `civitai_lora_inventory` with `base: "Anima"` (plus `category` and a short `q` when needed). Anima LoRAs are few, so one call with `base: "Anima"` and no `q` usually lists them all; pick from that list. Do not search other bases.
- A `character` LoRA draws that one character: use it only when the user asks for that character, never as a stand-in for a generic subject ("a knight", "a maid").
- If no Anima LoRA fits, generate without one and say so. If the **civitai-api** skill is active, you can search civitai.com for Anima LoRAs (base model "Anima"), but a LoRA must be installed before its tag works; offer to download it with Civitai Helper.
- Otherwise ask the user for the file name and trigger words (they can copy both from the app's LoRA browser, the **LoRA** button with the layers icon next to the chat input; filter it by the base model Anima). Do not invent a LoRA.

## Reply style

Write one short sentence, then call the image tool (with the checkpoint's negative prompt). When the user asks for the prompt text itself, give the full prompt and the negative prompt in code blocks and say which Anima checkpoint they are for. Answer in the user's language; the prompt itself (sentences and tags) is in English.

If the image tool fails with an error from the image server (HTTP 500, "Failed to load …", a missing text encoder or VAE), the prompt is not the cause: do not retry with a shorter or changed prompt. Tell the user the error in one or two sentences and stop.

## Settings the app cannot set from here

Anima wants different sampler settings than SDXL. WAI-ANIMA: sampler **Euler a**, **20–30** steps, CFG **4–5**; hires fix at most 1.5× (20 steps, R-ESRGAN 4x+ Anime6B, denoising 0.35–0.5). One Obsession: Euler a, 25–35 steps, CFG 3–6. Anima base: 30–50 steps, CFG 4–5. These live in the app's image settings, not in the prompt; if images come out burnt, over-saturated or noisy, tell the user to check them there.

If One Obsession (Anima 2.9B) returns pure noise whatever the prompt, the WebUI is too old for Anima 2.9B: Forge Neo before August 2026 loads only 28 of its 40 blocks. The user has to update Forge Neo (2.9B support also remaps 2B Anima LoRAs onto it); until then use WAI-ANIMA or Anima base.

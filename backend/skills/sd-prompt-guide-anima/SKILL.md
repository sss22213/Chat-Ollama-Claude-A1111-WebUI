---
name: SD Prompt Guide (Anima)
description: "How to write prompts for this app's local Stable Diffusion WebUI (Forge Neo) when the checkpoint is an Anima model — by default WAI-ANIMA (waiANIMA_v10Base10); also One Obsession Anima 2.9B and Anima base. Anima uses a Qwen3 text encoder, not SDXL, and understands English sentences: a short head (quality prefix, trigger word or character, safety tag), then a natural-language description of the character, outfit, action and place, then a full danbooru tag list of the same picture; the LoRA tag comes first. Covers @artist tags, stronger weights, the checkpoint's own negative prompt and Anima-only LoRAs; after each image, checks it against the prompt's features and asks the user to confirm. Use whenever the user wants an image generated with an Anima checkpoint, asks to use a LoRA on Anima, or asks how to write or improve an Anima prompt."
---

# SD Prompt Guide (Anima)

The images are rendered by a LOCAL Stable Diffusion WebUI (Forge Neo) with an **Anima** checkpoint. Unless the user says otherwise it is **WAI-ANIMA** (`waiANIMA_v10Base10`), a fine-tune of the Anima base model. Anima is **not** SDXL: its text encoder is the Qwen3 language model, so it reads **plain English sentences as well as danbooru tags**, and it was trained on captions that combine both. SDXL / Illustrious / Pony habits (tags only, quality tags at the end, `score_9, score_8_up`, small weights, `BREAK`, embeddings) do not carry over.

The image tool takes a `prompt` (and optional `negative_prompt`, `width`, `height`); the app controls steps, sampler, CFG, seed and VAE, and loads Anima's text encoder and VAE by itself. This skill tells you what to put in `prompt` and `negative_prompt`. If the image tool's own description asks for tags only, ignore that for Anima and follow this skill.

## Step by step

Go through all of these steps for every image — also for a redraw or a small change. The sections below give the details. Never skip step 2.

1. **Checkpoint** — the one the user named, otherwise WAI-ANIMA. Take its quality prefix and negative prompt from "Checkpoint presets".
2. **LoRA — decide it first, every time, and use only a LoRA that is confirmed to exist.** A LoRA is confirmed only when its exact file name is in a LoRA tool result in this conversation (`civitai_lora_inventory`), or the user pasted it inside a full `<lora:FILENAME:WEIGHT>` tag. Go down this list and stop at the first line that applies:
   1. A confirmed LoRA was used earlier in this conversation for this character or style → use it again, with the same file name, weight and trigger word. It stays on every later image of that character (redraws, changes, new scenes) until the user says to drop or switch it.
   2. The user pasted a full `<lora:FILENAME:WEIGHT>` tag → use it; when you can look LoRAs up, check first that the file name is in the list.
   3. The user wants a named character (from a series, or their own) or a named style, or names a LoRA without a full tag → **look it up** (see "Finding LoRAs"). Use a LoRA only when the result lists it for that character or style; take its file name exactly from the result. Not in the result → no LoRA; a character popular before September 2025 still works by name.
   4. You cannot look LoRAs up (no `civitai_lora_inventory` tool): if you have the `load_skill` tool, call it with `civitai-helper` and then look it up as in line 3. Otherwise → no LoRA, and tell the user you could not check the installed LoRAs.
   5. Anything else (a generic subject, a scene, a landscape) → no LoRA.

   **Never make up a LoRA tag.** A name the user writes — `is_the_order_a_rabbit_chino_kafu`, `kafuu chino`, a trigger word or a danbooru tag — is a character name or a tag, not a file name: never wrap it in `<lora:…>` without the check above. Keep the result for steps 5, 8 and 10: the confirmed `<lora:FILENAME:WEIGHT>` tag with its trigger word, or "no LoRA".
3. **Character** — with a LoRA, its trigger word is the character's name; a known character without a LoRA → their name plus character and series tags.
4. **Feature list** — break the request into the things the picture must show: the count of people / animals; for each character the look (hair, eyes, signature traits) and every outfit piece; the pose and action; the expression; the key objects; the place; the time of day, weather and light; the framing. Fill what the user left open with concrete choices (an outfit, a background), or the model falls back to its defaults. Steps 6 and 7 and the check after the image all use this list.
5. **Start the prompt** — the LoRA tag from step 2 first, then the quality prefix, the trigger word or character name, and `safe` (see "Prompt structure").
6. **Description** — 2 to 5 English sentences that cover the feature list; one sentence per character with their position (see "Writing the description").
7. **Tag list** — the same feature list as danbooru tags: the count first, the camera tag last; weight (`(tag:1.5)`) only the one or two things that must win (see "Tags, weights and artists").
8. **Self-check before calling the tool:**
   - **LoRA** — when step 2 chose one: the prompt starts with its `<lora:…>` tag, the file name is exactly the confirmed one (from a tool result or the user's own `<lora:…>` tag), and its trigger word is in the head and in the first sentence. If anything is missing, add it now. When step 2 chose none: no `<lora:…>` tag at all — remove any tag whose file name was not confirmed.
   - No tag twice; tags lowercase with spaces, but score tags and trigger words keep their underscores; no real people's names, no dialogue or text to render, no `BREAK`, no extra quality words; the LoRA tag is not in the negative prompt.
9. **Size** — portrait for one standing character, landscape for scenery and groups (see "Size").
10. **Generate** — one short sentence to the user that names the LoRA you use (or says you use none), then call the image tool with `prompt`, the checkpoint's `negative_prompt`, `width` and `height`. If the tool fails with an image-server error, do not change the prompt and retry (see "Reply style").
11. **Look at the image, check it, then wait** — the app sends the generated picture back to you: when you can view images, it comes attached to the image tool's result. Do these in order (details in "After each image"):
    1. First line: `LoRA: <lora:…>` with the tag you used, or `LoRA: none`.
    2. Look at the attached picture and go through the feature list from step 4 one item at a time: ✅ shown, ❌ missing or wrong — say what the picture shows instead (`❌ blue background — the background is white`), ❓ cannot tell. Judge from the picture, not from your prompt: an item you did not see in the picture is never ✅.
    3. If the result says no image is attached for you (or no picture came with it), you cannot see it: say so in one sentence and give the same list unticked (☐) for the user to check.
    4. Ask the user whether the picture matches; for every ❌ suggest the prompt change.
    5. Stop and wait for the user's answer: no new image and no changed prompt until they reply.

## Prompt structure

Write every prompt in this order, all in one line:

1. **LoRA tag(s)** first, when a LoRA is used: `<lora:FILENAME:WEIGHT>`, then a space. Forge removes the tag from the text wherever it stands, so putting it first changes nothing in the picture — and written first, it cannot be forgotten at the end.
2. **Head** — the quality prefix of the checkpoint (table below); if a LoRA is used, its **trigger word** exactly as trained (underscores and all); otherwise the character's name when it is a known character; then the safety tag (e.g. `safe`).
3. **Description** — 2 to 5 English sentences about the picture: who it is (use the trigger word or the character's name as the subject, or "a woman with …" for an original character), the **appearance** (hair length, colour and style, eyes, notable features), the **outfit** piece by piece, the **action and pose**, the **expression**, the **place and background** with its notable objects, the **time of day, weather and light**, and the **framing** ("Full body.", "Upper body, seen from below."). Concrete and visual, present tense, third person.
4. **Tag list** — the same picture again as lowercase danbooru tags with spaces (`long hair`, not `long_hair`): the count first (`1girl`, `1boy`, `2girls`, `1girl, 1boy`, `no humans`, plus `solo` when alone), then the expression, the character and series tags, hair and eyes, every clothing item, the pose and action, the objects, the place, time and weather, the lighting and the camera tag (`full body`, `cowboy shot`, `upper body`, `close-up`, `from above` …). Typically 20–40 tags.

Both the description and the tag list describe the character, the outfit, the action and the place. That repetition is intended: the sentences say how things relate (who does what, where things are, what is behind whom), the tags pin down each detail with the exact danbooru word. Anything left out of both is filled in by the model's defaults — an unspecified girl's outfit often turns into a school uniform.

Example with an Anima LoRA `my_oc_anima` (trigger word `my_oc_mira`):

```
<lora:my_oc_anima:0.8> masterpiece, best quality, score_7, my_oc_mira, safe, my_oc_mira sits by the window of a small cafe on a rainy afternoon. She has short black hair with a side part and red eyes, and wears a white knit sweater with a long brown skirt. Raindrops run down the glass behind her and a cup of coffee steams on the wooden table. She reads a paperback with a gentle smile. Upper body. 1girl, solo, smile, short hair, black hair, swept bangs, red eyes, sweater, white sweater, knit sweater, long skirt, brown skirt, sitting, holding book, reading, cup, coffee, steam, table, indoors, cafe, window, rain, water drop, day, warm lighting, upper body
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

A LoRA is only applied when its tag `<lora:FILENAME:WEIGHT>` is **inside the prompt** — put it at the very start (see "Prompt structure"). Forgetting the tag is the most common reason a character comes out wrong: the self-check in step 8 is there to catch it.

- **Only Anima LoRAs work on Anima.** LoRAs made for Illustrious, NoobAI, Pony, SDXL or SD 1.5 are a different architecture and do nothing on it. Never use one as a fallback.
- `FILENAME` = the LoRA file name **without** `.safetensors`, exactly as a tool result in this conversation lists it or as the user pasted it inside a `<lora:…>` tag. Never guess, build or "prettify" a file name: a character name, trigger word or danbooru tag is not a file name. A tag naming a file that is not installed does nothing.
- `WEIGHT` = `0.6` to `1` (`0.8` is a good default; `0.5`–`0.6` when mixing several LoRAs). Keep the sum of weights around `1.5` or lower. Anima LoRAs are trained on the Anima base model, so on a fine-tune like WAI-ANIMA or One Obsession start at `0.8` and raise it if the character does not come through.
- **Trigger word**: put it in the head and use it as the character's name in the first sentence, exactly as trained (`my_oc_mira sits …`). `trained_words` often holds several groups: the first is usually the trigger plus the character's look, the others are alternative outfits — describe the look from the first group in the sentences and tags, and add at most one outfit group that fits the request. Keep tags such as `anime screencap` that the LoRA was trained with.
- The LoRA tag goes in `prompt` only, never in `negative_prompt`. Separate it from what follows with a space.
- **Keep it for the whole conversation**: once a LoRA is used for a character or style, every later image of it gets the same tag, weight and trigger word — redraws, small changes and new scenes too — until the user says to drop or switch it.
- Characters that were popular before September 2025 often work with only their name in the sentences and their character and series tags, no LoRA needed.
- If the user asks "why did the LoRA not work": check that it is an Anima LoRA (base `Anima`), the file name is exact, the tag is in the prompt, the trigger word is in the head and the first sentence, and the weight is not too low.

## Finding LoRAs

- If the user pasted a full `<lora:...>` tag, use it as-is (check it is in the list and is an Anima LoRA when you can). Trigger words alone are not a file name: look the LoRA up.
- If the **Civitai Helper** skill is active, call `civitai_lora_inventory` with `base: "Anima"` (plus `category` and a short `q` when needed). Anima LoRAs are few, so one call with `base: "Anima"` and no `q` usually lists them all; pick from that list — match the character by the model name and trained words, and copy the file name from the result. Do not search other bases.
- If Civitai Helper is not active but you have the `load_skill` tool, call `load_skill` with `civitai-helper` first, then `civitai_lora_inventory` as above.
- A `character` LoRA draws that one character: use it only when the user asks for that character, never as a stand-in for a generic subject ("a knight", "a maid").
- If no Anima LoRA fits, generate without one and say so. If the **civitai-api** skill is active, you can search civitai.com for Anima LoRAs (base model "Anima"), but a LoRA must be installed before its tag works; offer to download it with Civitai Helper.
- If you cannot look (Civitai Helper is not active and there is no `load_skill` tool): for the user's own character, ask for the file name and trigger words (they can copy both from the app's LoRA browser, the **LoRA** button with the layers icon next to the chat input; filter it by the base model Anima); for a well-known character, go on without a LoRA and say one can be added. Do not invent a LoRA.

## After each image — check it against the prompt and ask the user

Every generated image is checked against its prompt, and the user confirms it before anything else happens.

1. **List the prompt's features** — first one line with the LoRA you used (`LoRA: <lora:my_oc_anima:0.8>` or `LoRA: none`), then the concrete things the picture must show, taken from the prompt you just sent (the sentences and the tag list): the number of people / animals; for each character the look (hair colour and style, eyes, signature traits, the LoRA character) and each outfit piece; the pose and action; the key objects; the place, time of day, weather and light; the expression; the framing. Leave out quality and style words, weights and the negative prompt. Group them in a few short lines.
2. **Check them.**
   - The app attaches the generated picture to the image tool's result when you can view images. Look at that picture and mark every item: ✅ shown, ❌ missing or wrong (always say what the picture shows instead, e.g. `❌ black cat — the cat is orange`, `❌ red circle — there is a yellow square`), ❓ cannot tell (too small, hidden, cropped). Mark only what you really see in the picture; never guess a ✅ from the prompt.
   - If the result says no image is attached for you, or no picture came with it, you cannot see the result: say so in one sentence and give the list as an unticked checklist (☐) for the user to go through.
3. **Ask the user to confirm**: one short question — does the picture match, and what should change. For every ❌ suggest the concrete prompt change (add the tag, move it earlier, weight it like `(black cat:1.3)`, pick a framing that can show it) and ask whether to regenerate with it.
4. **Wait for the answer.** Do not regenerate, change the prompt or go on to another image until the user replies. When they confirm, continue; when they ask for changes, apply them and check the new image the same way.

Write the checklist in the user's language and keep each feature as the English tag from the prompt (`✅ short orange hair`, `❌ yellow raincoat — she wears a red coat`). When several active skills ask for this check (e.g. Story Illustrator together with this guide), do it once per image.

## Reply style

Write one short sentence that names the LoRA you use (or says you use none), then call the image tool (with the checkpoint's negative prompt); after the image, do the check above and wait for the user's confirmation. When the user asks for the prompt text itself, give the full prompt and the negative prompt in code blocks and say which Anima checkpoint they are for. Answer in the user's language; the prompt itself (sentences and tags) is in English.

If the image tool fails with an error from the image server (HTTP 500, "Failed to load …", a missing text encoder or VAE), the prompt is not the cause: do not retry with a shorter or changed prompt. Tell the user the error in one or two sentences — for a text encoder or VAE error add the fix from "Settings the app cannot set from here" — and stop.

## Settings the app cannot set from here

Anima wants different sampler settings than SDXL. WAI-ANIMA: sampler **Euler a**, **20–30** steps, CFG **4–5**; hires fix at most 1.5× (20 steps, R-ESRGAN 4x+ Anime6B, denoising 0.35–0.5). One Obsession: Euler a, 25–35 steps, CFG 3–6. Anima base: 30–50 steps, CFG 4–5. These live in the app's image settings, not in the prompt; if images come out burnt, over-saturated or noisy, tell the user to check them there.

**Text encoder and VAE** are not set in the prompt either. For an Anima checkpoint the app loads Forge Neo's `qwen_3_06b_base` text encoder and `qwen_image_vae` by itself when nothing is ticked in the **VAE / Text encoder** option of the image settings (Auto, the default); when the user ticks only one of the two kinds there, the other is still added. Anima only works with `qwen_image_vae` (or a variant of that file, e.g. `_fp8`) and `qwen_3_06b_base`; an SDXL or SD 1.5 VAE or another text encoder does not fit it — if the user ticked other files there and the images break or fail to load, tell them to untick them (back to Auto). When the user asks which VAE or text encoder Anima needs, give this answer.

- The image tool says the text encoder or VAE cannot be found: the user has to put `qwen_3_06b_base` into Forge's `models/text_encoder` folder and `qwen_image_vae` into `models/VAE`. When the error names a file ticked in the image settings, that file is gone from Forge: untick it or tick another one. When it says more than one VAE is ticked, the user has to keep just one (Forge uses only one VAE).
- An Anima checkpoint whose file name does not contain "anima" fails with "Failed to load diffusion model": the app did not recognise it as Anima and loaded no text encoder or VAE. The user should let Civitai Helper fetch the checkpoint's Civitai info (its base model then reads Anima), or rename the file so it contains "anima".

If One Obsession (Anima 2.9B) returns pure noise whatever the prompt, the WebUI is too old for Anima 2.9B: Forge Neo before August 2026 loads only 28 of its 40 blocks. The user has to update Forge Neo (2.9B support also remaps 2B Anima LoRAs onto it); until then use WAI-ANIMA or Anima base.

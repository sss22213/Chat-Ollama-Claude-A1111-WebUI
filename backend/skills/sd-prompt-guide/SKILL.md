---
name: SD Prompt Guide (Illustrious)
description: "How to write prompts for this app's local Stable Diffusion (A1111 / Forge) with an Illustrious-based anime checkpoint (WAI-illustrious, Illustrious / NoobAI), step by step for every image: danbooru tag format and ordering, tag weights, negative prompt, and LoRA — only an installed LoRA confirmed by a tool result (or a full tag the user pasted), as <lora:filename:weight> (weight 0.6–1) with its trigger words. After each image, checks it against the prompt's features and asks the user to confirm. Use whenever the user wants an image generated, asks to use / apply / add a LoRA, mentions trigger words, asks why a LoRA did not take effect, or asks how to write or improve a prompt."
---

# SD Prompt Guide (Illustrious)

Every image in this app is rendered by a LOCAL Stable Diffusion WebUI (A1111 / Forge) with SDXL-family anime checkpoints (Illustrious / NoobAI / Pony / WAI). The image tool takes a `prompt` (and optional `negative_prompt`, `width`, `height`); the app controls steps, sampler, CFG and seed. This skill tells you what to put in `prompt`.

## Step by step

Go through all of these steps for every image — also for a redraw or a small change. The sections below give the details. Never skip step 2.

1. **Checkpoint family** — Illustrious / NoobAI / WAI, unless the user says the checkpoint is Pony (then the prompt starts with `score_9, score_8_up, score_7_up`) or another family (see the table in the syntax reference). It decides the quality tags (step 5) and which LoRAs fit (step 2).
2. **LoRA — decide it first, every time, and use only a LoRA that is confirmed to exist.** A LoRA is confirmed only when its exact file name is in a LoRA tool result in this conversation (`civitai_lora_inventory`), or the user pasted it inside a full `<lora:FILENAME:WEIGHT>` tag. Go down this list and stop at the first line that applies:
   1. A confirmed LoRA was used earlier in this conversation for this character, outfit or style → use it again, with the same file name, weight and trigger words. It stays on every later image of that character (redraws, changes, new scenes) until the user says to drop or switch it.
   2. The user pasted a full `<lora:FILENAME:WEIGHT>` tag → use it; when you can look LoRAs up, check first that the file name is in the list.
   3. The user wants a named character (from a series, or their own), a named outfit or style, or names a LoRA without a full tag → **look it up** (see "Finding LoRAs"). Use a LoRA only when the result lists it for that character or style and its base fits the checkpoint; take its file name and trigger words exactly from the result. Not in the result → no LoRA; a character with many danbooru pictures often still works by name (step 3).
   4. You cannot look LoRAs up (no `civitai_lora_inventory` tool): if you have the `load_skill` tool, call it with `civitai-helper` and then look it up as in line 3. Otherwise → no LoRA, and tell the user you could not check the installed LoRAs.
   5. Anything else (a generic subject, a scene, a landscape) → no LoRA.

   **Never make up a LoRA tag.** A name the user writes — `is_the_order_a_rabbit_chino_kafu`, `kafuu chino`, a trigger word or a danbooru tag — is a character name or a tag, not a file name: never wrap it in `<lora:…>` without the check above. Keep the result for steps 5, 7 and 9: the confirmed `<lora:FILENAME:WEIGHT>` tag with its trigger words, or "no LoRA".
3. **Character** — with a LoRA, its trigger words name the character. A known character without a LoRA → the character's danbooru tag (`hatsune miku`; with its qualifier when the tag has one, escaped: `saber \(fate\)`), the series tag (`vocaloid`) and their key look tags (hair, eyes) so the character comes out right.
4. **Feature list** — break the request into the things the picture must show: the count of people / animals; for each character the look (hair, eyes, signature traits) and every outfit piece; the pose and action; the expression; the key objects; the place; the time of day, weather and light; the framing. Fill what the user left open with concrete choices (an outfit, a background), or the checkpoint falls back to its defaults. Step 5 and the check after the image use this list.
5. **Write the tags** — turn the feature list into danbooru tags in the order of "Tag format": the count → the LoRA tag from step 2 and its trigger words → appearance → clothing → pose, expression, action → scene, place, time, light → framing / camera → `masterpiece, best quality, amazing quality` last (Pony: `score_9, score_8_up, score_7_up` first instead). Every item of the feature list needs at least one tag. Tags only, no sentences.
6. **Weights** — weight only the one or two things that must win, `(tag:1.2)` (1.1–1.4); leave the rest unweighted.
7. **Self-check before calling the tool:**
   - **LoRA** — when step 2 chose one: its `<lora:…>` tag is right after the count with a comma on both sides, the file name is exactly the confirmed one (from a tool result or the user's own `<lora:…>` tag), and its trigger words follow it as separate tags. If anything is missing, add it now. When step 2 chose none: no `<lora:…>` tag at all — remove any tag whose file name was not confirmed.
   - No tag twice; no sentences; exactly the three quality tags, at the end, and no other quality or aesthetic tags; parentheses inside tags escaped (`\(`, `\)`); no real people's names; the LoRA tag is not in the negative prompt.
8. **Size** — portrait for one standing character, landscape for scenery and groups, square otherwise (see "Tag format").
9. **Generate** — one short sentence to the user that names the LoRA you use (or says you use none), then call the image tool with `prompt`, `width` and `height`; add `negative_prompt` only when the user wants something excluded. If the tool fails with an image-server error, do not change the prompt and retry (see "Reply style").
10. **Look at the image, check it, then wait** — the app sends the generated picture back to you: when you can view images, it comes attached to the image tool's result. Do these in order (details in "After each image"):
    1. First line: `LoRA: <lora:…>` with the tag you used, or `LoRA: none`.
    2. Look at the attached picture and go through the feature list from step 4 one item at a time: ✅ shown, ❌ missing or wrong — say what the picture shows instead (`❌ blue background — the background is white`), ❓ cannot tell. Judge from the picture, not from your prompt: an item you did not see in the picture is never ✅.
    3. If the result says no image is attached for you (or no picture came with it), you cannot see it: say so in one sentence and give the same list unticked (☐) for the user to check.
    4. Ask the user whether the picture matches; for every ❌ suggest the prompt change.
    5. Stop and wait for the user's answer: no new image and no changed prompt until they reply.

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

- `FILENAME` = the LoRA file name **without** `.safetensors`, exactly as a LoRA tool result in this conversation lists it or as the user pasted it inside a `<lora:…>` tag (case, hyphens and underscores included). A character name, trigger word or danbooru tag is not a file name. Never guess or "prettify" a file name; if you only know a character, a Civitai model name or trigger words, find the installed file first (see "Finding LoRAs").
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

- If the user pasted a full `<lora:...>` tag, use it as-is (check the list first when you can look it up). Trigger words or a character name alone are not a file name: look the LoRA up.
- If the **Civitai Helper** skill is active, call `civitai_lora_inventory` — it returns the exact `prompt_tag`, trigger words, `base` (base-model family) and `category` of every installed LoRA; copy the file name and trigger words from it. Search by category first: pass the `category` of what the LoRA must add (`character`, `clothing`, `poses`, `action`, `style`, `concept`, `background`, …; see the Civitai Helper skill), `base` for the checkpoint, and a short `q` for the subject. Use `civitai_model_examples` for an example prompt from Civitai.
- Pick by base model. The checkpoint is Illustrious-based (WAI-illustrious-SDXL), so pass `base: "Illustrious"` and prefer LoRAs whose `base` is **Illustrious** or **NoobAI** (NoobAI is Illustrious-based; search it with `base: "NoobAI"` when Illustrious has nothing). A **Pony** LoRA works poorly on it, and an **SD 1.5** LoRA does nothing. Plain **SDXL** or `unknown` does not tell Illustrious from Pony, so treat it as uncertain. If the only match is a Pony or uncertain LoRA, say so when you use it.
- A `character` LoRA draws that one character: use it only when the user asks for that character, never as a stand-in for a generic subject ("a knight", "a maid"). If no LoRA really fits, generate without one.
- Do not keep re-searching: call `civitai_lora_inventory` **at most twice for each thing a LoRA should add** (e.g. the art style and the outfit → at most two calls each): one call with `category` + `base` + a specific `q`, then at most one broader call. Before the second call read the counts in the answer: an empty `categories` means no installed LoRA matches that `q` in any category, so do not retry it with another category or without `base`; try a different word, or give up on that one. Never page through the whole list hoping to spot one. If those find no suitable LoRA, stop searching: ask the user which LoRA to use, or generate without a LoRA and say that none was found.
- If Civitai Helper is not active but you have the `load_skill` tool, call it with `civitai-helper` first, then look the LoRA up.
- If the **civitai-api** skill is active, you can search civitai.com for candidates, but a LoRA must be installed in the WebUI before its tag works; offer to download it with Civitai Helper.
- If you cannot look (Civitai Helper is not active and there is no `load_skill` tool): for the user's own character, ask for the file name and trigger words (they can copy both from the app's LoRA browser, the **LoRA** button with the layers icon next to the chat input); for a well-known character, go on without a LoRA and say one can be added. Do not invent a LoRA.

## After each image — check it against the prompt and ask the user

Every generated image is checked against its prompt, and the user confirms it before anything else happens.

1. **List the prompt's features** — first one line with the LoRA you used (`LoRA: <lora:jp_school_uniform:0.8>` or `LoRA: none`), then the concrete things the picture must show, taken from the prompt you just sent: the number of people / animals; for each character the look (hair colour and style, eyes, signature traits, the LoRA character) and each outfit piece; the pose and action; the key objects; the place, time of day, weather and light; the expression; the framing. Leave out quality and style words, weights and the negative prompt. Group them in a few short lines.
2. **Check them.**
   - The app attaches the generated picture to the image tool's result when you can view images. Look at that picture and mark every item: ✅ shown, ❌ missing or wrong (always say what the picture shows instead, e.g. `❌ black cat — the cat is orange`, `❌ red circle — there is a yellow square`), ❓ cannot tell (too small, hidden, cropped). Mark only what you really see in the picture; never guess a ✅ from the prompt.
   - If the result says no image is attached for you, or no picture came with it, you cannot see the result: say so in one sentence and give the list as an unticked checklist (☐) for the user to go through.
3. **Ask the user to confirm**: one short question — does the picture match, and what should change. For every ❌ suggest the concrete prompt change (add the tag, move it earlier, weight it like `(black cat:1.3)`, pick a framing that can show it) and ask whether to regenerate with it.
4. **Wait for the answer.** Do not regenerate, change the prompt or go on to another image until the user replies. When they confirm, continue; when they ask for changes, apply them and check the new image the same way.

Write the checklist in the user's language and keep each feature as the English tag from the prompt (`✅ short orange hair`, `❌ yellow raincoat — she wears a red coat`). When several active skills ask for this check (e.g. Story Illustrator together with this guide), do it once per image.

## Reply style

Write one short sentence that names the LoRA you use (or says you use none), then call the image tool; after the image, do the check above and wait for the user's confirmation. When the user asks for the prompt text itself, give the full comma-separated prompt in a code block (LoRA tag + trigger words included) and say which checkpoint family it targets. Answer in the user's language; keep tags in English.

If the image tool fails with an error from the image server (HTTP 500, "Failed to load …", a missing model file), the prompt is not the cause: do not retry with a shorter or changed prompt. Tell the user the error in one or two sentences and stop.

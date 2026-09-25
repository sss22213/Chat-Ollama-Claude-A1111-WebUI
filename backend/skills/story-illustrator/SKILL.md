---
name: Story Illustrator
description: "Tell a story with pictures in chat: first write a scene outline (a cast sheet with each character's fixed appearance tags, then numbered scenes), then generate the images one by one in order — or, when the user only wants prompts, give one ready-to-use prompt per scene. Use when the user asks for an illustrated story, a picture book, a story told in N images, a sequence of scenes, or keywords / prompts for each scene of a story (e.g. 「用圖片講故事」「畫一個故事」「繪本」「每個場景的關鍵字」)."
---

# Story Illustrator

Goal: a story whose pictures follow one plan and keep the same characters from the first image to the last. Always plan the whole story first, then produce the scenes.

## Step 1 — Outline (always first, before any image)

Write the outline in the user's language (tags in English):

1. **Title** and a one-line premise.
2. **Cast sheet** — for every recurring character, two fixed lines of real danbooru tags (never invented phrases — `rust` and `robot`, not `weathered metal body`):
   - **Core**: the LoRA tag and its trigger words / character tag if there is one, then the face and body: hair, eyes and any signature traits. Include every tag the character needs to look right (for a LoRA, keep its trained look tags). For an animal: the danbooru animal tag (`fox`, `cat`) plus fur colour written as fur tags (`grey fur`, `white fur`; in danbooru `muzzle` means a mouth guard, never use it for the snout).
   - **Outfit**: the clothing and accessories (`serafuku, red sailor collar, red necktie, red skirt, pleated skirt, thighhighs`).
   Leave out the count tag and anything that changes per scene (expression, pose). These lines are copied verbatim into every scene with that character. Add a style line if the user asked for a style.
3. **Scene list** — numbered. For each scene: the story beat (1–2 sentences in the user's language) and a **picture line**: one sentence saying exactly what the image shows — who is visible (including teachers, classmates, crowds), what they are doing, the key object(s), where, and the time / light.

The picture line must be something a single still image can show. Turn non-visual beats into visible cues: late at night → `night, dark room, desk lamp`; the teacher announces an exam → the teacher at the chalkboard, pointing; a week passes → a calendar, a pile of finished notes; waiting for results → a crowd in front of a bulletin board. Stable Diffusion cannot write readable text, so never rely on words in the picture (a date on the board, a score on the paper).

- Number of scenes: what the user asks for; otherwise 4–6.
- The scenes must form a complete arc — setup, development, turning point, ending — so the last image closes the story.
- Pick LoRAs once, here (e.g. with Civitai Helper's `civitai_lora_inventory` when it is available and fits) — not again for every scene. For a character LoRA use weight 0.7–0.8 unless the user gave one: at 1 it tends to force its own training poses and override the scene's action.

Then continue straight to step 2 in the same reply. Only stop after the outline if the user asked to review it first.

## Step 2a — Images (default)

The app shows every image directly under the text that was written just before it was generated. So the reply must alternate strictly — scene text, its image, next scene text, its image — one scene at a time:

1. Write a heading exactly in the form `## Scene N — <short title>` and the scene's narration (2–4 sentences in the user's language; dialogue goes here, not into the image). The narration must describe the same moment the picture line shows — the reader looks at the image right below it.
2. Immediately call the image tool once for this scene — before writing anything about the next scene.
3. Wait for the image result. Only then write the next scene's heading and narration, and repeat.

Never write the text of several scenes first and generate their images afterwards, and never request several scenes' images in one batch — the pictures would all pile up under the last paragraph instead of under their own scenes. The outline from step 1 has no image; the first image comes right after Scene 1's narration.

Do not stop early, do not ask "shall I continue?" between scenes, and do not regenerate a scene unless the user asks. There is no limit on how many images one reply may generate, so a 10- or 12-scene story is fine — one image call per scene. If a generation fails, say so in one line and continue with the next scene.

### Writing each scene's prompt

The prompt turns the scene's picture line into comma-separated English danbooru tags. Stable Diffusion weighs early tags most and reads the prompt in 75-token chunks, so who and what happens must come first and the outfit later. Order:

1. **Count everyone visible**: `1girl`, `1boy`, `2girls`, `1girl, 1boy` (e.g. the heroine and a male teacher). Add `solo` only when the character is truly alone. One main character with people in the background: `1girl, solo focus` plus `crowd` or who they are. Only animals or objects: `no humans` (animals: `no humans, animal focus`, then the animal tag) — without it, animals doing human-like things get drawn as furry humanoids.
2. **Core** line of each visible main character (with the LoRA tag and trigger).
3. **What happens** — the heart of the picture line: the pose / action / gesture (`head on desk`, `handing over paper`, `running`), the key objects (`test paper`, `desk lamp`, `coffee cup`), and the other people with what they do (`teacher, pointing at chalkboard`, `classmates, looking at another`). Give the one action that defines the scene a weight, e.g. `(head on desk:1.2)`, especially when a character LoRA is used.
4. **Expression**: `smile`, `crying`, `surprised`, `nervous`, …
5. **Setting**, with its state: place, time of day, weather, lighting, and condition words the story relies on (`abandoned`, `broken`, `snow`, `messy room`).
6. **Shot / camera** that can show the action: `close-up` only when the picture is purely a face reaction; when hands, props, furniture or other people matter use `upper body`, `cowboy shot` or `full body`; `wide shot` to establish a place (it makes characters small). Add an angle when it helps (`from side`, `from above`).
7. **Outfit** line of each visible main character.
8. **Quality tags** at the end (follow SD Prompt Guide when it is active).

Before each image call, check the prompt against the narration you just wrote: every visible element of that moment — each person, the action, the key object, the place, the time of day — must be in the tags, and nothing may contradict it (no `solo` when a teacher is in the scene, no `close-up` when the desk matters).

Example (original character; Core `black hair, bob cut, green eyes, hair clip`, Outfit `school uniform, blazer, plaid skirt`). Picture line: *Mika slumps over her desk while the teacher writes on the chalkboard behind her.*

```
1girl, 1boy, black hair, bob cut, green eyes, hair clip, (head on desk:1.2), arms on desk, teacher, standing, writing on chalkboard, bored, classroom, chalkboard, daytime, sunlight, cowboy shot, from side, school uniform, blazer, plaid skirt, masterpiece, best quality, amazing quality
```

Consistency rules:

- Never change a character's Core or Outfit between scenes unless the story changes it; then update the cast-sheet line and say so.
- Between scenes only the action, expression, other people, camera, setting and lighting change.
- Write a character's name in the prompt only when it is a real danbooru character tag (e.g. `hatsune miku`); for original characters the cast-sheet tags are the identity.
- Use the same width / height for every scene (portrait, e.g. 832×1216), except a wide establishing shot may be landscape (1216×832).
- Usually omit `negative_prompt`; the app applies one. The app also controls the seed.

## Step 2b — Prompts only

When the user wants keywords / prompts / tags instead of images (「只要關鍵字」「給我 prompt」「不要生圖」), do not call the image tool. After the outline, give each scene as a heading, a one-sentence beat and the full prompt in a code block, composed exactly as in step 2a, so each one can be pasted into A1111 or into this app's Comic Studio.

## Step 3 — Wrap up

After the last scene: one or two sentences that close the story, then the cast-sheet blocks again in a code block so the user can reuse them for a sequel or as character cards in Comic Studio. Offer to redo a single scene or to continue the story.

## Notes

- Stable Diffusion cannot render readable text: keep dialogue and titles in the narration, never in the prompt.
- For a laid-out comic page with speech bubbles and PNG export, point the user to the app's **Comic Studio**.

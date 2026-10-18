---
name: Generate Manga Page
description: "Generate manga/comic pages with consistent recurring characters. Use when the user asks for a manga page, comic page, chapter page, cover, storyboard page, or character-consistent multi-panel art. First lock each recurring character's look (a reference + fixed tags/LoRA/seed), then generate the page so the same character never gets redesigned across panels or pages; every image is checked against its prompt and confirmed by the user before the next one."
---

# Generate Manga Page

Make manga/comic pages where recurring characters keep the SAME identity across panels and pages. The hard part of comics is consistency — this skill enforces it.

Adapted for this app: images come from a LOCAL Stable Diffusion (A1111) backend, so consistency is achieved with **fixed character tags + LoRA + a locked seed**, plus a generated **reference image** you keep using as the visual anchor. (Original idea: the "img-memory" workflow of agent-mangaka-forge, MIT.)

## Parameters (infer from the user)

- `page_type`: story_page | cover | splash_page | character_intro | battle_page | dialogue_page
- `reading_direction`: right_to_left (manga) | left_to_right
- `tone`: shonen | seinen | shojo | dark_fantasy | comedy | cinematic
- `ink_style`: clean_black_white | screentone | high_contrast | sketchy_ink | color_manga
- `panel_count`: a number, or "auto" (3–6 is typical)
- `characters`: who appears, with a stable name for each
- `location`: scene setting
- `script`: the action beats and dialogue intent for the page

## Non-negotiable rules

- Establish a character's look BEFORE putting them in a page. If you have not pinned a recurring character's appearance this conversation, do that first.
- Pin each recurring character as a fixed block of comma-separated English danbooru tags: face/hair/eyes, body, costume, accessories, palette, distinctive symbols. Reuse that EXACT block every time the character appears.
- Lock a seed per character (and keep it) so the same character renders consistently. Use a character LoRA when the user has one.
- Never silently redesign a recurring character. If the story changes them persistently (new costume, injury, power-up, age), make a NEW named version and note exactly what changed — don't overwrite the original look.
- Only vary pose, expression, camera angle, lighting, and temporary effects between panels — never identity.
- Do NOT invent dialogue. Use no text unless the user gives exact wording. Stable Diffusion can't reliably render text, so prefer generating clean art and leaving real lettering to the user (say so).

## Workflow

### 1. Plan
Briefly restate: characters on the page, the setting, panel count, reading direction, ink style, and the action beat of each panel. Keep it short.

### 2. Lock characters (consistency anchor)
For each recurring character not yet established this conversation:
- Write their fixed appearance tag block.
- Generate ONE clean reference image (a simple front-facing portrait / character sheet) at a fixed seed. This is the visual anchor you reuse.
- State the character's locked tags + seed so they can be reused verbatim.
- Check the reference image and let the user confirm it (step 4) before any panel uses it: a wrong anchor spoils every panel after it.

### 3. Generate panels
Generate the panels (one image each, in reading order), and after each panel do the check in step 4 and wait for the user's confirmation before the next panel. When the user asked for the whole page at once (「整頁一次畫完」「不用每格確認」), check each panel right after it is generated but keep going, and ask for confirmation of all panels at the end (only the ❌ / ❓ items per panel). For every panel, the prompt = `ink_style + quality tags` + `each present character's locked appearance block` + `this panel's pose / expression / camera / action` + `background`. Keep the same per-character seed where the backend allows it.

Compose each prompt as comma-separated English danbooru tags (these are SDXL / Pony / Illustrious anime models, not sentences). Example panel prompt:
`monochrome, manga, screentone, 1girl, silver hair, blue eyes, school uniform, red scarf, determined expression, low angle, running, rooftop, cloudy sky, masterpiece, best quality`

### 4. Check each image and ask the user
Right after each image (the reference and every panel):

1. **List the features** the image must show, from the prompt you just sent: each present character's locked appearance block (face, hair, eyes, costume pieces, palette, distinctive symbols), the panel's pose / expression / camera / action, the key objects and the background. Leave out ink style and quality words. What the panel's beat in the plan says counts too, even when the prompt left it out; if it is missing, the fix is to add it to the prompt.
2. **Check them.** If the generated image is attached to the tool result for you, look at it and mark each item ✅ shown, ❌ missing or wrong (say what is there instead), ❓ cannot tell; also say whether each recurring character still matches the locked look, and note broken anatomy, accidental text / watermarks or a confused scene. Mark only what you really see. If no image is attached for you, you cannot see the result: say so in one sentence and give the list as an unticked checklist (☐) for the user.
3. **Ask the user to confirm** in one short question: is this panel right — go on, or change something? For every ❌ suggest the concrete fix (reinforce the locked tags or the seed, weight the missing tag, change the camera).
4. **Wait.** Regenerate only when the user asks for it (then check the new image the same way); go on only when they confirm.

Keep the checklist short: a few lines in the user's language, features as the English tags from the prompt (`✅ silver hair`, `❌ red scarf — no scarf`).

### 5. Wrap up
After the last panel is confirmed, summarize the page: the panel order, each character's locked tags + seed (so the user can reproduce or continue on the next page), and note that speech bubbles / lettering should be added by the user (or in this app's Comic Studio page-layout view).

## Notes for this app
- You generate images with the app's built-in image capability (local Stable Diffusion). Producing the image IS how you "show" it.
- For arranging panels into a finished page with speech bubbles and exporting a PNG, point the user to the app's **Comic Studio** (the comic page), which does layout + bubbles + export and supports the same character cards / LoRA / locked seed.

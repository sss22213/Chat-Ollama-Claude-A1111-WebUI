---
name: Generate Manga Page
description: "Generate manga/comic pages with consistent recurring characters. Use when the user asks for a manga page, comic page, chapter page, cover, storyboard page, or character-consistent multi-panel art. First lock each recurring character's look (a reference + fixed tags/LoRA/seed), then generate the page so the same character never gets redesigned across panels or pages."
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

### 3. Generate panels
Generate the panels (one image each, in reading order). For every panel, the prompt = `ink_style + quality tags` + `each present character's locked appearance block` + `this panel's pose / expression / camera / action` + `background`. Keep the same per-character seed where the backend allows it.

Compose each prompt as comma-separated English danbooru tags (these are SDXL / Pony / Illustrious anime models, not sentences). Example panel prompt:
`monochrome, manga, screentone, 1girl, silver hair, blue eyes, school uniform, red scarf, determined expression, low angle, running, rooftop, cloudy sky, masterpiece, best quality`

### 4. Quality check
After each image, verify the recurring character still matches their locked look (face, hair, costume, palette). If it drifted, regenerate with the locked tags/seed reinforced. Reject broken anatomy, accidental text/watermarks, or a confused scene.

### 5. Wrap up
Summarize the page: the panel order, each character's locked tags + seed (so the user can reproduce or continue on the next page), and note that speech bubbles / lettering should be added by the user (or in this app's Comic Studio page-layout view).

## Notes for this app
- You generate images with the app's built-in image capability (local Stable Diffusion). Producing the image IS how you "show" it.
- For arranging panels into a finished page with speech bubbles and exporting a PNG, point the user to the app's **Comic Studio** (the comic page), which does layout + bubbles + export and supports the same character cards / LoRA / locked seed.

---
name: MMD Animation
description: "Turn a story into a short animated video (mp4) acted out by a 3D MMD character (e.g. Chino): write a storyboard of shots with narration, voiced and lip-synced lines, body motions, facial expressions and camera work, then render it with Blender on the local anime-render server (port 5280). Use whenever the user asks for an animation, a video, an MMD clip, or to animate / act out a story with the character."
---

# MMD Animation

You are the writer and director; the renderer is the animator. You write a storyboard and call `make_mmd_animation`. The server voices each line with TTS, lip-syncs the character, poses the body from a motion library, sets the camera, renders with Blender and returns an mp4 link. You never see the video.

## Workflow

1. If you don't know the character id or available motions, call `mmd_animation_catalog` once.
2. Write the story as 3–10 shots (whole clip ideally 20–90 s). For each shot pick:
   - `narration` (optional): the narrator's voice-over, e.g. scene setting.
   - `line` (optional): what the character says — one or two short, natural sentences. Chinese, Japanese or English.
   - `motion`: one of idle, talk, wave, nod, shake_head, bow, think, surprised, happy, sad, angry, shy, look_around, point, cheer, shrug (or a VMD name from the catalog, e.g. a dance). A line with no motion defaults to `talk`.
   - `expression`: neutral, smile, happy (eyes closed ^^), gentle, sad, cry, angry, surprised, troubled, shy, wink, smug, serious, sleepy. Match the emotion of the line.
   - `camera`: `shot` (closeup = face, medium = waist up, cowboy = knees up, full = whole body), `angle` (front, left, right, profile_left, profile_right, low, high), `move` (static, push_in, pull_out, orbit_left, orbit_right, tilt_up, tilt_down).
   - `duration` only for silent shots (e.g. a 3-second reaction or a dance).
3. Direct like an anime: open with a `full` or `medium` establishing shot (often with narration and `push_in`), use `closeup` for emotional lines, vary angles between consecutive shots, end on a `bow`, `wave` or `happy` beat.
4. Background: omit for a plain gradient, or pass `#RRGGBB`. If an image was generated earlier in this chat (e.g. a café interior with no people), pass its `/images/<name>.png` path as `background` — generate one first with the image tool when the user wants a specific place.
5. Call `make_mmd_animation`. It waits up to ~9 minutes. If it returns `queued`/`running`, call `mmd_animation_status` with the id.
6. When completed, reply with one or two sentences, the video link `[▶ 觀看動畫](video_url)` and the thumbnail `![](thumbnail_url)`. Mention warnings (e.g. an expression the model lacks) briefly.

## Example storyboard

```json
{
  "title": "Rabbit House 的早晨",
  "character": "chino",
  "shots": [
    {"narration": "早晨的 Rabbit House，今天也準時開門了。", "motion": "idle", "expression": "gentle", "camera": {"shot": "full", "move": "push_in"}},
    {"line": "歡迎光臨。請問要點什麼呢？", "motion": "bow", "expression": "smile", "camera": {"shot": "medium"}},
    {"line": "咦……您說要點兔子？這裡是咖啡店喔。", "motion": "surprised", "expression": "surprised", "camera": {"shot": "closeup", "angle": "left"}},
    {"line": "……那，推薦您本店的招牌咖啡。", "motion": "talk", "expression": "shy", "camera": {"shot": "medium", "angle": "right"}},
    {"motion": "nod", "expression": "happy", "duration": 2.5, "camera": {"shot": "closeup", "move": "pull_out"}}
  ]
}
```

## Rules

- Never claim a video exists unless the tool returned `completed` with a `video_url`; never invent URLs.
- Keep lines short; long monologues make long, slow renders. Split them across shots.
- If the server is unreachable, say the anime-render server on port 5280 is not running.
- If a request fails with a validation error, fix the storyboard (names/enums) and try once more.

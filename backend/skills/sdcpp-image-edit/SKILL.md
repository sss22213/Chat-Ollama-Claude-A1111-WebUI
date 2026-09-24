---
name: Image Edit (sd.cpp)
description: "Edit a user-attached image from a text instruction through the local stable-diffusion.cpp server (port 7861) running an image-editing model such as Qwen-Image-Edit 2.1: change backgrounds, clothes, colors, expressions, add or remove objects, restyle, fix details, or img2img-restyle with tags. Use whenever the user attaches or refers to an image and asks to change, modify, edit, replace, remove, add, recolor, restyle or fix something in it."
---

# Image Edit (sd.cpp)

The user points at an image and tells you what to change. You call `sdcpp_edit_image` with a written instruction; the app picks the source image, sends it to the stable-diffusion.cpp server as the reference image, waits for the job, and shows the result inline. You never see or handle image data yourself.

**Which image gets edited:** the most recent one in this conversation — the user's newest attachment, or otherwise the last image generated with A1111 or edited here. So "edit the picture you just drew" works without re-attaching, and consecutive edits build on each other. To edit an older image, ask the user to attach it (or click its Redraw button).

## Workflow

1. There must be an image in this conversation (attached or generated); the tool tells you if there is none, and then you ask the user to attach one or generate one first.
2. Turn the request into ONE clear edit instruction (`prompt`):
   - Say what to change **and** what to keep: "Replace the background with a rainy night street; keep the character, pose, face, hairstyle and outfit exactly the same."
   - One edit per call. For several changes, do them one at a time; each result is automatically the input of the next edit.
   - Chinese instructions are fine for Qwen-Image-Edit; keep them concrete (顏色、位置、物件、保留什麼).
   - Do not write danbooru tag lists for `sdcpp_edit_image`; tags are for `sdcpp_img2img` only.
3. Call `sdcpp_edit_image` with `prompt` (and `seed` when the user wants a variation of a previous result). Leave width/height unset unless the user asks for a size.
4. When the result comes back, reply with one short sentence about what changed and offer a follow-up (stronger/weaker change, different seed, another edit).

## When to use img2img instead

- The user wants a **restyle / variation described with tags** ("make it look like watercolor, 1girl, ..."), or the loaded model is a normal SD/SDXL checkpoint rather than an editing model (check with `sdcpp_status` if an edit comes back unchanged or errors). Then use `sdcpp_img2img` with danbooru tags and `strength` 0.3 (subtle) – 0.8 (strong), default 0.55.

## Rules

- Never claim an edit was done unless the tool returned success. If it reports "needs an image", ask for the image.
- If the server is unreachable, say the sd.cpp server on port 7861 is not running and stop.
- Do not print image URLs, base64 or raw JSON; the image is already displayed.
- Keep edits faithful: do not add NSFW content or change the subject's identity unless asked.

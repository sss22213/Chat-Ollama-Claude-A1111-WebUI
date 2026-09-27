# In this app

- For searching models use the `civitai_search_models` tool (it is a wrapper around `civitai.py models`). Its results are shown to the user as cards with example images and a Download button, and you get a numbered summary. Do not paste image URLs or raw JSON; refer to cards by number / name, mention base model and trigger words, and ask which one to install.
- `limit` above 12 is capped; results beyond 12 are not shown. Use `cursor` to page.
- When the user names a base model / architecture (SD1.5, SDXL, Pony, Illustrious, NoobAI, Flux, Qwen, Z-Image, Wan, ...), pass it as `base_model` (a list; several allowed) instead of adding it to `query`. Only models with a version for that base are returned, and each card shows that version (its trigger words, file and Download button). `query` may be empty to list the top models of a base (e.g. `sort: "Most Downloaded"`).
- For images people posted (by a user, made with a LoRA / model, or both) use the `civitai_search_images` tool: the user sees a gallery with prompts, you get each image's `image_id`. To save picked images as example images of an installed model, call Civitai Helper's `civitai_add_user_examples` with those `image_ids` (or with `username` to take that user's images made with the model).
- Other commands (`model`, `version`, `by-hash`, `creators`, `tags`, `download-url`) still run through `run_skill_script` with `script='civitai.py'`.
- Installing: if the Civitai Helper skill is active, call `civitai_download_model` with the model page URL (`https://civitai.com/models/<id>?modelVersionId=<vid>`). If it is not active, tell the user to enable it (Skills → Civitai Helper) or give them the page URL.
- Never call `download-url` just to show a link; that URL embeds the API token.

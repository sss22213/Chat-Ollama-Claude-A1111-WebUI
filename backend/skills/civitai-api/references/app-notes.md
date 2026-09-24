# In this app

- For searching models use the `civitai_search_models` tool (it is a wrapper around `civitai.py models`). Its results are shown to the user as cards with example images and a Download button, and you get a numbered summary. Do not paste image URLs or raw JSON; refer to cards by number / name, mention base model and trigger words, and ask which one to install.
- `limit` above 12 is capped; results beyond 12 are not shown. Use `cursor` to page.
- Other commands (`model`, `version`, `by-hash`, `creators`, `tags`, `images`, `download-url`) still run through `run_skill_script` with `script='civitai.py'`.
- Installing: if the Civitai Helper skill is active, call `civitai_download_model` with the model page URL (`https://civitai.com/models/<id>?modelVersionId=<vid>`). If it is not active, tell the user to enable it (Skills → Civitai Helper) or give them the page URL.
- Never call `download-url` just to show a link; that URL embeds the API token.

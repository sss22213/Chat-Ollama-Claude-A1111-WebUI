# Civitai Helper API (reference)

Base: `<WebUI>/civitai-helper/v1` (provided by the Civitai Helper extension; the app maps the tools below onto it).

| Tool | HTTP | Notes |
|---|---|---|
| civitai_lora_inventory | GET /loras?q=&limit=&offset=&metadata=true&format=json\|csv\|md | every LoRA: `prompt_tag`, `civitai` (null if unknown), `training` (from the safetensors header: `base_model_version`, `top_tags`) |
| civitai_list_local_models | GET /models?type=&q=&no_info_only=&metadata=&limit=&format= | `items[].civitai` is null when the model has no civitai record; `trained_words` = trigger words |
| civitai_local_model_info | GET /models/{type}/info?name= | `name` = file name or relative path |
| civitai_model_examples | GET /models/{type}/examples?name= | `images[]`: `index`, `url`, `nsfw`, `has_prompt`, `prompt`, `negative_prompt`, `steps`, `sampler`, `cfg_scale`, `seed`, `size`, `model`, `local_file`, `local_url`; plus `trained_words`, `base_model`, `downloaded`/`total`, `has_preview`, `has_card_info` |
| civitai_lookup_model | GET /model-info?url_or_id= | `versions[0]` is newest; `subfolders` lists existing target subfolders |
| civitai_download_model | POST /download | body: url_or_id, version_id?, version?, subfolder="/", create_subfolder?, dl_all?, wait, timeout |
| civitai_scan_models | POST /scan | body: model_types[], wait, timeout |
| civitai_check_new_versions | POST /check-new-version | body: model_types[], wait, timeout |
| civitai_fetch_previews | POST /fetch-previews | body: `model_types[]` OR `type`+`name`, wait, timeout → `result`: models, downloaded, exists, failed, no_info, empty_info, no_images, failed_models[] |
| civitai_download_examples | POST /download-examples | body: `model_types[]` OR `type`+`name`, max_images (0 = all), overwrite, wait, timeout → `result`: models, with_info, downloaded, existed, skipped_nsfw, failed, models_with_failures[] |
| civitai_write_card_info | POST /write-card-info | body: `model_types[]` OR `type`+`name`, overwrite, set_sd_version, wait, timeout → `result`: models, written, unchanged, no_info, bad_json, bad_json_models[] |
| civitai_task_status | GET /tasks/{id}?wait=&timeout= | task: `{id, kind, status: queued/running/done/error, result, error}` |
| refresh_loras | POST /sdapi/v1/refresh-loras | WebUI core API |
| refresh_checkpoints | POST /sdapi/v1/refresh-checkpoints | WebUI core API |

Task record: `status` is `queued`, `running`, `done` or `error`. For `download`, `result` holds `file`, `model_name`, `version_name`, `trained_words`, `already_exists`.

Files written next to a model `foo.safetensors`: `foo.civitai.info` (civitai version record incl. `images[].meta`), `foo.preview.png` (card preview), `foo.example_NN.<ext>` (example images, NN = 1-based position in `images[]`), `foo.json` (WebUI card metadata: `description`, `notes`, `sd version`, plus user fields `activation text`, `preferred weight`, `negative text` that the tools never touch).
`local_url` is relative to the WebUI (`./sd_extra_networks/thumb?filename=...`); the civitai `url` is public and can be embedded in chat as a markdown image.

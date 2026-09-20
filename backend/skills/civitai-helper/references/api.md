# Civitai Helper API (reference)

Base: `<WebUI>/civitai-helper/v1` (provided by the Civitai Helper extension; the app maps the tools below onto it).

| Tool | HTTP | Notes |
|---|---|---|
| civitai_lora_inventory | GET /loras?q=&limit=&offset=&metadata=true&format=json\|csv\|md | every LoRA: `prompt_tag`, `civitai` (null if unknown), `training` (from the safetensors header: `base_model_version`, `top_tags`) |
| civitai_list_local_models | GET /models?type=&q=&no_info_only=&metadata=&limit=&format= | `items[].civitai` is null when the model has no civitai record; `trained_words` = trigger words |
| civitai_local_model_info | GET /models/{type}/info?name= | `name` = file name or relative path |
| civitai_lookup_model | GET /model-info?url_or_id= | `versions[0]` is newest; `subfolders` lists existing target subfolders |
| civitai_download_model | POST /download | body: url_or_id, version_id?, version?, subfolder="/", create_subfolder?, dl_all?, wait, timeout |
| civitai_scan_models | POST /scan | body: model_types[], wait, timeout |
| civitai_check_new_versions | POST /check-new-version | body: model_types[], wait, timeout |
| civitai_task_status | GET /tasks/{id}?wait=&timeout= | task: `{id, kind, status: queued/running/done/error, result, error}` |
| refresh_loras | POST /sdapi/v1/refresh-loras | WebUI core API |
| refresh_checkpoints | POST /sdapi/v1/refresh-checkpoints | WebUI core API |

Task record: `status` is `queued`, `running`, `done` or `error`. For `download`, `result` holds `file`, `model_name`, `version_name`, `trained_words`, `already_exists`.

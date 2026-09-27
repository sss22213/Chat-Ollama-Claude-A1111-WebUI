---
name: civitai-api
description: Query the Civitai public REST API to search models, inspect creators, fetch model or version details, reverse-lookup models by hash, search the images people posted (by user, by LoRA / model, or both) with their prompts, list tags, and build authenticated download URLs. Use when working with Civitai programmatically, browsing Civitai assets from the terminal, checking model metadata, finding download links, or building automations against https://civitai.com and the developer portal.
---

# Civitai API

Use this skill to work with Civitai from the local workspace without re-deriving endpoints and auth each time.

## Quick start

Store the token in the workspace `.env` file as:

```env
CIVITAI_API_KEY=...
```

Use the bundled script:

```powershell
python .\skills\civitai-api\scripts\civitai.py models --query "flux lora" --limit 5
python .\skills\civitai-api\scripts\civitai.py model 12345
python .\skills\civitai-api\scripts\civitai.py version 67890
python .\skills\civitai-api\scripts\civitai.py by-hash SHA256_OR_AUTOV2_HASH
python .\skills\civitai-api\scripts\civitai.py creators --query "someuser"
python .\skills\civitai-api\scripts\civitai.py tags --query anime
python .\skills\civitai-api\scripts\civitai.py images --model-id 12345 --limit 10
python .\skills\civitai-api\scripts\civitai.py download-url 67890
```

## Image search (in this app: the `civitai_search_images` tool)

Use `civitai_search_images` whenever the user wants to *see images* rather than models. The results are shown to the user as a gallery with prompts; you get a numbered summary where every image has an `image_id`.

- **"What did user X make with LoRA Y?"** → `username` + `model`. `model` is a civitai model id or page URL; a URL with `?modelVersionId=` narrows to that version, or pass `model_version_id`. If Y is a LoRA installed locally, first get its civitai ids from the Civitai Helper skill (`civitai_local_model_info` → `civitai.model_id` / `version_id`), or find the model with `civitai_search_models`.
- **"Show me user X's images" / "everything X posted"** → `username` only.
- **Community images of a model** → `model` only.
- Order with `sort` (`Most Reactions`, `Newest`, ...), narrow with `period`, page with the returned `cursor`. NSFW images are included by default (`nsfw: "X"`); pass `nsfw: "None"` only when the user asks for SFW / safe images. Videos are left out of the gallery.
- **"Save these as example images of my LoRA"** → the Civitai Helper tool `civitai_add_user_examples` with `type`, the local file `name` and `image_ids` (the ids from this search). To take everything user X made with an installed LoRA without picking, call `civitai_add_user_examples` with `username` instead (it uses that LoRA's own civitai version). Both need the Civitai Helper skill to be active.
- Refer to images by their #number; never paste image URLs or markdown.

## Workflow

### 1. Find the thing

When the user has a vague name or concept, start with:

```powershell
python .\skills\civitai-api\scripts\civitai.py models --query "search text" --limit 10
```

Useful optional filters include `--types`, `--base-model` (e.g. `Illustrious`, `Pony`, `"SD 1.5"`; repeatable), `--tag`, `--username`, `--sort`, `--period`, `--cursor`, and `--nsfw true|false`.

### 2. Expand the record

Once you have a model id, inspect the full model payload:

```powershell
python .\skills\civitai-api\scripts\civitai.py model <modelId>
```

Use this to pull:

- version ids
- files and hashes
- tags
- creator info
- images
- download URLs already present in the payload

### 3. Inspect a specific version

When the user already knows the version id, or you need file-level details:

```powershell
python .\skills\civitai-api\scripts\civitai.py version <modelVersionId>
```

### 4. Reverse-lookup by hash

When the user has a local file hash and wants to identify it:

```powershell
python .\skills\civitai-api\scripts\civitai.py by-hash <hash>
```

### 5. Build a direct download URL

When the user wants an authenticated download URL, build it with:

```powershell
python .\skills\civitai-api\scripts\civitai.py download-url <modelVersionId>
```

Optional download selectors:

- `--type`
- `--format`
- `--size`
- `--fp`

Use the generated URL directly in a browser or another download tool. Treat the resulting URL as sensitive because it may include `?token=...`.

## Pagination note

Civitai search endpoints may use cursor-based pagination. When the response includes `metadata.nextCursor`, pass that value back with `--cursor` instead of forcing `--page` on search queries.

## Auth rules

- Prefer `Authorization: Bearer <token>` for JSON API calls.
- Use `?token=<token>` only for direct download URLs.
- Keep tokens in `.env`, not in the skill files.

## References

Read `references/api-notes.md` when you need a compact reminder of endpoints, auth, filters, and workflow hints.

"""Civitai 圖片搜尋結果（civitai-api 技能的 civitai_search_images 工具）：

- 前端：推一個 gallery 事件（同 Civitai Helper 範例圖的圖庫元件），縮圖存進本機快取
  （civitai_cards 的 civitai-cache），附提示詞、生成參數、作者與用到的 LoRA。
- 模型：精簡文字摘要，每張圖帶 civitai image id，讓模型能再用 Civitai Helper 的
  civitai_add_user_examples 把挑中的圖存成某個已安裝模型的範例圖。

由 skill_tools 的 postprocess "civitai_images" 呼叫；輸入是 civitai.py images 的 JSON 輸出。
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx

import civitai_cards

_MAX_ITEMS = 30
_LORA_TYPES = ("lora", "locon", "lycoris", "dora")


def _short(text: Any, n: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _nsfw(im: dict[str, Any]) -> bool:
    level = im.get("nsfwLevel")
    if isinstance(level, int):
        return level > 1
    if isinstance(level, str) and level:
        return level != "None"
    return bool(im.get("nsfw"))


def used_loras(meta: dict[str, Any]) -> list[str]:
    """圖片生成時用到的 LoRA（'名稱:權重'），從 meta 的 resources / civitaiResources 盡量取。"""
    out = []
    for r in meta.get("resources") or []:
        if isinstance(r, dict) and str(r.get("type") or "").lower() in _LORA_TYPES and r.get("name"):
            out.append(f"{r['name']}:{r.get('weight', 1)}")
    for r in meta.get("civitaiResources") or []:
        if isinstance(r, dict) and str(r.get("type") or "").lower() in _LORA_TYPES:
            out.append(f"{r.get('modelVersionName') or 'version ' + str(r.get('modelVersionId'))}:{r.get('weight', 1)}")
    return list(dict.fromkeys(out))


def gallery_items(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, im in enumerate(images, 1):
        meta = im.get("meta") or {}
        loras = used_loras(meta)
        params = {
            "by": im.get("username"),
            "id": im.get("id"),
            "steps": meta.get("steps"),
            "sampler": meta.get("sampler"),
            "cfg_scale": meta.get("cfgScale"),
            "seed": meta.get("seed"),
            "size": meta.get("Size") or (f"{im['width']}x{im['height']}" if im.get("width") else None),
            "model": meta.get("Model") or im.get("baseModel"),
            "loras": ", ".join(loras) if loras else None,
        }
        out.append(
            {
                "index": i,
                "image_id": im.get("id"),
                "src": civitai_cards._thumb_url(im["url"]),
                "full": im["url"],
                "local": False,
                "nsfw": _nsfw(im),
                "prompt": meta.get("prompt") or "",
                "negative_prompt": meta.get("negativePrompt") or "",
                "params": {k: v for k, v in params.items() if v not in (None, "", "None")},
                "_loras": loras,
                "_post_id": im.get("postId"),
                "_level": im.get("nsfwLevel"),
            }
        )
    return out


async def _cache_thumbs(items: list[dict[str, Any]]) -> None:
    """縮圖存本機快取，對話歷史裡的圖庫才不會因為 civitai 刪圖而失效。"""
    sem = asyncio.Semaphore(5)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:

        async def one(it: dict[str, Any]) -> None:
            async with sem:
                name = await civitai_cards._fetch_thumb(client, it["full"])
            if name:
                it["src"] = f"/api/civitai-cache/{name}"

        await asyncio.gather(*(one(it) for it in items))


def _title(q: dict[str, Any]) -> str:
    parts = ["Civitai"]
    if q.get("username"):
        parts.append(f"@{q['username']}")
    if q.get("model_name"):
        parts.append(str(q["model_name"]))
    return " · ".join(parts)


def model_text(q: dict[str, Any], items: list[dict[str, Any]], videos: int, next_cursor: str | None) -> str:
    who = f" posted by {q['username']}" if q.get("username") else ""
    what = ""
    if q.get("model_name") or q.get("model_version_id") or q.get("model_id"):
        ids = f"version id {q['model_version_id']}" if q.get("model_version_id") else f"model id {q.get('model_id')}"
        what = f" made with {q.get('model_name') or '?'} ({ids})"
    if not items:
        return (
            f"No still images{who}{what} found"
            + (f" ({videos} videos were skipped)" if videos else "")
            + ". Check the username / model, or try without the model filter."
        )
    lines = [
        f"{len(items)} image(s){who}{what}. The user already sees them as a gallery numbered #1-#{len(items)} "
        "with prompts and parameters." + (f" {videos} video(s) were left out." if videos else "")
    ]
    for it in items:
        p = it["params"]
        par = ", ".join(f"{k} {p[k]}" for k in ("steps", "sampler", "cfg_scale", "seed", "size", "model") if k in p)
        lines.append(
            f"#{it['index']} image_id {it['image_id']} by {p.get('by') or '?'}"
            + (f" (NSFW: {it['_level']})" if it["nsfw"] else "")
            + f": prompt: {_short(it['prompt'], 300) or '(none)'}"
            + (f" | negative: {_short(it['negative_prompt'], 120)}" if it["negative_prompt"] else "")
            + (f" | {par}" if par else "")
            + (f" | LoRAs: {', '.join(it['_loras'])}" if it["_loras"] else "")
        )
    if next_cursor:
        lines.append(f"More images available: call again with cursor='{next_cursor}'.")
    lines.append(
        "To keep some of these as example images of a model installed in the local WebUI, use the Civitai Helper "
        "tool civitai_add_user_examples with type, the local file name and image_ids=[the image_id values above]. "
        "Do NOT write image markdown or image URLs; refer to images by #number."
    )
    return "\n".join(lines)


async def process(stdout: str) -> tuple[str, list[dict[str, Any]]]:
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return stdout, []
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return json.dumps(data, ensure_ascii=False)[:4000], []
    q = data.get("_query") or {}
    raw = [x for x in data["items"] if isinstance(x, dict) and x.get("url")]
    stills = [x for x in raw if x.get("type") in (None, "image")][:_MAX_ITEMS]
    videos = len(raw) - len([x for x in raw if x.get("type") in (None, "image")])
    items = gallery_items(stills)
    next_cursor = (data.get("metadata") or {}).get("nextCursor")
    text = model_text(q, items, videos, next_cursor)
    if not items:
        return text, []
    await _cache_thumbs(items)
    event = {
        "type": "gallery",
        "title": _title(q),
        "trained_words": [],
        "items": [{k: v for k, v in it.items() if not k.startswith("_")} for it in items],
    }
    return text, [event]

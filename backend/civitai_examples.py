"""Civitai Helper「範例圖」結果整理（civitai-helper 技能的 civitai_model_examples 工具）：

- 前端：推一個 gallery 事件，本地存好的範例圖（<model>.example_NN.*）走 /api/a1111-thumb 代理，
  沒存的用 civitai 縮圖；附提示詞與生成參數。不再靠模型自己寫 markdown 圖片網址。
- 模型：精簡文字摘要（提示詞、參數），並挑前幾張（本地優先）縮成 768px 當視覺輸入，
  由 chat.py 附在工具訊息的 images 上——支援視覺的 Ollama 模型就能真的「看到」範例圖。

由 skill_tools 的 postprocess "civitai_examples" 呼叫。
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

import httpx

import a1111_client

log = logging.getLogger("civitai_examples")

VISION_MAX = 4
_VISION_SIZE = 768


def _local_filename(local_url: str | None) -> str | None:
    """./sd_extra_networks/thumb?filename=<path>（或已改寫的 /api/a1111-thumb?...）→ <path>。"""
    if not local_url:
        return None
    q = parse_qs(urlsplit(local_url).query)
    return (q.get("filename") or [None])[0]


def _proxy(filename: str, size: int) -> str:
    return f"/api/a1111-thumb?filename={quote(filename, safe='')}&size={size}"


def _civitai_thumb(url: str, width: int = 450) -> str:
    return re.sub(r"/(original=true|width=\d+)/", f"/width={width}/", url)


def _short(text: Any, n: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def gallery_items(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for im in images:
        fn = _local_filename(im.get("local_url"))
        url = im.get("url") or ""
        if fn:
            src, full = _proxy(fn, 512), _proxy(fn, 2048)
        elif url:
            src, full = _civitai_thumb(url), url
        else:
            continue
        out.append(
            {
                "index": im.get("index"),
                "src": src,
                "full": full,
                "local": bool(fn),
                "nsfw": bool(im.get("nsfw")),
                "prompt": im.get("prompt") or "",
                "negative_prompt": im.get("negative_prompt") or "",
                "params": {
                    k: im.get(k)
                    for k in ("steps", "sampler", "cfg_scale", "seed", "clip_skip", "model", "size")
                    if im.get(k) not in (None, "", "None")
                },
            }
        )
    return out


def _to_jpeg_b64(raw: bytes) -> str | None:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as im:
            im = im.convert("RGB")
            im.thumbnail((_VISION_SIZE, _VISION_SIZE))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:  # noqa: BLE001
        log.info("decode failed: %s", e)
        return None


async def vision_images(images: list[dict[str, Any]], limit: int = VISION_MAX) -> list[tuple[int, str]]:
    """挑前 limit 張（本地優先），回 [(index, base64 JPEG)]。"""
    local = [im for im in images if _local_filename(im.get("local_url"))]
    remote = [im for im in images if not _local_filename(im.get("local_url")) and im.get("url")]
    picked = (local + remote)[:limit]

    async def one(client: httpx.AsyncClient, im: dict[str, Any]) -> tuple[int, str] | None:
        fn = _local_filename(im.get("local_url"))
        raw = None
        if fn:
            raw = await a1111_client.fetch_lora_preview([fn])
        elif im.get("url"):
            try:
                r = await client.get(_civitai_thumb(im["url"], _VISION_SIZE))
                raw = r.content if r.status_code == 200 else None
            except httpx.HTTPError:
                raw = None
        b64 = _to_jpeg_b64(raw) if raw else None
        return (int(im.get("index") or 0), b64) if b64 else None

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        got = await asyncio.gather(*(one(client, im) for im in picked))
    return [g for g in got if g]


def model_text(data: dict[str, Any], items: list[dict[str, Any]], seen: list[int]) -> str:
    words = ", ".join(w for w in (data.get("trained_words") or []) if isinstance(w, str)) or "(none)"
    lines = [
        f"Model: {data.get('model_name') or data.get('name')} (version {data.get('version_name') or '?'}, base {data.get('base_model') or '?'}), file {data.get('name')}",
        f"Trigger words: {words}",
        f"Example images: {len(items)} shown to the user as a gallery ({sum(1 for i in items if i['local'])} saved locally, "
        f"{data.get('downloaded', '?')}/{data.get('total', '?')} downloaded).",
    ]
    for it in items:
        p = it["params"]
        par = ", ".join(f"{k} {v}" for k, v in p.items())
        lines.append(
            f"#{it['index']}{' (NSFW)' if it['nsfw'] else ''}{' [attached for you to see]' if it['index'] in seen else ''}: "
            f"prompt: {_short(it['prompt'], 500) or '(none)'}"
            + (f" | negative: {_short(it['negative_prompt'], 160)}" if it["negative_prompt"] else "")
            + (f" | {par}" if par else "")
        )
    lines.append(
        "The app already displays these images to the user (gallery with prompts and a copy button). "
        "Do NOT write image markdown or image URLs. Refer to images by their #number."
    )
    return "\n".join(lines)


async def process(tool: dict[str, Any], base: str, data: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(data, dict) or not isinstance(data.get("images"), list):
        import json

        return json.dumps(data, ensure_ascii=False, indent=1)[:4000], []
    images = [im for im in data["images"] if isinstance(im, dict)]
    items = gallery_items(images)
    if not items:
        return (
            f"{data.get('model_name') or data.get('name')}: no example images on record "
            "(run civitai_scan_models first if the model has no civitai info).",
            [],
        )
    vis = await vision_images(images, int(tool.get("vision_max") or VISION_MAX))
    events: list[dict[str, Any]] = [
        {
            "type": "gallery",
            "title": f"{data.get('model_name') or data.get('name')}"
            + (f" · {data.get('version_name')}" if data.get("version_name") else "")
            + (f" · {data.get('base_model')}" if data.get("base_model") else ""),
            "trained_words": [w for w in (data.get("trained_words") or []) if isinstance(w, str)],
            "items": items,
        }
    ]
    if vis:
        events.append({"type": "_vision", "images": [b for _, b in vis], "labels": [f"#{i}" for i, _ in vis]})
    return model_text(data, items, [i for i, _ in vis]), events

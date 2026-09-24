"""Civitai 搜尋結果 → 候選卡片：把腳本回傳的 civitai JSON 整理成精簡摘要（給模型）
與結構化清單（給前端畫成卡片、含本機暫存的範例圖縮圖）。

由 skill_tools 的 postprocess "civitai_models" 呼叫（civitai-api 技能的 tools.json 宣告）。
縮圖存在 DATA_DIR/civitai-cache/<sha1>.jpg，由 main.py 的 /api/civitai-cache/{name} 提供；
這樣卡片在對話歷史裡不會因為 civitai 刪圖而失效，也不必每次都連外站。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from config import DATA_DIR

log = logging.getLogger("civitai_cards")

CACHE_DIR = DATA_DIR / "civitai-cache"
_THUMB_WIDTH = 450
_MAX_IMAGES = 3
_MAX_ITEMS = 12
_NAME_RE = re.compile(r"^[0-9a-f]{40}\.(jpe?g|png|webp|gif)$")


def cache_path(name: str) -> Path | None:
    """驗證檔名後回快取檔路徑（給 main.py 的路由用）；不合法或不存在回 None。"""
    if not _NAME_RE.match(name or ""):
        return None
    p = CACHE_DIR / name
    return p if p.is_file() else None


def _thumb_url(url: str) -> str:
    """civitai 圖片網址的 original=true 換成寬度參數就是縮圖。"""
    return re.sub(r"/(original=true|width=\d+)/", f"/width={_THUMB_WIDTH}/", url)


def _ext(url: str, content_type: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct == "image/png":
        return "png"
    if ct == "image/webp":
        return "webp"
    if ct == "image/gif":
        return "gif"
    m = re.search(r"\.(jpe?g|png|webp|gif)(?:$|\?)", url.lower())
    return m.group(1) if m else "jpg"


async def _fetch_thumb(client: httpx.AsyncClient, url: str) -> str | None:
    """下載縮圖到快取；回本機路徑名（/api/civitai-cache/<name>），失敗回 None。"""
    key = hashlib.sha1(url.encode()).hexdigest()
    for existing in CACHE_DIR.glob(f"{key}.*"):
        return existing.name
    try:
        r = await client.get(_thumb_url(url))
        if r.status_code != 200 or not r.content:
            return None
        name = f"{key}.{_ext(url, r.headers.get('content-type', ''))}"
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / name).write_bytes(r.content)
        return name
    except httpx.HTTPError as e:
        log.info("thumb fetch failed %s: %s", url, e)
        return None


def _items(data: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """接受 /models 搜尋結果（items+metadata）或單一 model 物件。"""
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"], data.get("metadata") or {}
    if isinstance(data, dict) and data.get("modelVersions"):
        return [data], {}
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)], {}
    return [], {}


def summarize(data: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """把 civitai JSON 整理成卡片清單（尚未下載縮圖）。"""
    items, meta = _items(data)
    cards: list[dict[str, Any]] = []
    for it in items[:_MAX_ITEMS]:
        versions = it.get("modelVersions") or []
        v = versions[0] if versions else {}
        files = v.get("files") or []
        primary = next((f for f in files if f.get("primary")), files[0] if files else {})
        images = []
        for im in (v.get("images") or [])[:_MAX_IMAGES]:
            url = im.get("url")
            if not url:
                continue
            images.append(
                {
                    "url": url,
                    "nsfw": (im.get("nsfwLevel") or 0) > 1,
                    "width": im.get("width"),
                    "height": im.get("height"),
                }
            )
        stats = it.get("stats") or {}
        cards.append(
            {
                "id": it.get("id"),
                "name": it.get("name"),
                "type": it.get("type"),
                "nsfw": bool(it.get("nsfw")),
                "creator": (it.get("creator") or {}).get("username"),
                "downloads": stats.get("downloadCount"),
                "rating": stats.get("rating"),
                "tags": [t for t in (it.get("tags") or [])[:6] if isinstance(t, str)],
                "version_id": v.get("id"),
                "version": v.get("name"),
                "base_model": v.get("baseModel"),
                "trained_words": [w for w in (v.get("trainedWords") or []) if isinstance(w, str)][:8],
                "size_kb": primary.get("sizeKB"),
                "file": primary.get("name"),
                "url": f"https://civitai.com/models/{it.get('id')}" + (f"?modelVersionId={v.get('id')}" if v.get("id") else ""),
                "images": images,
            }
        )
    return cards, {"next_cursor": meta.get("nextCursor"), "total_items": len(items)}


async def cache_thumbs(cards: list[dict[str, Any]]) -> None:
    """平行下載每張範例圖的縮圖（最多 5 個同時），成功的加上 thumb 本機網址。"""
    sem = asyncio.Semaphore(5)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        async def one(im: dict[str, Any]) -> None:
            async with sem:
                name = await _fetch_thumb(client, im["url"])
            if name:
                im["thumb"] = f"/api/civitai-cache/{name}"

        await asyncio.gather(*(one(im) for c in cards for im in c["images"]))


def model_text(cards: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    """給模型看的精簡摘要（卡片已顯示給使用者，模型不必重複貼圖片網址）。"""
    if not cards:
        return "No models found."
    lines = [f"{len(cards)} model(s) found. The user now sees them as cards with example images; refer to them by number or name and ask which one to download:"]
    for i, c in enumerate(cards, 1):
        words = ", ".join(c["trained_words"]) or "(none)"
        size = f", {c['size_kb'] / 1024:.0f} MB" if c.get("size_kb") else ""
        lines.append(
            f"{i}. {c['name']} — {c['type']}, base {c['base_model']}, version '{c['version']}' "
            f"(model id {c['id']}, version id {c['version_id']}{size}), {c['downloads'] or 0} downloads, "
            f"by {c['creator'] or '?'}{', NSFW' if c['nsfw'] else ''}. Trigger words: {words}. "
            f"Page: {c['url']}. Example images shown: {sum(1 for im in c['images'] if im.get('thumb'))}/{len(c['images'])}."
        )
    if meta.get("next_cursor"):
        lines.append(f"More results available: pass cursor='{meta['next_cursor']}' to continue.")
    lines.append(
        "To install one, the user can click its Download button (it asks Civitai Helper to download it), "
        "or tell you which one; then use civitai_download_model with the page URL if the Civitai Helper skill is active."
    )
    return "\n".join(lines)


async def process(stdout: str) -> tuple[str, list[dict[str, Any]]]:
    """postprocess 進入點：回 (給模型的文字, 要送給前端的事件)。解析失敗就原文回傳。"""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return stdout, []
    cards, meta = summarize(data)
    if not cards:
        return "No models found in the Civitai response.", []
    await cache_thumbs(cards)
    event = {"type": "candidates", "kind": "civitai_models", "items": cards, "next_cursor": meta.get("next_cursor")}
    return model_text(cards, meta), [event]

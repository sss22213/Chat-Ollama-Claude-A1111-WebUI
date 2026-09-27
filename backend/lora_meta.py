"""LoRA 的「底模」「Civitai 來源」「內容分類」，給 LoRA 瀏覽器篩選與詳情用。

- 底模：Civitai Helper 的 .civitai.info 有 base_model（Illustrious / Pony / SD 1.5 …）就用它；
  沒有 Civitai 資料的，從 safetensors 內嵌的訓練資訊推斷（ss_sd_model_name 含 pony →
  Pony、含 illustrious → Illustrious；ss_base_model_version 是 sd_v1 → SD 1.5、sdxl → SDXL）。
- 來源：Civitai Helper 的 /loras 清單（模型 id / 版本 id / 名稱 / 類型 / 網址）。
- 分類：Civitai 模型的標籤裡的分類標籤（character / style / poses …）。本機沒有這項資料，
  只在使用者按「更新分類」（全部，背景進行）或 LoRA 詳情的「更新」（單一）時向 Civitai 查詢，
  不會自動抓；結果存在 DATA_DIR/civitai-cache/model_tags.json。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

import settings_store
from config import DATA_DIR

log = logging.getLogger("lora_meta")

# ---------------- 底模 ----------------

def normalize_base(raw: str | None) -> str | None:
    """Civitai 的 baseModel → 篩選用的底模群組（SDXL 1.0 / SDXL Hyper → SDXL，SD 1.4 → SD 1.5…）。"""
    b = (raw or "").strip()
    if not b:
        return None
    low = b.lower()
    if low.startswith("illustrious"):
        return "Illustrious"
    if low.startswith("noobai"):
        return "NoobAI"
    if low.startswith("pony"):
        return "Pony"
    if low.startswith("sdxl"):
        return "SDXL"
    if low in ("sd 1.4", "sd 1.5", "sd 1.5 lcm", "sd 1.5 hyper", "sd1.5", "sd15") or low.startswith("sd_v1"):
        return "SD 1.5"
    if low.startswith("flux"):
        return "Flux"
    return b


def infer_base(meta: dict[str, Any] | None) -> str | None:
    """沒有 Civitai 資料時，從 kohya 訓練資訊推斷底模。"""
    meta = meta or {}
    name = str(meta.get("ss_sd_model_name") or "").lower()
    version = str(meta.get("ss_base_model_version") or "").lower()
    if "pony" in name:
        return "Pony"
    if "noob" in name:
        return "NoobAI"
    if "illustrious" in name:
        return "Illustrious"
    if version.startswith("sd_v1") or name.startswith(("v1-5", "sd-v1", "sd15", "sd_v1")):
        return "SD 1.5"
    if version.startswith("sdxl") or "xl" in name:
        return "SDXL"
    return None


# ---------------- Civitai Helper 清單（來源資料） ----------------

def _ch_url(path: str) -> str:
    return f"{settings_store.get_a1111_url()}/civitai-helper/v1{path}"


async def inventory() -> dict[str, dict[str, Any]]:
    """{A1111 端的 LoRA 絕對路徑: civitai 摘要}；Civitai Helper 不在時回 {}。"""
    out: dict[str, dict[str, Any]] = {}
    page = 5000  # API 單頁上限
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            offset = 0
            while True:
                r = await client.get(
                    _ch_url("/loras"),
                    params={"limit": page, "offset": offset, "format": "json", "metadata": "false"},
                )
                r.raise_for_status()
                d = r.json()
                folder = str(d.get("folder") or "").rstrip("/")
                items = d.get("items") or []
                for it in items:
                    c = it.get("civitai")
                    if isinstance(c, dict) and c.get("model_id"):
                        out[f"{folder}/{it.get('path')}"] = c
                offset += len(items)
                if len(items) < page or offset >= int(d.get("total") or 0):
                    break
    except (httpx.HTTPError, ValueError) as e:
        log.info("civitai helper inventory unavailable: %s", e)
        return {}
    return out


_CIVITAI_HOST = re.compile(r"^civitai\.(com|red|green)$")


def source_of(c: dict[str, Any]) -> dict[str, Any]:
    """civitai 摘要 → 詳情顯示用的來源資料（網址帶版本 id，直接開到那個版本）。"""
    url = str(c.get("model_url") or "")
    host = urlsplit(url).hostname or ""
    if not _CIVITAI_HOST.match(host):
        host = "civitai.com"
    model_id, version_id = c.get("model_id"), c.get("version_id")
    page = f"https://{host}/models/{model_id}" + (f"?modelVersionId={version_id}" if version_id else "")
    return {
        "model_id": model_id,
        "version_id": version_id,
        "model_name": c.get("model_name") or "",
        "version_name": c.get("version_name") or "",
        "type": c.get("type") or "",
        "base_model": c.get("base_model") or "",
        "nsfw": bool(c.get("nsfw")),
        "url": page,
        "host": host,
    }


# ---------------- 內容分類（Civitai 模型標籤，背景抓取 + 快取） ----------------

# Civitai 的分類標籤，依優先順序（一個模型有好幾個時取最前面的）
CATEGORIES = (
    "character", "celebrity", "clothing", "poses", "action", "style", "concept",
    "background", "buildings", "vehicle", "objects", "animal", "tool", "assets",
)
_TAGS_FILE = DATA_DIR / "civitai-cache" / "model_tags.json"
_CONCURRENCY = 4

_tags: dict[str, dict[str, Any]] | None = None
_job: asyncio.Task | None = None
_job_total = 0
_job_done = 0
_last_failed = 0  # 上一輪抓取失敗的數量（顯示給使用者）


def _load() -> dict[str, dict[str, Any]]:
    global _tags
    if _tags is None:
        try:
            _tags = json.loads(_TAGS_FILE.read_text(encoding="utf-8"))
            if not isinstance(_tags, dict):
                _tags = {}
        except (OSError, ValueError):
            _tags = {}
    return _tags


def _save() -> None:
    try:
        _TAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _TAGS_FILE.with_suffix(".part")
        tmp.write_text(json.dumps(_load(), ensure_ascii=False), encoding="utf-8")
        tmp.replace(_TAGS_FILE)
    except OSError as e:
        log.warning("save %s failed: %s", _TAGS_FILE, e)


def category(model_id: Any) -> str | None:
    """分類 key（character / style …）；有標籤但都不是分類標籤 → "other"；還沒抓到 → None。"""
    e = _load().get(str(model_id)) if model_id else None
    if not e or e.get("missing"):
        return None
    tags = {str(t).lower() for t in e.get("tags") or []}
    return next((c for c in CATEGORIES if c in tags), "other")


def creator(model_id: Any) -> str:
    e = _load().get(str(model_id)) if model_id else None
    return (e or {}).get("creator") or ""


async def _fetch_one(client: httpx.AsyncClient, model_id: str, host: str) -> bool:
    """抓一個模型的標籤存進快取；成功（含 404）回 True，要下次再試回 False。"""
    for attempt in range(3):
        try:
            r = await client.get(f"https://{host}/api/v1/models/{model_id}")
        except httpx.HTTPError:
            await asyncio.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 429:
            await asyncio.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 404:
            _load()[model_id] = {"missing": True, "at": int(time.time())}
            return True
        if r.status_code != 200:
            return False
        try:
            d = r.json()
        except ValueError:
            return False
        _load()[model_id] = {
            "tags": [str(t) for t in d.get("tags") or []],
            "creator": (d.get("creator") or {}).get("username") or "",
            "at": int(time.time()),
        }
        return True
    return False


async def _run(todo: list[tuple[str, str]]) -> None:
    global _job_done, _last_failed
    sem = asyncio.Semaphore(_CONCURRENCY)
    errors = 0

    async def one(client: httpx.AsyncClient, model_id: str, host: str) -> None:
        nonlocal errors
        global _job_done
        async with sem:
            ok = await _fetch_one(client, model_id, host)
        _job_done += 1
        if not ok:
            errors += 1
        if _job_done % 25 == 0:
            _save()

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        await asyncio.gather(*(one(client, mid, host) for mid, host in todo))
    _save()
    _last_failed = errors
    log.info("civitai model tags: %d fetched, %d failed", len(todo) - errors, errors)


def _running() -> bool:
    return bool(_job and not _job.done())


def refresh_all(sources: list[dict[str, Any]]) -> bool:
    """使用者按「更新分類」：背景向 Civitai 查詢全部模型的標籤（已經在跑就不重複開）。"""
    global _job, _job_total, _job_done
    if _running():
        return False
    todo: dict[str, str] = {}
    for s in sources:
        mid = str(s.get("model_id") or "")
        if mid and mid not in todo:
            todo[mid] = s.get("host") or "civitai.com"
    if not todo:
        return False
    _job_total, _job_done = len(todo), 0
    _job = asyncio.create_task(_run(list(todo.items())))
    return True


async def refresh_one(source: dict[str, Any]) -> bool:
    """立刻重抓一個模型的標籤（LoRA 詳情的「更新」）；失敗回 False，快取維持原狀。"""
    mid = str(source.get("model_id") or "")
    if not mid:
        return False
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        ok = await _fetch_one(client, mid, source.get("host") or "civitai.com")
    if ok:
        _save()
    return ok


def status(sources: list[dict[str, Any]]) -> dict[str, Any]:
    """抓取中：這一輪的進度（全部重抓時也從 0 算起）；沒在抓：已有標籤的模型數。
    failed＝上一輪失敗的數量。"""
    if _running():
        return {"total": _job_total, "done": _job_done, "running": True, "failed": 0}
    ids = {str(s.get("model_id")) for s in sources if s.get("model_id")}
    cache = _load()
    return {
        "total": len(ids),
        "done": sum(1 for i in ids if i in cache),
        "running": False,
        "failed": _last_failed,
    }

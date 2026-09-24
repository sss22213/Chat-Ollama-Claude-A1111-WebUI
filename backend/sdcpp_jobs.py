"""stable-diffusion.cpp 伺服器（/sdcpp/v1）的非同步工作：技能 HTTP 工具送出 img_gen 後，
由這裡輪詢 /sdcpp/v1/jobs/{id} 直到完成，把結果圖存進圖片目錄並推 image 事件給前端
（與 A1111 生圖的顯示方式相同）。由 skill_tools 的 postprocess "sdcpp_job" 呼叫。
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from typing import Any

import httpx

import settings_store

log = logging.getLogger("sdcpp_jobs")

_POLL_EVERY = 2.0
_DONE = {"completed", "done", "finished", "success"}
_FAILED = {"failed", "error", "cancelled", "canceled"}


def _fail(reason: str) -> tuple[str, list[dict[str, Any]]]:
    """失敗：寫進後端 log、在對話顯示紅色錯誤框（不只靠模型轉述），並告訴模型原因。"""
    log.warning("sd.cpp edit failed: %s", reason)
    return (
        f"{reason}\nTell the user this exact reason in their language; do not claim the edit succeeded.",
        [{"type": "error", "message": f"sd.cpp：{reason}"}],
    )


def _save(b64: str, fmt: str) -> str:
    raw = base64.b64decode(b64.split(",", 1)[1] if b64.startswith("data:") else b64)
    ext = "jpg" if fmt in ("jpeg", "jpg") else (fmt or "png")
    name = f"{uuid.uuid4().hex}.{ext}"
    d = settings_store.get_image_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(raw)
    return f"/images/{name}"


async def process(tool: dict[str, Any], base: str, data: Any) -> tuple[str, list[dict[str, Any]]]:
    """data＝img_gen 的回應（含 id / poll_url / status）。回 (給模型的文字, image 事件)。"""
    if not isinstance(data, dict):
        return _fail("sd.cpp returned an unexpected response.")
    job_id = data.get("id")
    poll_url = data.get("poll_url") or (f"/sdcpp/v1/jobs/{job_id}" if job_id else None)
    if not poll_url:
        return _fail(f"sd.cpp did not return a job id: {str(data)[:300]}")
    url = base + poll_url
    deadline = time.monotonic() + float(tool.get("timeout") or 300)
    job: dict[str, Any] = data
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            status = str(job.get("status") or "").lower()
            if status in _DONE or status in _FAILED:
                break
            if time.monotonic() > deadline:
                with _suppress():
                    await client.post(url + "/cancel")
                return _fail(f"sd.cpp job {job_id} did not finish within {tool.get('timeout')}s and was cancelled.")
            await asyncio.sleep(_POLL_EVERY)
            try:
                r = await client.get(url)
                job = r.json()
            except (httpx.HTTPError, ValueError) as e:
                log.info("poll failed: %s", e)
                continue
    if str(job.get("status") or "").lower() in _FAILED:
        return _fail(f"sd.cpp job {job_id} failed: {job.get('error') or job.get('status')}")
    result = job.get("result") or {}
    images = result.get("images") or []
    fmt = str(result.get("output_format") or "png").lower()
    events: list[dict[str, Any]] = []
    params = {k: v for k, v in (tool.get("_sent") or {}).items() if k not in ("ref_images", "init_image", "mask_image", "control_image")}
    for im in images:
        b64 = im.get("b64_json") if isinstance(im, dict) else im
        if not b64:
            continue
        try:
            url_out = _save(b64, fmt)
        except Exception as e:  # noqa: BLE001
            log.warning("save failed: %s", e)
            continue
        events.append({"type": "image", "url": url_out, "params": params, "info": ""})
    if not events:
        return _fail(f"sd.cpp job {job_id} completed but returned no image ({job.get('error') or 'no error given'}).")
    text = (
        f"Done: {len(events)} image(s) were generated and are already shown to the user inline. "
        "You cannot see the result, so do not claim specific details changed; say the edited image "
        "is shown and ask the user to check it. Do not print image URLs or base64."
    )
    # 參考圖編輯但伺服器載的是一般 SD checkpoint → 參考圖會被忽略，要讓模型老實告訴使用者
    if (tool.get("attach_image") or {}).get("field") == "ref_images":
        warn = await _edit_model_warning(base)
        if warn:
            text += "\n\n" + warn
    return text, events


async def _edit_model_warning(base: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            caps = (await client.get(base + "/sdcpp/v1/capabilities")).json()
    except (httpx.HTTPError, ValueError):
        return ""
    model = (caps or {}).get("model") or {}
    name = str(model.get("name") or model.get("stem") or "")
    if not name or any(h in (name + str(model.get("path") or "")).lower() for h in _EDIT_HINTS):
        return ""
    return (
        f"WARNING: the sd.cpp server has '{name}' loaded, a normal Stable Diffusion checkpoint, not an "
        "image-editing model, so the reference image was most likely IGNORED and the result is a new "
        "picture from the text alone. Tell the user this plainly, and say that instruction edits need "
        "an editing model (e.g. Qwen-Image 2.1) loaded in the sd.cpp server; offer sdcpp_img2img as the "
        "alternative that keeps the composition."
    )


class _suppress:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return True


_EDIT_HINTS = ("qwen", "edit", "kontext", "flux", "omnigen", "step1x")


def caps_summary(data: Any) -> str:
    """/sdcpp/v1/capabilities 精簡成模型看得懂的幾行（原始回應很長，會把重點截掉）。"""
    if not isinstance(data, dict):
        return str(data)[:500]
    model = data.get("model") or {}
    name = model.get("name") or model.get("stem") or "(split model: see server args)"
    path = str(model.get("path") or "")
    feats = [k for k, v in (data.get("features") or {}).items() if v]
    lim = data.get("limits") or {}
    looks_edit = any(h in (name + path).lower() for h in _EDIT_HINTS) or not model
    return "\n".join(
        [
            f"Loaded model: {name}" + (f" ({path})" if path and path != name else ""),
            "Looks like an image-EDITING model: "
            + ("yes/unknown (split model) — use sdcpp_edit_image" if looks_edit else "NO — a normal SD checkpoint; ref_images are ignored, use sdcpp_img2img"),
            f"Features: {', '.join(feats) or '(none)'}",
            f"Size limits: {lim.get('min_width', '?')}–{lim.get('max_width', '?')} x {lim.get('min_height', '?')}–{lim.get('max_height', '?')}",
        ]
    )

"""A1111 (Automatic1111) 串接：列模型/取樣器/選項、txt2img、img2img、進度查詢、PNG Info。"""
from __future__ import annotations

import base64
import json
import re
import uuid
from typing import Any

import httpx

import settings_store
from config import HTTP_TIMEOUT


async def list_sd_models() -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{settings_store.get_a1111_url()}/sdapi/v1/sd-models")
        resp.raise_for_status()
        return [
            {"model_name": m["model_name"], "title": m["title"]}
            for m in resp.json()
        ]


async def list_samplers() -> list[str]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{settings_store.get_a1111_url()}/sdapi/v1/samplers")
        resp.raise_for_status()
        return [s["name"] for s in resp.json()]


async def get_options() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{settings_store.get_a1111_url()}/sdapi/v1/options")
        resp.raise_for_status()
        return resp.json()


async def get_current_model() -> str | None:
    try:
        return (await get_options()).get("sd_model_checkpoint")
    except Exception:
        return None


async def get_progress() -> dict[str, Any]:
    """目前生成進度。回傳 A1111 progress payload（含 progress 0~1、state、current_image）。"""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{settings_store.get_a1111_url()}/sdapi/v1/progress",
            params={"skip_current_image": "false"},
        )
        resp.raise_for_status()
        return resp.json()


def _strip_data_url(b64: str) -> str:
    """移除 data:image/...;base64, 前綴。"""
    return b64.split(",", 1)[-1] if b64.startswith("data:") else b64


def _common_payload(
    *,
    prompt: str,
    negative_prompt: str,
    steps: int,
    cfg_scale: float,
    width: int,
    height: int,
    sampler_name: str,
    seed: int,
    sd_model_checkpoint: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt": prompt,
        "negative_prompt": negative_prompt or "",
        "steps": steps,
        "cfg_scale": cfg_scale,
        "width": width,
        "height": height,
        "sampler_name": sampler_name,
        "seed": seed,
    }
    if sd_model_checkpoint:
        payload["override_settings"] = {"sd_model_checkpoint": sd_model_checkpoint}
        payload["override_settings_restore_afterwards"] = True
    return payload


def _save_first_image(data: dict[str, Any]) -> str:
    images = data.get("images") or []
    if not images:
        raise RuntimeError("A1111 未回傳任何圖片")
    raw = base64.b64decode(_strip_data_url(images[0]))
    filename = f"{uuid.uuid4().hex}.png"
    image_dir = settings_store.get_image_dir()
    image_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / filename).write_bytes(raw)
    return f"/images/{filename}"


def _clean_geninfo(data: dict[str, Any]) -> str:
    """A1111 txt2img/img2img 的 info 常是 JSON 字串，真正人類可讀的 geninfo
    （含實際 seed/model）在 infotexts[0]；取它，取不到才退回原字串。"""
    raw = data.get("info") or ""
    if not raw:
        return ""
    try:
        obj = json.loads(raw)
        texts = obj.get("infotexts")
        if isinstance(texts, list) and texts:
            return str(texts[0])
    except (ValueError, TypeError):
        pass
    return str(raw)


def _result(url: str, params: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    return {"url": url, "params": params, "info": _clean_geninfo(data)}


async def txt2img(
    prompt: str,
    negative_prompt: str = "",
    *,
    steps: int = 28,
    cfg_scale: float = 5.0,
    width: int = 1024,
    height: int = 1024,
    sampler_name: str = "Euler a",
    seed: int = -1,
    sd_model_checkpoint: str = "",
) -> dict[str, Any]:
    payload = _common_payload(
        prompt=prompt,
        negative_prompt=negative_prompt,
        steps=steps,
        cfg_scale=cfg_scale,
        width=width,
        height=height,
        sampler_name=sampler_name,
        seed=seed,
        sd_model_checkpoint=sd_model_checkpoint,
    )
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(f"{settings_store.get_a1111_url()}/sdapi/v1/txt2img", json=payload)
        resp.raise_for_status()
        data = resp.json()

    url = _save_first_image(data)
    params = {
        "mode": "txt2img",
        "prompt": prompt,
        "negative_prompt": negative_prompt or "",
        "steps": steps,
        "cfg_scale": cfg_scale,
        "width": width,
        "height": height,
        "sampler_name": sampler_name,
        "seed": seed,
        "sd_model_checkpoint": sd_model_checkpoint or None,
    }
    return _result(url, params, data)


async def img2img(
    init_image_b64: str,
    prompt: str,
    negative_prompt: str = "",
    *,
    denoising_strength: float = 0.6,
    steps: int = 28,
    cfg_scale: float = 5.0,
    width: int = 1024,
    height: int = 1024,
    sampler_name: str = "Euler a",
    seed: int = -1,
    sd_model_checkpoint: str = "",
) -> dict[str, Any]:
    payload = _common_payload(
        prompt=prompt,
        negative_prompt=negative_prompt,
        steps=steps,
        cfg_scale=cfg_scale,
        width=width,
        height=height,
        sampler_name=sampler_name,
        seed=seed,
        sd_model_checkpoint=sd_model_checkpoint,
    )
    payload["init_images"] = [_strip_data_url(init_image_b64)]
    payload["denoising_strength"] = denoising_strength

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(f"{settings_store.get_a1111_url()}/sdapi/v1/img2img", json=payload)
        resp.raise_for_status()
        data = resp.json()

    url = _save_first_image(data)
    params = {
        "mode": "img2img",
        "prompt": prompt,
        "negative_prompt": negative_prompt or "",
        "denoising_strength": denoising_strength,
        "steps": steps,
        "cfg_scale": cfg_scale,
        "width": width,
        "height": height,
        "sampler_name": sampler_name,
        "seed": seed,
        "sd_model_checkpoint": sd_model_checkpoint or None,
    }
    return _result(url, params, data)


# ---- PNG Info：讀取圖片內嵌的生成參數 ----

# 解析 A1111 參數行：key: value，value 可被引號包住（內含逗號）。
_PARAM_RE = re.compile(r'\s*([\w \-/]+):\s*("(?:\\.|[^\\"])*"|[^,]*?)(?:,|$)')
# 判斷哪一行是「參數行」（含 Steps/Sampler/Seed/CFG/Size 等鍵）。
_PARAM_LINE_RE = re.compile(r"(^|,)\s*(Steps|Sampler|Seed|CFG scale|Size|Model):")


def parse_geninfo(info: str) -> dict[str, Any]:
    """把 A1111 的 geninfo 字串拆成 prompt / negative / 原始參數 / 可套用設定。"""
    info = (info or "").strip()
    if not info:
        return {"prompt": "", "negative_prompt": "", "params": {}, "settings": {}}

    lines = info.split("\n")
    params_line = ""
    body = lines
    if lines and _PARAM_LINE_RE.search(lines[-1]):
        params_line = lines[-1].strip()
        body = lines[:-1]

    prompt_parts: list[str] = []
    negative = ""
    in_neg = False
    for ln in body:
        if ln.startswith("Negative prompt:"):
            in_neg = True
            negative = ln[len("Negative prompt:") :].strip()
        elif in_neg:
            negative += "\n" + ln
        else:
            prompt_parts.append(ln)
    prompt = "\n".join(prompt_parts).strip()
    negative = negative.strip()

    raw: dict[str, str] = {}
    for m in _PARAM_RE.finditer(params_line):
        key = m.group(1).strip()
        val = m.group(2).strip()
        if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
            val = val[1:-1]
        if key:
            raw[key] = val

    settings: dict[str, Any] = {}
    if negative:
        settings["negative_prompt"] = negative

    def _as_int(key: str) -> int | None:
        try:
            return int(float(raw[key]))
        except (KeyError, ValueError):
            return None

    def _as_float(key: str) -> float | None:
        try:
            return float(raw[key])
        except (KeyError, ValueError):
            return None

    if (v := _as_int("Steps")) is not None:
        settings["steps"] = v
    if (v := _as_float("CFG scale")) is not None:
        settings["cfg_scale"] = v
    if (v := _as_int("Seed")) is not None:
        settings["seed"] = v
    if raw.get("Sampler"):
        settings["sampler_name"] = raw["Sampler"]
    if (v := _as_float("Denoising strength")) is not None:
        settings["denoising_strength"] = v
    size = raw.get("Size", "")
    if "x" in size.lower():
        try:
            w, h = size.lower().split("x", 1)
            settings["width"] = int(w)
            settings["height"] = int(h)
        except ValueError:
            pass
    if raw.get("Model"):
        settings["sd_model_checkpoint"] = raw["Model"]

    return {
        "prompt": prompt,
        "negative_prompt": negative,
        "params": raw,
        "settings": settings,
    }


async def png_info(image_b64: str) -> dict[str, Any]:
    """呼叫 A1111 /sdapi/v1/png-info 讀取圖片內嵌的生成參數並解析。

    回傳 {info(原始字串), prompt, negative_prompt, params(原始 key:value), settings(可套用)}。
    info 為空代表該圖沒有可讀的 metadata（截圖、轉存、非 AI 生成等）。
    """
    b64 = _strip_data_url(image_b64)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{settings_store.get_a1111_url()}/sdapi/v1/png-info",
            json={"image": f"data:image/png;base64,{b64}"},
        )
        resp.raise_for_status()
        data = resp.json()

    info = (data.get("info") or "").strip()
    return {"info": info, **parse_geninfo(info)}

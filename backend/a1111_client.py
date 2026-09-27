"""A1111 (Automatic1111) 串接：列模型/取樣器/選項、txt2img、img2img、進度查詢、PNG Info。"""
from __future__ import annotations

import base64
import json
import os
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


async def list_loras() -> list[dict[str, Any]]:
    """列出 A1111 目前掃描到的 LoRA（含安全張量內嵌 metadata，可萃取觸發詞）。"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{settings_store.get_a1111_url()}/sdapi/v1/loras")
        resp.raise_for_status()
        return resp.json()


async def refresh_loras() -> None:
    """請 A1111 重新掃描 LoRA 目錄（放了新檔不必重啟 WebUI）。"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{settings_store.get_a1111_url()}/sdapi/v1/refresh-loras"
        )
        resp.raise_for_status()


async def fetch_lora_preview(candidates: list[str]) -> bytes | None:
    """依序向 A1111 內部 extra-networks 路由探多個候選預覽路徑，
    回第一個成功取得的圖片位元組；全部失敗回 None。
    注意：/sd_extra_networks/thumb 是 A1111 未公開的內部路由（隨版本可能變動）。"""
    base = settings_store.get_a1111_url()
    async with httpx.AsyncClient(timeout=15) as client:
        for cand in candidates:
            try:
                resp = await client.get(
                    f"{base}/sd_extra_networks/thumb", params={"filename": cand}
                )
            except httpx.HTTPError:
                continue
            if resp.status_code == 200 and resp.headers.get(
                "content-type", ""
            ).startswith("image"):
                return resp.content
    return None


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


class A1111Error(RuntimeError):
    """A1111 / Forge 端的錯誤（伺服器或模型設定問題，不是 prompt 的問題）。"""


def _check(resp: httpx.Response) -> None:
    """回錯誤碼時把 Forge 給的原因（error / message / detail）帶進例外，不要只剩「HTTP 500」。"""
    if resp.status_code < 400:
        return
    reason = ""
    try:
        data = resp.json()
        if isinstance(data, dict):
            parts = [str(data.get(k) or "").strip() for k in ("error", "message", "detail")]
            reason = "：".join(dict.fromkeys(p for p in parts if p))
    except ValueError:
        reason = resp.text[:200].strip()
    raise A1111Error(f"A1111 回應 HTTP {resp.status_code}" + (f"（{reason}）" if reason else ""))


# ---------------- Forge Neo 的額外模組（VAE / 文字編碼器） ----------------
# 有些架構的 checkpoint 不含文字編碼器 / VAE，要在 Forge Neo 上方的「VAE / Text Encoder」另外選；
# API 只指定 checkpoint 會失敗（Failed to load diffusion model）。依 checkpoint 的家族自動帶上。
_FAMILY_MODULES: dict[str, tuple[tuple[str, str], ...]] = {
    # Anima（Anima base / WAI-ANIMA / One Obsession Anima 2.9B）：Qwen3 0.6B 文字編碼器 + Qwen-Image VAE
    "Anima": (("文字編碼器", "qwen_3_06b_base"), ("VAE", "qwen_image_vae")),
}
_ANIMA_NAME = re.compile(r"anima(?![a-z])", re.I)  # waiANIMA_、anima-base、oneObsession_anima29B；不含 animagine
_family_cache: dict[str, str | None] = {}


def _ckpt_key(checkpoint: str) -> str:
    """設定裡的 checkpoint 可能是 model_name、檔名或 title（帶 [hash]）→ 統一成不含副檔名的名稱。"""
    name = checkpoint.split(" [", 1)[0].strip()
    return re.sub(r"\.(safetensors|ckpt|gguf|pt)$", "", name, flags=re.I)


async def checkpoint_family(checkpoint: str) -> str | None:
    """需要額外模組的 checkpoint 家族（目前只有 "Anima"），其他回 None。
    Civitai Helper 記錄的底模優先；沒有記錄（或查不到）才看檔名。"""
    key = _ckpt_key(checkpoint)
    if not key:
        return None
    if key in _family_cache:
        return _family_cache[key]
    base = ""
    url = settings_store.get_a1111_url()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            models = (await client.get(f"{url}/sdapi/v1/sd-models")).json()
            m = next((m for m in models if key in (m.get("model_name"), _ckpt_key(m.get("title") or ""))), None)
            if m:
                # Civitai Helper 用相對於 checkpoint 資料夾的路徑找模型
                rel = re.split(r"[\\/]Stable-diffusion[\\/]", m.get("filename") or "", maxsplit=1)[-1]
                r = await client.get(f"{url}/civitai-helper/v1/models/ckp/info", params={"name": rel})
                if r.status_code == 200:
                    base = str(((r.json() or {}).get("civitai") or {}).get("base_model") or "")
    except (httpx.HTTPError, ValueError, TypeError):
        return "Anima" if _ANIMA_NAME.search(key) else None  # 暫時查不到：不快取，下次再問
    if base:
        family = "Anima" if base.lower().startswith("anima") else None
    else:
        family = "Anima" if _ANIMA_NAME.search(key) else None
    _family_cache[key] = family
    return family


async def _module_overrides(checkpoint: str) -> dict[str, Any]:
    """這個 checkpoint 需要的 Forge 額外模組（override_settings 用）；不需要回 {}。"""
    family = await checkpoint_family(checkpoint) if checkpoint else None
    wanted = _FAMILY_MODULES.get(family or "")
    if not wanted:
        return {}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{settings_store.get_a1111_url()}/sdapi/v1/sd-modules")
        _check(resp)
        modules = resp.json()
    stems = {m["filename"]: _ckpt_key(os.path.basename(m.get("filename") or "")).lower() for m in modules}
    picked, missing = [], []
    for label, stem in wanted:
        # 同名優先（qwen_image_vae 不要挑到 qwen_image_2.1_vae），其次同前綴（例如 _fp8 版）
        hit = next((f for f, s in stems.items() if s == stem), None) or next(
            (f for f, s in stems.items() if s.startswith(stem)), None
        )
        if hit:
            picked.append(hit)
        else:
            missing.append(f"{label} {stem}")
    if missing:
        raise A1111Error(
            f"{_ckpt_key(checkpoint)} 是 {family} 模型，Forge 需要另外載入 {'、'.join(missing)}，"
            "但 Forge 的 models/text_encoder、models/VAE 裡找不到"
        )
    return {"forge_additional_modules": picked}


async def _apply_modules(payload: dict[str, Any], checkpoint: str) -> None:
    """把 checkpoint 需要的 Forge 額外模組放進 override_settings（生完還原）。
    checkpoint 留空＝沿用 Forge 目前選的，就先問 Forge 選的是哪個（Forge 介面選了 Anima
    卻沒選文字編碼器 / VAE 時也能生）。問不到就照舊不帶。"""
    extra = await _module_overrides(checkpoint or await get_current_model() or "")
    if extra:
        payload.setdefault("override_settings", {}).update(extra)
        payload["override_settings_restore_afterwards"] = True


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
    await _apply_modules(payload, sd_model_checkpoint)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(f"{settings_store.get_a1111_url()}/sdapi/v1/txt2img", json=payload)
        _check(resp)
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
    await _apply_modules(payload, sd_model_checkpoint)

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(f"{settings_store.get_a1111_url()}/sdapi/v1/img2img", json=payload)
        _check(resp)
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

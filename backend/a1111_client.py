"""A1111（Forge Neo）串接：列模型 / 取樣器 / LoRA、txt2img、img2img、進度查詢、PNG Info。

一律經由 A1111 與 Civitai Helper 的 MCP 伺服器（mcp_client）：工具名稱見 Forge 的
extensions-builtin/sd_forge_mcp。只有 LoRA 預覽圖這種靜態檔案（/sd_extra_networks/thumb）直接用 HTTP 取。
"""
from __future__ import annotations

import base64
import json
import os
import re
import uuid
from typing import Any

import httpx

import mcp_client
import settings_store
from config import HTTP_TIMEOUT


class A1111Error(RuntimeError):
    """A1111 / Forge 端的錯誤（伺服器、MCP 連線或模型設定問題，不是 prompt 的問題）。"""


async def _mcp(tool: str, args: dict[str, Any] | None = None, *, server: str = "a1111",
               timeout: float | None = 60) -> Any:
    """呼叫 A1111（或 Civitai Helper）的 MCP 工具，回結構化結果；連線或工具錯誤丟 A1111Error。"""
    try:
        return await mcp_client.call_json(server, tool, args or {}, timeout=timeout)
    except mcp_client.McpError as e:
        raise A1111Error(str(e)) from None


async def list_sd_models() -> list[dict[str, str]]:
    data = await _mcp("list_checkpoints")
    return [{"model_name": m["name"], "title": m["title"]} for m in data.get("checkpoints") or []]


async def list_samplers() -> list[str]:
    return [s["name"] for s in (await _mcp("list_samplers")).get("items") or []]


async def list_loras() -> list[dict[str, Any]]:
    """列出 A1111 目前掃描到的 LoRA（含安全張量內嵌 metadata，可萃取觸發詞）。"""
    return (await _mcp("list_loras", {"full": True})).get("items") or []


async def refresh_loras() -> None:
    """請 A1111 重新掃描 LoRA 目錄（放了新檔不必重啟 WebUI）。"""
    await _mcp("refresh_loras")


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


async def get_current_model() -> str | None:
    try:
        return (await _mcp("list_checkpoints")).get("current") or None
    except Exception:
        return None


async def get_progress() -> dict[str, Any]:
    """目前生成進度：{progress 0~1, eta_relative, state, current_image（預覽圖 base64）}。"""
    try:
        res = await mcp_client.call("a1111", "get_progress", {"preview": True}, timeout=15)
    except mcp_client.McpError as e:
        raise A1111Error(str(e)) from None
    if res.is_error:
        raise A1111Error(res.text)
    data = dict(res.structured or {})
    data["current_image"] = res.images[0][0] if res.images else None
    return data


def _strip_data_url(b64: str) -> str:
    """移除 data:image/...;base64, 前綴。"""
    return b64.split(",", 1)[-1] if b64.startswith("data:") else b64


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
    try:
        models = (await _mcp("list_checkpoints", timeout=10)).get("checkpoints") or []
        m = next((m for m in models if key in (_ckpt_key(m.get("name") or ""), _ckpt_key(m.get("title") or ""))), None)
        if m:
            # Civitai Helper 用相對於 checkpoint 資料夾的路徑找模型
            info = await mcp_client.call("civitai-helper", "civitai_local_model_info",
                                         {"type": "ckp", "name": m.get("file") or m["name"]}, timeout=10)
            if not info.is_error and isinstance(info.structured, dict):
                base = str((info.structured.get("civitai") or {}).get("base_model") or "")
    except (A1111Error, mcp_client.McpError):
        return "Anima" if _ANIMA_NAME.search(key) else None  # 暫時查不到：不快取，下次再問
    if base:
        family = "Anima" if base.lower().startswith("anima") else None
    else:
        family = "Anima" if _ANIMA_NAME.search(key) else None
    _family_cache[key] = family
    return family


# 沒有 Civitai 記錄時從檔名猜底模（順序重要：waiANINSFWPONYXL 是 Pony、animagineXL 是 SDXL）
_BASE_BY_NAME = (
    (_ANIMA_NAME, "Anima"),
    (re.compile(r"pony", re.I), "Pony"),
    (re.compile(r"noob", re.I), "NoobAI"),
    (re.compile(r"illustrious|illu(?![a-z])", re.I), "Illustrious"),
    (re.compile(r"flux", re.I), "Flux"),
    (re.compile(r"xl|sdxl", re.I), "SDXL"),
)


async def list_checkpoints() -> dict[str, Any]:
    """A1111 的 checkpoint 與各自的底模（Illustrious / Pony / SDXL / SD 1.5 / Anima …）。
    回 {"current": 目前載入的 model_name, "checkpoints": [{"name", "title", "base", "base_source"}]}；
    底模用 Civitai Helper 的記錄（civitai），沒有記錄看檔名（name），都猜不到是空字串。"""
    import lora_meta  # 底模名稱正規化跟 LoRA 共用

    data = await _mcp("list_checkpoints")
    recorded: dict[str, str] = {}
    try:
        inv = await mcp_client.call_json("civitai-helper", "civitai_list_local_models",
                                         {"type": "ckp", "limit": 5000})
        for it in (inv or {}).get("items") or []:
            base = str((it.get("civitai") or {}).get("base_model") or "")
            if base:
                recorded[_ckpt_key(str(it.get("path") or it.get("name") or "")).replace("\\", "/")] = base
    except (mcp_client.McpError, AttributeError):
        pass  # Civitai Helper 不在：全部看檔名
    out = []
    for m in data.get("checkpoints") or []:
        raw = recorded.get(_ckpt_key(m.get("file") or m["name"]).replace("\\", "/"), "")
        base = lora_meta.normalize_base(raw) if raw else next(
            (b for rx, b in _BASE_BY_NAME if rx.search(m["name"])), "")
        out.append({"name": m["name"], "title": m["title"], "base": base or "",
                    "base_source": "civitai" if raw else "name" if base else ""})
    return {"current": data.get("current") or "", "checkpoints": out}


async def _module_overrides(checkpoint: str) -> dict[str, Any]:
    """這個 checkpoint 需要的 Forge 額外模組（override_settings 用）；不需要回 {}。"""
    family = await checkpoint_family(checkpoint) if checkpoint else None
    wanted = _FAMILY_MODULES.get(family or "")
    if not wanted:
        return {}
    modules = (await _mcp("list_modules")).get("items") or []
    stems = {m["file"]: _ckpt_key(os.path.basename(m.get("file") or "")).lower() for m in modules}
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


_GEN_ARGS = ("prompt", "negative_prompt", "steps", "cfg_scale", "width", "height", "sampler_name", "seed",
             "override_settings", "init_images", "denoising_strength")


async def _generate(tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    """經 A1111 MCP 的 txt2img / img2img 生圖，回跟 REST 一樣的 {"images": [base64], "info": JSON 字串}。
    MCP 工具沒列的欄位（例如 override_settings_restore_afterwards）放在 extra 原樣帶過去。"""
    args = {k: payload[k] for k in _GEN_ARGS if k in payload}
    extra = {k: v for k, v in payload.items() if k not in args}
    if extra:
        args["extra"] = extra
    try:
        res = await mcp_client.call("a1111", tool, args, timeout=HTTP_TIMEOUT)
    except mcp_client.McpError as e:
        raise A1111Error(str(e)) from None
    if res.is_error:
        raise A1111Error(f"A1111 生圖失敗：{res.text[:500]}")
    info = (res.structured or {}).get("info")
    return {"images": [b for b, _ in res.images], "info": json.dumps(info, ensure_ascii=False) if info else ""}


def save_image(b64: str) -> str:
    """把一張 base64 圖存進 app 的圖片資料夾，回 /images/… 網址。"""
    raw = base64.b64decode(_strip_data_url(b64))
    ext = ".jpg" if raw[:3] == b"\xff\xd8\xff" else ".webp" if raw[8:12] == b"WEBP" else ".png"
    filename = f"{uuid.uuid4().hex}{ext}"
    image_dir = settings_store.get_image_dir()
    image_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / filename).write_bytes(raw)
    return f"/images/{filename}"


def _save_first_image(data: dict[str, Any]) -> str:
    images = data.get("images") or []
    if not images:
        raise RuntimeError("A1111 未回傳任何圖片")
    return save_image(images[0])


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
    data = await _generate("txt2img", payload)

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

    data = await _generate("img2img", payload)

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
    """經 A1111 MCP 的 png_info 讀取圖片內嵌的生成參數並解析。

    回傳 {info(原始字串), prompt, negative_prompt, params(原始 key:value), settings(可套用)}。
    info 為空代表該圖沒有可讀的 metadata（截圖、轉存、非 AI 生成等）。
    """
    b64 = _strip_data_url(image_b64)
    data = await _mcp("png_info", {"image": f"data:image/png;base64,{b64}"})
    info = (data.get("parameters") or "").strip()
    return {"info": info, **parse_geninfo(info)}

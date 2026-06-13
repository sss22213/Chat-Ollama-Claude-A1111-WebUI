"""工具定義：給 ollama 的 schema + 解析成 A1111 呼叫參數。

- generate_image：txt2img，從文字生圖。
- edit_image：img2img，依使用者附上的圖片重繪（只有當對話含初始圖時才提供）。
技術參數(steps/sampler/cfg/checkpoint/seed/denoising)由 UI 預設控制；
模型只負責 prompt / negative / 尺寸（與選擇性的 denoising 力度）。
"""
from __future__ import annotations

from typing import Any

from config import DEFAULT_IMAGE_SETTINGS

GENERATE_IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": (
            "Generate a NEW image from a text prompt using a local Stable Diffusion "
            "(A1111) backend. Call this whenever the user asks to draw, paint, "
            "create, generate, or show an image/picture/illustration from scratch. "
            "These are SDXL / Pony / Illustrious anime models, so write the prompt "
            "as comma-separated English danbooru-style tags (e.g. "
            "'1girl, silver hair, blue eyes, school uniform, cherry blossoms, "
            "masterpiece, best quality') rather than a full sentence."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Positive prompt: comma-separated English tags describing the desired image.",
                },
                "negative_prompt": {
                    "type": "string",
                    "description": "Optional tags to avoid (e.g. 'lowres, bad anatomy, worst quality').",
                },
                "width": {"type": "integer", "description": "Optional width in px (multiple of 64)."},
                "height": {"type": "integer", "description": "Optional height in px (multiple of 64)."},
            },
            "required": ["prompt"],
        },
    },
}

EDIT_IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "edit_image",
        "description": (
            "Redraw / transform the image the user just attached, using img2img on a "
            "local Stable Diffusion (A1111) backend. Call this when the user asks to "
            "modify, redraw, restyle, change, or edit the attached/previous image "
            "(e.g. 'make this cyberpunk', 'turn it into anime style', 'add a hat'). "
            "Write the prompt as comma-separated English danbooru-style tags describing "
            "the DESIRED result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Positive prompt describing the desired result, as comma-separated English tags.",
                },
                "negative_prompt": {"type": "string", "description": "Optional tags to avoid."},
                "denoising_strength": {
                    "type": "number",
                    "description": "0.0~1.0. How much to change the original (low=subtle, high=very different). Default ~0.6. Optional.",
                },
            },
            "required": ["prompt"],
        },
    },
}


READ_PNG_INFO_TOOL = {
    "type": "function",
    "function": {
        "name": "read_png_info",
        "description": (
            "Read the Stable Diffusion generation parameters embedded in the image "
            "the user just attached (the 'PNG Info' metadata: prompt, negative prompt, "
            "steps, sampler, CFG scale, seed, size, model). Call this when the user "
            "asks what prompt / seed / settings were used to make the attached image, "
            "or how to reproduce it. Note: only works if the image still carries "
            "A1111 / ComfyUI metadata; screenshots or re-saved images usually don't."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}


WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for up-to-date information. Use this whenever the user "
            "asks about current events, recent facts, prices, documentation, or "
            "anything you may not know or that could be outdated. Returns a list of "
            "results with title, url and snippet. After searching, you may call "
            "fetch_url on a promising result to read its full content."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "max_results": {
                    "type": "integer",
                    "description": "Optional number of results (default 5).",
                },
            },
            "required": ["query"],
        },
    },
}

FETCH_URL_TOOL = {
    "type": "function",
    "function": {
        "name": "fetch_url",
        "description": (
            "Fetch and read the main text content of a web page by URL. Use this to "
            "read a search result in depth before answering. Returns the page title "
            "and readable text (may be truncated)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The http(s) URL to read."},
            },
            "required": ["url"],
        },
    },
}


def image_tools(has_init_image: bool) -> list[dict[str, Any]]:
    """有初始圖時才提供 edit_image（img2img）與 read_png_info（讀生成參數）。"""
    tools = [GENERATE_IMAGE_TOOL]
    if has_init_image:
        tools += [EDIT_IMAGE_TOOL, READ_PNG_INFO_TOOL]
    return tools


def web_tools_schema() -> list[dict[str, Any]]:
    return [WEB_SEARCH_TOOL, FETCH_URL_TOOL]


def get_tools(has_init_image: bool) -> list[dict[str, Any]]:
    """相容舊呼叫：僅圖片工具。"""
    return image_tools(has_init_image)


def build_call(
    name: str,
    args: dict[str, Any],
    image_settings: dict[str, Any] | None,
    init_image_b64: str | None,
) -> tuple[str, dict[str, Any]]:
    """把工具呼叫解析成 ('txt2img'|'img2img', kwargs)。"""
    settings = {**DEFAULT_IMAGE_SETTINGS, **(image_settings or {})}

    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        raise ValueError(f"{name} 缺少 prompt")

    # negative：UI 預設 + 模型補充
    neg_parts = [
        p.strip()
        for p in (settings.get("negative_prompt", ""), args.get("negative_prompt", ""))
        if p and p.strip()
    ]
    negative = ", ".join(neg_parts)

    width = int(args.get("width") or settings["width"])
    height = int(args.get("height") or settings["height"])

    base = dict(
        prompt=prompt,
        negative_prompt=negative,
        steps=int(settings["steps"]),
        cfg_scale=float(settings["cfg_scale"]),
        width=width,
        height=height,
        sampler_name=settings["sampler_name"],
        seed=int(settings["seed"]),
        sd_model_checkpoint=settings.get("sd_model_checkpoint", "") or "",
    )

    if name == "edit_image":
        if not init_image_b64:
            raise ValueError("edit_image 需要使用者先附上一張圖片")
        denoise = args.get("denoising_strength")
        if denoise is None:
            denoise = settings.get("denoising_strength", 0.6)
        base["init_image_b64"] = init_image_b64
        base["denoising_strength"] = float(denoise)
        return "img2img", base

    return "txt2img", base

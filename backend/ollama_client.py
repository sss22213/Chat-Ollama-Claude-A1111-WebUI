"""Ollama 串接：列模型、查能力、串流聊天。"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

import settings_store
from config import HTTP_TIMEOUT

# /api/show 快取：{model: {"caps": [...], "ctx": int|None}}
_show_cache: dict[str, dict[str, Any]] = {}


def clear_caps_cache() -> None:
    """來源變更時呼叫，清掉快取。"""
    _show_cache.clear()


async def list_models() -> list[dict[str, Any]]:
    """回傳模型清單，附帶 supports_tools/thinking/vision 與 context_length。"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{settings_store.get_ollama_url()}/api/tags")
        resp.raise_for_status()
        models = resp.json().get("models", [])

        result = []
        for m in models:
            name = m["name"]
            info = await _show(client, name)
            caps = info["caps"]
            result.append(
                {
                    "name": name,
                    "size": m.get("size"),
                    "family": m.get("details", {}).get("family"),
                    "supports_tools": "tools" in caps,
                    "supports_thinking": "thinking" in caps,
                    "supports_vision": "vision" in caps,
                    "context_length": info["ctx"],
                }
            )
        return result


async def _show(client: httpx.AsyncClient, model: str) -> dict[str, Any]:
    if model in _show_cache:
        return _show_cache[model]
    info = {"caps": [], "ctx": None}
    try:
        resp = await client.post(
            f"{settings_store.get_ollama_url()}/api/show",
            json={"model": model},
            timeout=30,
        )
        resp.raise_for_status()
        d = resp.json()
        info["caps"] = d.get("capabilities", []) or []
        mi = d.get("model_info", {}) or {}
        for k, v in mi.items():
            if k.endswith("context_length"):
                info["ctx"] = v
                break
    except Exception:
        pass
    _show_cache[model] = info
    return info


async def model_supports_tools(model: str) -> bool:
    async with httpx.AsyncClient(timeout=30) as client:
        return "tools" in (await _show(client, model))["caps"]


async def model_supports_vision(model: str) -> bool:
    async with httpx.AsyncClient(timeout=30) as client:
        return "vision" in (await _show(client, model))["caps"]


async def chat_stream(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    think: bool | None = None,
    num_ctx: int | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """串流呼叫 ollama /api/chat，逐塊 yield 解析後的 JSON。

    每塊形如 {"message": {...}, "done": bool, "prompt_eval_count": int, ...}
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
    if think is not None:
        payload["think"] = think
    if num_ctx:
        payload["options"] = {"num_ctx": int(num_ctx)}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        async with client.stream(
            "POST", f"{settings_store.get_ollama_url()}/api/chat", json=payload
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


async def chat_once(
    model: str, messages: list[dict[str, Any]], num_ctx: int | None = None
) -> str:
    """非串流呼叫，回傳完整文字（給 compact 摘要用）。"""
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    if num_ctx:
        payload["options"] = {"num_ctx": int(num_ctx)}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            f"{settings_store.get_ollama_url()}/api/chat", json=payload
        )
        resp.raise_for_status()
        return (resp.json().get("message") or {}).get("content", "")

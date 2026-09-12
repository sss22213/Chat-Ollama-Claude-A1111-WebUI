"""Ollama 串接：列模型、查能力、串流聊天。"""
from __future__ import annotations

import contextvars
import json
import logging
from typing import Any, AsyncIterator

import httpx

import settings_store
from config import HTTP_TIMEOUT

log = logging.getLogger(__name__)

# 一次請求裡發生、使用者應該知道的事（例如思考模式沒給出答案而自動改用不思考）。
# 入口（分鏡、圖片說故事、壓縮摘要）先呼叫 start_notices() 拿到清單，chat_once 往裡面塞，
# 入口最後把清單放進回應的 notices 給前端顯示。用 ContextVar 所以不用一路傳參數；
# asyncio.gather 起的子任務會複製 context，拿到的是同一個 list 物件，照樣寫得進去。
_notices: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "ollama_notices", default=None
)


def start_notices() -> list[dict[str, Any]]:
    """開始收集這次請求的提醒；回傳的 list 會被 chat_once 就地附加。"""
    lst: list[dict[str, Any]] = []
    _notices.set(lst)
    return lst


def _notice(code: str, **detail: Any) -> None:
    lst = _notices.get()
    if lst is not None and not any(n.get("code") == code for n in lst):
        lst.append({"code": code, **detail})

# /api/show 快取：{model: {"caps": [...], "ctx": int|None}}
_show_cache: dict[str, dict[str, Any]] = {}


def clear_caps_cache() -> None:
    """來源變更時呼叫，清掉快取。"""
    _show_cache.clear()



def _raise_for_ollama(resp: httpx.Response) -> None:
    """非 2xx 時把 Ollama 回的 error 文字（模型不存在、記憶體不足…）帶進例外，
    不然 raise_for_status 只會給一串 URL。"""
    if resp.status_code < 400:
        return
    try:
        msg = (resp.json() or {}).get("error") or ""
    except ValueError:
        msg = resp.text[:300]
    raise RuntimeError(f"Ollama 回應 {resp.status_code}" + (f"：{msg}" if msg else ""))

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
            if resp.status_code >= 400:
                await resp.aread()
                _raise_for_ollama(resp)
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


async def chat_once(
    model: str,
    messages: list[dict[str, Any]],
    num_ctx: int | None = None,
    think: bool | None = None,
) -> str:
    """非串流呼叫，回傳模型的最終輸出（分鏡 / 圖片說故事 / compact 摘要用）。

    think：True/False 明確開關思考（只對有 thinking 能力的模型送出），None＝交給模型預設。
    思考型模型有時會在思考裡打轉直到額度用完、沒走到最終答案（content 空字串），
    或思考把 num_ctx 吃掉大半、最終答案寫到一半被截斷（done_reason=length）；
    這兩種情況若還沒關思考，就自動關掉再試一次。有完整的最終答案時一律用最終答案。"""
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    if num_ctx:
        payload["options"] = {"num_ctx": int(num_ctx)}
    url = f"{settings_store.get_ollama_url()}/api/chat"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        can_think = "thinking" in (await _show(client, model))["caps"]
        if can_think and think is not None:
            payload["think"] = bool(think)

        async def call() -> dict[str, Any]:
            resp = await client.post(url, json=payload)
            if resp.status_code == 400 and "think" in payload and "think" in resp.text.lower():
                payload.pop("think")  # 此模型不允許切換思考
                resp = await client.post(url, json=payload)
            _raise_for_ollama(resp)
            data = resp.json()
            msg = data.get("message") or {}
            # done_reason=length 代表輸出被截斷（超出 num_ctx / num_predict），JSON 類回覆會因此壞掉
            (log.warning if data.get("done_reason") == "length" else log.info)(
                "chat_once %s think=%s done_reason=%s prompt_eval=%s eval=%s thinking=%d content=%d",
                model, payload.get("think"), data.get("done_reason"), data.get("prompt_eval_count"),
                data.get("eval_count"), len(msg.get("thinking") or ""), len(msg.get("content") or ""),
            )
            return data

        data = await call()
        content = ((data.get("message") or {}).get("content") or "").strip()
        # 沒有最終內容、或輸出被截斷（思考把 num_ctx 吃完），且思考還沒關：關掉思考重來一次
        cut = data.get("done_reason") == "length"
        if (not content or cut) and can_think and payload.get("think") is not False:
            log.warning("chat_once %s: %s while thinking; retrying with think=false",
                        model, "truncated" if cut else "empty content")
            _notice("think_fallback", reason="truncated" if cut else "empty", model=model)
            payload["think"] = False
            data = await call()
            content = ((data.get("message") or {}).get("content") or "").strip()
        if not content:
            raise RuntimeError(
                "模型沒有回傳最終內容（done_reason=%s）。可能整段輸出都在思考或被截斷，"
                "請關閉思考、換個模型或縮短提示再試。" % data.get("done_reason")
            )
        return content

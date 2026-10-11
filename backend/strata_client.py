"""Strata 引擎：本機 LLM 伺服器（OpenAI 相容 API，/v1/chat/completions，見 ~/Desktop/ai/strata）。

對外介面刻意跟 ollama_client 一樣（chat_stream 吐 ollama 形狀的區塊、model_supports_tools /
model_supports_vision / chat_once），chat.run_chat 的主迴圈（工具呼叫、生圖、技能、防卡住）
就能直接共用：

- 訊息：app 內部用 ollama 格式（images＝base64 清單、tool_calls 的 arguments 是 dict、
  tool 訊息沒有 id）→ 轉成 OpenAI 格式（content parts 的 image_url、arguments 是 JSON 字串、
  每個 tool 訊息帶 tool_call_id）。
- 串流：OpenAI SSE 的 delta.content / reasoning_content / tool_calls（依 index 分段）→
  {"message": {"content", "thinking", "tool_calls"}} ；最後一塊的 usage.prompt_tokens →
  prompt_eval_count。
- 思考：app 的 think 開關＋effort → reasoning_effort（none / low / medium / high）。
- 驗證：設定裡的 API key 以 Authorization: Bearer 送出（金鑰只存在後端設定檔）。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator

import httpx

import settings_store
from config import HTTP_TIMEOUT

log = logging.getLogger("strata")

EFFORTS = ["none", "low", "medium", "high"]
_INFO_TTL = 30  # /v1/models 的快取秒數（模型、context、能否看圖）

_info: dict[str, Any] = {"at": 0.0, "url": "", "models": []}
_avail: dict[str, Any] = {"at": 0.0, "ok": False}


class StrataError(RuntimeError):
    pass


def _base() -> str:
    return settings_store.get_strata_url()


def _headers() -> dict[str, str]:
    key = settings_store.get_strata_key()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _detail(resp: httpx.Response) -> str:
    try:
        d = resp.json()
        err = d.get("error") if isinstance(d, dict) else None
        if isinstance(err, dict):
            return str(err.get("message") or err)
        return str(err or d.get("detail") or d)[:300]
    except ValueError:
        return resp.text[:300]


def _raise(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    if resp.status_code == 401:
        raise StrataError("Strata 拒絕了 API key（HTTP 401）：請到設定 → 服務來源檢查 Strata 的 API key")
    raise StrataError(f"Strata 回應 HTTP {resp.status_code}：{_detail(resp)}")


async def _models(refresh: bool = False) -> list[dict[str, Any]]:
    """/v1/models 的 data（模型還沒載入時是空清單）。"""
    now = time.monotonic()
    if not refresh and _info["url"] == _base() and now - _info["at"] < _INFO_TTL:
        return _info["models"]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{_base()}/v1/models", headers=_headers())
        _raise(resp)
        data = (resp.json() or {}).get("data") or []
    _info.update(at=now, url=_base(), models=data)
    return data


def clear_cache() -> None:
    _info["at"] = 0.0
    _avail["at"] = 0.0


async def available() -> bool:
    """引擎清單用：伺服器連得上、key 對、模型已載入（結果快取幾秒，免得每次開頁都等逾時）。"""
    now = time.monotonic()
    if now - _avail["at"] < 10:
        return _avail["ok"]
    try:
        ok = bool(await _models(refresh=True))
    except Exception as e:  # noqa: BLE001 — 連不上、key 錯都算不可用
        log.info("strata unavailable: %s", e)
        ok = False
    _avail.update(at=now, ok=ok)
    return ok


def _entry(m: dict[str, Any]) -> dict[str, Any]:
    mods = ((m.get("architecture") or {}).get("input_modalities")) or ["text"]
    return {
        "name": m.get("id") or "strata",
        "supports_tools": True,
        "supports_thinking": True,
        "supports_vision": "image" in mods,
        "context_length": (m.get("meta") or {}).get("n_ctx"),
        "efforts": EFFORTS,
    }


async def list_models() -> list[dict[str, Any]]:
    """給模型下拉選單：跟 ollama 的欄位一樣，另附 efforts（思考深淺）。"""
    return [_entry(m) for m in await _models(refresh=True)]


async def _model(model: str) -> dict[str, Any]:
    entries = [_entry(m) for m in await _models()]
    return next((e for e in entries if e["name"] == model), entries[0] if entries else {})


async def model_supports_tools(model: str) -> bool:
    return True


async def model_supports_vision(model: str) -> bool:
    try:
        return bool((await _model(model)).get("supports_vision"))
    except Exception:  # noqa: BLE001
        return False


async def context_length(model: str) -> int | None:
    try:
        return (await _model(model)).get("context_length")
    except Exception:  # noqa: BLE001
        return None


def reasoning_effort(think: bool | None, effort: str | None) -> str | None:
    """app 的思考開關＋強度 → Strata 的 reasoning_effort；None＝交給伺服器預設（high）。"""
    if think is False:
        return "none"
    if effort in EFFORTS:
        return effort
    return None


# ---------------- 訊息格式轉換 ----------------

def _image_part(b64: str) -> dict[str, Any]:
    url = b64 if b64.startswith("data:") else f"data:image/jpeg;base64,{b64}"
    return {"type": "image_url", "image_url": {"url": url}}


def to_openai(messages: list[dict[str, Any]], vision: bool) -> list[dict[str, Any]]:
    """app 內部（ollama 格式）的對話 → OpenAI chat 格式。"""
    out: list[dict[str, Any]] = []
    pending: list[str] = []        # 上一則 assistant 的 tool_call id，依序配給接下來的 tool 訊息
    last_id = ""
    tool_images: list[str] = []     # tool 結果附的圖：OpenAI 的 tool 訊息只能放文字，改成之後的 user 訊息
    n = 0

    def flush_tool_images() -> None:
        if tool_images and vision:
            out.append({"role": "user", "content": [
                {"type": "text", "text": "(Images returned by the tool call above.)"},
                *(_image_part(b) for b in tool_images),
            ]})
        tool_images.clear()

    for m in messages:
        role = m.get("role")
        if role != "tool":
            flush_tool_images()
        if role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.get("content") or ""}
            calls = []
            for c in m.get("tool_calls") or []:
                fn = c.get("function") or {}
                args = fn.get("arguments")
                n += 1
                cid = c.get("id") or f"call_{n}"
                calls.append({"id": cid, "type": "function", "function": {
                    "name": fn.get("name") or "",
                    "arguments": args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False),
                }})
            if calls:
                msg["tool_calls"] = calls
            pending, last_id = [c["id"] for c in calls], ""
            out.append(msg)
        elif role == "tool":
            if pending:
                last_id = pending.pop(0)
            elif not last_id:
                n += 1
                last_id = f"call_{n}"
            out.append({"role": "tool", "tool_call_id": last_id, "content": str(m.get("content") or "")})
            tool_images.extend(m.get("images") or [])
        else:
            images = m.get("images") or []
            if images and vision and role == "user":
                parts: list[dict[str, Any]] = [{"type": "text", "text": m.get("content") or ""}]
                parts += [_image_part(b) for b in images]
                out.append({"role": role, "content": parts})
            else:
                out.append({"role": role, "content": m.get("content") or ""})
    flush_tool_images()
    return out


# ---------------- 聊天 ----------------

async def chat_stream(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    think: bool | str | None = None,
    num_ctx: int | None = None,  # noqa: ARG001 — context 由伺服器設定決定，介面跟 ollama_client 一致
) -> AsyncIterator[dict[str, Any]]:
    """串流 /v1/chat/completions，逐塊 yield ollama 形狀的 {"message": {...}, "prompt_eval_count": n}。
    think：reasoning_effort 字串（見 reasoning_effort()）或 None。"""
    vision = await model_supports_vision(model)
    payload: dict[str, Any] = {"model": model, "messages": to_openai(messages, vision), "stream": True}
    if tools:
        payload["tools"] = tools
    if isinstance(think, str):
        payload["reasoning_effort"] = think
    calls: dict[int, dict[str, Any]] = {}
    finish = None
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            async with client.stream("POST", f"{_base()}/v1/chat/completions",
                                     json=payload, headers=_headers()) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    _raise(resp)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue  # 空行、SSE 註解（讀 prompt 時的心跳）
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        err = chunk["error"]
                        yield {"error": f"Strata：{err.get('message') if isinstance(err, dict) else err}"}
                        return
                    usage = chunk.get("usage") or {}
                    choice = (chunk.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    finish = choice.get("finish_reason") or finish
                    msg: dict[str, Any] = {}
                    if delta.get("reasoning_content"):
                        msg["thinking"] = delta["reasoning_content"]
                    if delta.get("content"):
                        msg["content"] = delta["content"]
                    for tc in delta.get("tool_calls") or []:
                        cur = calls.setdefault(tc.get("index", len(calls)), {"id": None, "name": "", "arguments": ""})
                        cur["id"] = tc.get("id") or cur["id"]
                        fn = tc.get("function") or {}
                        cur["name"] += fn.get("name") or ""
                        cur["arguments"] += fn.get("arguments") or ""
                    out: dict[str, Any] = {}
                    if msg:
                        out["message"] = msg
                    if usage.get("prompt_tokens"):
                        out["prompt_eval_count"] = usage["prompt_tokens"]
                    if out:
                        yield out
    except httpx.HTTPError as e:
        yield {"error": f"無法連線到 Strata（{_base()}）：{e.__class__.__name__} {e}".strip()}
        return
    except StrataError as e:
        yield {"error": str(e)}
        return

    tool_calls = []
    for i in sorted(calls):
        c = calls[i]
        try:
            args = json.loads(c["arguments"]) if c["arguments"].strip() else {}
        except json.JSONDecodeError:
            if finish != "tool_calls":
                continue  # 輸出在呼叫中途結束：參數不完整，丟掉
            args = {}
        tool_calls.append({"id": c["id"], "function": {"name": c["name"], "arguments": args}})
    yield {"message": {"tool_calls": tool_calls} if tool_calls else {}, "done": True, "done_reason": finish}


async def chat_once(
    model: str,
    messages: list[dict[str, Any]],
    system: str | None = None,
    think: bool | None = None,
    effort: str | None = None,
) -> str:
    """非串流（分鏡 / 圖片說故事 / compact 摘要）：回傳最終內容。
    思考把額度用完、沒有最終答案時，關掉思考再試一次。"""
    convo = ([{"role": "system", "content": system}] if system else []) + list(messages)
    vision = await model_supports_vision(model)
    payload: dict[str, Any] = {"model": model, "messages": to_openai(convo, vision), "stream": False}
    level = reasoning_effort(think, effort)
    if level:
        payload["reasoning_effort"] = level
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            async def call() -> tuple[str, str | None]:
                resp = await client.post(f"{_base()}/v1/chat/completions", json=payload, headers=_headers())
                _raise(resp)
                choice = ((resp.json() or {}).get("choices") or [{}])[0]
                return ((choice.get("message") or {}).get("content") or "").strip(), choice.get("finish_reason")

            content, finish = await call()
            if (not content or finish == "length") and payload.get("reasoning_effort") != "none":
                log.warning("chat_once %s: %s while thinking; retrying without thinking",
                            model, "truncated" if finish == "length" else "empty content")
                payload["reasoning_effort"] = "none"
                content, finish = await call()
    except httpx.HTTPError as e:
        raise StrataError(f"無法連線到 Strata（{_base()}）：{e.__class__.__name__} {e}".strip()) from e
    if not content:
        raise StrataError(f"Strata 沒有回傳最終內容（finish_reason={finish}）")
    return content

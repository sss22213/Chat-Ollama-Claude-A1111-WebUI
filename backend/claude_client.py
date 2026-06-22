"""Claude Code CLI 引擎：把本地已登入的 `claude` 當成 AI 引擎（與 ollama 二選一）。

透過 `claude -p --input-format stream-json --output-format stream-json` 子行程串接：
- 用 stream-json 餵入一則 user 訊息（可含 base64 圖片 → vision）。
- 解析輸出的 stream_event（content_block_delta）取得逐字串流與 thinking。
- 一律 `--tools ""` 關閉內建工具，claude 不會碰到後端檔案系統；
  生圖改由 chat.py 的「指令解析」（directive）觸發 A1111。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from typing import Any, AsyncIterator

from config import (
    CLAUDE_BIN,
    CLAUDE_CONTEXT_LENGTH,
    CLAUDE_EXTRA_ARGS,
    CLAUDE_MODELS,
    CLAUDE_TIMEOUT,
)


def available() -> bool:
    """claude 執行檔是否存在（PATH 或絕對路徑）。"""
    return bool(shutil.which(CLAUDE_BIN) or os.path.isfile(CLAUDE_BIN))


def list_models() -> list[dict[str, Any]]:
    """Claude 可選模型（別名）。vision/tools 都標 True（tools 走 directive）。"""
    return [
        {
            "name": m,
            "supports_tools": True,
            "supports_vision": True,
            "context_length": CLAUDE_CONTEXT_LENGTH,
            "engine": "claude_cli",
        }
        for m in CLAUDE_MODELS
    ]


def _guess_media_type(b64: str) -> str:
    """從 base64 開頭的魔術位元猜圖片類型（PNG / JPEG / WEBP / GIF）。"""
    if b64.startswith("iVBOR"):
        return "image/png"
    if b64.startswith("/9j/"):
        return "image/jpeg"
    if b64.startswith("UklGR"):
        return "image/webp"
    if b64.startswith("R0lGOD"):
        return "image/gif"
    return "image/png"


def _build_user_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把對話攤平成一則 user 訊息的 content：歷史轉成文字 + 最後一則 user 的圖片。"""
    turns = [m for m in messages if m.get("role") in ("user", "assistant")]
    last_user = max(
        (i for i, m in enumerate(turns) if m.get("role") == "user"),
        default=len(turns) - 1,
    )
    history = turns[:last_user] if turns else []
    current = turns[last_user] if turns else {"role": "user", "content": ""}

    prefix = ""
    if history:
        lines = []
        for m in history:
            c = (m.get("content") or "").strip()
            if c:
                who = "User" if m.get("role") == "user" else "Assistant"
                lines.append(f"{who}: {c}")
        if lines:
            prefix = "Conversation so far:\n" + "\n".join(lines) + "\n\n---\n\n"

    text = prefix + (current.get("content") or "").strip()
    content: list[dict[str, Any]] = [{"type": "text", "text": text or "(no text)"}]
    for b64 in current.get("images") or []:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": _guess_media_type(b64),
                    "data": b64,
                },
            }
        )
    return content


_EFFORTS = ("low", "medium", "high", "xhigh", "max")


def _base_args(
    model: str, system: str, output_format: str, effort: str | None = None
) -> list[str]:
    args = [
        CLAUDE_BIN,
        "-p",
        "--input-format",
        "stream-json",
        "--output-format",
        output_format,
        "--verbose",
        "--model",
        model,
        "--tools",
        "",  # 關閉所有內建工具：claude 不會碰後端檔案系統
        "--no-session-persistence",
        "--system-prompt",
        system,
    ]
    if effort in _EFFORTS:
        args += ["--effort", effort]  # 推理強度：low/medium/high/xhigh/max
    args += [*CLAUDE_EXTRA_ARGS]
    return args


async def _spawn(args: list[str], stdin_payload: str):
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    proc.stdin.write((stdin_payload + "\n").encode())
    await proc.stdin.drain()
    proc.stdin.close()
    return proc


async def chat_stream(
    model: str,
    messages: list[dict[str, Any]],
    system: str,
    think: bool = False,
    effort: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """串流 claude 回覆。

    yield 正規化事件：{type: text|thinking|usage|error, ...}
    """
    payload = json.dumps(
        {"type": "user", "message": {"role": "user", "content": _build_user_content(messages)}},
        ensure_ascii=False,
    )
    args = _base_args(model, system, "stream-json", effort) + ["--include-partial-messages"]

    try:
        proc = await _spawn(args, payload)
    except FileNotFoundError:
        yield {"type": "error", "message": f"找不到 claude 執行檔（{CLAUDE_BIN}）"}
        return

    got_text = False
    try:
        while True:
            try:
                line = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=CLAUDE_TIMEOUT
                )
            except asyncio.TimeoutError:
                proc.kill()
                yield {"type": "error", "message": "claude 回覆逾時"}
                return
            if not line:
                break
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue

            t = evt.get("type")
            if t == "stream_event":
                e = evt.get("event") or {}
                if e.get("type") == "content_block_delta":
                    d = e.get("delta") or {}
                    if d.get("type") == "text_delta" and d.get("text"):
                        got_text = True
                        yield {"type": "text", "delta": d["text"]}
                    elif think and d.get("type") == "thinking_delta" and d.get("thinking"):
                        yield {"type": "thinking", "delta": d["thinking"]}
            elif t == "result":
                if evt.get("is_error"):
                    msg = evt.get("result") or evt.get("api_error_status") or "claude error"
                    yield {"type": "error", "message": str(msg)}
                usage = evt.get("usage") or {}
                if usage.get("input_tokens"):
                    yield {"type": "usage", "prompt_tokens": usage["input_tokens"]}
    finally:
        rc = await proc.wait()
        if rc != 0 and not got_text:
            err = (await proc.stderr.read()).decode(errors="replace").strip()
            yield {"type": "error", "message": err or f"claude 結束碼 {rc}"}


async def chat_once(model: str, messages: list[dict[str, Any]], system: str) -> str:
    """非串流：回傳完整文字（給壓縮摘要用）。"""
    payload = json.dumps(
        {"type": "user", "message": {"role": "user", "content": _build_user_content(messages)}},
        ensure_ascii=False,
    )
    args = _base_args(model, system, "json")
    proc = await _spawn(args, payload)
    try:
        out = await asyncio.wait_for(proc.stdout.read(), timeout=CLAUDE_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("claude 回覆逾時")
    rc = await proc.wait()
    if rc != 0:
        err = (await proc.stderr.read()).decode(errors="replace").strip()
        raise RuntimeError(err or f"claude 結束碼 {rc}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return out.decode(errors="replace") if isinstance(out, bytes) else str(out)
    return (data.get("result") or "").strip()

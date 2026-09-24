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


_1M = 1_000_000
_200K = 200_000

# 推理強度等級（CLI --effort 接受的全集；個別模型的支援範圍見 MODEL_CATALOG）
_EFFORTS = ("low", "medium", "high", "xhigh", "max")
_EFFORTS_FULL = ("low", "medium", "high", "xhigh", "max")  # Claude 5 系列、Opus 4.7+
_EFFORTS_NO_XHIGH = ("low", "medium", "high", "max")  # Opus 4.6 / Sonnet 4.6
_NO_EFFORT: tuple[str, ...] = ()  # Haiku 4.5 與更舊的模型：CLI 不接受 --effort

# Claude Code CLI（2.1.281，2026-09-25 從執行檔目錄比對）內建模型目錄：
# 名稱 → (顯示名稱, context 視窗, 支援的推理強度)。
# 別名由 CLI 解析成該系列最新版；也可直接填完整 ID。
# Fable / Opus 5.5 / Opus 5 / Opus 4.7+ / Sonnet 5 原生 1M；Opus 4.6 / Sonnet 4.6 / Haiku 4.5 為 200K
# （加 "[1m]" 後綴可開 1M，見 model_info）。Mythos 5 / 5.1 也在 CLI 目錄裡，但只開放給
# 核准的組織，所以不列預設；填完整 ID 一樣能用。
MODEL_CATALOG: dict[str, tuple[str, int, tuple[str, ...]]] = {
    # 別名（永遠指向最新版）
    "fable": ("Fable 5.1", _1M, _EFFORTS_FULL),
    "opus": ("Opus 5.5", _1M, _EFFORTS_FULL),
    "sonnet": ("Sonnet 5", _1M, _EFFORTS_FULL),
    "haiku": ("Haiku 4.5", _200K, _NO_EFFORT),
    # 完整 ID（固定版本）
    "claude-fable-5-1": ("Fable 5.1", _1M, _EFFORTS_FULL),
    "claude-fable-5": ("Fable 5", _1M, _EFFORTS_FULL),
    "claude-mythos-5-1": ("Mythos 5.1", _1M, _EFFORTS_FULL),
    "claude-mythos-5": ("Mythos 5", _1M, _NO_EFFORT),
    "claude-opus-5-5": ("Opus 5.5", _1M, _EFFORTS_FULL),
    "claude-opus-5": ("Opus 5", _1M, _EFFORTS_FULL),
    "claude-opus-4-8": ("Opus 4.8", _1M, _EFFORTS_FULL),
    "claude-opus-4-7": ("Opus 4.7", _1M, _EFFORTS_FULL),
    "claude-opus-4-6": ("Opus 4.6", _200K, _EFFORTS_NO_XHIGH),
    "claude-opus-4-5": ("Opus 4.5", _200K, _NO_EFFORT),
    "claude-sonnet-5": ("Sonnet 5", _1M, _EFFORTS_FULL),
    "claude-sonnet-4-6": ("Sonnet 4.6", _200K, _EFFORTS_NO_XHIGH),
    "claude-sonnet-4-5": ("Sonnet 4.5", _200K, _NO_EFFORT),
    "claude-haiku-4-5": ("Haiku 4.5", _200K, _NO_EFFORT),
}


def _base_name(name: str) -> str:
    return name[:-4] if name.endswith("[1m]") else name


def model_info(name: str) -> tuple[str, int]:
    """(顯示名稱, context)。目錄外的名稱原樣顯示、context 用 200K 保守值；
    "[1m]" 後綴＝CLI 的 1M 視窗開關。"""
    base = _base_name(name)
    label, ctx, _ = MODEL_CATALOG.get(base, (base, _200K, _EFFORTS_FULL))
    if base != name:
        label, ctx = f"{label} · 1M", _1M
    return label, ctx


def efforts_for(name: str) -> tuple[str, ...]:
    """該模型接受的推理強度；目錄外的名稱假設是新模型（全部等級）。"""
    return MODEL_CATALOG.get(_base_name(name), ("", 0, _EFFORTS_FULL))[2]


def clamp_effort(model: str, effort: str | None) -> str | None:
    """把設定裡的強度調成該模型接受的：不支援 --effort 的模型回 None（不送），
    xhigh 在沒有 xhigh 的模型上退成 high。"""
    if effort not in _EFFORTS:
        return None
    supported = efforts_for(model)
    if not supported:
        return None
    if effort in supported:
        return effort
    order = [e for e in _EFFORTS if e in supported]
    lower = [e for e in order if _EFFORTS.index(e) < _EFFORTS.index(effort)]
    return lower[-1] if lower else order[0]


def context_length_for(model: str) -> int:
    """該模型的 context 長度；CLAUDE_CONTEXT_LENGTH 設了正整數就一律用它。"""
    if CLAUDE_CONTEXT_LENGTH > 0:
        return CLAUDE_CONTEXT_LENGTH
    return model_info(model)[1]


def list_models() -> list[dict[str, Any]]:
    """Claude 可選模型（CLAUDE_MODELS）。vision/tools 都標 True（tools 走 directive）。"""
    out = []
    for m in CLAUDE_MODELS:
        label, _ = model_info(m)
        out.append(
            {
                "name": m,
                "label": label,  # 前端下拉顯示「name · label」（別名解析到的版本）
                "supports_tools": True,
                "supports_vision": True,
                "context_length": context_length_for(m),
                # 該模型接受的推理強度（Haiku 4.5 為空＝不送 --effort）；設定頁的下拉用
                "efforts": list(efforts_for(m)),
                "engine": "claude_cli",
            }
        )
    return out


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
    effort = clamp_effort(model, effort)  # 依模型能力修正；不支援的模型不送
    if effort:
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
    errored = False  # 已 yield 過 error 就不在 finally 重複回報（避免雙重錯誤事件）
    aborted = False  # 消費端提前 aclose（例如退化偵測中止）
    try:
        while True:
            try:
                line = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=CLAUDE_TIMEOUT
                )
            except asyncio.TimeoutError:
                proc.kill()
                errored = True
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
                    errored = True
                    yield {"type": "error", "message": str(msg)}
                usage = evt.get("usage") or {}
                if usage.get("input_tokens"):
                    yield {"type": "usage", "prompt_tokens": usage["input_tokens"]}
    except GeneratorExit:
        # 消費端提前中止（例如偵測到模型輸出退化重複）：殺掉子行程，
        # 否則 finally 的 proc.wait() 會等一個還在無限輸出的 claude 等不完。
        aborted = True
        proc.kill()
        raise
    finally:
        rc = await proc.wait()
        # aborted 時不可再 yield（generator 正在關閉）
        if not aborted and rc != 0 and not got_text and not errored:
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

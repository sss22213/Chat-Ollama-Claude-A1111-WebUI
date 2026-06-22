"""OpenAI Codex CLI 引擎：用本地已登入的 `codex` 當 AI 引擎（與 ollama / claude 並列）。

透過 `codex exec --json` 子行程串接：
- 提示經 stdin 傳入（prompt 用 "-"），附件圖片寫成暫存檔以 `-i` 傳入（vision）。
- 解析輸出的 JSONL：`item.completed`(agent_message) 取回覆文字、`turn.completed` 取用量。
- 沙箱預設 read-only；對話用途幾乎不會執行命令。
- 生圖：Codex 不肯穩定輸出文字標記，改用 `--output-schema` 結構化輸出
  回 {reply, image_prompt, edit} → 由 chat._run_codex 轉成 A1111 生圖。
"""
from __future__ import annotations

import asyncio
import base64
import glob
import json
import os
import shutil
import tempfile
from typing import Any, AsyncIterator

from config import (
    CODEX_BIN,
    CODEX_CONTEXT_LENGTH,
    CODEX_EXTRA_ARGS,
    CODEX_MODELS,
    CODEX_SANDBOX_MODE,
    CODEX_TIMEOUT,
)

_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _codex_home() -> str:
    return os.getenv("CODEX_HOME") or os.path.expanduser("~/.codex")


def resolve_bin() -> str | None:
    """找出 codex 執行檔：CODEX_BIN → PATH → CODEX_HOME/packages 下的 standalone binary。"""
    if CODEX_BIN and (shutil.which(CODEX_BIN) or os.path.isfile(CODEX_BIN)):
        return CODEX_BIN
    found = shutil.which("codex")
    if found:
        return found
    # 掛載進容器時 binary 在版本化路徑下，glob 取最新
    cands = sorted(
        glob.glob(f"{_codex_home()}/packages/standalone/releases/*/bin/codex")
    )
    return cands[-1] if cands else None


def available() -> bool:
    return resolve_bin() is not None


def _cached_model_slugs() -> list[str]:
    """讀 codex 快取的可用模型（依帳號而定）；排除非對話用的 review 模型。"""
    try:
        with open(os.path.join(_codex_home(), "models_cache.json")) as f:
            data = json.load(f)
        out = []
        for m in data.get("models", []):
            slug = (m or {}).get("slug")
            if slug and "review" not in slug:
                out.append(slug)
        return out
    except Exception:
        return []


def list_models() -> list[dict[str, Any]]:
    # 優先用環境變數覆寫，其次用 codex 快取的帳號可用模型，最後退回內建預設
    env = os.getenv("CODEX_MODELS")
    if env:
        slugs = [s.strip() for s in env.split(",") if s.strip()]
    else:
        slugs = _cached_model_slugs() or CODEX_MODELS
    return [
        {
            "name": m,
            # 生圖透過 --output-schema 結構化輸出可靠取得意圖（見 chat._run_codex）。
            "supports_tools": True,
            "supports_vision": True,  # -i 附圖
            "context_length": CODEX_CONTEXT_LENGTH,
            "engine": "codex",
        }
        for m in slugs
    ]


def _guess_media_type(b64: str) -> str:
    if b64.startswith("iVBOR"):
        return "image/png"
    if b64.startswith("/9j/"):
        return "image/jpeg"
    if b64.startswith("UklGR"):
        return "image/webp"
    if b64.startswith("R0lGOD"):
        return "image/gif"
    return "image/png"


def _build_prompt(messages: list[dict[str, Any]], system: str) -> tuple[str, list[str]]:
    """把對話攤平成單一提示字串（含 system 與歷史）；回傳 (prompt, 當前訊息的圖片b64)。"""
    turns = [m for m in messages if m.get("role") in ("user", "assistant")]
    last_user = max(
        (i for i, m in enumerate(turns) if m.get("role") == "user"),
        default=len(turns) - 1,
    )
    history = turns[:last_user] if turns else []
    current = turns[last_user] if turns else {"role": "user", "content": ""}

    parts: list[str] = []
    if system:
        parts.append(system.strip())
    if history:
        lines = []
        for m in history:
            c = (m.get("content") or "").strip()
            if c:
                who = "User" if m.get("role") == "user" else "Assistant"
                lines.append(f"{who}: {c}")
        if lines:
            parts.append("Conversation so far:\n" + "\n".join(lines))
    cur = (current.get("content") or "").strip()
    parts.append((("Current user message:\n" if history else "") + cur) or "(no text)")
    return "\n\n".join(parts), (current.get("images") or [])


def _args(
    bin_path: str, model: str, image_paths: list[str], extra: list[str] | None = None
) -> list[str]:
    if CODEX_SANDBOX_MODE == "bypass":
        sandbox = ["--dangerously-bypass-approvals-and-sandbox"]
    else:
        sandbox = ["-s", CODEX_SANDBOX_MODE]
    args = [
        bin_path,
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--ephemeral",
        *sandbox,
        "-m",
        model,
        "-C",
        tempfile.gettempdir(),
    ]
    for p in image_paths:
        args += ["-i", p]
    args += [*(extra or []), *CODEX_EXTRA_ARGS, "-"]  # "-" = 從 stdin 讀提示
    return args


# 生圖意圖的結構化輸出 schema：reply 為對話、image_prompt 非空代表要生圖。
_IMAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "image_prompt": {"type": "string"},
        "edit_attached_image": {"type": "boolean"},
    },
    "required": ["reply", "image_prompt", "edit_attached_image"],
    "additionalProperties": False,
}


def _write_images(images: list[str]) -> list[str]:
    paths: list[str] = []
    for b64 in images:
        try:
            raw = base64.b64decode(b64)
        except Exception:
            continue
        fd, path = tempfile.mkstemp(suffix=_EXT.get(_guess_media_type(b64), ".png"))
        os.write(fd, raw)
        os.close(fd)
        paths.append(path)
    return paths


_CODEX_EFFORTS = ("minimal", "low", "medium", "high")


def _reasoning_cfg(think: bool, effort: str | None) -> list[str]:
    """codex 推理設定：effort 控速度/深度；summary 決定是否吐出思考摘要（給 thinking 顯示）。"""
    cfg: list[str] = []
    if effort in _CODEX_EFFORTS:
        cfg += ["-c", f"model_reasoning_effort={effort}"]
    cfg += ["-c", f"model_reasoning_summary={'detailed' if think else 'none'}"]
    return cfg


async def _exec(
    model: str,
    prompt: str,
    images: list[str],
    extra: list[str] | None = None,
    *,
    think: bool = False,
    effort: str | None = None,
    stop_after_message: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """低階執行 codex exec，yield 原始事件：agent_message / reasoning / usage / error。
    stop_after_message：拿到第一則 agent_message 就結束並 kill。結構化輸出模式必開——
    因為 gpt-5.5 產出 JSON 答案後常以為要『用工具/跑指令』而繼續 command_execution，
    一直等不到 turn.completed，會讓使用者卡在『思考中』直到逾時。"""
    bin_path = resolve_bin()
    if not bin_path:
        yield {"type": "error", "message": "找不到 codex 執行檔"}
        return

    image_paths = _write_images(images)
    cfg = _reasoning_cfg(think, effort)
    try:
        proc = await asyncio.create_subprocess_exec(
            *_args(bin_path, model, image_paths, cfg + (extra or [])),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        proc.stdin.write(prompt.encode())
        await proc.stdin.drain()
        proc.stdin.close()

        produced = False
        while True:
            try:
                line = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=CODEX_TIMEOUT
                )
            except asyncio.TimeoutError:
                proc.kill()
                yield {"type": "error", "message": "codex 回覆逾時"}
                return
            if not line:
                break
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue

            t = evt.get("type")
            if t == "item.completed":
                item = evt.get("item") or {}
                itype = item.get("type")
                if itype == "agent_message" and item.get("text"):
                    produced = True
                    yield {"type": "agent_message", "text": item["text"]}
                    if stop_after_message:
                        proc.kill()
                        return
                elif itype == "reasoning":
                    # 思考摘要（model_reasoning_summary=detailed 時才有）→ 當 thinking 顯示
                    rtext = item.get("text") or item.get("summary") or item.get("content")
                    if isinstance(rtext, list):
                        rtext = "\n".join(str(x) for x in rtext)
                    if rtext:
                        yield {"type": "reasoning", "text": str(rtext)}
            elif t == "turn.completed":
                usage = evt.get("usage") or {}
                if usage.get("input_tokens"):
                    produced = True
                    yield {"type": "usage", "prompt_tokens": usage["input_tokens"]}
            elif t in ("turn.failed", "error", "thread.error"):
                err = evt.get("error") or evt.get("message") or "codex error"
                if isinstance(err, dict):
                    err = err.get("message") or json.dumps(err, ensure_ascii=False)
                yield {"type": "error", "message": str(err)}

        rc = await proc.wait()
        if rc != 0 and not produced:
            stderr = (await proc.stderr.read()).decode(errors="replace").strip()
            yield {"type": "error", "message": stderr or f"codex 結束碼 {rc}"}
    finally:
        for p in image_paths:
            try:
                os.remove(p)
            except OSError:
                pass


async def _run_freeform(
    model: str,
    messages: list[dict[str, Any]],
    system: str,
    think: bool = False,
    effort: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    prompt, images = _build_prompt(messages, system)
    async for ev in _exec(model, prompt, images, think=think, effort=effort):
        if ev["type"] == "agent_message":
            yield {"type": "text", "delta": ev["text"]}
        elif ev["type"] == "reasoning":
            yield {"type": "thinking", "delta": ev["text"] + "\n"}
        else:
            yield ev


async def _run_schema(
    model: str,
    messages: list[dict[str, Any]],
    system: str,
    has_init_image: bool,
    think: bool = False,
    effort: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """結構化輸出模式：回 {reply, image_prompt, edit} → text + image_request。"""
    prompt, images = _build_prompt(messages, system)
    fd, schema_path = tempfile.mkstemp(suffix=".json")
    os.write(fd, json.dumps(_IMAGE_SCHEMA).encode())
    os.close(fd)

    last_msg = None
    usage = None
    err = None
    try:
        async for ev in _exec(
            model, prompt, images, extra=["--output-schema", schema_path],
            think=think, effort=effort, stop_after_message=True,
        ):
            if ev["type"] == "agent_message":
                last_msg = ev["text"]
            elif ev["type"] == "reasoning":
                yield {"type": "thinking", "delta": ev["text"] + "\n"}
            elif ev["type"] == "usage":
                usage = ev["prompt_tokens"]
            elif ev["type"] == "error":
                err = ev["message"]
    finally:
        try:
            os.remove(schema_path)
        except OSError:
            pass

    if err:
        yield {"type": "error", "message": err}
        return

    data = None
    if last_msg:
        try:
            data = json.loads(last_msg)
        except json.JSONDecodeError:
            data = None

    if isinstance(data, dict):
        reply = (data.get("reply") or "").strip()
        if reply:
            yield {"type": "text", "delta": reply}
        image_prompt = (data.get("image_prompt") or "").strip()
        if image_prompt:
            name = (
                "editimg"
                if (data.get("edit_attached_image") and has_init_image)
                else "genimg"
            )
            yield {"type": "image_request", "name": name, "args": {"prompt": image_prompt}}
    elif last_msg:
        yield {"type": "text", "delta": last_msg}  # 非 JSON 後備

    if usage:
        yield {"type": "usage", "prompt_tokens": usage}


async def chat_stream(
    model: str,
    messages: list[dict[str, Any]],
    system: str,
    think: bool = False,  # 開啟時請 codex 吐出思考摘要（當 thinking 顯示）
    use_schema: bool = False,
    has_init_image: bool = False,
    effort: str | None = None,  # 推理強度：minimal/low/medium/high（低＝更快）
) -> AsyncIterator[dict[str, Any]]:
    if use_schema:
        async for ev in _run_schema(
            model, messages, system, has_init_image, think=think, effort=effort
        ):
            yield ev
    else:
        async for ev in _run_freeform(
            model, messages, system, think=think, effort=effort
        ):
            yield ev


async def chat_once(model: str, messages: list[dict[str, Any]], system: str) -> str:
    """非串流：回傳完整文字（給壓縮摘要用）。"""
    chunks: list[str] = []
    async for ev in _run_freeform(model, messages, system):
        if ev.get("type") == "text":
            chunks.append(ev["delta"])
        elif ev.get("type") == "error":
            raise RuntimeError(ev["message"])
    return "".join(chunks).strip()

"""OpenAI Codex CLI 引擎：用本地已登入的 `codex` 當 AI 引擎（與 ollama / claude 並列）。

透過 `codex exec --json` 子行程串接：
- 提示經 stdin 傳入（prompt 用 "-"），附件圖片寫成暫存檔以 `-i` 傳入（vision）。
- 解析輸出的 JSONL：`item.completed`(agent_message) 取回覆文字、`turn.completed` 取用量。
- 沙箱預設 read-only；對話用途幾乎不會執行命令。
- 工具（生圖、搜尋、技能與 A1111 / Civitai Helper 的工具）：原生 MCP——`-c mcp_servers.webui.url=…`
  掛上 webui 的 MCP 閘道，codex 自己呼叫（chat._run_cli_mcp）；codex 內建的生圖、shell 等工具關掉。
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


def _cached_models() -> list[dict[str, Any]]:
    """讀 codex 快取的可用模型（依帳號而定）；排除隱藏與非對話用的 review 模型。
    回傳 [{slug, context_length, efforts}]，缺欄位時給預設。"""
    try:
        with open(os.path.join(_codex_home(), "models_cache.json")) as f:
            data = json.load(f)
        out = []
        for m in data.get("models", []):
            m = m or {}
            slug = m.get("slug")
            if not slug or "review" in slug or m.get("visibility") == "hide":
                continue
            efforts = [
                l.get("effort")
                for l in (m.get("supported_reasoning_levels") or [])
                if l.get("effort")
            ]
            out.append(
                {
                    "slug": slug,
                    "label": m.get("display_name") or slug,
                    "context_length": int(
                        m.get("context_window") or CODEX_CONTEXT_LENGTH
                    ),
                    "efforts": efforts,
                }
            )
        return out
    except Exception:
        return []


def context_length_for(model: str) -> int:
    """該模型的 context 長度（快取有就用快取，否則退回預設值）。"""
    for m in _cached_models():
        if m["slug"] == model:
            return m["context_length"]
    return CODEX_CONTEXT_LENGTH


def list_models() -> list[dict[str, Any]]:
    # 優先用環境變數覆寫，其次用 codex 快取的帳號可用模型，最後退回內建預設
    env = os.getenv("CODEX_MODELS")
    if env:
        cached = {m["slug"]: m for m in _cached_models()}
        models = [
            cached.get(s.strip()) or {"slug": s.strip()}
            for s in env.split(",")
            if s.strip()
        ]
    else:
        models = _cached_models() or [{"slug": s} for s in CODEX_MODELS]
    return [
        {
            "name": m["slug"],
            "label": m.get("label") or m["slug"],  # 目錄的 display_name（如 GPT-6-Astra）
            # 生圖透過 --output-schema 結構化輸出可靠取得意圖（見 chat._run_codex）。
            "supports_tools": True,
            "supports_vision": True,  # -i 附圖
            "context_length": m.get("context_length") or CODEX_CONTEXT_LENGTH,
            # 該模型支援的推理強度（GPT-6 / 5.6 系列多了 max/ultra）；前端下拉用
            "efforts": m.get("efforts") or [],
            "engine": "codex",
        }
        for m in models
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


# CLI 接受的推理強度全集；個別模型的支援範圍見 models_cache（GPT-6 / 5.6 系列才有 max/ultra）
_CODEX_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")


def _reasoning_cfg(think: bool, effort: str | None) -> list[str]:
    """codex 推理設定：effort 控速度/深度；summary 決定是否吐出思考摘要（給 thinking 顯示）。"""
    cfg: list[str] = []
    if effort in _CODEX_EFFORTS:
        cfg += ["-c", f"model_reasoning_effort={effort}"]
    cfg += ["-c", f"model_reasoning_summary={'detailed' if think else 'none'}"]
    return cfg


# stop_after_message 拿到答案後，額外等 turn.completed（帶 usage）的收尾秒數。
# 正常情況 turn 會緊接著完成、usage 立刻到手；若模型繼續跑 command_execution，
# 期限一到照樣 kill，只是少了 usage。
_USAGE_GRACE = 5.0


# 原生 MCP：工具呼叫（生圖、下載模型…）期間 codex 不會輸出事件，閒置逾時要放寬
MCP_IDLE_TIMEOUT = max(CODEX_TIMEOUT, 1200.0)
MCP_SERVER_NAME = "webui"


def mcp_config(url: str) -> list[str]:
    """掛上 webui 的 MCP 閘道（這次對話專用的網址）；工具逾時放寬到跟閒置逾時一樣。
    codex exec 的核准策略是 never：MCP 工具預設要人核准就會被拒，所以這個伺服器的工具一律核准
    （閘道只提供這次對話選用的工具）。"""
    name = MCP_SERVER_NAME
    args = ["-c", f'mcp_servers.{name}.url="{url}"',
            "-c", f'mcp_servers.{name}.default_tools_approval_mode="approve"',
            "-c", f"mcp_servers.{name}.tool_timeout_sec={int(MCP_IDLE_TIMEOUT)}",
            "-c", f"mcp_servers.{name}.startup_timeout_sec=30"]
    for feature in _BUILTIN_TOOL_FEATURES:
        args += ["-c", f"features.{feature}=false"]
    return args


# codex 自己的工具：跟 Claude CLI（--tools ""）一樣全部關掉，只用 webui 閘道的工具——
# 尤其 image_generation（它會改用 OpenAI 的生圖，不經 A1111）與 shell（不碰後端的檔案）
_BUILTIN_TOOL_FEATURES = ("image_generation", "shell_tool", "unified_exec", "browser_use", "computer_use",
                          "apps", "plugins", "view_image")


async def _exec(
    model: str,
    prompt: str,
    images: list[str],
    extra: list[str] | None = None,
    *,
    think: bool = False,
    effort: str | None = None,
    stop_after_message: bool = False,
    idle_timeout: float | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """低階執行 codex exec，yield 原始事件：agent_message / reasoning / usage / error。
    stop_after_message：拿到第一則 agent_message 後只留 _USAGE_GRACE 秒收 usage 就結束並
    kill。結構化輸出模式必開——因為 gpt-5.5 產出 JSON 答案後常以為要『用工具/跑指令』
    而繼續 command_execution，一直等不到 turn.completed，會讓使用者卡在『思考中』直到逾時。"""
    bin_path = resolve_bin()
    if not bin_path:
        yield {"type": "error", "message": "找不到 codex 執行檔"}
        return

    image_paths = _write_images(images)
    cfg = _reasoning_cfg(think, effort)
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *_args(bin_path, model, image_paths, cfg + (extra or [])),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=64 * 1024 * 1024,  # --json 一行可能很長（MCP 工具結果裡的圖）
        )
        proc.stdin.write(prompt.encode())
        await proc.stdin.drain()
        proc.stdin.close()

        produced = False
        # stop_after_message：拿到答案後設定收尾期限，期限內只為了等 usage
        stop_deadline: float | None = None
        loop = asyncio.get_running_loop()
        while True:
            if stop_deadline is not None:
                remaining = stop_deadline - loop.time()
                if remaining <= 0:
                    proc.kill()
                    return
                timeout = remaining
            else:
                timeout = idle_timeout or CODEX_TIMEOUT
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                if stop_deadline is not None:
                    return  # 答案已到手，只是等不到 usage，不算錯誤
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
                        stop_deadline = loop.time() + _USAGE_GRACE
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
                if stop_deadline is not None:
                    proc.kill()
                    return
            elif t in ("turn.failed", "error", "thread.error"):
                if stop_deadline is not None:
                    # 答案已交付；後續（多半是被中止的 command_execution）的錯誤
                    # 不該蓋掉正常結果
                    proc.kill()
                    return
                err = evt.get("error") or evt.get("message") or "codex error"
                if isinstance(err, dict):
                    err = err.get("message") or json.dumps(err, ensure_ascii=False)
                yield {"type": "error", "message": str(err)}

        rc = await proc.wait()
        if rc != 0 and not produced:
            stderr = (await proc.stderr.read()).decode(errors="replace").strip()
            yield {"type": "error", "message": stderr or f"codex 結束碼 {rc}"}
    finally:
        # 消費端提前 aclose（例如退化偵測中止）或例外時，別讓 codex 子行程留著繼續跑。
        # 對已結束的行程送 SIGKILL 是無害的 no-op。
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
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
    mcp_url: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    prompt, images = _build_prompt(messages, system)
    gen = _exec(model, prompt, images, mcp_config(mcp_url) if mcp_url else None, think=think, effort=effort,
                idle_timeout=MCP_IDLE_TIMEOUT if mcp_url else None)
    said = False
    try:
        async for ev in gen:
            if ev["type"] == "agent_message":
                # 工具呼叫前後各是一則訊息：中間空一行
                yield {"type": "text", "delta": ("\n\n" if said else "") + ev["text"]}
                said = True
            elif ev["type"] == "reasoning":
                yield {"type": "thinking", "delta": ev["text"] + "\n"}
            else:
                yield ev
    finally:
        await gen.aclose()  # 提前中止時同步關閉 _exec（觸發 kill 子行程）


async def chat_stream(
    model: str,
    messages: list[dict[str, Any]],
    system: str,
    think: bool = False,  # 開啟時請 codex 吐出思考摘要（當 thinking 顯示）
    effort: str | None = None,  # 推理強度：minimal/low/medium/high（低＝更快）
    mcp_url: str | None = None,  # webui MCP 閘道：codex 直接呼叫它的工具
) -> AsyncIterator[dict[str, Any]]:
    gen = _run_freeform(model, messages, system, think=think, effort=effort, mcp_url=mcp_url)
    try:
        async for ev in gen:
            yield ev
    finally:
        await gen.aclose()  # 消費端提前中止時，把關閉一路傳到 _exec


async def chat_once(model: str, messages: list[dict[str, Any]], system: str) -> str:
    """非串流：回傳完整文字（給壓縮摘要用）。"""
    chunks: list[str] = []
    async for ev in _run_freeform(model, messages, system):
        if ev.get("type") == "text":
            chunks.append(ev["delta"])
        elif ev.get("type") == "error":
            raise RuntimeError(ev["message"])
    return "".join(chunks).strip()

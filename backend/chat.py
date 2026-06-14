"""Agentic 聊天迴圈：串流 ollama、處理工具（生圖 / web 搜尋）、即時進度，輸出 SSE。"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import a1111_client
import claude_client
import codex_client
import ollama_client
import tools as tools_mod
import web_tools
from config import CLAUDE_CONTEXT_LENGTH, CODEX_CONTEXT_LENGTH

MAX_TOOL_ROUNDS = 6  # 防止無限呼叫工具（足夠 搜尋→抓頁→回答 多步）
POLL_INTERVAL = 0.4  # 進度輪詢秒數
IMAGE_TOOLS = ("generate_image", "edit_image")


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _last_init_image(messages: list[dict[str, Any]]) -> str | None:
    """取最後一則含 images 的 user 訊息的第一張圖，作為 img2img 初始圖。"""
    for m in reversed(messages):
        if m.get("role") == "user":
            imgs = m.get("images")
            if imgs:
                return imgs[0]
    return None


async def _generate_with_progress(
    kind: str, kwargs: dict[str, Any]
) -> AsyncIterator[dict[str, Any]]:
    """執行 txt2img/img2img，期間 yield 進度事件，最後 yield 完成事件。"""
    coro = (
        a1111_client.img2img(**kwargs)
        if kind == "img2img"
        else a1111_client.txt2img(**kwargs)
    )
    task = asyncio.create_task(coro)

    while not task.done():
        await asyncio.sleep(POLL_INTERVAL)
        if task.done():
            break
        try:
            prog = await a1111_client.get_progress()
        except Exception:
            continue
        state = prog.get("state") or {}
        yield {
            "type": "progress",
            "value": prog.get("progress") or 0,
            "step": state.get("sampling_step"),
            "steps": state.get("sampling_steps"),
            "eta": prog.get("eta_relative"),
            "preview": prog.get("current_image") or None,
        }

    result = await task  # 失敗會在此拋出
    yield {"type": "image", "url": result["url"], "params": result["params"]}


def _fmt_search(query: str, results: list[dict]) -> str:
    if not results:
        return f"No web results for '{query}'."
    lines = [f"Web search results for '{query}':"]
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. {r['title']}\n   URL: {r['url']}\n   {r['snippet']}"
        )
    lines.append(
        "Cite the sources you used. Call fetch_url to read a result in full if needed."
    )
    return "\n".join(lines)


async def run_chat(
    model: str,
    messages: list[dict[str, Any]],
    tools_enabled: bool,
    image_settings: dict[str, Any] | None,
    think: bool | None = None,
    web_enabled: bool = False,
    num_ctx: int | None = None,
    image_sources: list[str] | None = None,
    engine: str = "ollama",
) -> AsyncIterator[str]:
    """主迴圈，yield SSE 字串。

    事件型別：thinking / token / tool_call / progress / image / sources / usage / error / done
    """
    if engine == "claude_cli":
        async for s in _run_cli_engine(
            claude_client, CLAUDE_CONTEXT_LENGTH,
            model, messages, tools_enabled, image_settings, bool(think)
        ):
            yield s
        return
    if engine == "codex":
        async for s in _run_codex(
            model, messages, tools_enabled, image_settings, bool(think)
        ):
            yield s
        return

    can_tools = await ollama_client.model_supports_tools(model)
    init_image = _last_init_image(messages)
    # read_png_info 要讀「原圖」metadata；image_sources 是本回合未經縮圖的原始位元組，
    # 沒有時退回 init_image（縮圖後的 JPEG 通常已無 metadata）。
    png_source = (image_sources or [None])[-1] or init_image

    tool_schema: list[dict[str, Any]] = []
    if can_tools and tools_enabled:
        tool_schema += tools_mod.image_tools(bool(init_image))
    if can_tools and web_enabled:
        tool_schema += tools_mod.web_tools_schema()
    tool_schema = tool_schema or None

    convo = [dict(m) for m in messages]
    # 非 vision 模型若收到 images 會 500，先剝除（img2img 仍可用 init_image）
    if not await ollama_client.model_supports_vision(model):
        for m in convo:
            m.pop("images", None)

    try:
        answered = False
        prompt_tokens = 0
        for _round in range(MAX_TOOL_ROUNDS):
            assistant_content = ""
            tool_calls: list[dict[str, Any]] = []

            async for chunk in ollama_client.chat_stream(
                model, convo, tools=tool_schema, think=think, num_ctx=num_ctx
            ):
                if chunk.get("error"):
                    yield _sse({"type": "error", "message": str(chunk["error"])})
                    yield _sse({"type": "done"})
                    return
                if chunk.get("prompt_eval_count"):
                    prompt_tokens = chunk["prompt_eval_count"]
                msg = chunk.get("message") or {}
                if msg.get("thinking"):
                    yield _sse({"type": "thinking", "delta": msg["thinking"]})
                if msg.get("content"):
                    assistant_content += msg["content"]
                    yield _sse({"type": "token", "delta": msg["content"]})
                if msg.get("tool_calls"):
                    tool_calls.extend(msg["tool_calls"])

            if not tool_calls:
                answered = True
                break

            convo.append(
                {
                    "role": "assistant",
                    "content": assistant_content,
                    "tool_calls": tool_calls,
                }
            )

            for call in tool_calls:
                fn = call.get("function", {})
                name = fn.get("name")
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}

                async for content in _run_tool(
                    name, args, image_settings, init_image, png_source
                ):
                    if isinstance(content, str):
                        convo.append({"role": "tool", "content": content})
                    else:
                        yield _sse(content)

        # 用完輪數仍想呼叫工具 → 最後再不帶工具讓模型用文字收尾（不報錯）
        if not answered:
            async for chunk in ollama_client.chat_stream(
                model, convo, tools=None, think=think, num_ctx=num_ctx
            ):
                if chunk.get("error"):
                    yield _sse({"type": "error", "message": str(chunk["error"])})
                    break
                if chunk.get("prompt_eval_count"):
                    prompt_tokens = chunk["prompt_eval_count"]
                msg = chunk.get("message") or {}
                if msg.get("thinking"):
                    yield _sse({"type": "thinking", "delta": msg["thinking"]})
                if msg.get("content"):
                    yield _sse({"type": "token", "delta": msg["content"]})

        if prompt_tokens:
            yield _sse({"type": "usage", "prompt_tokens": prompt_tokens, "num_ctx": num_ctx})
        yield _sse({"type": "done"})
    except Exception as e:
        yield _sse({"type": "error", "message": str(e)})
        yield _sse({"type": "done"})


# ===================== CLI 引擎（Claude CLI / OpenAI Codex）=====================
#
# 這些 CLI agent 不開放外部工具給我們，所以「生圖」不走原生 function calling，
# 而是請模型在文字裡輸出一段指令標記（directive），由後端邊串流邊解析出來、
# 跑 A1111、把圖塞回對話。Claude 與 Codex 共用同一條解析路徑。

_OPENERS = {"[[GENIMG]]": "genimg", "[[EDITIMG]]": "editimg"}
_CLOSERS = {"genimg": "[[/GENIMG]]", "editimg": "[[/EDITIMG]]"}


def _safe_emit_len(buf: str, openers: list[str]) -> int:
    """可安全輸出的長度：保留結尾可能是「半個開頭標記」的尾巴，避免漏字或誤判。"""
    maxlen = max(len(o) for o in openers)
    for k in range(min(maxlen - 1, len(buf)), 0, -1):
        tail = buf[-k:]
        if any(o.startswith(tail) for o in openers):
            return len(buf) - k
    return len(buf)


class _DirectiveParser:
    """串流文字解析器：吐出 ('text', str) 或 ('directive', name, json_str)。"""

    def __init__(self) -> None:
        self.buf = ""
        self.capturing: str | None = None

    def feed(self, text: str) -> list[tuple]:
        self.buf += text
        out: list[tuple] = []
        while True:
            if self.capturing is None:
                idx, which, openlen = -1, None, 0
                for opener, name in _OPENERS.items():
                    p = self.buf.find(opener)
                    if p != -1 and (idx == -1 or p < idx):
                        idx, which, openlen = p, name, len(opener)
                if idx == -1:
                    cut = _safe_emit_len(self.buf, list(_OPENERS))
                    if cut > 0:
                        out.append(("text", self.buf[:cut]))
                        self.buf = self.buf[cut:]
                    break
                if idx > 0:
                    out.append(("text", self.buf[:idx]))
                self.buf = self.buf[idx + openlen :]
                self.capturing = which
            else:
                closer = _CLOSERS[self.capturing]
                p = self.buf.find(closer)
                if p == -1:
                    break
                out.append(("directive", self.capturing, self.buf[:p]))
                self.buf = self.buf[p + len(closer) :]
                self.capturing = None
        return out

    def flush(self) -> list[tuple]:
        if self.capturing is None and self.buf:
            text, self.buf = self.buf, ""
            return [("text", text)]
        return []


def _base_system(messages: list[dict[str, Any]]) -> str:
    base_parts = [
        m["content"]
        for m in messages
        if m.get("role") == "system" and m.get("content")
    ]
    return "\n\n".join(base_parts) or (
        "You are a helpful assistant. Reply in the user's language."
    )


def _directive_system(
    messages: list[dict[str, Any]], tools_enabled: bool, has_init_image: bool
) -> str:
    base = _base_system(messages)
    if not tools_enabled:
        return base

    instr = [
        "",
        "# Image generation (IMPORTANT)",
        "You are a chat assistant with NO file system and NO shell. Do NOT run "
        "commands, do NOT create or edit files, do NOT use any tools. You cannot "
        "save an image to disk.",
        "The ONLY way to show the user an image is to print this marker inline in "
        "your reply (the app intercepts it, runs Stable Diffusion / A1111, and "
        "replaces it with the rendered image):",
        '[[GENIMG]]{"prompt": "comma, separated, english, danbooru, tags", '
        '"negative_prompt": "optional", "width": 1024, "height": 1024}[[/GENIMG]]',
        "So whenever the user asks you to draw / paint / create / generate / show "
        "an image, you MUST output that marker. Rules: the prompt MUST be "
        "comma-separated English tags (these are SDXL / Pony / Illustrious anime "
        "models, not full sentences). width/height optional (multiples of 64). Do "
        "NOT include steps/sampler/seed/cfg — the app controls those.",
        "Write one short natural sentence first, THEN the marker on its own line. "
        "Never explain the marker, never wrap it in code fences, and never claim "
        "you cannot generate images — emitting the marker IS how you generate them.",
    ]
    if has_init_image:
        instr += [
            "To redraw / restyle / edit the image the user just attached, use this "
            "marker instead of GENIMG:",
            '[[EDITIMG]]{"prompt": "desired result as english tags", '
            '"negative_prompt": "optional", "denoising_strength": 0.6}[[/EDITIMG]]',
        ]
    return base + "\n".join(instr)


async def _run_directive(
    name: str,
    payload: str,
    image_settings: dict[str, Any] | None,
    init_image: str | None,
) -> AsyncIterator[dict[str, Any]]:
    try:
        args = json.loads(payload.strip())
        if not isinstance(args, dict):
            raise ValueError("not an object")
    except (json.JSONDecodeError, ValueError):
        yield {"type": "error", "message": "圖片指令解析失敗"}
        return

    tool = "edit_image" if name == "editimg" else "generate_image"
    yield {"type": "tool_call", "name": tool, "args": args}
    try:
        kind, kwargs = tools_mod.build_call(tool, args, image_settings, init_image)
        async for ev in _generate_with_progress(kind, kwargs):
            yield ev
    except Exception as e:
        yield {"type": "error", "message": f"圖片生成失敗：{e}"}


async def _run_cli_engine(
    client,
    ctx_len: int,
    model: str,
    messages: list[dict[str, Any]],
    tools_enabled: bool,
    image_settings: dict[str, Any] | None,
    think: bool,
) -> AsyncIterator[str]:
    """通用 CLI 引擎路徑：串流文字 + 解析生圖指令。client 為 claude_client / codex_client。"""
    init_image = _last_init_image(messages)
    system = _directive_system(messages, tools_enabled, bool(init_image))
    parser = _DirectiveParser()
    prompt_tokens = 0

    try:
        async for ev in client.chat_stream(model, messages, system, think=think):
            kind = ev.get("type")
            if kind == "error":
                yield _sse({"type": "error", "message": ev["message"]})
                yield _sse({"type": "done"})
                return
            if kind == "usage":
                prompt_tokens = ev["prompt_tokens"]
            elif kind == "thinking":
                yield _sse({"type": "thinking", "delta": ev["delta"]})
            elif kind == "text":
                for item in parser.feed(ev["delta"]):
                    if item[0] == "text":
                        if item[1]:
                            yield _sse({"type": "token", "delta": item[1]})
                    else:
                        async for out in _run_directive(
                            item[1], item[2], image_settings, init_image
                        ):
                            yield _sse(out)
        for item in parser.flush():
            if item[1]:
                yield _sse({"type": "token", "delta": item[1]})
        if prompt_tokens:
            yield _sse(
                {
                    "type": "usage",
                    "prompt_tokens": prompt_tokens,
                    "num_ctx": ctx_len,
                }
            )
        yield _sse({"type": "done"})
    except Exception as e:
        yield _sse({"type": "error", "message": str(e)})
        yield _sse({"type": "done"})


# --- Codex 專用：用結構化輸出（--output-schema）可靠取得生圖意圖 ---
# Codex 是程式碼 agent，不肯穩定輸出文字標記，但會乖乖遵守 JSON schema。
# codex_client 在 use_schema 模式回 {reply, image_prompt, edit} → 這裡轉成生圖。

def _codex_image_instructions(has_init_image: bool) -> str:
    s = (
        "\n\nYou are a chat assistant connected to a local Stable Diffusion (A1111) "
        "image generator. Respond via the structured output: put your natural-language "
        "reply in 'reply'. If the user asks you to draw / paint / create / generate / "
        "show an image, put comma-separated English danbooru-style tags describing it in "
        "'image_prompt' (these are SDXL/Pony/Illustrious anime models); otherwise leave "
        "'image_prompt' empty. Do not include steps/sampler/seed. "
    )
    if has_init_image:
        s += (
            "Set 'edit_attached_image' to true only when the user wants to modify / "
            "redraw the image they attached."
        )
    else:
        s += "Set 'edit_attached_image' to false."
    return s


async def _run_codex(
    model: str,
    messages: list[dict[str, Any]],
    tools_enabled: bool,
    image_settings: dict[str, Any] | None,
    think: bool,
) -> AsyncIterator[str]:
    init_image = _last_init_image(messages)
    use_schema = bool(tools_enabled)
    system = _base_system(messages)
    if use_schema:
        system += _codex_image_instructions(bool(init_image))

    prompt_tokens = 0
    try:
        async for ev in codex_client.chat_stream(
            model,
            messages,
            system,
            think=think,
            use_schema=use_schema,
            has_init_image=bool(init_image),
        ):
            kind = ev.get("type")
            if kind == "error":
                yield _sse({"type": "error", "message": ev["message"]})
                yield _sse({"type": "done"})
                return
            if kind == "usage":
                prompt_tokens = ev["prompt_tokens"]
            elif kind == "text":
                if ev.get("delta"):
                    yield _sse({"type": "token", "delta": ev["delta"]})
            elif kind == "image_request":
                async for out in _run_directive(
                    ev["name"], json.dumps(ev["args"]), image_settings, init_image
                ):
                    yield _sse(out)
        if prompt_tokens:
            yield _sse(
                {
                    "type": "usage",
                    "prompt_tokens": prompt_tokens,
                    "num_ctx": CODEX_CONTEXT_LENGTH,
                }
            )
        yield _sse({"type": "done"})
    except Exception as e:
        yield _sse({"type": "error", "message": str(e)})
        yield _sse({"type": "done"})


def _fmt_png_info(d: dict[str, Any]) -> str:
    if not d.get("info"):
        return (
            "The attached image has NO embedded Stable Diffusion metadata "
            "(it may be a screenshot, a re-saved / recompressed file, or not "
            "AI-generated). Tell the user the generation parameters can't be read."
        )
    p = d.get("params") or {}
    lines = ["PNG Info — generation parameters embedded in the image:"]
    if d.get("prompt"):
        lines.append(f"Prompt: {d['prompt']}")
    if d.get("negative_prompt"):
        lines.append(f"Negative prompt: {d['negative_prompt']}")
    keys = ["Steps", "Sampler", "CFG scale", "Seed", "Size", "Model", "Denoising strength"]
    extra = ", ".join(f"{k}: {p[k]}" for k in keys if k in p)
    if extra:
        lines.append(extra)
    lines.append(
        "Present these to the user in their language. Do not call the tool again."
    )
    return "\n".join(lines)


async def _run_tool(
    name: str,
    args: dict[str, Any],
    image_settings: dict[str, Any] | None,
    init_image: str | None,
    png_source: str | None = None,
) -> AsyncIterator[Any]:
    """執行單一工具。yield dict=SSE 事件、yield str=要 append 回對話的 tool 訊息。"""
    # --- 讀 PNG 生成參數 ---
    if name == "read_png_info":
        yield {"type": "tool_call", "name": "read_png_info", "args": {}}
        if not png_source:
            yield "No attached image to read PNG info from."
            return
        try:
            info = await a1111_client.png_info(png_source)
            yield _fmt_png_info(info)
        except Exception as e:
            yield {"type": "error", "message": f"讀取 PNG 參數失敗：{e}"}
            yield f"Failed to read PNG info: {e}"
        return

    # --- 生圖 ---
    if name in IMAGE_TOOLS:
        yield {"type": "tool_call", "name": name, "args": args}
        try:
            kind, kwargs = tools_mod.build_call(name, args, image_settings, init_image)
            params = {}
            async for ev in _generate_with_progress(kind, kwargs):
                if ev["type"] == "image":
                    params = ev["params"]
                yield ev
            yield (
                "Image generated successfully and shown to the user. "
                f"Prompt used: {params.get('prompt')}. "
                "Briefly describe it to the user in their language; "
                "do not call the tool again unless asked."
            )
        except Exception as e:
            yield {"type": "error", "message": f"圖片生成失敗：{e}"}
            yield f"圖片生成失敗：{e}"
        return

    # --- web 搜尋 ---
    if name == "web_search":
        query = (args.get("query") or "").strip()
        yield {"type": "tool_call", "name": "web_search", "args": {"query": query}}
        try:
            results = await web_tools.web_search(query, args.get("max_results"))
            yield {"type": "sources", "query": query, "results": results}
            yield _fmt_search(query, results)
        except Exception as e:
            yield {"type": "error", "message": f"搜尋失敗：{e}"}
            yield f"Web search failed: {e}"
        return

    # --- 抓網頁 ---
    if name == "fetch_url":
        url = (args.get("url") or "").strip()
        yield {"type": "tool_call", "name": "fetch_url", "args": {"url": url}}
        try:
            page = await web_tools.fetch_url(url)
            yield {
                "type": "sources",
                "results": [
                    {"title": page["title"] or url, "url": page["url"], "snippet": ""}
                ],
            }
            note = " …(truncated)" if page.get("truncated") else ""
            yield (
                f"Fetched page.\nTitle: {page['title']}\nURL: {page['url']}\n\n"
                f"{page['text']}{note}"
            )
        except Exception as e:
            yield {"type": "error", "message": f"抓取失敗：{e}"}
            yield f"Fetch failed: {e}"
        return

    yield f"未知工具：{name}"

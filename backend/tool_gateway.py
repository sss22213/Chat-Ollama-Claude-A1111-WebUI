"""webui 的 MCP 工具閘道：聊天與工作流呼叫工具一律經由它（MCP 的 tools/list、tools/call）。

閘道本身是一個 MCP 伺服器（mcp_lite），提供哪些工具由這次對話 / 執行的情境（ToolContext）決定：
- generate_image / edit_image：經 A1111 的 MCP 生圖（套用生圖設定、存到圖片資料夾、進度與預覽）
- read_png_info：附圖的生成參數（A1111 MCP 的 png_info）
- web_search / fetch_url：webui 自己的網頁搜尋
- 技能的工具：tools.json 的 kind "mcp" 轉給 A1111 / Civitai Helper 的 MCP，HTTP / 腳本工具由閘道執行
畫面事件（進度、圖片、搜尋來源、技能卡片、錯誤）經 ToolContext.emit 送給呼叫端；MCP 的結果只放
給模型的文字與圖片（_meta 標註圖的種類：kind=generated 是剛生成的圖、labels 是技能附的圖）。
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import secrets
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response

import mcp_client
import mcp_lite
import skills_store
import tools as tools_mod

log = logging.getLogger(__name__)

Emit = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class ToolContext:
    image_tools: bool = False  # generate_image（有附圖時再加 edit_image、read_png_info）
    web: bool = False  # web_search、fetch_url
    skill: str | None = None  # 技能 slug（逗號分隔或 "__auto__"）：SKILL.md 宣告的工具
    names: list[str] = field(default_factory=list)  # 另外點名的工具（工作流的 tools=[...]）
    # 交給 LLM 自己挑：內建工具、所有技能的工具、A1111 / Civitai Helper MCP 伺服器上的其他工具
    # （不含破壞性的與內部用的，那些要點名）
    auto: bool = False
    exclude: list[str] = field(default_factory=list)  # 不給的工具（例如只查資料的步驟不給生圖）
    # 只給查資料的工具：MCP 標了 readOnlyHint 的、tools.json 標了 read_only 的、搜尋與 PNG Info
    # （點名的與工作流自己的函式照給）
    read_only: bool = False
    image_settings: dict[str, Any] | None = None
    init_image: str | None = None  # 對話最後附的圖（改圖、技能的 attach_image）
    edit_image: str | None = None
    png_source: str | None = None  # 讀 PNG Info 用的原圖
    emit: Emit | None = None
    # 工作流裡的 Python 函式（Claude CLI / Codex 透過閘道呼叫時，轉回工作流執行）：
    # local_tools＝{名稱: function schema}，call_local(名稱, 參數) → 結果文字
    local_tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    call_local: Callable[[str, dict[str, Any]], Awaitable[str]] | None = None

    def skill_defs(self) -> dict[str, dict[str, Any]]:
        """選用技能的工具（auto：所有技能的），加上點名的其他技能工具（同名取選用技能的）。"""
        defs = {t["name"]: t for t in skills_store.tools_for(self.skill)} if self.skill else {}
        wanted = [n for n in self.names if n not in defs and n not in _BUILTIN]
        if wanted or self.auto:
            every = {t["name"]: t for t in skills_store.tools_for(skills_store.AUTO)}
            for n, d in every.items():
                if n not in defs and (self.auto or n in wanted):
                    defs[n] = d
        return defs


_BUILTIN = {
    "generate_image": tools_mod.GENERATE_IMAGE_TOOL,
    "edit_image": tools_mod.EDIT_IMAGE_TOOL,
    "read_png_info": tools_mod.READ_PNG_INFO_TOOL,
    "web_search": tools_mod.WEB_SEARCH_TOOL,
    "fetch_url": tools_mod.FETCH_URL_TOOL,
}


def _builtins(ctx: ToolContext) -> list[str]:
    wanted = set(ctx.names)
    images, web = ctx.image_tools or ctx.auto, ctx.web or ctx.auto
    out = []
    if images or "generate_image" in wanted:
        out.append("generate_image")
    if ctx.init_image and (images or "edit_image" in wanted):
        out.append("edit_image")
    if (ctx.png_source or ctx.init_image) and (images or "read_png_info" in wanted):
        out.append("read_png_info")
    if web or "web_search" in wanted:
        out.append("web_search")
    if web or "fetch_url" in wanted:
        out.append("fetch_url")
    return out


# auto 不給的 Forge 工具：進度 / 中斷是內部用的；破壞性的（例如刪除模型）要點名才給
_AUTO_SKIP = {"get_progress", "interrupt", "skip"}


async def _server(ctx: ToolContext) -> mcp_lite.McpServer:
    server = mcp_lite.McpServer("webui", "1.0.0", log=log.warning)
    defs = ctx.skill_defs()

    def handler(name: str):
        return lambda args, _mctx: _execute(ctx, name, args, defs)

    for name in _builtins(ctx):
        fn = _BUILTIN[name]["function"]
        server.add_tool(name, fn.get("description") or "", fn.get("parameters"), handler(name))
    for name, d in defs.items():
        server.add_tool(name, d.get("description") or "", d.get("parameters"), handler(name))
    for name, schema in ctx.local_tools.items():
        fn = schema.get("function") or {}
        server.add_tool(name, fn.get("description") or "", fn.get("parameters"), _local_handler(ctx, name))
    # 外部 MCP 伺服器（Forge、Civitai Helper、sd.cpp、MMD）上的其他工具：auto 全給（扣掉上面），或點名的
    missing = [n for n in ctx.names if n not in server.tools]
    if ctx.auto or missing:
        for remote, tools in (await _remote_tools()).items():
            for t in tools:
                name = t["name"]
                if name in server.tools:
                    continue
                destructive = (t.get("annotations") or {}).get("destructiveHint")
                if name in missing or (ctx.auto and name not in _AUTO_SKIP and not destructive):
                    server.add_tool(name, t.get("description") or "", t.get("inputSchema"),
                                    _remote_handler(ctx, remote, name))
    if ctx.read_only:
        hints = await _remote_hints()
        for name in list(server.tools):
            if name in ctx.names or name in ctx.local_tools or name in _READ_ONLY_BUILTIN:
                continue
            d = defs.get(name)
            remote = d.get("tool") if d and d.get("kind") == "mcp" else (None if d else name)
            if not ((d and d.get("read_only")) or (remote and hints.get(remote, {}).get("readOnlyHint"))):
                server.tools.pop(name)
    for name in ctx.exclude:
        server.tools.pop(name, None)
    missing = [n for n in ctx.names if n not in server.tools and n not in ctx.exclude]
    if missing:
        raise ValueError(f"沒有工具「{'、'.join(missing)}」：可用 generate_image、web_search、fetch_url、技能的"
                         "工具或 A1111 / Civitai Helper / sd.cpp / MMD 動畫 MCP 的工具名稱（連不上的伺服器沒有"
                         "工具；技能的腳本工具要在設定頁開啟「允許技能執行腳本」）；也可以用 tools=\"auto\" 讓模型自己挑")
    return server


_READ_ONLY_BUILTIN = {"web_search", "fetch_url", "read_png_info"}


async def _remote_tools() -> dict[str, list[dict[str, Any]]]:
    """每個外部 MCP 伺服器的工具清單（同時問）；連不上的略過，點名它的工具時才會報錯。"""
    async def one(remote: str) -> list[dict[str, Any]]:
        try:
            return await mcp_client.list_tools(remote)
        except mcp_client.McpError as e:
            log.info("MCP %s unavailable: %s", remote, e)
            return []
    lists = await asyncio.gather(*(one(r) for r in mcp_client.SERVERS))
    return dict(zip(mcp_client.SERVERS, lists))


async def _remote_hints() -> dict[str, dict[str, Any]]:
    """外部 MCP 伺服器上每個工具的 annotations（readOnlyHint…）。"""
    return {t["name"]: t.get("annotations") or {} for tools in (await _remote_tools()).values() for t in tools}


def _remote_handler(ctx: ToolContext, remote: str, name: str):
    """直接轉給 Forge 的 MCP 工具。結果帶圖（例如 txt2img）就存進 app 的圖片資料夾、推圖片事件，
    並附縮圖給模型看。"""
    async def run(args: dict[str, Any], _mctx: Any) -> mcp_lite.Result:
        import a1111_client
        import chat as chat_mod
        from config import HTTP_TIMEOUT

        if ctx.emit:
            await ctx.emit({"type": "tool_call", "name": name, "args": args})

        async def on_progress(progress: float, total: float | None, message: str | None) -> None:
            if ctx.emit and total:
                await ctx.emit({"type": "progress", "value": min(1.0, progress / total)})

        try:
            res = await mcp_client.call(remote, name, args, on_progress=on_progress, timeout=HTTP_TIMEOUT)
        except mcp_client.McpError as e:
            if ctx.emit:
                await ctx.emit({"type": "error", "message": str(e)})
            return mcp_lite.Result([mcp_lite.text(f"Tool {name} failed: {e}")], is_error=True)
        text = res.text or "(no text)"
        if not res.images:
            return mcp_lite.Result([mcp_lite.text(text)], is_error=res.is_error)
        info = ((res.structured or {}).get("info") or {}) if isinstance(res.structured, dict) else {}
        infotexts = info.get("infotexts") or [] if isinstance(info, dict) else []
        urls = []
        for i, (b64, _mime) in enumerate(res.images):
            url = a1111_client.save_image(b64)
            urls.append(url)
            if ctx.emit:
                params = {"mode": name, **{k: args[k] for k in ("prompt", "negative_prompt", "checkpoint") if args.get(k)}}
                await ctx.emit({"type": "image", "url": url, "params": params,
                                "info": infotexts[i] if i < len(infotexts) else ""})
        vision = [chat_mod.vision_copy(b) for b, _ in res.images[:4]]
        note = f"\n\nThe image(s) were saved and shown to the user: {', '.join(urls)}"
        return mcp_lite.Result([mcp_lite.text(text + note)] + [mcp_lite.image(v, "image/jpeg") for v in vision],
                               is_error=res.is_error, meta={"kind": "generated"})
    return run


def _local_handler(ctx: ToolContext, name: str):
    async def run(args: dict[str, Any], _mctx: Any) -> mcp_lite.Result:
        if ctx.call_local is None:
            raise mcp_lite.ToolError(f"{name} 只能在工作流執行中呼叫")
        return mcp_lite.Result([mcp_lite.text(await ctx.call_local(name, args))])
    return run


async def _execute(ctx: ToolContext, name: str, args: dict[str, Any],
                   defs: dict[str, dict[str, Any]]) -> mcp_lite.Result:
    """實際執行（chat._run_tool：生圖、搜尋、技能工具）；畫面事件交給 emit，給模型的內容放進 MCP 結果。"""
    import chat as chat_mod  # chat 也 import 這個模組

    texts: list[str] = []
    images: list[str] = []
    meta: dict[str, Any] = {}
    async for item in chat_mod._run_tool(
        name, args, ctx.image_settings, ctx.init_image, ctx.png_source,
        skill_tool_map={name: defs[name]} if name in defs else None, edit_image=ctx.edit_image,
    ):
        if isinstance(item, str):
            texts.append(item)
        elif item.get("type") == "_tool_result":
            texts.append(str(item.get("content") or ""))
            images += item.get("images") or []
            meta = {k: item[k] for k in ("kind", "labels") if item.get(k)}
        elif ctx.emit:
            await ctx.emit(item)
    content = [mcp_lite.text("\n".join(t for t in texts if t))] + [mcp_lite.image(b, "image/jpeg") for b in images]
    return mcp_lite.Result(content, meta=meta or None)


async def schemas(ctx: ToolContext) -> list[dict[str, Any]]:
    """這個情境可用的工具（MCP tools/list）→ Ollama / OpenAI 的 function schema。"""
    tools = await (await _server(ctx)).list_local()
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                               "parameters": t["inputSchema"]}} for t in tools]


async def run(ctx: ToolContext, name: str, args: dict[str, Any]) -> AsyncIterator[Any]:
    """經閘道（MCP tools/call）執行一個工具：畫面事件即時 yield（dict），最後 yield 給模型的結果——
    純文字（str），或帶圖時 {"type": "_tool_result", "content", "images", "kind"/"labels"}。"""
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(ev: dict[str, Any]) -> None:
        await queue.put(ev)

    server = await _server(dataclasses.replace(ctx, emit=emit))
    task = asyncio.ensure_future(server.call_local(name, args if isinstance(args, dict) else {}))
    try:
        while True:
            getter = asyncio.ensure_future(queue.get())
            done, _ = await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                yield getter.result()
                continue
            getter.cancel()
            while not queue.empty():
                yield queue.get_nowait()
            break
    finally:
        if not task.done():
            task.cancel()
    res = task.result()
    content = res.get("content") or []
    text = "\n".join(c.get("text") or "" for c in content if c.get("type") == "text")
    images = [c["data"] for c in content if c.get("type") == "image"]
    meta = res.get("_meta") or {}
    if images or meta:
        yield {"type": "_tool_result", "content": text, "images": images, **meta}
    else:
        yield text


# ---------------- HTTP（Claude CLI / Codex 原生 MCP） ----------------
# 每次對話開一個 session：網址帶一次性的 token（/mcp/session/<token>），只在本機連、用完就關。
_sessions: dict[str, ToolContext] = {}
_local_port: int | None = None


def note_port(port: int | None) -> None:
    """記下後端自己聽的 port（main.py 的 middleware 從請求的 scope 取得）。"""
    global _local_port
    if port and not _local_port:
        _local_port = int(port)


def base_url() -> str:
    """CLI 連回閘道用的網址（CLI 跟後端在同一台 / 同一個容器）；MCP_GATEWAY_URL 可覆寫。"""
    env = os.getenv("MCP_GATEWAY_URL", "").rstrip("/")
    return env or f"http://127.0.0.1:{_local_port or int(os.getenv('PORT', '8000'))}"


def open_session(ctx: ToolContext) -> str:
    token = secrets.token_urlsafe(24)
    _sessions[token] = ctx
    return token


def close_session(token: str) -> None:
    _sessions.pop(token, None)


def session_url(token: str) -> str:
    return f"{base_url()}/mcp/session/{token}"


async def handle_http(token: str, request: Request) -> Response:
    ctx = _sessions.get(token)
    if ctx is None:
        return JSONResponse({"error": "unknown or closed session"}, status_code=404)
    return await (await _server(ctx)).handle(request)

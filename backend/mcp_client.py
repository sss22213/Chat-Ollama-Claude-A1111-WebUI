"""MCP 客戶端：webui 對外部服務的工具一律經由它們的 MCP 伺服器呼叫。

伺服器（網址由設定頁「服務來源」的位址推得，token 也在那裡，或用環境變數）：
- a1111：{A1111}/mcp（Forge Neo 內建的 sd_forge_mcp 擴充：生圖、改圖、模型清單、進度、PNG Info…）
- civitai-helper：{A1111}/civitai-helper/mcp（Civitai Helper 擴充：本機模型、LoRA、下載、範例圖、civitai 搜尋…）
- sdcpp：{sd.cpp}/mcp（stable-diffusion.cpp 的 A1111 橋接層：參考圖編輯、img2img、狀態）
- mmd：{MMD}/mcp（anime-render：MMD 動畫算圖）
token：A1111_MCP_TOKEN / CIVITAI_HELPER_MCP_TOKEN / SDCPP_MCP_TOKEN / MMD_MCP_TOKEN。

伺服器是 stateless：每次呼叫開一條連線（initialize → tools/call）。tools/list 快取一分鐘；
連不上的伺服器記 20 秒，這段時間 list_tools 直接報錯（tools="auto" 才不會每次都等它逾時）。
"""
from __future__ import annotations

import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
from mcp.shared.exceptions import MCPError

import settings_store

log = logging.getLogger(__name__)

@dataclass(frozen=True)
class Server:
    path: str  # 接在服務網址後
    label: str
    service: str  # 設定頁「服務來源」的哪一個（網址與 token 在那裡）
    token_from: str  # token 去哪裡拿
    update: str  # 沒有 MCP 端點（404）時怎麼辦


_FORGE_UPDATE = "Forge 要更新到有 MCP 的版本並重啟，設定頁的 MCP 開關要開著"
SERVERS = {
    "a1111": Server("/mcp", "A1111", "a1111", "Forge 設定頁「MCP Server」顯示的 token", _FORGE_UPDATE),
    "civitai-helper": Server("/civitai-helper/mcp", "Civitai Helper", "a1111",
                             "Forge 設定頁「Civitai Helper」顯示的 token", _FORGE_UPDATE),
    "sdcpp": Server("/mcp", "sd.cpp", "sdcpp", "stable-diffusion.cpp 專案 .env 的 MCP_TOKEN",
                    "stable-diffusion.cpp 要更新到有 MCP 的 bridge.py 並重建容器（docker compose up -d --build），"
                    "MCP_ENABLE 不能是 0"),
    "mmd": Server("/mcp", "MMD 動畫", "mmd", "anime-render 專案 .env 的 MCP_TOKEN",
                  "anime-render 要更新到有 MCP 的版本並重建容器（docker compose up -d --build），MCP_ENABLE 不能是 0"),
}
_SOURCE_LABELS = {"a1111": "A1111", "sdcpp": "sd.cpp", "mmd": "MMD"}  # 設定頁上的名稱
TOOLS_TTL = 60.0
DOWN_TTL = 20.0
_tools_cache: dict[str, tuple[float, str, list[dict[str, Any]]]] = {}
_down: dict[str, tuple[float, str, str]] = {}  # server → (時間, 網址, 錯誤訊息)

ProgressFn = Callable[[float, float | None, str | None], Awaitable[None]]


class McpError(RuntimeError):
    """MCP 伺服器連不上、token 不對、或協定錯誤（工具本身回報的錯誤不算，看 ToolResult.is_error）。"""


@dataclass
class ToolResult:
    text: str  # 所有文字內容接起來
    images: list[tuple[str, str]] = field(default_factory=list)  # (base64, mime)
    structured: Any = None  # structuredContent（伺服器回的 JSON）
    is_error: bool = False


def server_url(server: str, base: str | None = None) -> str:
    return (base or settings_store.get_service_url(SERVERS[server].service)).rstrip("/") + SERVERS[server].path


def _explain(server: str, err: BaseException, base: str | None = None) -> str:
    """把 SDK / 網路的例外變成看得懂的一句話。"""
    while isinstance(err, BaseExceptionGroup) and err.exceptions:
        err = err.exceptions[0]
    srv, url = SERVERS[server], server_url(server, base)
    status = getattr(getattr(err, "response", None), "status_code", None)
    if status == 401:
        return (f"{srv.label} 的 MCP token 不對或沒填（{url}）：到設定頁「服務來源 → "
                f"{_SOURCE_LABELS[srv.service]}」填入 {srv.token_from}")
    if status == 404:
        return f"{srv.label} 沒有 MCP 端點或已關閉（{url}）：{srv.update}"
    if isinstance(err, (httpx2.ConnectError, httpx2.ConnectTimeout, OSError)):
        return f"連不上 {srv.label} 的 MCP（{url}）：{err or type(err).__name__}"
    return f"{srv.label} MCP（{url}）：{type(err).__name__}: {err}"


async def _probe(server: str, base: str | None = None, token: str | None = None) -> str | None:
    """SDK 對 HTTP 錯誤只說「Server returned an error response」：直接 ping 一次看狀態碼。"""
    token = settings_store.get_mcp_token(server) if token is None else token
    try:
        async with httpx2.AsyncClient(timeout=10) as client:
            resp = await client.post(server_url(server, base), json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                     headers={"Accept": "application/json, text/event-stream",
                                              **({"Authorization": f"Bearer {token}"} if token else {})})
    except httpx2.HTTPError as e:
        return _explain(server, e, base)
    if resp.status_code in (401, 404):
        return _explain(server, httpx2.HTTPStatusError("", request=resp.request, response=resp), base)
    return None


async def _failure(server: str, err: BaseException, base: str | None = None, token: str | None = None) -> McpError:
    inner = err
    while isinstance(inner, BaseExceptionGroup) and inner.exceptions:
        inner = inner.exceptions[0]
    if isinstance(inner, MCPError):
        if "error response" in str(inner):
            return McpError(await _probe(server, base, token) or f"{SERVERS[server].label} MCP：{inner}")
        return McpError(f"{SERVERS[server].label} MCP：{inner}")
    return McpError(_explain(server, err, base))


@contextlib.asynccontextmanager
async def _session(server: str, timeout: float | None, base: str | None = None, token: str | None = None):
    if server not in SERVERS:
        raise McpError(f"沒有 MCP 伺服器「{server}」")
    token = settings_store.get_mcp_token(server) if token is None else token
    http = create_mcp_http_client(
        headers={"Authorization": f"Bearer {token}"} if token else None,
        timeout=httpx2.Timeout(30.0, read=timeout, connect=10.0),
    )
    async with http, streamable_http_client(server_url(server, base), http_client=http,
                                            max_sse_event_size=None, terminate_on_close=False) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            yield session


async def list_tools(server: str, *, refresh: bool = False) -> list[dict[str, Any]]:
    """[{"name", "description", "inputSchema", "annotations"}]（換了服務網址就重抓）。"""
    url = server_url(server)
    cached = _tools_cache.get(server)
    if cached and not refresh and cached[1] == url and time.monotonic() - cached[0] < TOOLS_TTL:
        return cached[2]
    down = _down.get(server)
    if down and not refresh and down[1] == url and time.monotonic() - down[0] < DOWN_TTL:
        raise McpError(down[2])
    try:
        async with _session(server, 60) as session:
            tools = (await session.list_tools()).tools
    except Exception as e:  # SDK 的錯誤常包在 ExceptionGroup 裡
        err = e if isinstance(e, McpError) else await _failure(server, e)
        _down[server] = (time.monotonic(), url, str(err))
        raise err from None
    _down.pop(server, None)
    out = [{"name": t.name, "description": t.description or "", "inputSchema": t.input_schema or {},
            # MCP 的欄位名（readOnlyHint、destructiveHint…），不是 SDK 的 snake_case
            "annotations": t.annotations.model_dump(exclude_none=True, by_alias=True) if t.annotations else {}}
           for t in tools]
    _tools_cache[server] = (time.monotonic(), url, out)
    return out


async def call(server: str, name: str, args: dict[str, Any] | None = None, *,
               on_progress: ProgressFn | None = None, timeout: float | None = 600) -> ToolResult:
    """呼叫一個工具。連線 / 協定錯誤丟 McpError；工具回報的錯誤放在 ToolResult.is_error。"""
    try:
        async with _session(server, timeout) as session:
            res = await session.call_tool(name, args or {}, read_timeout_seconds=timeout,
                                          progress_callback=on_progress)
    except McpError:
        raise
    except Exception as e:  # JSON-RPC 錯誤（例如沒有這個工具）、HTTP 錯誤、連不上
        raise await _failure(server, e) from None
    texts, images = [], []
    for c in res.content or []:
        if c.type == "text":
            texts.append(c.text)
        elif c.type == "image":
            images.append((c.data, c.mime_type or "image/png"))
    return ToolResult("\n".join(texts), images, res.structured_content, bool(res.is_error))


async def call_json(server: str, name: str, args: dict[str, Any] | None = None, **kw: Any) -> Any:
    """呼叫並取結構化結果（工具回報錯誤就丟 McpError）。給 a1111_client 等內部使用。"""
    res = await call(server, name, args, **kw)
    if res.is_error:
        raise McpError(f"{SERVERS[server].label} 的 {name} 失敗：{res.text[:500]}")
    return res.structured if res.structured is not None else res.text


async def check(server: str, base: str, token: str | None = None) -> dict[str, Any]:
    """設定頁「測試連線」：用（可能還沒儲存的）服務位址與 token 連一次。
    回 {"ok": True, "tools": 數量} 或 {"ok": False, "detail": 原因}。token=None 用已儲存的。"""
    try:
        async with _session(server, 15, base, token) as session:
            tools = (await session.list_tools()).tools
        _down.pop(server, None)  # 剛修好的不必等記錄過期
        return {"ok": True, "tools": len(tools)}
    except McpError as e:
        return {"ok": False, "detail": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": str(await _failure(server, e, base, token))}

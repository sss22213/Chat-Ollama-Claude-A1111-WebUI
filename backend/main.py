"""FastAPI 主程式：REST 代理 + SSE 聊天 + 圖片服務 + 儲存位置設定。"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import a1111_client
import chat as chat_mod
import claude_client
import docker_probe
import ollama_client
import settings_store
import web_tools
from config import CORS_ORIGINS, DEFAULT_IMAGE_SETTINGS

app = FastAPI(title="Chat + Ollama + A1111 WebUI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 載入持久化設定（圖片儲存目錄等）
settings_store.load()


@app.get("/images/{filename}")
async def serve_image(filename: str):
    """從目前（與歷來）儲存目錄動態服務生成圖片。"""
    fp = settings_store.find_image(filename)
    if not fp:
        raise HTTPException(404, "找不到圖片")
    return FileResponse(fp)


class ChatRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    tools_enabled: bool = True
    image_settings: dict[str, Any] | None = None
    think: bool | None = None
    web_enabled: bool = False
    num_ctx: int | None = None
    # 本回合附件的「原始」圖片位元組（未經前端縮圖/轉檔），僅供 read_png_info 讀 metadata。
    image_sources: list[str] | None = None
    # AI 引擎：ollama | claude_cli
    engine: str = "ollama"


@app.get("/api/health")
async def health() -> dict[str, Any]:
    ollama_ok = a1111_ok = True
    try:
        await ollama_client.list_models()
    except Exception:
        ollama_ok = False
    try:
        await a1111_client.get_options()
    except Exception:
        a1111_ok = False
    return {"ollama": ollama_ok, "a1111": a1111_ok}


@app.get("/api/models")
async def models(engine: str = "ollama") -> list[dict[str, Any]]:
    if engine == "claude_cli":
        return claude_client.list_models()
    try:
        return await ollama_client.list_models()
    except Exception as e:
        raise HTTPException(502, f"無法連線 Ollama：{e}")


@app.get("/api/engines")
async def engines() -> dict[str, Any]:
    """回報哪些 AI 引擎可用（給前端啟用/停用選項）。"""
    return {
        "ollama": True,
        "claude_cli": claude_client.available(),
    }


@app.get("/api/sd-models")
async def sd_models() -> list[dict[str, str]]:
    try:
        return await a1111_client.list_sd_models()
    except Exception as e:
        raise HTTPException(502, f"無法連線 A1111：{e}")


@app.get("/api/samplers")
async def samplers() -> list[str]:
    try:
        return await a1111_client.list_samplers()
    except Exception as e:
        raise HTTPException(502, f"無法連線 A1111：{e}")


@app.get("/api/defaults")
async def defaults() -> dict[str, Any]:
    """前端初始化用：預設 SD 參數 + A1111 當前載入的 checkpoint。"""
    current = await a1111_client.get_current_model()
    return {
        "image_settings": DEFAULT_IMAGE_SETTINGS,
        "current_sd_model": current,
        "storage": settings_store.info(),
    }


# ---- 圖片儲存位置 ----
@app.get("/api/storage")
def get_storage() -> dict[str, Any]:
    return settings_store.info()


class StorageRequest(BaseModel):
    image_dir: str


@app.put("/api/storage")
def set_storage(req: StorageRequest) -> dict[str, Any]:
    try:
        settings_store.set_image_dir(req.image_dir)
    except (ValueError, PermissionError) as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"無法設定此目錄：{e}")
    return settings_store.info()


# ---- 伺服器端資料夾瀏覽（給目錄選擇器用）----
@app.get("/api/browse")
def browse(path: str | None = None) -> dict[str, Any]:
    """列出某目錄下的子資料夾，供前端逐層瀏覽。未給 path 時從家目錄開始。"""
    base = Path(path).expanduser() if path else Path.home()
    try:
        base = base.resolve()
    except Exception:
        raise HTTPException(400, "無效的路徑")
    if not base.is_dir():
        raise HTTPException(400, "不是有效的資料夾")

    dirs: list[str] = []
    try:
        for entry in sorted(base.iterdir(), key=lambda e: e.name.lower()):
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    dirs.append(entry.name)
            except (PermissionError, OSError):
                continue
    except PermissionError:
        raise HTTPException(403, "沒有權限存取此資料夾")

    parent = str(base.parent) if base.parent != base else None
    return {
        "path": str(base),
        "parent": parent,
        "dirs": dirs,
        "writable": os.access(base, os.W_OK),
    }


class MkdirRequest(BaseModel):
    path: str
    name: str


@app.post("/api/browse/mkdir")
def make_dir(req: MkdirRequest) -> dict[str, Any]:
    name = req.name.strip()
    if not name or "/" in name or name in (".", ".."):
        raise HTTPException(400, "資料夾名稱無效")
    target = Path(req.path).expanduser() / name
    try:
        target.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        raise HTTPException(400, "資料夾已存在")
    except (PermissionError, OSError) as e:
        raise HTTPException(400, f"無法建立資料夾：{e}")
    return {"path": str(target.resolve())}


# ---- 服務來源（Ollama / A1111）----
@app.get("/api/sources")
def get_sources() -> dict[str, Any]:
    return settings_store.get_sources()


class SourceCfg(BaseModel):
    mode: str | None = None
    url: str | None = None
    container: str | None = None
    port: int | None = None


class SourcesRequest(BaseModel):
    ollama: SourceCfg | None = None
    a1111: SourceCfg | None = None


@app.put("/api/sources")
def set_sources(req: SourcesRequest) -> dict[str, Any]:
    changed = []
    try:
        if req.ollama is not None:
            settings_store.set_source("ollama", req.ollama.model_dump(exclude_none=True))
            changed.append("ollama")
        if req.a1111 is not None:
            settings_store.set_source("a1111", req.a1111.model_dump(exclude_none=True))
            changed.append("a1111")
    except (ValueError, PermissionError) as e:
        raise HTTPException(400, str(e))
    if "ollama" in changed:
        ollama_client.clear_caps_cache()  # 來源變了，能力快取作廢
    return settings_store.get_sources()


class TestRequest(BaseModel):
    service: str  # "ollama" | "a1111"
    mode: str = "api"
    url: str | None = None
    container: str | None = None
    port: int | None = None


@app.post("/api/sources/test")
async def test_source(req: TestRequest) -> dict[str, Any]:
    """測試某來源是否連得上（用各服務的健康端點）。"""
    url = settings_store.effective_url(req.model_dump())
    if not url:
        return {"ok": False, "url": url, "detail": "URL 為空"}
    path = "/api/version" if req.service == "ollama" else "/sdapi/v1/options"
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(f"{url}{path}")
            resp.raise_for_status()
        latency = int((time.monotonic() - t0) * 1000)
        return {"ok": True, "url": url, "latency_ms": latency}
    except Exception as e:
        return {"ok": False, "url": url, "detail": str(e)}


@app.get("/api/docker/containers")
async def docker_containers() -> dict[str, Any]:
    """列出 docker 容器（best-effort，存取不到 socket 時 available=False）。"""
    try:
        containers = await docker_probe.list_containers()
        return {"available": True, "containers": containers}
    except Exception as e:
        return {"available": False, "reason": str(e), "containers": []}


# ---- Web 搜尋設定 ----
@app.get("/api/web")
def get_web() -> dict[str, Any]:
    return settings_store.get_web()


class WebRequest(BaseModel):
    provider: str | None = None
    searxng_url: str | None = None
    max_results: int | None = None
    fetch_max_chars: int | None = None


@app.put("/api/web")
def set_web(req: WebRequest) -> dict[str, Any]:
    try:
        return settings_store.set_web(req.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/web/test")
async def test_web() -> dict[str, Any]:
    """用目前 provider 試搜一筆，確認可用。"""
    import time as _t

    t0 = _t.monotonic()
    try:
        results = await web_tools.web_search("hello world", max_results=1)
        return {
            "ok": bool(results),
            "count": len(results),
            "latency_ms": int((_t.monotonic() - t0) * 1000),
            "sample": results[0] if results else None,
        }
    except Exception as e:
        return {"ok": False, "detail": str(e)}


class PngInfoRequest(BaseModel):
    image: str  # data URL 或 base64（原圖位元組，metadata 才會在）


@app.post("/api/png-info")
async def png_info(req: PngInfoRequest) -> dict[str, Any]:
    """讀取圖片內嵌的 Stable Diffusion 生成參數（A1111 PNG Info）。"""
    if not req.image:
        raise HTTPException(400, "缺少圖片")
    try:
        return await a1111_client.png_info(req.image)
    except Exception as e:
        raise HTTPException(502, f"讀取 PNG 參數失敗：{e}")


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    stream = chat_mod.run_chat(
        model=req.model,
        messages=req.messages,
        tools_enabled=req.tools_enabled,
        image_settings=req.image_settings,
        think=req.think,
        web_enabled=req.web_enabled,
        num_ctx=req.num_ctx,
        image_sources=req.image_sources,
        engine=req.engine,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class CompactRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    num_ctx: int | None = None
    engine: str = "ollama"


@app.post("/api/compact")
async def compact(req: CompactRequest) -> dict[str, Any]:
    """把對話濃縮成摘要，讓後續對話省 context。"""
    lines = []
    for m in req.messages:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            who = "User" if role == "user" else "Assistant"
            lines.append(f"{who}: {content}")
    if not lines:
        raise HTTPException(400, "沒有可摘要的內容")

    system = (
        "You compress conversations. Produce a concise but information-dense summary "
        "of the conversation below, preserving all key facts, decisions, names, "
        "numbers, code snippets, file paths and unresolved questions needed to "
        "continue seamlessly. Use the same language as the conversation. "
        "Output only the summary."
    )
    try:
        if req.engine == "claude_cli":
            summary = await claude_client.chat_once(
                req.model,
                [{"role": "user", "content": "\n\n".join(lines)}],
                system,
            )
        else:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": "\n\n".join(lines)},
            ]
            summary = await ollama_client.chat_once(req.model, messages, req.num_ctx)
    except Exception as e:
        raise HTTPException(502, f"摘要失敗：{e}")
    return {"summary": summary.strip()}


class ImageRequest(BaseModel):
    prompt: str
    image_settings: dict[str, Any] | None = None


@app.post("/api/generate-image")
async def generate_image(req: ImageRequest) -> dict[str, Any]:
    """/image 手動後備：直接出圖、跳過 LLM 判斷。"""
    try:
        return await tools_run(req)
    except Exception as e:
        raise HTTPException(502, f"圖片生成失敗：{e}")


async def tools_run(req: ImageRequest) -> dict[str, Any]:
    import tools as tools_mod

    kind, kwargs = tools_mod.build_call(
        "generate_image", {"prompt": req.prompt}, req.image_settings, None
    )
    return await a1111_client.txt2img(**kwargs)

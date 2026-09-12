"""FastAPI 主程式：REST 代理 + SSE 聊天 + 圖片服務 + 儲存位置設定。"""
from __future__ import annotations

import base64
import binascii
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import threading

import logging

from errors import describe
import a1111_client
import booru_characters
import chat as chat_mod
import claude_client
import codex_client
import comic as comic_mod
import comics_store
import conversations_store
import docker_probe
import loras
import ollama_client
import prompt_history_store
import settings_store
import skills_store
import story as story_mod
import web_tools
from config import BROWSE_ROOTS, CORS_ORIGINS, DEFAULT_IMAGE_SETTINGS

# uvicorn 只幫自己的 logger 接 handler；這裡把 root 接上，comic / story / ollama_client 的
# INFO（每次 chat_once 的 done_reason、token 數）與 WARNING（非 JSON 回覆）才會出現在 docker logs
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
log = logging.getLogger("webui")

app = FastAPI(title="Chat + Ollama + A1111 WebUI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 載入持久化設定（圖片儲存目錄等）+ 初始化對話資料庫
settings_store.load()
conversations_store.init()
comics_store.init()
# 背景補齊角色關鍵字（向 danbooru 抓人氣角色；失敗則只用內建清單，不阻塞啟動）
threading.Thread(target=booru_characters.ensure_enriched, daemon=True).start()


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
    # AI 引擎：ollama | claude_cli | codex
    engine: str = "ollama"
    # 推理強度（claude: low..max；codex: low..ultra，依模型而定）；ollama 不適用
    effort: str | None = None
    # 啟用的技能 slug（Agent Skill）；空＝不啟用
    skill: str | None = None


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
    if engine == "codex":
        return codex_client.list_models()
    try:
        return await ollama_client.list_models()
    except Exception as e:
        raise HTTPException(502, f"無法連線 Ollama：{describe(e)}")


@app.get("/api/engines")
async def engines() -> dict[str, Any]:
    """回報哪些 AI 引擎可用（給前端啟用/停用選項）。"""
    return {
        "ollama": True,
        "claude_cli": claude_client.available(),
        "codex": codex_client.available(),
    }


@app.get("/api/sd-models")
async def sd_models() -> list[dict[str, str]]:
    try:
        return await a1111_client.list_sd_models()
    except Exception as e:
        raise HTTPException(502, f"無法連線 A1111：{describe(e)}")


@app.get("/api/samplers")
async def samplers() -> list[str]:
    try:
        return await a1111_client.list_samplers()
    except Exception as e:
        raise HTTPException(502, f"無法連線 A1111：{describe(e)}")


@app.get("/api/defaults")
async def defaults() -> dict[str, Any]:
    """前端初始化用：預設 SD 參數 + A1111 當前載入的 checkpoint。"""
    current = await a1111_client.get_current_model()
    return {
        "image_settings": DEFAULT_IMAGE_SETTINGS,
        "current_sd_model": current,
        "storage": settings_store.info(),
        # 是否有掛載 sd-webui-prompt-history 的資料目錄（決定前端是否顯示「歷史」按鈕）
        "prompt_history": prompt_history_store.available(),
    }


# ---- 圖片儲存位置 ----
@app.get("/api/storage")
def get_storage() -> dict[str, Any]:
    return settings_store.info()


class StorageRequest(BaseModel):
    image_dir: str


def _ensure_allowed(path: Path) -> Path:
    """把路徑限制在 BROWSE_ROOTS 白名單內（預設家目錄與 DATA_DIR，可用環境變數調整）。"""
    try:
        resolved = path.expanduser().resolve()
    except Exception:
        raise HTTPException(400, "無效的路徑")
    if not any(
        resolved == root or resolved.is_relative_to(root) for root in BROWSE_ROOTS
    ):
        raise HTTPException(403, "此路徑不在允許範圍內（可用 BROWSE_ROOTS 環境變數調整）")
    return resolved


@app.put("/api/storage")
def set_storage(req: StorageRequest) -> dict[str, Any]:
    _ensure_allowed(Path(req.image_dir))
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
    base = _ensure_allowed(Path(path) if path else Path.home())
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

    # 上一層若超出白名單就不給（否則前端點「上一層」會 403）
    parent = None
    if base.parent != base and any(
        base.parent == root or base.parent.is_relative_to(root)
        for root in BROWSE_ROOTS
    ):
        parent = str(base.parent)
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
    target = _ensure_allowed(Path(req.path)) / name
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
        raise HTTPException(502, f"讀取 PNG 參數失敗：{describe(e)}")


# ---- 提示詞歷史（讀取 sd-webui-prompt-history 擴充的紀錄）----
@app.get("/api/prompt-history")
def prompt_history(page: int = 1, q: str = "", page_size: int = 24) -> dict[str, Any]:
    if not prompt_history_store.available():
        raise HTTPException(404, "未設定提示詞歷史目錄（PROMPT_HISTORY_DIR）")
    return prompt_history_store.list_items(page=page, q=q, page_size=page_size)


@app.get("/api/prompt-history/{rec_id}/thumb")
def prompt_history_thumb(rec_id: str, size: int = 256):
    fp = prompt_history_store.thumb_file(rec_id, size)
    if not fp:
        raise HTTPException(404, "找不到縮圖")
    return FileResponse(fp)


def _prompt_history_dir_info() -> dict[str, Any]:
    info = settings_store.prompt_history_info()
    if info["available"]:
        try:
            info["count"] = prompt_history_store.list_items(page=1, page_size=1)["total"]
        except Exception:
            info["count"] = 0
    return info


@app.get("/api/prompt-history-dir")
def prompt_history_dir_get() -> dict[str, Any]:
    return _prompt_history_dir_info()


class PromptHistoryDirRequest(BaseModel):
    dir: str = ""


@app.put("/api/prompt-history-dir")
def prompt_history_dir_set(req: PromptHistoryDirRequest) -> dict[str, Any]:
    try:
        settings_store.set_prompt_history_dir(req.dir)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _prompt_history_dir_info()


# ---- WAI 角色關鍵字搜尋 ----
@app.get("/api/booru-characters")
def booru_characters_search(q: str = "", limit: int = 60) -> list[dict[str, str]]:
    return booru_characters.search(q, max(1, min(200, limit)))


# ---- LoRA 清單 + 觸發詞（讀 A1111 /sdapi/v1/loras） ----
@app.get("/api/loras")
async def loras_search(q: str = "", limit: int = 0) -> list[dict[str, Any]]:
    # limit<=0 → 不限制，回傳全部 LoRA（選單要顯示全部）
    return await loras.search(q, None if limit <= 0 else min(2000, limit))


@app.post("/api/loras/refresh")
async def loras_refresh() -> dict[str, Any]:
    try:
        items = await loras.refresh()
    except Exception as e:
        raise HTTPException(502, f"無法連到 A1111 重新整理 LoRA：{describe(e)}")
    return {"count": len(items), "items": items}


@app.get("/api/lora-thumb")
async def lora_thumb(name: str, size: int = 96):
    """LoRA 縮圖（代理 A1111 預覽圖 + Pillow 縮放快取）；無預覽回 404，前端顯示首字母佔位。"""
    fp = await loras.thumb_file(name, max(48, min(512, size)))
    if not fp:
        raise HTTPException(404, "無縮圖")
    return FileResponse(fp)


# ---- 技能（Agent Skills）外掛 ----
@app.get("/api/skills-dir")
def skills_dir_get() -> dict[str, Any]:
    return settings_store.skills_dir_info()


class SkillsDirRequest(BaseModel):
    dir: str = ""


@app.put("/api/skills-dir")
def skills_dir_set(req: SkillsDirRequest) -> dict[str, Any]:
    try:
        return settings_store.set_skills_dir(req.dir)
    except (ValueError, PermissionError) as e:
        raise HTTPException(400, str(e))


@app.get("/api/skills")
def skills_list() -> list[dict[str, Any]]:
    """列出可用技能（給前端選單）。"""
    return skills_store.list_skills()


@app.get("/api/skills/{slug}")
def skills_get(slug: str) -> dict[str, Any]:
    skill = skills_store.get_skill(slug)
    if not skill:
        raise HTTPException(404, "找不到技能")
    return skill


class SkillSaveRequest(BaseModel):
    slug: str
    content: str  # 完整 SKILL.md 原文


@app.post("/api/skills")
def skills_create(req: SkillSaveRequest) -> dict[str, Any]:
    """新增 / 覆寫技能（在網頁直接編輯 SKILL.md）。"""
    try:
        return skills_store.save_skill(req.slug, req.content)
    except ValueError as e:
        raise HTTPException(400, str(e))


class SkillUpdateRequest(BaseModel):
    content: str


@app.put("/api/skills/{slug}")
def skills_update(slug: str, req: SkillUpdateRequest) -> dict[str, Any]:
    try:
        return skills_store.save_skill(slug, req.content)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/skills/{slug}")
def skills_delete(slug: str) -> dict[str, bool]:
    try:
        ok = skills_store.delete_skill(slug)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "找不到技能")
    return {"ok": True}


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
        effort=req.effort,
        skill=req.skill,
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
    # Ollama 思考型模型是否先思考（None＝模型預設）
    think: bool | None = None


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
    notices = ollama_client.start_notices()
    try:
        if req.engine == "claude_cli":
            summary = await claude_client.chat_once(
                req.model,
                [{"role": "user", "content": "\n\n".join(lines)}],
                system,
            )
        elif req.engine == "codex":
            summary = await codex_client.chat_once(
                req.model,
                [{"role": "user", "content": "\n\n".join(lines)}],
                system,
            )
        else:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": "\n\n".join(lines)},
            ]
            summary = await ollama_client.chat_once(
                req.model, messages, req.num_ctx, think=req.think
            )
    except Exception as e:
        raise HTTPException(502, f"摘要失敗：{describe(e)}")
    return {"summary": summary.strip(), "notices": notices}


# ---- 前端 UI 設定（跨裝置同步；存於 app_settings.json 的 ui blob）----
@app.get("/api/ui-settings")
def get_ui_settings() -> dict[str, Any]:
    return settings_store.get_ui()


@app.put("/api/ui-settings")
def put_ui_settings(body: dict[str, Any]) -> dict[str, Any]:
    try:
        return settings_store.set_ui(body)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---- 對話紀錄（跨裝置、長期保存；存於 SQLite）----
@app.get("/api/conversations")
def list_conversations() -> list[dict[str, Any]]:
    """側欄用的對話摘要清單（不含 messages）。"""
    return conversations_store.list_summaries()


@app.get("/api/conversations/{conv_id}")
def get_conversation(conv_id: str) -> dict[str, Any]:
    conv = conversations_store.get(conv_id)
    if not conv:
        raise HTTPException(404, "找不到對話")
    return conv


@app.put("/api/conversations/{conv_id}")
def put_conversation(conv_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """新增或更新整則對話（含 messages）。"""
    body = {**body, "id": conv_id}
    try:
        return conversations_store.upsert(body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/conversations/{conv_id}")
def delete_conversation(conv_id: str) -> dict[str, bool]:
    conversations_store.delete(conv_id)
    return {"ok": True}


# ---- 漫畫作品（跨裝置、長期保存；作品存 SQLite，圖片在圖片目錄）----
_COMIC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _check_comic_id(comic_id: str) -> str:
    if not _COMIC_ID_RE.match(comic_id or ""):
        raise HTTPException(400, "作品 id 格式不正確")
    return comic_id


@app.get("/api/comics")
def list_comics() -> list[dict[str, Any]]:
    """作品庫清單（摘要）。"""
    return comics_store.list_summaries()


@app.get("/api/comics/{comic_id}")
def get_comic(comic_id: str) -> dict[str, Any]:
    comic = comics_store.get(_check_comic_id(comic_id))
    if not comic:
        raise HTTPException(404, "找不到作品")
    return comic


@app.put("/api/comics/{comic_id}")
def put_comic(comic_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """新增或更新整份作品（前端自動儲存）。"""
    body = {**body, "id": _check_comic_id(comic_id)}
    try:
        return comics_store.upsert(body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/comics/{comic_id}")
def delete_comic(comic_id: str) -> dict[str, bool]:
    comics_store.delete(_check_comic_id(comic_id))
    return {"ok": True}


# 分鏡版本：伺服器端不設上限；清單只回摘要，預覽 / 回復才取整份
@app.get("/api/comics/{comic_id}/versions")
def list_comic_versions(comic_id: str) -> list[dict[str, Any]]:
    return comics_store.list_versions(_check_comic_id(comic_id))


@app.post("/api/comics/{comic_id}/versions")
def add_comic_version(comic_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """新增一版（內容相同不重複存，回 duplicate=true）。"""
    _check_comic_id(comic_id)
    if body.get("id") is not None:
        _check_comic_id(str(body["id"]))
    try:
        return comics_store.add_version(comic_id, body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/comics/{comic_id}/versions/{version_id}")
def get_comic_version(comic_id: str, version_id: str) -> dict[str, Any]:
    v = comics_store.get_version(_check_comic_id(comic_id), _check_comic_id(version_id))
    if not v:
        raise HTTPException(404, "找不到版本")
    return v


@app.delete("/api/comics/{comic_id}/versions/{version_id}")
def delete_comic_version(comic_id: str, version_id: str) -> dict[str, bool]:
    comics_store.delete_version(_check_comic_id(comic_id), _check_comic_id(version_id))
    return {"ok": True}


class ComicPageRequest(BaseModel):
    image: str  # 整頁 PNG 的 data URL 或純 base64


@app.post("/api/comics/{comic_id}/page")
def save_comic_page(comic_id: str, req: ComicPageRequest) -> dict[str, str]:
    """把匯出的整頁 PNG 存進圖片目錄（與生成圖同處、可永久保存），並記到作品上。"""
    _check_comic_id(comic_id)
    b64 = req.image.split(",", 1)[-1] if req.image.startswith("data:") else req.image
    try:
        raw = base64.b64decode(b64, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(400, "圖片不是合法的 base64")
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise HTTPException(400, "只接受 PNG")
    filename = f"comic_{comic_id}_{int(time.time())}.png"
    image_dir = settings_store.get_image_dir()
    image_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / filename).write_bytes(raw)
    url = f"/images/{filename}"
    comic = comics_store.get(comic_id)
    if comic:
        comics_store.upsert({**comic, "pageUrl": url})
    return {"url": url}


class ImageRequest(BaseModel):
    prompt: str
    image_settings: dict[str, Any] | None = None


@app.post("/api/generate-image")
async def generate_image(req: ImageRequest) -> dict[str, Any]:
    """/image 手動後備：直接出圖、跳過 LLM 判斷。"""
    try:
        return await tools_run(req)
    except Exception as e:
        log.exception("圖片生成失敗")
        raise HTTPException(502, f"圖片生成失敗：{describe(e)}")


async def tools_run(req: ImageRequest) -> dict[str, Any]:
    import tools as tools_mod

    kind, kwargs = tools_mod.build_call(
        "generate_image", {"prompt": req.prompt}, req.image_settings, None
    )
    return await a1111_client.txt2img(**kwargs)


# ---- 漫畫分鏡（用 LLM 把劇情拆成多格腳本；出圖仍走 /api/generate-image）----
class StoryboardRequest(BaseModel):
    engine: str = "ollama"
    model: str
    premise: str
    panel_count: int = 6
    # 角色卡：[{name, appearance}]；name 會被引用到每格的 characters
    characters: list[dict[str, Any]] | None = None
    style: str = ""
    lang: str = "zh-TW"
    num_ctx: int | None = None
    # Ollama 思考型模型是否先思考（None＝模型預設；前端有開關）
    think: bool | None = None
    # 使用者自訂的額外指示（指引 AI 分鏡的風格/語氣/內容）
    system: str = ""
    # 覆寫內建的分鏡 system 範本（空＝用預設）
    system_base: str = ""


# ---- 圖片說故事（上傳圖片 → LLM 看圖生成故事或漫畫腳本；與漫畫工作室分開的入口）----
class StoryRequest(BaseModel):
    engine: str = "ollama"
    model: str
    # base64（可含 data URL 前綴）；張數不限，context 夠不夠由前端預估提醒
    images: list[str]
    mode: str = "story"  # story | comic | panels（每張圖一格，補文字）
    lang: str = "zh-TW"
    instructions: str = ""
    length: str = "medium"  # story：short | medium | long
    panel_count: int = 6  # comic
    num_ctx: int | None = None
    think: bool | None = None


@app.post("/api/story/from-image")
async def story_from_image(req: StoryRequest) -> dict[str, Any]:
    try:
        return await story_mod.from_image(
            engine=req.engine,
            model=req.model,
            images=req.images,
            mode=req.mode,
            lang=req.lang,
            instructions=req.instructions,
            length=req.length,
            panel_count=req.panel_count,
            num_ctx=req.num_ctx,
            think=req.think,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.exception("生成失敗")
        raise HTTPException(502, f"生成失敗：{describe(e)}")


@app.get("/api/comic/system-default")
def comic_system_default() -> dict[str, str]:
    """內建分鏡 system 範本，給前端「載入預設」編輯。"""
    return {"system": comic_mod.default_system()}


class PanelPromptRequest(BaseModel):
    engine: str = "ollama"
    model: str
    # 整份分鏡（prompt / expression / characters / dialogue / caption），給模型看前後文
    panels: list[dict[str, Any]]
    index: int  # 要重生的那一格（0 起算）
    premise: str = ""
    characters: list[dict[str, Any]] | None = None
    style: str = ""
    lang: str = "zh-TW"
    instruction: str = ""  # 使用者對這格的要求（選填）
    num_ctx: int | None = None
    think: bool | None = None
    system: str = ""


@app.post("/api/comic/panel-prompt")
async def comic_panel_prompt(req: PanelPromptRequest) -> dict[str, Any]:
    """只為一格重新產生場景關鍵字與表情。"""
    try:
        return await comic_mod.panel_prompt(
            engine=req.engine,
            model=req.model,
            panels=req.panels,
            index=req.index,
            premise=req.premise,
            characters=req.characters,
            style=req.style,
            lang=req.lang,
            instruction=req.instruction,
            num_ctx=req.num_ctx,
            system=req.system,
            think=req.think,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.exception("關鍵字生成失敗")
        raise HTTPException(502, f"關鍵字生成失敗：{describe(e)}")


@app.post("/api/comic/storyboard")
async def comic_storyboard(req: StoryboardRequest) -> dict[str, Any]:
    try:
        return await comic_mod.storyboard(
            engine=req.engine,
            model=req.model,
            premise=req.premise,
            panel_count=req.panel_count,
            characters=req.characters,
            style=req.style,
            lang=req.lang,
            num_ctx=req.num_ctx,
            think=req.think,
            system=req.system,
            system_base=req.system_base,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.exception("分鏡生成失敗")
        raise HTTPException(502, f"分鏡生成失敗：{describe(e)}")

"""讀取 sd-webui-prompt-history 擴充的歷史紀錄（唯讀整合）。

該擴充沒有 HTTP API，唯一介面是它的 data 目錄：
- data.json：JSON 陣列，每筆 {id, name, model, info_text, created_at}（最新在前）。
- <id>.jpg：每筆對應的預覽圖（擴充以 full 尺寸存）。

目錄來自 settings_store.get_prompt_history_dir()（env 預設 PROMPT_HISTORY_DIR，
可由 UI 覆寫並持久化），所以可在執行期切換、不需重啟。info_text 是 A1111 標準參數
字串，直接用 a1111_client.parse_geninfo 解析，與 PNG Info 共用「套用到設定」邏輯。
"""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Any

import settings_store
from a1111_client import parse_geninfo
from config import DATA_DIR

# id 用於組檔名/快取名，限制成安全字元避免路徑穿越（擴充用 uuid4().hex）。
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

_lock = threading.Lock()
# 快取鍵含 path：UI 切換目錄後路徑變了就重讀（不只看 mtime）。
_cache: dict[str, Any] = {"path": None, "mtime": None, "records": []}
_THUMB_DIR = DATA_DIR / "history_thumbs"


def _data_file() -> str | None:
    d = settings_store.get_prompt_history_dir()
    return os.path.join(d, "data.json") if d else None


def available() -> bool:
    f = _data_file()
    return bool(f and os.path.isfile(f))


def _load() -> list[dict[str, Any]]:
    """載入 data.json（依 path+mtime 快取）。

    擴充每次生成都會整檔改寫，故以 mtime 偵測變更後重讀；讀失敗（可能正改寫到一半）
    時保留同路徑的舊快取，避免回傳空清單。
    """
    f = _data_file()
    if not f or not os.path.isfile(f):
        return []
    same = _cache["path"] == f

    def _stale_fallback() -> list[dict[str, Any]]:
        return _cache["records"] if same else []

    try:
        mtime = os.path.getmtime(f)
    except OSError:
        return _stale_fallback()
    if same and _cache["mtime"] == mtime and _cache["records"]:
        return _cache["records"]
    with _lock:
        # 重新檢查：其他執行緒可能已在等鎖期間讀好了
        if _cache["path"] == f and _cache["mtime"] == mtime and _cache["records"]:
            return _cache["records"]
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return _stale_fallback()  # 改寫中 → 用舊快取
        if not isinstance(data, list):
            data = []
        _cache["path"] = f
        _cache["mtime"] = mtime
        _cache["records"] = data
        return data


def _item(rec: dict[str, Any]) -> dict[str, Any]:
    """把一筆原始紀錄轉成前端用的物件（含解析後的 prompt / 參數 / 可套用設定）。"""
    parsed = parse_geninfo(rec.get("info_text") or "")
    return {
        "id": rec.get("id"),
        "name": rec.get("name") or "",
        "model": rec.get("model") or "",
        "created_at": rec.get("created_at"),
        "prompt": parsed["prompt"],
        "negative_prompt": parsed["negative_prompt"],
        "params": parsed["params"],
        "settings": parsed["settings"],
    }


def list_items(page: int = 1, page_size: int = 24, q: str = "") -> dict[str, Any]:
    """分頁 + 關鍵字搜尋（比對 name / info_text / model，不分大小寫）。"""
    records = _load()
    needle = (q or "").strip().lower()
    if needle:
        records = [
            r
            for r in records
            if needle in (r.get("name") or "").lower()
            or needle in (r.get("info_text") or "").lower()
            or needle in (r.get("model") or "").lower()
        ]
    total = len(records)
    page_size = max(1, min(100, int(page_size)))
    pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(int(page), pages))
    start = (page - 1) * page_size
    items = [_item(r) for r in records[start : start + page_size]]
    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": pages,
        "page_size": page_size,
    }


def thumb_file(rec_id: str, size: int = 256) -> str | None:
    """回傳縮圖路徑：用 Pillow 即時縮放並快取於 DATA_DIR/history_thumbs。

    歷史圖不會變動，故縮圖可永久快取。Pillow 缺失或解碼失敗時退回原圖（較大仍可顯示）。
    """
    base = settings_store.get_prompt_history_dir()
    if not _ID_RE.match(rec_id or "") or not base:
        return None
    src = os.path.join(base, f"{rec_id}.jpg")
    if not os.path.isfile(src):
        return None
    size = max(48, min(512, int(size)))
    _THUMB_DIR.mkdir(parents=True, exist_ok=True)
    cache = _THUMB_DIR / f"{rec_id}_{size}.jpg"
    if cache.is_file():
        return str(cache)
    try:
        from PIL import Image

        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((size, size), Image.LANCZOS)
            im.save(cache, "JPEG", quality=80)
        return str(cache)
    except Exception:
        return src

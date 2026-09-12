"""漫畫作品持久化（SQLite）：漫畫工作室的整份作品（劇本、角色卡、分鏡格、氣泡、出圖設定）
存在伺服器端，瀏覽器的 localStorage 只是快取。存於 DATA_DIR/comics.db（compose 已把
DATA_DIR 綁定到主機資料夾，重建容器不掉）；圖片本身在圖片目錄，作品只記 /images/<檔名>。
單機個人工具：所有作品共用一張表、無帳號隔離，連到同一個後端的裝置看到同一份。

分鏡版本（comic_versions）另存一張表、不設上限：每一版是一份分鏡格的快照（JSON），
用內容雜湊去重（同一份作品內容一模一樣的不重複存）。清單只回摘要，預覽 / 回復才取整份。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from typing import Any

from config import DATA_DIR

_DB_PATH = DATA_DIR / "comics.db"
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS comics (
                id          TEXT PRIMARY KEY,
                title       TEXT,
                panel_count INTEGER,
                cover       TEXT,
                created_at  REAL,
                updated_at  REAL,
                data        TEXT NOT NULL
            )
            """
        )
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS comic_versions (
                id       TEXT PRIMARY KEY,
                comic_id TEXT NOT NULL,
                at       REAL,
                label    TEXT,
                premise  TEXT,
                count    INTEGER,
                images   INTEGER,
                cover    TEXT,
                hash     TEXT,
                data     TEXT NOT NULL
            )
            """
        )
        _conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_comic_versions ON comic_versions(comic_id, at DESC)"
        )
        _conn.commit()
    return _conn


def init() -> None:
    with _lock:
        _connect()


def _cover(comic: dict[str, Any]) -> str:
    """作品庫縮圖：匯出過的整頁圖優先，否則第一張有圖的分鏡格。"""
    if comic.get("pageUrl"):
        return str(comic["pageUrl"])
    for p in comic.get("panels") or []:
        url = ((p or {}).get("image") or {}).get("url")
        if url:
            return str(url)
    return ""


def list_summaries() -> list[dict[str, Any]]:
    """作品庫用：只回摘要，依最後更新時間新到舊。"""
    with _lock:
        rows = _connect().execute(
            "SELECT id, title, panel_count, cover, created_at, updated_at "
            "FROM comics ORDER BY updated_at DESC"
        ).fetchall()
    return [
        {
            "id": r[0],
            "title": r[1] or "",
            "panel_count": r[2] or 0,
            "cover": r[3] or "",
            "created_at": r[4],
            "updated_at": r[5],
        }
        for r in rows
    ]


def get(comic_id: str) -> dict[str, Any] | None:
    with _lock:
        row = _connect().execute("SELECT data FROM comics WHERE id = ?", (comic_id,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def upsert(comic: dict[str, Any]) -> dict[str, Any]:
    """新增或更新整份作品。回傳含時間戳的作品。"""
    comic_id = comic.get("id")
    if not comic_id:
        raise ValueError("comic 缺少 id")
    now = time.time()
    created = comic.get("created_at") or now
    stored = {**comic, "created_at": created, "updated_at": now}
    # 舊版前端把版本塞在作品 JSON 裡：搬進版本表，作品本身不再帶
    legacy_versions = stored.pop("versions", None)
    if isinstance(legacy_versions, list):
        for v in legacy_versions:
            if isinstance(v, dict) and isinstance(v.get("panels"), list):
                add_version(comic_id, v)
    panels = stored.get("panels") or []
    with _lock:
        c = _connect()
        c.execute(
            """
            INSERT INTO comics (id, title, panel_count, cover, created_at, updated_at, data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                panel_count=excluded.panel_count,
                cover=excluded.cover,
                updated_at=excluded.updated_at,
                data=excluded.data
            """,
            (
                comic_id,
                str(stored.get("title") or ""),
                len(panels) if isinstance(panels, list) else 0,
                _cover(stored),
                created,
                now,
                json.dumps(stored, ensure_ascii=False),
            ),
        )
        c.commit()
    return stored


def delete(comic_id: str) -> None:
    with _lock:
        c = _connect()
        c.execute("DELETE FROM comics WHERE id = ?", (comic_id,))
        c.execute("DELETE FROM comic_versions WHERE comic_id = ?", (comic_id,))
        c.commit()


# ---------------- 分鏡版本 ----------------

_VERSION_COLS = "id, comic_id, at, label, premise, count, images, cover"


def _version_summary(r: tuple) -> dict[str, Any]:
    return {
        "id": r[0],
        "comic_id": r[1],
        "at": r[2],  # 前端給的毫秒 epoch（Date.now()），原樣保存
        "label": r[3] or "",
        "premise": r[4] or "",
        "count": r[5] or 0,
        "images": r[6] or 0,
        "cover": r[7] or "",
    }


def _panels_hash(panels: list[Any]) -> str:
    return hashlib.sha1(
        json.dumps(panels, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def list_versions(comic_id: str) -> list[dict[str, Any]]:
    """某份作品的所有版本摘要（不含分鏡格內容），新到舊。"""
    with _lock:
        rows = _connect().execute(
            f"SELECT {_VERSION_COLS} FROM comic_versions WHERE comic_id = ? ORDER BY at DESC",
            (comic_id,),
        ).fetchall()
    return [_version_summary(r) for r in rows]


def get_version(comic_id: str, version_id: str) -> dict[str, Any] | None:
    """整份版本（含 panels）。"""
    with _lock:
        row = _connect().execute(
            f"SELECT {_VERSION_COLS}, data FROM comic_versions WHERE comic_id = ? AND id = ?",
            (comic_id, version_id),
        ).fetchone()
    if not row:
        return None
    out = _version_summary(row)
    try:
        out["panels"] = json.loads(row[8])
    except json.JSONDecodeError:
        out["panels"] = []
    return out


def add_version(comic_id: str, v: dict[str, Any]) -> dict[str, Any]:
    """新增一版。內容與既有版本一模一樣時不重複存，回傳既有的那版並標 duplicate=True。"""
    panels = v.get("panels")
    if not isinstance(panels, list) or not panels:
        raise ValueError("version 缺少 panels")
    h = _panels_hash(panels)
    with _lock:
        c = _connect()
        dup = c.execute(
            f"SELECT {_VERSION_COLS} FROM comic_versions WHERE comic_id = ? AND hash = ? "
            "ORDER BY at DESC LIMIT 1",
            (comic_id, h),
        ).fetchone()
        if dup:
            return {**_version_summary(dup), "duplicate": True}
        vid = str(v.get("id") or f"{int(time.time() * 1000)}-{h[:8]}")
        row = (
            vid,
            comic_id,
            float(v.get("at") or time.time() * 1000),
            str(v.get("label") or "manual"),
            str(v.get("premise") or ""),
            len(panels),
            sum(1 for p in panels if isinstance(p, dict) and ((p.get("image") or {}).get("url"))),
            next(
                (
                    str(p["image"]["url"])
                    for p in panels
                    if isinstance(p, dict) and ((p.get("image") or {}).get("url"))
                ),
                "",
            ),
            h,
            json.dumps(panels, ensure_ascii=False),
        )
        c.execute(
            "INSERT OR REPLACE INTO comic_versions "
            "(id, comic_id, at, label, premise, count, images, cover, hash, data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )
        c.commit()
    return {**_version_summary(row[:8]), "duplicate": False}


def delete_version(comic_id: str, version_id: str) -> None:
    with _lock:
        c = _connect()
        c.execute(
            "DELETE FROM comic_versions WHERE comic_id = ? AND id = ?", (comic_id, version_id)
        )
        c.commit()

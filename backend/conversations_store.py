"""對話紀錄持久化（SQLite）：跨裝置共用、長期保存。

存於 DATA_DIR/conversations.db（compose 已 bind-mount 到主機，重建不掉）。
這是單機個人工具：所有對話共用一張表，無帳號隔離；連到同一個後端的裝置看到同一份。
每則對話以一列存放，完整內容（含 messages）放在 data 欄的 JSON。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from config import DATA_DIR

_DB_PATH = DATA_DIR / "conversations.db"
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
ANY = object()  # upsert 的 base：不比對版本，整份覆蓋（舊版前端、測試腳本直接 PUT）


class Conflict(Exception):
    """整則寫入的基礎版本不是伺服器上目前的版本。current：目前的對話；對話已刪除時是 None。"""

    def __init__(self, current: dict[str, Any] | None) -> None:
        super().__init__("conflict")
        self.current = current


def _next_time(prev: float | None) -> float:
    """新的 updated_at：一定比上一個大（時鐘沒前進也一樣），版本才不會被誤認成同一個。"""
    now = time.time()
    return now if prev is None or now > prev else prev + 1e-6


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id         TEXT PRIMARY KEY,
                title      TEXT,
                model      TEXT,
                created_at REAL,
                updated_at REAL,
                data       TEXT NOT NULL
            )
            """
        )
        _conn.commit()
    return _conn


def init() -> None:
    with _lock:
        _connect()


def list_summaries() -> list[dict[str, Any]]:
    """側欄用：只回摘要（不含 messages），依最後更新時間新到舊。"""
    with _lock:
        rows = _connect().execute(
            "SELECT id, title, model, created_at, updated_at "
            "FROM conversations ORDER BY updated_at DESC"
        ).fetchall()
    return [
        {
            "id": r[0],
            "title": r[1],
            "model": r[2],
            "created_at": r[3],
            "updated_at": r[4],
        }
        for r in rows
    ]


def scan_texts() -> list[tuple[str, str, str]]:
    """(id, 標題, 完整 JSON) — 圖片庫找「哪些對話用了這張圖」用。"""
    with _lock:
        return _connect().execute("SELECT id, title, data FROM conversations").fetchall()


def get(conv_id: str) -> dict[str, Any] | None:
    """完整對話（含 messages）。"""
    with _lock:
        row = _connect().execute(
            "SELECT data FROM conversations WHERE id = ?", (conv_id,)
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def update_message(conv_id: str, msg_id: str, patch: dict[str, Any]) -> tuple[float, float] | None:
    """只改一則訊息（回覆在後端跑時用）：讀、改、寫在同一把鎖裡，不會蓋掉網頁同時存的標題等內容。
    找不到訊息就接在最後（回覆不能丟）；對話已刪回 None，不會把它救回來。
    回 (改之前的 updated_at, 新的 updated_at)：正在看這則回覆的網頁，本機版本是改之前那個時，
    就知道自己已經看過新版本（訊息內容它都收到了），之後整則存檔不會被當成舊版本。"""
    with _lock:
        c = _connect()
        row = c.execute("SELECT updated_at, data FROM conversations WHERE id = ?", (conv_id,)).fetchone()
        if not row:
            return None
        conv = json.loads(row[1])
        messages = conv.setdefault("messages", [])
        for m in messages:
            if m.get("id") == msg_id:
                m.update(patch)
                break
        else:
            messages.append({"id": msg_id, "role": "assistant", **patch})
        now = _next_time(row[0])
        conv["updated_at"] = now
        c.execute(
            "UPDATE conversations SET updated_at = ?, data = ? WHERE id = ?",
            (now, json.dumps(conv, ensure_ascii=False), conv_id),
        )
        c.commit()
    return row[0], now


def upsert(conv: dict[str, Any], base: Any = ANY) -> dict[str, Any]:
    """新增或更新整則對話。回傳含時間戳的對話。
    base：這份資料是以哪個版本為基礎（用戶端上次看到的 updated_at；None＝從沒存過的新對話）。
    伺服器上的版本不是它、或對話已經刪除，就丟 Conflict、不寫入：舊分頁 / 另一台裝置的整份資料
    才不會蓋掉它沒看過的訊息（包括後端回覆之後才存的內容），也不會把別處刪掉的對話建回來。
    比對和寫入在同一把鎖裡。"""
    conv_id = conv.get("id")
    if not conv_id:
        raise ValueError("conversation 缺少 id")
    with _lock:
        c = _connect()
        row = c.execute("SELECT updated_at, data FROM conversations WHERE id = ?", (conv_id,)).fetchone()
        if base is not ANY:
            if row is None and base is not None:
                raise Conflict(None)
            if row is not None and (base is None or row[0] != base):
                raise Conflict(json.loads(row[1]))
        now = _next_time(row[0] if row else None)
        created = conv.get("created_at") or now
        stored = {**conv, "created_at": created, "updated_at": now}
        data = json.dumps(stored, ensure_ascii=False)
        c.execute(
            """
            INSERT INTO conversations (id, title, model, created_at, updated_at, data)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                model=excluded.model,
                updated_at=excluded.updated_at,
                data=excluded.data
            """,
            (conv_id, stored.get("title"), stored.get("model"), created, now, data),
        )
        c.commit()
    return stored


def delete(conv_id: str) -> None:
    with _lock:
        c = _connect()
        c.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        c.commit()

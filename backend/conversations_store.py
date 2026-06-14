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


def upsert(conv: dict[str, Any]) -> dict[str, Any]:
    """新增或更新整則對話。回傳含時間戳的對話。"""
    conv_id = conv.get("id")
    if not conv_id:
        raise ValueError("conversation 缺少 id")
    now = time.time()
    created = conv.get("created_at") or now
    stored = {**conv, "created_at": created, "updated_at": now}
    data = json.dumps(stored, ensure_ascii=False)
    with _lock:
        c = _connect()
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

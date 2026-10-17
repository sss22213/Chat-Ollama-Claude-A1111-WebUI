"""LangGraph 工作流的執行紀錄：每次執行（工作流頁面或聊天 /workflow）存成一個 JSON 檔。

位置 LANGGRAPH_RUNS_DIR/<資料夾代號>/<專案>/<run_id>.json，每個專案留最近 MAX_RUNS 筆。
紀錄內容：圖、輸入、引擎 / 模型、來源、狀態、開始 / 結束時間、事件（截短）、最終輸出、錯誤、圖片。
"""
from __future__ import annotations

import contextlib
import json
import re
import time
from pathlib import Path
from typing import Any

import langgraph_store as store
from config import LANGGRAPH_RUNS_DIR

MAX_RUNS = 100
MAX_EVENTS = 600
_RUN_ID_RE = re.compile(r"^[0-9a-f]{6,32}$")
# 執行中的 run（還沒結束）；不在這裡卻是 running 的紀錄＝後端中途重啟，顯示為中斷
_active: set[str] = set()


def runs_dir(slug: str) -> Path:
    return LANGGRAPH_RUNS_DIR / store.folder_key() / slug


def _path(slug: str, run_id: str) -> Path:
    if not store.valid_slug(slug) or not _RUN_ID_RE.match(run_id or ""):
        raise ValueError("不合法的紀錄編號")
    return runs_dir(slug) / f"{run_id}.json"


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _images_in(value: Any, out: list[str]) -> list[str]:
    if isinstance(value, str):
        if re.fullmatch(r"/images/[^\s\"']+\.(png|jpe?g|webp)", value, re.I) and value not in out:
            out.append(value)
    elif isinstance(value, list):
        for v in value:
            _images_in(v, out)
    elif isinstance(value, dict):
        for v in value.values():
            _images_in(v, out)
    return out


def start(slug: str, run_id: str, *, graph: str, input: Any, engine: str, model: str, source: str) -> None:
    _active.add(run_id)
    _write(_path(slug, run_id), {
        "id": run_id, "project": slug, "graph": graph, "input": input, "engine": engine,
        "model": model, "source": source, "status": "running", "started_at": time.time(),
    })


def finish(slug: str, run_id: str, *, status: str, events: list[dict[str, Any]],
           output: Any = None, error: str = "", trace: str = "") -> None:
    _active.discard(run_id)
    path = _path(slug, run_id)
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rec = {"id": run_id, "project": slug, "started_at": time.time()}
    images = [e["url"] for e in events if e.get("type") == "image" and e.get("url")]
    _images_in(output, images)
    kept = [e for e in events if e.get("type") not in ("progress",)]
    if len(kept) > MAX_EVENTS:
        kept = kept[: MAX_EVENTS // 2] + [{"type": "note", "text": f"…（省略 {len(kept) - MAX_EVENTS} 筆事件）"}] + kept[-MAX_EVENTS // 2:]
    rec.update({
        "status": status, "finished_at": time.time(), "events": kept, "output": output,
        "error": error, "trace": trace, "images": images[:40],
    })
    _write(path, rec)
    _prune(slug)


def _prune(slug: str) -> None:
    files = sorted(runs_dir(slug).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[MAX_RUNS:]:
        with contextlib.suppress(OSError):
            old.unlink()


def _summary(rec: dict[str, Any]) -> dict[str, Any]:
    status = rec.get("status")
    if status == "running" and rec.get("id") not in _active:
        status = "interrupted"  # 後端在執行中重啟
    inp = rec.get("input")
    preview = inp if isinstance(inp, str) else json.dumps(inp, ensure_ascii=False)
    started, finished = rec.get("started_at"), rec.get("finished_at")
    return {
        "id": rec.get("id"), "graph": rec.get("graph"), "status": status,
        "engine": rec.get("engine"), "model": rec.get("model"), "source": rec.get("source"),
        "started_at": started, "seconds": round(finished - started, 1) if started and finished else None,
        "input_preview": (preview or "")[:160], "images": (rec.get("images") or [])[:4],
        "error": (rec.get("error") or "")[:300],
    }


def list_runs(slug: str, limit: int = MAX_RUNS) -> list[dict[str, Any]]:
    d = runs_dir(slug)
    if not store.valid_slug(slug) or not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        with contextlib.suppress(OSError, ValueError):
            out.append(_summary(json.loads(f.read_text(encoding="utf-8"))))
    out.sort(key=lambda r: r.get("started_at") or 0, reverse=True)
    return out


def last_run(slug: str) -> dict[str, Any] | None:
    runs = list_runs(slug, limit=3)
    if not runs:
        return None
    r = runs[0]
    return {"id": r["id"], "status": r["status"], "started_at": r["started_at"], "graph": r["graph"]}


def get_run(slug: str, run_id: str) -> dict[str, Any]:
    path = _path(slug, run_id)
    if not path.is_file():
        raise FileNotFoundError("找不到這筆執行紀錄")
    rec = json.loads(path.read_text(encoding="utf-8"))
    return {**rec, "status": _summary(rec)["status"]}


def delete_run(slug: str, run_id: str) -> None:
    path = _path(slug, run_id)
    if run_id in _active:
        raise ValueError("這筆還在執行中")
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def clear_runs(slug: str) -> int:
    if not store.valid_slug(slug):
        raise ValueError("不合法的專案名稱")
    n = 0
    for f in runs_dir(slug).glob("*.json"):
        if f.stem not in _active:
            f.unlink()
            n += 1
    return n

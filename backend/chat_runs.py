"""聊天回覆在後端跑：不跟著瀏覽器的連線走，關掉網頁也會跑完並存進對話。

前端先把問題和空的助理訊息存好，再 POST /api/chat。回覆由這裡的背景工作驅動：依事件組出助理訊息
（規則要跟前端 store/chat.js 的 _applyChatEvent 一致），定期存回 conversations_store。
網頁只是旁觀者：連線斷了不影響回覆，重開時先拿目前內容（snapshot），再接著收之後的事件。
一個對話同時只有一個 run。run 放在記憶體：後端重啟就沒了（連 SIGTERM 也來不及收尾，uvicorn 關完會
再送一次訊號），訊息停在 streaming，存下來的部分還在；前端打開時發現沒在跑，就標成中斷。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any, AsyncIterator

import conversations_store
from config import CHAT_RUN_TIMEOUT
from errors import describe

log = logging.getLogger("webui")

_SAVE_EVERY = 3.0  # 打字中多久存一次（秒）
# 沒事件時多久送一次 ping（秒）：網頁靠它分辨「模型只是安靜」和「連線其實死了」。
# 連線死掉不一定收得到通知（手機換網路、電腦休眠、代理卡住），要跟前端 lib/api.js 的 STALL_MS 搭配
_PING_EVERY = 10.0
# 這些事件之後馬上存：內容不會再從別處補回來，重開網頁要看得到
_SAVE_NOW = {"tool_call", "image", "gallery", "candidates", "sources", "error"}
# 模型偶爾把給它看的系統備註抄進回覆：從標記起切掉（跟前端 stripEchoedNote 同一個標記）
_NOTE_MARKER = "[系統備註，使用者看不到"

_runs: dict[str, "ChatRun"] = {}


class Busy(Exception):
    """這個對話已經有回覆在跑。"""


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _js_len(text: str) -> int:
    """JavaScript 的字串長度（UTF-16）：圖片的 at 是前端拿來切文字的位置，emoji 算兩個。"""
    return len(text.encode("utf-16-le")) // 2


def _strip_note(text: str) -> str:
    i = text.find(_NOTE_MARKER)
    return text if i < 0 else text[:i].rstrip()


class ChatRun:
    def __init__(self, conv_id: str, msg_id: str) -> None:
        self.conv_id = conv_id
        self.msg_id = msg_id
        self.message: dict[str, Any] = {"content": "", "thinking": "", "images": [], "status": "streaming"}
        self.usage: dict[str, Any] | None = None
        self.subscribers: set[asyncio.Queue] = set()
        self.loop = asyncio.get_running_loop()
        self.task: asyncio.Task | None = None
        self.timer: asyncio.TimerHandle | None = None
        self.closing = False  # 已在收尾：不能再取消，否則 done 送不出去

    def apply(self, e: dict[str, Any]) -> None:
        """事件 → 助理訊息。"""
        m, t = self.message, e.get("type")
        if t == "thinking":
            m["thinking"] += e.get("delta") or ""
        elif t == "token":
            m["content"] += e.get("delta") or ""
            m["toolRunning"] = False  # 開始輸出答案代表工具階段結束
        elif t == "tool_call":
            m.update(toolRunning=True, toolName=e.get("name"), progress=None)
        elif t == "gallery":
            m.setdefault("galleries", []).append(
                {"title": e.get("title") or "", "trained_words": e.get("trained_words") or [], "items": e.get("items") or []})
        elif t == "candidates":
            m.setdefault("candidates", []).append(
                {"kind": e.get("kind"), "items": e.get("items") or [], "next_cursor": e.get("next_cursor")})
        elif t == "sources":
            sources = m.setdefault("sources", [])
            seen = {s.get("url") for s in sources}
            for s in e.get("results") or []:
                if s.get("url") and s["url"] not in seen:
                    seen.add(s["url"])
                    sources.append(s)
            m["toolRunning"] = False
        elif t == "progress":
            preview = e.get("preview")
            m["progress"] = {"value": e.get("value") or 0, "text": e.get("text") or "", "step": e.get("step"),
                             "steps": e.get("steps"), "preview": f"data:image/png;base64,{preview}" if preview else None}
        elif t == "image":
            m["images"].append({"url": e.get("url"), "params": e.get("params"), "info": e.get("info") or "",
                                "at": _js_len(m["content"])})
            m.update(toolRunning=False, progress=None)
        elif t == "usage":
            self.usage = {"prompt_tokens": e.get("prompt_tokens"), "num_ctx": e.get("num_ctx")}
        elif t == "error":
            m.update(toolRunning=False, error=e.get("message"))

    def publish(self, event: dict[str, Any] | None) -> None:
        for q in self.subscribers:
            q.put_nowait(event)

    async def save(self) -> float | None:
        """存進對話（生圖進度只給正在看的人，不存）。對話已刪就回 None。"""
        patch = {k: v for k, v in self.message.items() if k != "progress"}
        return await asyncio.to_thread(conversations_store.update_message, self.conv_id, self.msg_id, patch)


async def _drive(run: ChatRun, stream: AsyncIterator[str]) -> None:
    cancelled = False
    saved_at = time.monotonic()
    try:
        async for chunk in stream:
            ev = json.loads(chunk.removeprefix("data: "))
            if ev.get("type") == "done":
                continue  # 收尾時才送，那時已經存好了
            run.apply(ev)
            run.publish(ev)
            if ev.get("type") in _SAVE_NOW or time.monotonic() - saved_at >= _SAVE_EVERY:
                await run.save()
                saved_at = time.monotonic()
    except asyncio.CancelledError:
        cancelled = True
    except Exception as e:
        log.exception("聊天回覆失敗")
        ev = {"type": "error", "message": describe(e)}
        run.apply(ev)
        run.publish(ev)
    finally:
        run.closing = True
        if run.timer:
            run.timer.cancel()
        with contextlib.suppress(Exception):
            await stream.aclose()
    m = run.message
    m.update(status="done", toolRunning=False, content=_strip_note(m["content"]))
    m.pop("progress", None)
    updated_at = None
    try:
        updated_at = await run.save()
    except Exception:
        log.exception("聊天回覆存檔失敗")
    # 先存好才移除：查不到 run 就代表對話裡已經是最後結果
    _runs.pop(run.conv_id, None)
    run.publish({"type": "done", "cancelled": cancelled, "updated_at": updated_at})
    run.publish(None)


def _expire(run: ChatRun) -> None:
    if run.closing or not run.task:
        return
    ev = {"type": "error", "message": f"回覆超過 {CHAT_RUN_TIMEOUT:.0f} 秒上限，已停止（CHAT_RUN_TIMEOUT）"}
    run.apply(ev)
    run.publish(ev)
    run.task.cancel()


def start(conv_id: str, msg_id: str, stream: AsyncIterator[str]) -> ChatRun:
    if conv_id in _runs:
        raise Busy
    run = ChatRun(conv_id, msg_id)
    _runs[conv_id] = run
    run.task = asyncio.create_task(_drive(run, stream))
    run.timer = run.loop.call_later(CHAT_RUN_TIMEOUT, _expire, run)
    return run


def get(conv_id: str) -> ChatRun | None:
    return _runs.get(conv_id)


def cancel(conv_id: str) -> bool:
    """停止回覆（可從其他執行緒呼叫）；已存的部分留著。沒有在跑回 False。"""
    run = _runs.get(conv_id)
    if not run or run.closing or not run.task:
        return False
    run.loop.call_soon_threadsafe(run.task.cancel)
    return True


def follow(run: ChatRun, *, snapshot: bool = False) -> AsyncIterator[str]:
    """訂閱 run 的事件（SSE）。現在就登記，不等串流開始：之後的事件一個都不會漏。
    snapshot：先送目前內容，給中途才接上的網頁。連線斷了只是退訂，回覆繼續跑。"""
    q: asyncio.Queue = asyncio.Queue()
    run.subscribers.add(q)
    first = _sse({"type": "snapshot", "id": run.msg_id, "message": run.message, "usage": run.usage}) if snapshot else None

    async def events() -> AsyncIterator[str]:
        try:
            if first:
                yield first
            while True:
                try:
                    async with asyncio.timeout(_PING_EVERY):
                        ev = await q.get()
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if ev is None:
                    break
                yield _sse(ev)
        finally:
            run.subscribers.discard(q)

    return events()

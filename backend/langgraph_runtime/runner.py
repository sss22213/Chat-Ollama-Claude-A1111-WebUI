"""LangGraph 工作流執行器：在專案自己的 venv 裡跑（只用標準函式庫＋langgraph）。

app 後端以子程序啟動它（見 backend/langgraph_exec.py）：
- stdin 第一行是工作（JSON）：{"mode": "run"|"inspect", "graphs": {id: spec}, "graph", "input",
  "run_id", "interactive", ...}；之後的每一行是 webui_app 呼叫的回覆 {"id", "result"|"error"}，
  或 interrupt 的回覆 {"type": "resume", "value"}（interactive 時才會等）。
- 原本的 stdout（fd 1）只送 JSON 事件（一行一則）。使用者程式的 print 變成 log 事件，
  其他直接寫到 fd 1 的東西（例如子程序）改去 stderr，不會弄壞協定。

graph 的寫法照官方 langgraph.json："./path/file.py:變數" 或 "套件.模組:變數"；
變數可以是編譯好的圖、還沒 compile 的 StateGraph，或接收 config 的工廠函式（可為 async）。
"""
from __future__ import annotations

import asyncio
import dataclasses
import importlib
import importlib.util
import inspect
import json
import os
import random
import string
import sys
import traceback
from pathlib import Path
from typing import Any

import webui_app

EVENT_STR_LIMIT = 4000  # 節點更新裡每個字串最多帶這麼長
OUTPUT_STR_LIMIT = 100_000  # 最終輸出


def send(event: dict[str, Any]) -> None:
    webui_app._send(event)


def jsonable(obj: Any, limit: int = EVENT_STR_LIMIT, depth: int = 0) -> Any:
    """狀態 → 可轉 JSON 的資料（LangChain 訊息、pydantic、dataclass 都處理；長字串截斷）。"""
    if depth > 12:
        return "…"
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        return obj if len(obj) <= limit else obj[:limit] + f"…(+{len(obj) - limit} chars)"
    if isinstance(obj, (bytes, bytearray)):
        return f"<{len(obj)} bytes>"
    if isinstance(obj, dict):
        return {str(k): jsonable(v, limit, depth + 1) for k, v in list(obj.items())[:200]}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [jsonable(v, limit, depth + 1) for v in list(obj)[:500]]
    if type(obj).__name__ == "Interrupt" and hasattr(obj, "value"):
        return {"interrupt": jsonable(obj.value, limit, depth + 1)}
    if isinstance(getattr(obj, "type", None), str) and hasattr(obj, "content"):  # LangChain 訊息
        out = {"type": obj.type, "content": jsonable(obj.content, limit, depth + 1)}
        for k in ("name", "tool_calls", "tool_call_id"):
            v = getattr(obj, k, None)
            if v:
                out[k] = jsonable(v, limit, depth + 1)
        return out
    if hasattr(obj, "model_dump"):
        try:
            return jsonable(obj.model_dump(), limit, depth + 1)
        except Exception:
            pass
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return jsonable(dataclasses.asdict(obj), limit, depth + 1)
    return repr(obj)[:limit]


# ---------------- 載入圖 ----------------

def load_target(project: Path, spec: str) -> Any:
    left, sep, attr = spec.rpartition(":")
    if not sep or not left or not attr:
        raise ValueError(f"graph 要寫成 './檔案.py:變數' 或 '模組:變數'：{spec}")
    if left.endswith((".ts", ".mts", ".js", ".mjs")):
        raise ValueError(f"只支援 Python 的圖：{spec}")
    if left.endswith(".py") or "/" in left or "\\" in left:
        file = (project / left).resolve()
        if not file.is_file():
            raise ValueError(f"找不到 {left}")
        # 跟官方一樣用隨機模組名載入檔案；專案根目錄與檔案所在資料夾都在 sys.path
        sys.path.insert(0, str(file.parent))
        name = "lg_" + "".join(random.choices(string.ascii_lowercase, k=16))
        modspec = importlib.util.spec_from_file_location(name, file)
        if modspec is None or modspec.loader is None:
            raise ValueError(f"無法載入 {left}")
        module = importlib.util.module_from_spec(modspec)
        sys.modules[name] = module
        modspec.loader.exec_module(module)
    else:
        module = importlib.import_module(left)
    if not hasattr(module, attr):
        raise ValueError(f"{left} 裡沒有 {attr}")
    return getattr(module, attr)


async def resolve(obj: Any, config: dict[str, Any]) -> Any:
    """編譯好的圖直接用；StateGraph 先 compile；工廠函式帶 config 呼叫（可為 async）。"""
    for _ in range(3):
        if hasattr(obj, "astream"):
            return obj
        if hasattr(obj, "compile"):
            obj = obj.compile()
            continue
        if callable(obj):
            params = [p for p in inspect.signature(obj).parameters.values()
                      if p.default is inspect.Parameter.empty
                      and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]
            obj = obj(config) if params else obj()
            if inspect.isawaitable(obj):
                obj = await obj
            if hasattr(obj, "__aenter__") and not hasattr(obj, "astream"):
                raise ValueError("不支援 async context manager 形式的圖工廠")
            continue
        break
    raise ValueError(f"不是 LangGraph 的圖：{type(obj).__name__}")


def _is_text_schema(prop: dict[str, Any]) -> bool:
    if prop.get("type") == "string":
        return True
    return any(isinstance(a, dict) and a.get("type") == "string" for a in prop.get("anyOf") or [])


def text_to_input(graph: Any, text: str) -> dict[str, Any]:
    """一段文字當輸入：有 messages 就當使用者訊息，否則放進第一個字串欄位。"""
    try:
        props = (graph.get_input_jsonschema() or {}).get("properties") or {}
    except Exception:
        props = {}
    if "messages" in props:
        return {"messages": [{"role": "user", "content": text}]}
    for key, prop in props.items():
        if isinstance(prop, dict) and _is_text_schema(prop):
            return {key: text}
    fields = ", ".join(props) or "(沒有欄位資訊)"
    raise ValueError(f"這個工作流的輸入不是文字，請給 JSON 物件。欄位：{fields}")


def describe_graph(graph: Any) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for key, fn in (("input_schema", "get_input_jsonschema"), ("output_schema", "get_output_jsonschema")):
        try:
            info[key] = getattr(graph, fn)()
        except Exception as e:
            info[key] = None
            info.setdefault("warnings", []).append(f"{fn}: {e}")
    try:
        drawable = graph.get_graph()
        data = drawable.to_json()
        info["nodes"] = [n["id"] for n in data.get("nodes", [])]
        info["edges"] = [
            {"source": e["source"], "target": e["target"], "conditional": bool(e.get("conditional")),
             # 條件邊的分支名稱（path_map 的鍵跟目標不同時才有）
             **({"label": e["data"]} if isinstance(e.get("data"), str) else {})}
            for e in data.get("edges", [])
        ]
        info["mermaid"] = drawable.draw_mermaid()
    except Exception as e:
        info.setdefault("warnings", []).append(f"get_graph: {e}")
    return info


# ---------------- 模式 ----------------

def _config(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "recursion_limit": int(job.get("recursion_limit") or 50),
        "configurable": dict(job.get("configurable") or {}),
    }


async def inspect_graphs(job: dict[str, Any]) -> None:
    project = Path(job["project_dir"])
    out: dict[str, Any] = {}
    for gid, spec in (job.get("graphs") or {}).items():
        try:
            graph = await resolve(load_target(project, spec), _config(job))
            out[gid] = {"spec": spec, **describe_graph(graph)}
        except Exception as e:
            out[gid] = {"spec": spec, "error": f"{type(e).__name__}: {e}",
                        "traceback": traceback.format_exc()[-4000:]}
    send({"type": "inspect", "graphs": jsonable(out, OUTPUT_STR_LIMIT)})


def _ns_name(ns: tuple[str, ...]) -> str:
    return "/".join(part.split(":", 1)[0] for part in ns)


def _stream_modes() -> list[str]:
    """tasks 模式（節點開始執行時通知，給流程圖標出執行中的節點）較新的 langgraph 才有。"""
    modes = ["updates", "custom", "values", "messages"]
    try:
        import typing

        from langgraph.types import StreamMode

        if "tasks" in typing.get_args(StreamMode):
            modes.append("tasks")
    except Exception:
        pass
    return modes


def _with_checkpointer(graph: Any) -> Any:
    """interrupt（webui_app.ask）要有 checkpointer 才能暫停後接著跑：圖沒有自己的就加記憶體版，
    只在這次執行（這個子程序）裡有效。compile(checkpointer=False) 明確關掉的不動。"""
    if getattr(graph, "checkpointer", None) not in (None, True) or not hasattr(graph, "copy"):
        return graph
    try:
        from langgraph.checkpoint.memory import InMemorySaver
    except ImportError:
        try:
            from langgraph.checkpoint.memory import MemorySaver as InMemorySaver
        except ImportError:
            return graph
    try:
        return graph.copy(update={"checkpointer": InMemorySaver()})
    except Exception:
        return graph


async def _pending_interrupts(graph: Any, config: dict[str, Any]) -> list[tuple[str, Any]]:
    """串流停下來後還在等回覆的 interrupt：[(節點名稱, Interrupt)]。"""
    try:
        snap = await graph.aget_state(config)
    except Exception:
        return []
    found = [(str(t.name), i) for t in getattr(snap, "tasks", None) or () for i in getattr(t, "interrupts", None) or ()]
    if not found:
        found = [("", i) for i in getattr(snap, "interrupts", None) or ()]
    return found


async def run_graph(job: dict[str, Any]) -> None:
    project = Path(job["project_dir"])
    gid = job["graph"]
    spec = (job.get("graphs") or {}).get(gid)
    if not spec:
        raise ValueError(f"langgraph.json 沒有 graph「{gid}」")
    config = _config(job)
    config["configurable"].setdefault("thread_id", job.get("run_id") or "run")
    graph = _with_checkpointer(await resolve(load_target(project, spec), config))
    resumable = getattr(graph, "checkpointer", None) not in (None, False)
    if not job.get("recursion_limit"):  # 沒指定就用圖自己 with_config 的步數上限
        bound = (getattr(graph, "config", None) or {}).get("recursion_limit")
        if bound:
            config["recursion_limit"] = int(bound)
    inp = job.get("input")
    if isinstance(inp, str):
        inp = text_to_input(graph, inp)
    send({"type": "start", "graph": gid, "input": jsonable(inp)})
    final: Any = None
    while True:
        async for ns, mode, data in graph.astream(inp, config, stream_mode=_stream_modes(), subgraphs=True):
            where = _ns_name(ns)
            if mode == "tasks":
                # 開始執行有 input；結束的那則（result / error）跟 updates 重複，不送
                if isinstance(data, dict) and "input" in data and data.get("name"):
                    send({"type": "task", "ns": where, "node": str(data["name"])})
            elif mode == "updates":
                for node, update in (data or {}).items():
                    if node != "__interrupt__":
                        send({"type": "node", "ns": where, "node": node, "update": jsonable(update)})
                    elif not resumable:  # 沒有 checkpointer：只能顯示，執行到這裡就結束
                        send({"type": "interrupt", "ns": where, "value": jsonable(update)})
            elif mode == "values":
                if not ns:
                    final = data
            elif mode == "custom":
                send({"type": "custom", "ns": where, "data": jsonable(data)})
            elif mode == "messages":
                chunk, meta = data
                text = webui_app._text(getattr(chunk, "content", ""))
                if text:
                    send({"type": "token", "ns": where,
                          "node": (meta or {}).get("langgraph_node") or "", "text": text[:EVENT_STR_LIMIT]})
        pending = await _pending_interrupts(graph, config) if resumable else []
        if not pending:
            break
        # 一次問一個；同時有好幾個（平行的節點都在等）就回覆完一個再問下一個
        node, first = pending[0]
        iid = getattr(first, "id", None) or getattr(first, "interrupt_id", None)
        send({"type": "interrupt", "ns": "", "node": node, "id": iid, "pending": len(pending),
              "value": jsonable(getattr(first, "value", first), OUTPUT_STR_LIMIT)})
        if not job.get("interactive"):
            raise RuntimeError("這個工作流要等人輸入（interrupt），聊天裡沒辦法回覆：請到工作流頁面執行")
        answer = await asyncio.to_thread(webui_app._wait_resume)
        send({"type": "resume", "ns": "", "node": node, "id": iid, "value": jsonable(answer)})
        from langgraph.types import Command

        inp = Command(resume={iid: answer} if iid else answer)
    # values 串流給的是整個狀態；最終輸出跟 invoke 一樣只留 output_schema 的欄位
    channels = getattr(graph, "output_channels", None)
    if isinstance(final, dict) and isinstance(channels, (list, tuple)):
        final = {k: final[k] for k in channels if k in final}
    send({"type": "done", "output": jsonable(final, OUTPUT_STR_LIMIT)})


def main() -> int:
    proto = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)  # 其他寫到 fd 1 的東西改去 stderr
    job = json.loads(sys.stdin.readline() or "{}")
    webui_app._init(proto, job, sys.stdin)
    sys.stdout = webui_app._LogStream()
    project = job.get("project_dir") or os.getcwd()
    sys.path[:0] = [project, *[p for p in job.get("extra_paths") or [] if p]]
    try:
        asyncio.run(inspect_graphs(job) if job.get("mode") == "inspect" else run_graph(job))
        return 0
    except BaseException as e:  # noqa: BLE001 — 任何錯誤都要回報給 app
        sys.stdout.flush()
        send({"type": "error", "message": f"{type(e).__name__}: {e}",
              "traceback": traceback.format_exc()[-6000:]})
        return 1
    finally:
        sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())

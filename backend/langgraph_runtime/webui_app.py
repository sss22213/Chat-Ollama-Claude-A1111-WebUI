"""給 LangGraph 工作流用的 app 介面（在專案自己的 venv 裡 `import webui_app`）。

節點可以直接用 app 的引擎、生圖與搜尋，不需要任何 API key：

    import webui_app

    def write(state):
        text = webui_app.chat(f"Write one paragraph about {state['idea']}")
        return {"scene": text}

    def draw(state):
        img = webui_app.generate_image("1girl, solo, rain, umbrella, night")
        return {"image": img["url"]}

- chat / achat：用工作流頁面（或聊天）目前選的引擎與模型；engine / model 可逐次指定。
  images=[...] 讓模型看圖：generate_image 回的 url（/images/xxx.png）、data URL 或 base64 都可以
  （模型要有視覺能力；Claude / Codex 都有，Ollama / Strata 看模型）。
  tools=[...] 讓模型呼叫工具（app 的 generate_image / web_search / fetch_url、技能的工具、
  工作流裡的 Python 函式），skill="…" 載入技能的 SKILL.md 和它的工具。
- app_tools：app / 技能的工具 → LangChain 工具（配 get_chat_model().bind_tools 與 ToolNode）。
- generate_image / agenerate_image：走 app 的 A1111，套用 app 的生圖設定；回 {"url", "info", "params"}。
- list_checkpoints / alist_checkpoints：A1111 的 checkpoint 與各自的底模（Illustrious、Pony、SD 1.5…）。
- web_search / aweb_search：app 的網頁搜尋；回 [{"title", "url", "snippet"}]。
- ask：暫停工作流，在工作流頁面請人填表（LangGraph 的 interrupt），回填好的值。
- emit：在執行紀錄顯示一行進度。
- get_chat_model()：LangChain 的 chat model（BaseChatModel），可用在 llm.invoke(state["messages"])。

呼叫經由執行器的 stdin / stdout 交給 app 後端處理（見 runner.py），所以只能在工作流執行中使用。
"""
from __future__ import annotations

import asyncio
import inspect
import io
import itertools
import json
import queue
import threading
from typing import Any

_proto: Any = None  # 協定輸出（原本的 stdout）
_send_lock = threading.Lock()
_pending: dict[int, dict[str, Any]] = {}
_pending_lock = threading.Lock()
_ids = itertools.count(1)
_job: dict[str, Any] = {}
_closed = False
_resumes: queue.Queue[Any] = queue.Queue()  # 工作流頁面送回來的 interrupt 回覆
_CLOSED = object()
# Claude CLI / Codex 原生 MCP 的對話進行中：{agent id: {"tools": {名稱: 函式}, "node": 節點}}——
# CLI 經閘道呼叫工作流裡的 Python 函式時，後端送 local_tool 過來，由這裡執行
_agents: dict[str, dict[str, Any]] = {}


# ---------------- 協定（runner.py 使用） ----------------

def _send(event: dict[str, Any]) -> None:
    line = json.dumps(event, ensure_ascii=False)
    with _send_lock:
        _proto.write(line + "\n")
        _proto.flush()


def _reader(stream: Any) -> None:
    """讀 app 後端的回覆（stdin），交給等待中的呼叫；{"type": "resume"} 是 interrupt 的回覆。"""
    global _closed
    for line in stream:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("type") == "resume":
            _resumes.put(msg.get("value"))
            continue
        if msg.get("type") == "local_tool":  # 另開執行緒：函式可能很久，也可能再呼叫 webui_app
            threading.Thread(target=_serve_local, args=(msg,), daemon=True).start()
            continue
        with _pending_lock:
            slot = _pending.pop(msg.get("id"), None)
        if slot is not None:
            slot.update(msg)
            slot["event"].set()
    _closed = True
    with _pending_lock:
        waiting = list(_pending.values())
        _pending.clear()
    for slot in waiting:
        slot["error"] = "app 後端已關閉連線"
        slot["event"].set()
    _resumes.put(_CLOSED)


def _wait_resume() -> Any:
    """等工作流頁面回覆 interrupt（runner.py 用）。"""
    value = _resumes.get()
    if value is _CLOSED:
        raise RuntimeError("app 後端已關閉連線")
    return value


def _init(proto: Any, job: dict[str, Any], stdin: Any) -> None:
    global _proto
    _proto = proto
    _job.update(job)
    threading.Thread(target=_reader, args=(stdin,), daemon=True).start()


class _LogStream(io.TextIOBase):
    """使用者程式的 print → 執行紀錄的 log 事件（一行一則）。"""

    def __init__(self) -> None:
        self._buf = ""

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            _send({"type": "log", "text": line[:4000]})
        return len(s)

    def flush(self) -> None:
        if self._buf:
            _send({"type": "log", "text": self._buf[:4000]})
            self._buf = ""


def _current_node() -> str:
    try:
        from langgraph.config import get_config

        return str(get_config().get("metadata", {}).get("langgraph_node") or "")
    except Exception:
        return ""


def _call(fn: str, args: dict[str, Any]) -> Any:
    if _proto is None or _closed:
        raise RuntimeError("webui_app 只能在 app 執行的工作流裡使用")
    cid = next(_ids)
    slot: dict[str, Any] = {"event": threading.Event()}
    with _pending_lock:
        _pending[cid] = slot
    _send({"type": "call", "id": cid, "fn": fn, "args": args, "node": _current_node()})
    slot["event"].wait()
    if slot.get("error"):
        raise RuntimeError(f"webui_app.{fn}: {slot['error']}")
    return slot.get("result")


# ---------------- 訊息轉換 ----------------

_ROLES = {"human": "user", "user": "user", "ai": "assistant", "assistant": "assistant",
          "system": "system", "tool": "tool", "function": "tool"}


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # LangChain 多段內容
        return "".join(
            p if isinstance(p, str) else str(p.get("text") or "") if isinstance(p, dict) else ""
            for p in content
        )
    return "" if content is None else str(content)


def _images(content: Any) -> list[str]:
    """LangChain 多段內容裡的圖片（image_url / image）→ url 或 data URL / base64。"""
    out: list[str] = []
    for p in content if isinstance(content, list) else []:
        if not isinstance(p, dict):
            continue
        if p.get("type") == "image_url":
            url = p.get("image_url")
            url = url.get("url") if isinstance(url, dict) else url
            if url:
                out.append(str(url))
        elif p.get("type") == "image":
            src = p.get("url") or p.get("base64") or p.get("data") or (p.get("source") or {}).get("data")
            if src:
                out.append(str(src))
    return out


def _tool_calls(value: Any) -> list[dict[str, Any]]:
    """LangChain 的 tool_calls、OpenAI / Ollama 的 {"function": …} → [{"id", "name", "args"}]。"""
    out = []
    for c in value or []:
        c = c if isinstance(c, dict) else {"name": getattr(c, "name", ""), "args": getattr(c, "args", {}),
                                           "id": getattr(c, "id", None)}
        fn = c.get("function") if isinstance(c.get("function"), dict) else c
        args = fn.get("args", fn.get("arguments"))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        out.append({"id": c.get("id"), "name": str(fn.get("name") or ""), "args": args if isinstance(args, dict) else {}})
    return out


def _messages(messages: Any) -> tuple[list[dict[str, Any]], str]:
    """dict / (role, text) / LangChain 訊息 → [{"role", "content", "images"?, "tool_calls"?}] 與合併後的 system。
    工具呼叫與結果（AIMessage.tool_calls、ToolMessage）保留下來，由後端依引擎轉換。"""
    out: list[dict[str, Any]] = []
    system: list[str] = []
    for m in messages or []:
        get = m.get if isinstance(m, dict) else (lambda k, d=None, _m=m: getattr(_m, k, d))
        if isinstance(m, dict):
            role, content = m.get("role") or m.get("type") or "user", m.get("content")
        elif isinstance(m, (tuple, list)) and len(m) == 2:
            role, content = m
            get = lambda k, d=None: d  # noqa: E731
        elif isinstance(m, str):
            role, content = "user", m
            get = lambda k, d=None: d  # noqa: E731
        else:
            role, content = getattr(m, "type", "user"), getattr(m, "content", "")
        role = _ROLES.get(str(role).lower(), "user")
        text = _text(content)
        imgs = _images(content) + [str(i) for i in (m.get("images") or [] if isinstance(m, dict) else [])]
        if role == "system":
            system.append(text)
        elif role == "tool":
            out.append({"role": "tool", "content": text, "name": get("name") or "",
                        "tool_call_id": get("tool_call_id") or "", **({"images": imgs} if imgs else {})})
        else:
            calls = _tool_calls(get("tool_calls")) if role == "assistant" else []
            out.append({"role": role, "content": text, **({"images": imgs} if imgs else {}),
                        **({"tool_calls": calls} if calls else {})})
    return out, "\n\n".join(s for s in system if s)


# ---------------- 工具（chat 的 tools / skill） ----------------

def _schema_of(tool: Any) -> dict[str, Any]:
    """Python 函式（型別註記＋docstring）或 LangChain 工具 → function schema。"""
    from langchain_core.utils.function_calling import convert_to_openai_tool

    return convert_to_openai_tool(tool)


def _cli_engine(engine: str | None) -> bool:
    """Claude CLI / Codex：帶工具時走原生 MCP（CLI 自己呼叫工具），不是一回合一回合交給工作流。"""
    return (engine or _job.get("engine")) in ("claude_cli", "codex")


def _tool_list(tools: Any) -> tuple[list[Any], bool]:
    """tools 參數 → (清單, 是否 auto)。"auto"（或清單裡放 "auto"）＝全部的 MCP 工具給模型挑。"""
    items = [tools] if isinstance(tools, str) else list(tools or [])
    auto = "auto" in [t for t in items if isinstance(t, str)]
    return [t for t in items if t != "auto"], auto


def _tool_specs(tools: Any, skill: str | None, exclude: list[str] | None = None,
                read_only: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """tools（"auto"、app / 技能 / MCP 工具的名稱、Python 函式、LangChain 工具）＋ skill 的工具 →
    (function schemas, {名稱: 在工作流裡執行的函式 / 工具})。"""
    items, auto = _tool_list(tools)
    names: list[str] = []
    local: dict[str, Any] = {}
    schemas: list[dict[str, Any]] = []
    for t in items:
        if isinstance(t, str):
            names.append(t)
        else:
            schema = _schema_of(t)
            local[schema["function"]["name"]] = t
            schemas.append(schema)
    if names or skill or auto:
        app = _call("tool_schemas", {"names": names, "skill": skill, "auto": auto,
                                     "exclude": list(exclude or []), "read_only": read_only}) or []
        schemas = [s for s in app if s["function"]["name"] not in local] + schemas
    return schemas, local


def _run_sync(value: Any) -> Any:
    """async 工具的結果（coroutine）在另一個執行緒跑完。"""
    if not inspect.isawaitable(value):
        return value
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["v"] = asyncio.run(value)
        except BaseException as e:  # noqa: BLE001
            box["e"] = e

    t = threading.Thread(target=run)
    t.start()
    t.join()
    if "e" in box:
        raise box["e"]
    return box.get("v")


def _as_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if hasattr(result, "content") and not isinstance(result, dict):  # ToolMessage
        return _text(result.content)
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(result)


def _run_local(tool: Any, name: str, args: dict[str, Any], node: str) -> str:
    """執行工作流裡的函式 / LangGraph 工具，錯誤也變成文字（交給模型決定怎麼辦）。"""
    _send({"type": "tool_call", "node": node, "name": name, "args": args})
    try:
        out = tool.invoke(args) if hasattr(tool, "invoke") and not inspect.isroutine(tool) else tool(**args)
        text = _as_text(_run_sync(out))
    except Exception as e:  # noqa: BLE001
        text = f"Tool {name} failed: {type(e).__name__}: {e}"
        _send({"type": "call_error", "node": node, "fn": name, "message": str(e)[:500]})
    _send({"type": "tool_result", "node": node, "name": name, "text": text[:2000]})
    return text


def _serve_local(msg: dict[str, Any]) -> None:
    """後端轉來的 local_tool（CLI 經閘道呼叫工作流裡的函式）→ 執行 → 回 local_tool_result。"""
    agent = _agents.get(str(msg.get("agent") or "")) or {}
    name = str(msg.get("name") or "")
    tool = (agent.get("tools") or {}).get(name)
    args = msg.get("args") if isinstance(msg.get("args"), dict) else {}
    text = (_run_local(tool, name, args, agent.get("node") or "") if tool is not None
            else f"Tool {name} is not available in this workflow")
    _send({"type": "local_tool_result", "id": msg.get("id"), "text": text})


def _invoke_tool(call: dict[str, Any], local: dict[str, Any], skill: str | None,
                 auto: bool = False, exclude: list[str] | None = None, read_only: bool = False) -> dict[str, Any]:
    """執行一個工具呼叫：工作流裡的函式就地執行，其他交給 app（生圖、搜尋、技能與 MCP 工具）。"""
    name, args = call["name"], call.get("args") or {}
    node = _current_node()
    if name not in local:
        try:
            result = _call("call_tool", {"name": name, "args": args, "skill": skill, "auto": auto,
                                         "exclude": list(exclude or []), "read_only": read_only}) or {}
        except RuntimeError as e:
            result = {"text": f"Tool {name} failed: {e}"}
        _send({"type": "tool_result", "node": node, "name": name, "text": str(result.get("text") or "")[:2000]})
        return result
    return {"text": _run_local(local[name], name, args, node)}


# ---------------- 公開 API ----------------

def current() -> dict[str, Any]:
    """這次執行預設用的引擎與模型：{"engine", "model"}。"""
    return {"engine": _job.get("engine"), "model": _job.get("model")}


def chat(
    prompt: str | None = None,
    *,
    messages: Any = None,
    system: str | None = None,
    engine: str | None = None,
    model: str | None = None,
    think: bool | None = None,
    images: list[Any] | None = None,
    tools: Any = None,
    skill: str | None = None,
    max_rounds: int = 8,
    details: bool = False,
    exclude_tools: list[str] | None = None,
    read_only: bool = False,
) -> Any:
    """問 app 的 LLM，回傳文字。prompt 或 messages 擇一（messages 可含 LangChain 訊息）。

    images：要給模型看的圖，接在最後一則使用者訊息上——generate_image 的結果（dict 或
    它的 url）、/images/xxx.png、data URL 或 base64 都可以。

    tools：讓模型呼叫工具，跑到它不再呼叫（最多 max_rounds 輪）才回最後的文字。
    tools="auto"：全部的 MCP 工具（生圖、搜尋、所有技能、A1111 / Civitai Helper 伺服器上的工具）
    讓模型自己挑；也可以 ["auto", 自己的函式]。或者點名，可以混著放：
    - app 的工具名稱："generate_image"、"web_search"、"fetch_url"，或技能工具的名稱（例如 Civitai Helper
      的 "civitai_list_local_models"）——由 app 執行，生圖進度、搜尋來源照樣出現在執行紀錄
    - Python 函式（要有型別註記；docstring 第一行當說明）或 LangChain 工具——在工作流裡執行
    skill：技能 slug（逗號分隔多個，或 "__auto__"）——跟聊天選技能一樣把 SKILL.md 放進 system，
    並提供該技能的全部工具（tools=False 只放說明、不給工具）。
    exclude_tools：不給模型的工具名稱。read_only=True：只給查資料的工具（MCP 標了 readOnlyHint 的、
    搜尋、PNG Info、tools.json 標了 read_only 的；點名的與自己的函式照給）——例如只該查 LoRA、不該生圖的步驟。
    details=True 回 {"text", "calls": [{"name", "args", "result", "images"}], "images": [生成的圖網址]}。"""
    msgs, sys_from_msgs = _messages(messages)
    if prompt:
        msgs.append({"role": "user", "content": str(prompt)})
    if not msgs:
        raise ValueError("webui_app.chat 需要 prompt 或 messages")
    extra = [i.get("url") if isinstance(i, dict) else i for i in (images or [])]
    extra = [str(i) for i in extra if i]
    if extra:
        last = next((m for m in reversed(msgs) if m["role"] == "user"), None)
        if last is None:
            last = {"role": "user", "content": ""}
            msgs.append(last)
        last["images"] = [*(last.get("images") or []), *extra]
    system = "\n\n".join(s for s in (system, sys_from_msgs) if s) or None
    base = {"system": system, "engine": engine, "model": model, "think": think, "skill": skill}
    schemas, local = ([], {}) if tools is False else _tool_specs(tools, skill, exclude_tools, read_only)
    calls: list[dict[str, Any]] = []
    if not schemas:
        text = str(_call("chat", {"messages": msgs, **base}) or "")
        return {"text": text, "calls": calls, "images": []} if details else text
    if _cli_engine(engine):
        # Claude CLI / Codex：掛上 webui 的 MCP 閘道，CLI 自己呼叫工具到回答為止；
        # 工作流裡的函式由閘道轉回來執行（_serve_local）
        aid = f"{threading.get_ident()}-{next(_ids)}"
        _agents[aid] = {"tools": local, "node": _current_node()}
        items, auto = _tool_list(tools)
        try:
            res = _call("chat_agent", {
                "messages": msgs, **base, "agent": aid, "auto": auto, "exclude": list(exclude_tools or []),
                "read_only": read_only,
                "names": [n for n in items if isinstance(n, str)],
                "local_tools": [s for s in schemas if s["function"]["name"] in local],
            }) or {}
        finally:
            _agents.pop(aid, None)
        text = str(res.get("text") or "")
        return {"text": text, "calls": res.get("calls") or [], "images": res.get("images") or []} if details else text
    seen: set[str] = set()
    auto_tools = _tool_list(tools)[1]
    text = ""
    for _ in range(max(1, max_rounds)):
        turn = _call("chat_turn", {"messages": msgs, "tools": schemas, **base}) or {}
        wanted = turn.get("tool_calls") or []
        text = str(turn.get("content") or "")
        if not wanted:
            break
        msgs.append({"role": "assistant", "content": text, "tool_calls": wanted})
        for call in wanted:
            key = call["name"] + json.dumps(call.get("args") or {}, sort_keys=True, ensure_ascii=False)
            if key in seen:  # 同樣的呼叫做過了：不重跑，請模型用之前的結果
                result = {"text": "(Same call as before — use the earlier result.)"}
            else:
                seen.add(key)
                result = _invoke_tool(call, local, skill, auto_tools, exclude_tools, read_only)
            msgs.append({"role": "tool", "name": call["name"], "tool_call_id": call["id"],
                         "content": result.get("text") or "",
                         **({"images": result["vision"]} if result.get("vision") else {})})
            calls.append({"name": call["name"], "args": call.get("args") or {},
                          "result": result.get("text") or "", "images": result.get("images") or []})
    else:  # 輪數用完：不給工具，請它就現有的結果回答
        text = str((_call("chat_turn", {"messages": msgs, "tools": [], **base}) or {}).get("content") or "")
    if details:
        return {"text": text, "calls": calls, "images": [u for c in calls for u in c["images"]]}
    return text


async def achat(*args: Any, **kwargs: Any) -> str:
    return await asyncio.to_thread(chat, *args, **kwargs)


def generate_image(
    prompt: str,
    *,
    negative_prompt: str | None = None,
    width: int | None = None,
    height: int | None = None,
    seed: int | None = None,
    steps: int | None = None,
    cfg_scale: float | None = None,
    checkpoint: str | None = None,
) -> dict[str, Any]:
    """用 app 的 A1111 生一張圖（套用 app 的生圖設定，給的參數優先）。回 {"url", "info", "params"}。"""
    args = {"prompt": prompt, "negative_prompt": negative_prompt, "width": width, "height": height,
            "seed": seed, "steps": steps, "cfg_scale": cfg_scale, "checkpoint": checkpoint}
    return _call("generate_image", {k: v for k, v in args.items() if v is not None})


async def agenerate_image(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return await asyncio.to_thread(generate_image, *args, **kwargs)


def web_search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """app 的網頁搜尋：[{"title", "url", "snippet"}]。"""
    return _call("web_search", {"query": query, "max_results": max_results}) or []


async def aweb_search(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    return await asyncio.to_thread(web_search, *args, **kwargs)


def list_checkpoints() -> dict[str, Any]:
    """A1111 的 checkpoint：{"current": 目前載入的名稱, "checkpoints": [{"name", "title", "base"}]}。
    base 是底模（Illustrious / NoobAI / Pony / SDXL / SD 1.5 / Flux / Anima …，Civitai Helper 的記錄優先，
    沒有就看檔名；猜不到是空字串）。name 可以直接給 generate_image(checkpoint=…)。"""
    return _call("list_checkpoints", {}) or {"current": "", "checkpoints": []}


async def alist_checkpoints() -> dict[str, Any]:
    return await asyncio.to_thread(list_checkpoints)


def app_tools(names: Any = None, *, skill: str | None = None) -> list[Any]:
    """app 的工具（名稱）、技能的工具與 A1111 / Civitai Helper MCP 的工具 → LangChain 工具，給
    ToolNode / create_react_agent 用。names="auto"＝全部（給模型自己挑）：

        tools = webui_app.app_tools("auto")
        agent = create_react_agent(webui_app.get_chat_model().bind_tools(tools), tools)
    """
    from langchain_core.tools import StructuredTool

    items, auto = _tool_list(names)

    def make(name: str) -> Any:
        def run(**kwargs: Any) -> str:
            return str(_invoke_tool({"name": name, "args": kwargs}, {}, skill, auto).get("text") or "")

        return run

    out = []
    for s in _call("tool_schemas", {"names": [n for n in items if isinstance(n, str)], "skill": skill,
                                    "auto": auto}) or []:
        fn = s["function"]
        out.append(StructuredTool.from_function(
            func=make(fn["name"]), name=fn["name"], description=fn.get("description") or fn["name"],
            args_schema=fn.get("parameters") or {"type": "object", "properties": {}}))
    return out


def ask(title: str, fields: list[dict[str, Any]] | None = None, *, message: str = "",
        images: list[Any] | None = None) -> Any:
    """暫停工作流，在工作流頁面顯示一張表單請人填，回 {欄位 name: 值}（沒有 fields 時回一段文字）。

    fields 的每一項：{"name", "label", "type", "options", "default", "required", "placeholder", "help"}
    - type：text（一行）、textarea（多行）、select（下拉選單）、choice（一排按鈕選一個）、checkbox
    - options（select / choice）：字串，或 {"value": 任何 JSON 值, "label": 顯示文字}
    message 用 Markdown 顯示在表單上方；images 可放 generate_image 的結果或 /images/… 網址。

    底層是 LangGraph 的 interrupt()：app 執行時會自動加 checkpointer。回覆後「整個節點從頭重跑」，
    ask 才回傳值——所以同一個節點裡 ask 之前不要做花時間或有副作用的事（放到前一個節點）。
    從聊天 /workflow 執行時沒辦法填表，工作流會停在這裡並提示到工作流頁面執行。"""
    from langgraph.types import interrupt

    norm = [i.get("url") if isinstance(i, dict) else i for i in (images or [])]
    return interrupt({"kind": "webui_form", "title": title, "message": message,
                      "images": [str(i) for i in norm if i], "fields": fields or []})


def emit(message: Any) -> None:
    """在執行紀錄顯示一行（字串，或可轉 JSON 的資料）。"""
    _send({"type": "note", "node": _current_node(),
           "text": message if isinstance(message, str) else json.dumps(message, ensure_ascii=False)})


_chat_model_cls: Any = None


def get_chat_model(*, engine: str | None = None, model: str | None = None,
                   think: bool | None = None) -> Any:
    """LangChain chat model：llm.invoke(messages) 走 app 的引擎。

    bind_tools(tools) 之後回的 AIMessage 帶 tool_calls（不會自己執行），可以接 LangGraph 的
    ToolNode / tools_condition / create_react_agent。tools 可放 Python 函式、LangChain 工具，
    或 app_tools() 給的 app / 技能工具。"""
    global _chat_model_cls
    if _chat_model_cls is None:
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult

        class ChatWebUI(BaseChatModel):
            engine: str | None = None
            model_name: str | None = None
            think: bool | None = None

            @property
            def _llm_type(self) -> str:
                return "webui-app"

            def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any) -> Any:
                schemas, _local = _tool_specs([t for t in tools if not isinstance(t, dict)], None)
                return self.bind(tools=schemas + [t for t in tools if isinstance(t, dict)], **kwargs)

            def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None,
                          tools: Any = None, **kwargs: Any) -> Any:
                if not tools:
                    text = chat(messages=messages, engine=self.engine, model=self.model_name,
                                think=self.think)
                    return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])
                msgs, system = _messages(messages)
                turn = _call("chat_turn", {"messages": msgs, "system": system or None, "tools": tools,
                                           "engine": self.engine, "model": self.model_name,
                                           "think": self.think}) or {}
                calls = [{"name": c["name"], "args": c.get("args") or {}, "id": c["id"], "type": "tool_call"}
                         for c in turn.get("tool_calls") or []]
                message = AIMessage(content=str(turn.get("content") or ""), tool_calls=calls)
                return ChatResult(generations=[ChatGeneration(message=message)])

        _chat_model_cls = ChatWebUI
    return _chat_model_cls(engine=engine, model_name=model, think=think)

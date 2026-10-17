"""執行 LangGraph 工作流：在專案的 venv 裡跑 langgraph_runtime/runner.py，把它的事件轉成 SSE。

執行器的 stdout 只送 JSON 事件；其中 {"type": "call"} 是工作流裡 webui_app 的呼叫
（chat / generate_image / web_search），由這裡用 app 自己的引擎、A1111 與搜尋處理，
結果寫回執行器的 stdin。所以專案不需要任何 API key（Strata 的 key 不會進到子程序）。

事件（給前端）：run / start / task（節點開始）/ node（節點完成）/ token / custom / note / log /
stderr / llm / llm_done / progress / image / sources / interrupt（等人回覆）/ resume / ping / done / error。

interrupt（webui_app.ask）：執行器停下來等，SSE 保持連線（定時送 ping），工作流頁面用
resume(run_id, value) 把回覆寫進執行器的 stdin；等待的時間不算在 LANGGRAPH_RUN_TIMEOUT 裡。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

import a1111_client
import chat as chat_mod
import claude_client
import codex_client
import langgraph_history as history
import langgraph_store as store
import ollama_client
import settings_store
import skills_store
import strata_client
import tool_gateway
import tools as tools_mod
import web_tools
from config import LANGGRAPH_RUN_TIMEOUT
from errors import describe

log = logging.getLogger(__name__)

RUNTIME_DIR = Path(__file__).parent / "langgraph_runtime"
ENGINES = ("ollama", "claude_cli", "codex", "strata")
_LINE_LIMIT = 64 * 1024 * 1024  # 最終輸出可能很大
INPUT_TIMEOUT = 12 * 3600  # interrupt 最多等人回覆多久
PING_EVERY = 20  # 等回覆時多久送一次 ping，免得閒置的 SSE 被 proxy 切斷
# 執行中的工作流：{run_id: {"proc", "waiting": 開始等回覆的時間或 None, "paused": 已經等了幾秒}}
_runs: dict[str, dict[str, Any]] = {}


def _redact(value: Any, secrets: list[str]) -> Any:
    if not secrets:
        return value
    if isinstance(value, str):
        for s in secrets:
            value = value.replace(s, "***")
        return value
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    return value


def _require_enabled() -> None:
    if not settings_store.get_langgraph_enabled():
        raise PermissionError("LangGraph 工作流的執行還沒開啟（工作流頁面上方的開關）")


def _prepare(slug: str) -> tuple[Path, dict[str, Any], dict[str, str], list[str]]:
    """專案資料夾、設定、子程序環境、要在輸出遮罩的值。"""
    _require_enabled()
    pdir = store.project_dir(slug)
    cfg = store.read_config(pdir)
    status = store.venv_status(slug, pdir, cfg)
    if status["state"] in ("missing", "installing"):
        raise ValueError("這個專案還沒安裝依賴：請先在工作流頁面按「安裝依賴」")
    env = store._proc_env(slug)
    values = store.env_values(pdir, cfg)
    env.update(values)
    env["PYTHONPATH"] = os.pathsep.join([str(RUNTIME_DIR), str(pdir)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    secrets = [v for v in values.values() if len(v) >= 6]
    return pdir, cfg, env, secrets


async def _spawn(slug: str, pdir: Path, env: dict[str, str], job: dict[str, Any]) -> asyncio.subprocess.Process:
    proc = await asyncio.create_subprocess_exec(
        str(store.venv_python(slug)), "-u", str(RUNTIME_DIR / "runner.py"),
        cwd=str(pdir), env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        limit=_LINE_LIMIT, start_new_session=True,
    )
    assert proc.stdin is not None
    proc.stdin.write((json.dumps(job, ensure_ascii=False) + "\n").encode())
    await proc.stdin.drain()
    return proc


async def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, 9)  # 連同使用者程式開的子程序
        with contextlib.suppress(Exception):
            await proc.wait()


# ---------------- 檢視圖 ----------------

_INSPECT_CALLS = {"tool_schemas", "list_checkpoints"}  # 載入圖時也可以呼叫的 webui_app 函式（唯讀）


async def _ignore(_ev: dict[str, Any]) -> None:
    pass

async def inspect(slug: str, timeout: float = 120) -> dict[str, Any]:
    """載入每個 graph：輸入 / 輸出 schema、節點、邊、mermaid；載入失敗的附錯誤訊息。"""
    pdir, cfg, env, secrets = _prepare(slug)
    job = {"mode": "inspect", "project_dir": str(pdir), "graphs": cfg["graphs"],
           "extra_paths": store.extra_paths(slug)}
    proc = await _spawn(slug, pdir, env, job)
    events: list[dict[str, Any]] = []

    async def read() -> bytes:
        assert proc.stderr is not None
        err = (await asyncio.gather(pump(), proc.stderr.read()))[1]  # stderr 同時讀，免得塞住
        await proc.wait()
        return err

    async def pump() -> None:
        # 模組層級的 webui_app 呼叫（例如 tools = webui_app.app_tools([...])）：唯讀的照常回答
        assert proc.stdout is not None and proc.stdin is not None
        async for raw in proc.stdout:
            with contextlib.suppress(ValueError):
                msg = json.loads(raw)
                if msg.get("type") != "call":
                    events.append(msg)
                    continue
                try:
                    if msg.get("fn") not in _INSPECT_CALLS:
                        raise ValueError(f"webui_app.{msg.get('fn')} 只能在節點裡（執行時）呼叫")
                    reply = {"id": msg.get("id"), "result": await _bridge(
                        str(msg["fn"]), msg.get("args") or {}, "", {"engine": "ollama", "model": ""}, _ignore)}
                except Exception as e:
                    reply = {"id": msg.get("id"), "error": describe(e)}
                proc.stdin.write((json.dumps(reply, ensure_ascii=False) + "\n").encode())
                await proc.stdin.drain()

    try:
        err = await asyncio.wait_for(read(), timeout=timeout)
    except asyncio.TimeoutError:
        await _kill(proc)
        raise TimeoutError(f"載入圖超過 {timeout:.0f} 秒") from None
    result: dict[str, Any] | None = None
    for ev in events:
        if ev.get("type") == "inspect":
            result = ev["graphs"]
        elif ev.get("type") == "error":
            raise RuntimeError(ev.get("message") or "載入失敗")
    if result is None:
        tail = err.decode("utf-8", "replace").strip()[-2000:]
        raise RuntimeError(f"載入圖失敗：{tail or f'exit {proc.returncode}'}")
    for gid, why in cfg["unsupported"].items():
        result[gid] = {"spec": "", "error": why}
    return _redact(result, secrets)


# ---------------- webui_app 的呼叫 ----------------

def _image_b64(src: str, max_side: int = 1024) -> str:
    """/images/xxx.png、data URL 或 base64 → 給模型看的 base64（大圖縮小、轉 JPEG）。"""
    src = (src or "").strip()
    if src.startswith("/images/") or src.startswith("images/"):
        b64 = chat_mod._load_generated(src)
        if not b64:
            raise ValueError(f"找不到圖片 {src}")
    elif src.startswith("data:"):
        b64 = src.split(",", 1)[-1]
    elif src.startswith(("http://", "https://")):
        raise ValueError("只接受 app 生成的圖（/images/…）、data URL 或 base64，不抓外部網址")
    else:
        b64 = src
    return chat_mod.vision_copy(b64, max_side)


async def _vision_ok(engine: str, model: str) -> bool:
    if engine in ("claude_cli", "codex"):
        return True
    llm = strata_client if engine == "strata" else ollama_client
    with contextlib.suppress(Exception):
        return bool(await llm.model_supports_vision(model))
    return False


async def llm_once(engine: str, model: str, messages: list[dict[str, Any]], system: str | None,
                   *, num_ctx: int | None, think: bool | None, effort: str | None) -> str:
    if engine == "claude_cli":
        return await claude_client.chat_once(model, messages, system or "")
    if engine == "codex":
        return await codex_client.chat_once(model, messages, system or "")
    if engine == "strata":
        return await strata_client.chat_once(model, messages, system, think=think, effort=effort)
    convo = ([{"role": "system", "content": system}] if system else []) + messages
    return await ollama_client.chat_once(model, convo, num_ctx, think=think)


# ---------------- 工具呼叫（webui_app.chat 的 tools / skill） ----------------
# Ollama / Strata：工作流端（webui_app.chat）跑「LLM ↔ 工具」的迴圈，這裡負責一回合的 LLM（chat_turn，
# 回文字與要呼叫的工具，不執行）和經 MCP 閘道執行工具（call_tool）。
# Claude CLI / Codex：chat_agent 掛上 MCP 閘道，CLI 自己呼叫工具（原生 MCP）。只有單回合的 chat_turn
# （LangChain 的 bind_tools 要拿回 tool_calls、不能讓 CLI 自己執行）和不支援 tools 的 Ollama 模型
# 才用 [[CALL]] 文字標記。

_CALL_RE = re.compile(r"\[\[CALL\]\](.*?)\[\[/CALL\]\]", re.S)


def _engine_model(args: dict[str, Any], opts: dict[str, Any]) -> tuple[str, str]:
    engine = args.get("engine") or opts["engine"]
    if engine not in ENGINES:
        raise ValueError(f"不認得的引擎 {engine}（可用：{', '.join(ENGINES)}）")
    model = args.get("model") or (opts["model"] if engine == opts["engine"] else "")
    if not model:
        raise ValueError(f"用 {engine} 時要指定 model")
    return engine, model


def _with_skill(system: str | None, skill: str | None) -> str | None:
    """skill（技能 slug、逗號分隔或 "__auto__"）的 SKILL.md 接在 system 前面，跟聊天選技能一樣。"""
    if not skill:
        return system
    if skill != skills_store.AUTO:
        missing = [s for s in str(skill).split(",") if s.strip() and not skills_store.get_skill(s.strip())]
        if missing:
            raise ValueError(f"找不到技能：{'、'.join(missing)}")
    text = skills_store.build_auto_prompt() if skill == skills_store.AUTO else skills_store.build_prompt(skill)
    return "\n\n".join(s for s in (text, system) if s) or None


def _tool_ctx(names: list[str], skill: str | None, opts: dict[str, Any], auto: bool = False,
              exclude: list[str] | None = None, read_only: bool = False) -> tool_gateway.ToolContext:
    """工作流的工具情境：點名的工具＋技能的工具（auto：全部的 MCP 工具給模型挑），生圖套用這次執行的生圖設定。"""
    if skill and skill != skills_store.AUTO:
        _with_skill(None, skill)  # 技能不存在就報錯
    return tool_gateway.ToolContext(names=[str(n) for n in names], skill=skill or None, auto=bool(auto),
                                    exclude=[str(n) for n in exclude or []], read_only=bool(read_only),
                                    image_settings=opts.get("image_settings"))


async def tool_schemas(names: list[str], skill: str | None, opts: dict[str, Any] | None = None,
                       auto: bool = False, exclude: list[str] | None = None,
                       read_only: bool = False) -> list[dict[str, Any]]:
    """工具名稱（內建、技能、或 A1111 / Civitai Helper MCP 的工具）＋ skill 的全部工具
    （auto：全部）→ function schema（經閘道的 tools/list）。"""
    return await tool_gateway.schemas(_tool_ctx(names, skill, opts or {}, auto, exclude, read_only))


async def _call_app_tool(args: dict[str, Any], opts: dict[str, Any], node: str, emit: Any) -> dict[str, Any]:
    """經 MCP 閘道執行 app 端的工具（跟聊天同一套）：生圖進度、搜尋來源等事件照樣顯示在執行紀錄。
    回 {"text": 給模型的結果, "images": 生成的圖網址, "vision": 給視覺模型看的圖（base64）}。"""
    name = str(args.get("name") or "")
    targs = args.get("args") if isinstance(args.get("args"), dict) else {}
    ctx = _tool_ctx([name], args.get("skill"), opts, args.get("auto"), args.get("exclude"), args.get("read_only"))
    text, images, vision = "", [], []
    async for item in tool_gateway.run(ctx, name, targs):
        if isinstance(item, str):
            text = item
        elif item.get("type") == "_tool_result":
            text, vision = str(item.get("content") or ""), list(item.get("images") or [])
        else:
            if item.get("type") == "image" and item.get("url"):
                images.append(item["url"])
            await emit({**item, "node": node})
    return {"text": text, "images": images, "vision": vision}


async def _prepare_messages(engine: str, model: str, messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """工作流送來的訊息：圖片轉成給模型看的 base64。使用者給的圖模型看不到就報錯；
    工具結果附的圖（例如剛生成的）看不到就略過。"""
    msgs = [dict(m) for m in messages or []]
    n_images = sum(len(m.get("images") or []) for m in msgs if m.get("role") != "tool")
    can_see = await _vision_ok(engine, model) if any(m.get("images") for m in msgs) else False
    if n_images and not can_see:
        raise ValueError(f"{model} 看不到圖片（不是視覺模型），請換一個有視覺能力的模型")
    for m in msgs:
        if m.get("images"):
            m["images"] = [_image_b64(str(i)) for i in m["images"]] if can_see else []
            if not m["images"]:
                m.pop("images")
    return msgs, n_images


def _native(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """→ Ollama 格式（Strata 再由 strata_client 轉成 OpenAI 格式）。"""
    out = []
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": [
                {"id": c.get("id"), "function": {"name": c.get("name"), "arguments": c.get("args") or {}}}
                for c in m["tool_calls"]]})
        elif role == "tool":
            out.append({"role": "tool", "content": str(m.get("content") or ""),
                        **({"tool_name": m["name"]} if m.get("name") else {}),
                        **({"images": m["images"]} if m.get("images") else {})})
        else:
            out.append({k: v for k, v in m.items() if k in ("role", "content", "images")})
    return out


def _flat(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """→ 只有 user / assistant 的對話（Claude CLI / Codex、不支援 tools 的模型）：
    工具呼叫寫回 [[CALL]] 標記，工具結果變成下一則 user 訊息（跟聊天一樣）。"""
    out: list[dict[str, Any]] = []
    results: list[str] = []

    def flush() -> None:
        if results:
            out.append({"role": "user", "content": chat_mod._tool_results_message(results)})
            results.clear()

    for m in messages:
        role = m.get("role")
        if role == "tool":
            results.append(f"[{m.get('name') or 'tool'}]\n{m.get('content') or ''}")
            continue
        flush()
        if role == "assistant":
            calls = "".join(
                "\n[[CALL]]" + json.dumps({"tool": c.get("name"), "args": c.get("args") or {}}, ensure_ascii=False)
                + "[[/CALL]]" for c in m.get("tool_calls") or [])
            out.append({"role": "assistant", "content": ((m.get("content") or "") + calls).strip()})
        elif role == "user":
            out.append({k: v for k, v in m.items() if k in ("role", "content", "images")})
    flush()
    return out


def _directive_tools(schemas: list[dict[str, Any]]) -> str:
    lines = [
        "# Tools",
        "You can call tools. To call one, print this marker on its own line and stop — the app runs "
        "the tool and sends you the result in the next message:",
        '[[CALL]]{"tool": "<tool name>", "args": {<arguments as JSON>}}[[/CALL]]',
        "Rules: at most ONE [[CALL]] marker per reply; never put it in a code fence; never invent "
        "tool results. When you have everything you need, give your final answer without any marker.",
        "Available tools:",
    ]
    for s in schemas:
        fn = s.get("function") or {}
        params = fn.get("parameters") or {}
        required = set(params.get("required") or [])
        args = ", ".join(
            f"{k}{'*' if k in required else ''}: {(v or {}).get('type', 'any')}"
            + (f" — {(v or {}).get('description')}" if (v or {}).get("description") else "")
            for k, v in (params.get("properties") or {}).items())
        lines.append(f"- {fn.get('name')}: {fn.get('description') or ''}" + (f" Args: {args}" if args else ""))
    lines.append("(* = required argument)")
    return "\n".join(lines)


def _parse_directives(text: str) -> tuple[str, list[dict[str, Any]]]:
    calls = []
    for raw in _CALL_RE.findall(text or ""):
        with contextlib.suppress(ValueError):
            d = json.loads(raw)
            if isinstance(d, dict) and d.get("tool"):
                calls.append({"name": str(d["tool"]), "args": d.get("args") if isinstance(d.get("args"), dict) else {}})
    return _CALL_RE.sub("", text or "").strip(), calls


def _args_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            value = json.loads(value)
    return value if isinstance(value, dict) else {}


async def chat_turn(args: dict[str, Any], opts: dict[str, Any], node: str, emit: Any) -> dict[str, Any]:
    """一回合 LLM：回 {"content", "tool_calls": [{"id", "name", "args"}]}（工具由工作流端執行）。
    沒給 tools 就是一般的回答（訊息裡可以有之前的工具呼叫與結果）。"""
    engine, model = _engine_model(args, opts)
    messages, n_images = await _prepare_messages(engine, model, args.get("messages") or [])
    system = _with_skill(args.get("system"), args.get("skill"))
    tools = [t for t in args.get("tools") or [] if isinstance(t, dict)]
    think = opts.get("think") if args.get("think") is None else args.get("think")
    llm = strata_client if engine == "strata" else ollama_client
    native = engine in ("ollama", "strata") and (not tools or await llm.model_supports_tools(model))
    await emit({"type": "llm", "node": node, "engine": engine, "model": model, "images": n_images,
                **({"tools": len(tools)} if tools else {})})
    started = time.monotonic()
    calls: list[dict[str, Any]] = []
    if native and tools:
        if engine == "strata":
            think = strata_client.reasoning_effort(think, opts.get("effort"))
        convo = ([{"role": "system", "content": system}] if system else []) + _native(messages)
        content, raw_calls = "", []
        async for chunk in llm.chat_stream(model, convo, tools=tools, think=think, num_ctx=opts.get("num_ctx")):
            if chunk.get("error"):
                raise RuntimeError(str(chunk["error"]))
            msg = chunk.get("message") or {}
            content += msg.get("content") or ""
            raw_calls += msg.get("tool_calls") or []
        names = tuple((t.get("function") or {}).get("name") or "" for t in tools)
        # 模型把呼叫印在文字裡（沒有正式 tool call）時撿回來，跟聊天一樣
        raw_calls = raw_calls or chat_mod._salvage_tool_calls(content, names)
        for c in raw_calls:
            fn = c.get("function") or {}
            calls.append({"id": c.get("id"), "name": fn.get("name") or "", "args": _args_dict(fn.get("arguments"))})
    else:
        if tools:  # 用 [[CALL]] 標記
            system = "\n\n".join(s for s in (system, _directive_tools(tools)) if s)
        convo = _native(messages) if native else _flat(messages)
        text = await llm_once(engine, model, convo, system, num_ctx=opts.get("num_ctx"), think=think,
                              effort=opts.get("effort"))
        content, calls = _parse_directives(text) if tools else (text, [])
    for i, c in enumerate(calls):
        c["id"] = c.get("id") or f"call_{uuid.uuid4().hex[:8]}_{i}"
    await emit({"type": "llm_done", "node": node, "chars": len(content),
                "seconds": round(time.monotonic() - started, 1), "preview": content[:300],
                **({"tool_calls": [c["name"] for c in calls]} if calls else {})})
    return {"content": content, "tool_calls": calls}


async def chat_agent(args: dict[str, Any], opts: dict[str, Any], node: str, emit: Any,
                     local_call: Any = None) -> dict[str, Any]:
    """Claude CLI / Codex 帶工具的對話：掛上 webui 的 MCP 閘道，由 CLI 自己呼叫工具到回答為止。
    工具＝點名的 app / 技能工具＋工作流裡的 Python 函式（local_tools，經 local_call 轉回工作流執行）。
    回 {"text", "calls": [{"name", "args"}], "images": [生成的圖網址]}。"""
    import chat as chat_mod

    engine, model = _engine_model(args, opts)
    if engine not in ("claude_cli", "codex"):
        raise ValueError("chat_agent 只給 Claude CLI / Codex 用")
    messages, n_images = await _prepare_messages(engine, model, args.get("messages") or [])
    calls: list[dict[str, Any]] = []
    images: list[str] = []

    async def on_event(ev: dict[str, Any]) -> None:
        if ev.get("type") == "tool_call":
            calls.append({"name": ev.get("name"), "args": ev.get("args") or {}})
        elif ev.get("type") == "image" and ev.get("url"):
            images.append(ev["url"])
        await emit({**ev, "node": node})

    ctx = _tool_ctx(args.get("names") or [], args.get("skill"), opts, args.get("auto"), args.get("exclude"),
                    args.get("read_only"))
    ctx.emit = on_event
    ctx.local_tools = {t["function"]["name"]: t for t in args.get("local_tools") or []
                       if isinstance(t, dict) and t.get("function")}

    async def run_local(name: str, targs: dict[str, Any]) -> str:
        calls.append({"name": name, "args": targs})
        if local_call is None:
            raise ValueError(f"{name} 只能在工作流執行中呼叫")
        return await local_call(args.get("agent") or "", name, targs)

    ctx.call_local = run_local
    names = [t["function"]["name"] for t in await tool_gateway.schemas(ctx)]
    system = (_with_skill(args.get("system"), args.get("skill")) or "") + chat_mod._mcp_instructions(names)
    think = opts.get("think") if args.get("think") is None else args.get("think")
    token = tool_gateway.open_session(ctx)
    url = tool_gateway.session_url(token)
    await emit({"type": "llm", "node": node, "engine": engine, "model": model, "images": n_images,
                "tools": len(names)})
    started = time.monotonic()
    client = claude_client if engine == "claude_cli" else codex_client
    stream = client.chat_stream(model, _flat(messages), system, think=bool(think), effort=opts.get("effort"),
                                mcp_url=url)
    text = ""
    try:
        async for ev in stream:
            if ev.get("type") == "error":
                raise RuntimeError(ev.get("message") or f"{engine} 失敗")
            if ev.get("type") == "text":
                text += ev.get("delta") or ""
    finally:
        await stream.aclose()
        tool_gateway.close_session(token)
    text = text.strip()
    await emit({"type": "llm_done", "node": node, "chars": len(text),
                "seconds": round(time.monotonic() - started, 1), "preview": text[:300],
                **({"tool_calls": [c["name"] for c in calls]} if calls else {})})
    return {"text": text, "calls": calls, "images": images}


async def _bridge(fn: str, args: dict[str, Any], node: str, opts: dict[str, Any], emit: Any,
                  local_call: Any = None) -> Any:
    if fn == "chat_agent":
        return await chat_agent(args, opts, node, emit, local_call)
    if fn == "chat":
        return (await chat_turn({**args, "tools": []}, opts, node, emit))["content"]
    if fn == "chat_turn":
        return await chat_turn(args, opts, node, emit)
    if fn == "tool_schemas":
        return await tool_schemas([str(n) for n in args.get("names") or []], args.get("skill"), opts,
                                  args.get("auto"), args.get("exclude"), args.get("read_only"))
    if fn == "call_tool":
        return await _call_app_tool(args, opts, node, emit)
    if fn == "generate_image":
        call_args = {k: args[k] for k in ("prompt", "negative_prompt", "width", "height") if args.get(k)}
        _kind, kwargs = tools_mod.build_call("generate_image", call_args, opts.get("image_settings"), None)
        for key, target in (("seed", "seed"), ("steps", "steps"), ("cfg_scale", "cfg_scale"),
                            ("checkpoint", "sd_model_checkpoint")):
            if args.get(key) is not None:
                kwargs[target] = args[key]
        result: dict[str, Any] = {}
        async for ev in chat_mod._generate_with_progress("txt2img", kwargs):
            if ev["type"] == "image":
                result = {"url": ev["url"], "info": ev.get("info", ""), "params": ev.get("params")}
            await emit({**ev, "node": node})
        return result
    if fn == "list_checkpoints":
        return await a1111_client.list_checkpoints()
    if fn == "web_search":
        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("web_search 需要 query")
        results = await web_tools.web_search(query, int(args.get("max_results") or 5))
        await emit({"type": "sources", "node": node, "query": query, "results": results})
        return results
    raise ValueError(f"webui_app 沒有 {fn}")


# ---------------- 執行 ----------------

async def run(slug: str, graph: str, inp: Any, opts: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """執行一個 graph；逐一 yield 事件（第一個是 {"type": "run", "id"}），並存成執行紀錄。
    opts：engine / model / think / effort / num_ctx / image_settings / recursion_limit / source。"""
    pdir, cfg, env, secrets = _prepare(slug)
    if graph not in cfg["graphs"]:
        raise ValueError(cfg["unsupported"].get(graph) or f"langgraph.json 沒有 graph「{graph}」")
    if opts.get("engine") not in ENGINES:
        raise ValueError(f"不認得的引擎 {opts.get('engine')}")
    run_id = uuid.uuid4().hex[:12]
    interactive = (opts.get("source") or "page") != "chat"  # 聊天裡沒有地方回覆 interrupt
    job = {"mode": "run", "project_dir": str(pdir), "graphs": cfg["graphs"], "graph": graph,
           "input": inp, "engine": opts["engine"], "model": opts.get("model"),
           "recursion_limit": opts.get("recursion_limit"), "extra_paths": store.extra_paths(slug),
           "run_id": run_id, "interactive": interactive}
    proc = await _spawn(slug, pdir, env, job)
    live: dict[str, Any] = {"proc": proc, "waiting": None, "paused": 0.0}
    _runs[run_id] = live
    history.start(slug, run_id, graph=graph, input=inp, engine=opts["engine"],
                  model=opts.get("model") or "", source=opts.get("source") or "page")
    seen: list[dict[str, Any]] = []
    outcome: dict[str, Any] = {"status": "stopped"}
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    tasks: set[asyncio.Task[Any]] = set()
    stderr_tail: list[str] = []

    async def emit(ev: dict[str, Any]) -> None:
        await queue.put(_redact(ev, secrets))

    local_waiters: dict[str, asyncio.Future] = {}

    async def local_call(agent: str, name: str, targs: dict[str, Any]) -> str:
        """CLI 經閘道呼叫工作流裡的 Python 函式：請執行器執行（stdin），等它回 local_tool_result。"""
        lid = uuid.uuid4().hex[:10]
        fut = asyncio.get_running_loop().create_future()
        local_waiters[lid] = fut
        try:
            assert proc.stdin is not None
            proc.stdin.write((json.dumps({"type": "local_tool", "id": lid, "agent": agent, "name": name,
                                          "args": targs}, ensure_ascii=False) + "\n").encode())
            await proc.stdin.drain()
            return str(await fut)
        finally:
            local_waiters.pop(lid, None)

    async def answer(msg: dict[str, Any]) -> None:
        try:
            result = await _bridge(str(msg.get("fn")), msg.get("args") or {}, str(msg.get("node") or ""),
                                   opts, emit, local_call)
            reply = {"id": msg.get("id"), "result": result}
        except Exception as e:  # 回給工作流，讓它自己決定怎麼處理
            log.warning("langgraph %s/%s webui_app.%s failed: %s", slug, graph, msg.get("fn"), e)
            reply = {"id": msg.get("id"), "error": describe(e)}
            await emit({"type": "call_error", "node": msg.get("node") or "", "fn": msg.get("fn"),
                        "message": describe(e)})
        if proc.stdin and not proc.stdin.is_closing():
            with contextlib.suppress(ConnectionError, RuntimeError):
                proc.stdin.write((json.dumps(reply, ensure_ascii=False) + "\n").encode())
                await proc.stdin.drain()

    async def pump_stdout() -> None:
        assert proc.stdout is not None
        async for raw in proc.stdout:
            try:
                msg = json.loads(raw)
            except ValueError:
                await emit({"type": "log", "text": raw.decode("utf-8", "replace").rstrip()[:4000]})
                continue
            if msg.get("type") == "call":
                t = asyncio.create_task(answer(msg))
                tasks.add(t)
                t.add_done_callback(tasks.discard)
            elif msg.get("type") == "local_tool_result":
                fut = local_waiters.get(str(msg.get("id")))
                if fut and not fut.done():
                    fut.set_result(msg.get("text") or "")
            else:
                await emit(msg)

    async def pump_stderr() -> None:
        assert proc.stderr is not None
        async for raw in proc.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            stderr_tail.append(line)
            del stderr_tail[:-40]
            await emit({"type": "stderr", "text": line[:4000]})

    async def watch() -> None:
        await asyncio.gather(pump_stdout(), pump_stderr())
        await proc.wait()
        await queue.put(None)

    watcher = asyncio.create_task(watch())
    deadline = time.monotonic() + LANGGRAPH_RUN_TIMEOUT
    finished = False
    try:
        yield {"type": "run", "id": run_id, "project": slug, "graph": graph,
               "engine": opts["engine"], "model": opts.get("model")}
        while True:
            now = time.monotonic()
            if live["waiting"] is not None:
                left = live["waiting"] + INPUT_TIMEOUT - now
                if left <= 0:
                    yield {"type": "error", "message": f"等待輸入超過 {INPUT_TIMEOUT // 3600} 小時，已停止"}
                    return
            else:
                left = deadline + live["paused"] - now
                if left <= 0:
                    yield {"type": "error", "message": f"執行超過 {LANGGRAPH_RUN_TIMEOUT:.0f} 秒，已停止"}
                    return
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=min(left, PING_EVERY))
            except asyncio.TimeoutError:
                if live["waiting"] is not None:
                    yield {"type": "ping"}
                continue
            if ev is None:
                break
            if ev.get("type") == "interrupt" and "pending" in ev and interactive:
                live["waiting"] = time.monotonic()
            if ev.get("type") in ("done", "error"):
                finished = True
            _note(ev, seen, outcome)
            yield ev
        if not finished:
            code = proc.returncode
            reason = "已取消" if code in (-9, 137) else f"執行器結束（exit {code}）"
            tail = "\n".join(stderr_tail[-15:])
            ev = {"type": "error", "message": reason + (f"\n{tail}" if tail and code not in (-9, 137) else "")}
            _note(ev, seen, outcome)
            yield ev
    finally:
        with contextlib.suppress(Exception):
            history.finish(slug, run_id, events=seen, **outcome)
        _runs.pop(run_id, None)
        await _kill(proc)
        watcher.cancel()
        for t in list(tasks):
            t.cancel()


async def cancel(run_id: str) -> bool:
    live = _runs.get(run_id)
    if not live:
        return False
    await _kill(live["proc"])
    return True


async def resume(run_id: str, value: Any) -> None:
    """回覆正在等的 interrupt（webui_app.ask 的表單）：值原樣交給工作流。"""
    live = _runs.get(run_id)
    if not live:
        raise ValueError("找不到這次執行（可能已經結束）")
    if live["waiting"] is None:
        raise ValueError("這次執行目前沒有在等輸入")
    proc = live["proc"]
    if not proc.stdin or proc.stdin.is_closing():
        raise ValueError("執行器已經結束")
    live["paused"] += time.monotonic() - live["waiting"]
    live["waiting"] = None
    proc.stdin.write((json.dumps({"type": "resume", "value": value}, ensure_ascii=False) + "\n").encode())
    await proc.stdin.drain()


def _note(ev: dict[str, Any], seen: list[dict[str, Any]], outcome: dict[str, Any]) -> None:
    """記下事件給執行紀錄；done / error 決定最後的狀態。"""
    if ev.get("type") == "done":
        outcome.update(status="done", output=ev.get("output"))
    elif ev.get("type") == "error":
        msg = str(ev.get("message") or "")
        outcome.update(status="cancelled" if msg.startswith("已取消") else "error",
                       error=msg, trace=str(ev.get("traceback") or ""))
    if ev.get("type") in ("done", "progress", "ping"):
        return
    last = seen[-1] if seen else None
    if ev.get("type") == "token" and last and last.get("type") == "token" and last.get("node") == ev.get("node"):
        last["text"] = (last.get("text") or "") + (ev.get("text") or "")  # 串流的字併成一段
        return
    seen.append({k: v for k, v in ev.items() if k != "traceback"})


def resolve_target(name: str) -> tuple[str, str]:
    """聊天 /workflow 的名稱：「專案」「專案:圖」或在所有專案裡唯一的圖 id。"""
    name = (name or "").strip()
    projects = store.list_projects()
    if ":" in name:
        slug, graph = name.split(":", 1)
        return slug, graph
    for p in projects:
        if p["slug"] == name:
            if not p.get("graphs"):
                raise ValueError(p.get("error") or f"專案「{name}」沒有可用的圖")
            return name, p["graphs"][0]
    owners = [p["slug"] for p in projects if name in (p.get("graphs") or [])]
    if len(owners) == 1:
        return owners[0], name
    if len(owners) > 1:
        raise ValueError(f"有好幾個專案都有圖「{name}」：{'、'.join(owners)}，請寫成 專案:{name}")
    names = [f"{p['slug']}:{g}" for p in projects for g in p.get("graphs") or []]
    raise ValueError(f"找不到工作流「{name}」。可用：{'、'.join(names) or '（還沒有專案）'}")

"""Agentic 聊天迴圈：串流 ollama、處理工具（生圖 / web 搜尋）、即時進度，輸出 SSE。"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, AsyncIterator

import a1111_client
import claude_client
import codex_client
import ollama_client
import skills_store
import tools as tools_mod
import web_tools
from config import CLAUDE_CONTEXT_LENGTH

MAX_TOOL_ROUNDS = 6  # 防止無限呼叫工具（足夠 搜尋→抓頁→回答 多步）
POLL_INTERVAL = 0.4  # 進度輪詢秒數
IMAGE_TOOLS = ("generate_image", "edit_image")

# ---- 「忘記調用工具」三層防護 ----
# 長對話後模型注意力被稀釋，常把 SD prompt 印成文字而不調用工具。對策：
# 1) 每回合把提醒接在最後一則 user 訊息尾端（模型對結尾注意力最強）
# 2) 偵測「使用者要圖但整輪沒生圖」→ 自動補一輪糾正重試（文字不重複輸出）
# 3) 撿回模型印在文字裡的 tool call 殘骸（qwen 的 <tool_call> / ```json 區塊）

# 生圖意圖偵測（供補救重試判斷；誤判的代價只是多跑一輪安靜的推理）
_IMAGE_INTENT_RE = re.compile(
    r"畫[一個張出幅]|[幫替]我畫|畫個|畫成|重畫|生成|產生|生圖|出圖|繪製|"
    r"[來換再加]一?[張幅]|"
    r"\bdraw\b|\bpaint\b|\bgenerate\b|\bimage of\b|\bpicture of\b|\billustrat|"
    r"\bmake (?:an? )?(?:image|picture|pic)\b",
    re.IGNORECASE,
)


def _wants_image(messages: list[dict[str, Any]]) -> bool:
    """最後一則 user 訊息是否看起來在要求生成／修改圖片。"""
    for m in reversed(messages):
        if m.get("role") == "user":
            return bool(_IMAGE_INTENT_RE.search(m.get("content") or ""))
    return False


def _append_to_last_user(
    messages: list[dict[str, Any]], text: str
) -> list[dict[str, Any]]:
    """複製訊息並把提醒接在最後一則 user 訊息文字尾端。

    不能另開一則訊息：CLI 引擎把「最後一則 user」當本回合輸入（含圖片），
    多加訊息會把使用者的圖片擠進歷史。"""
    msgs = [dict(m) for m in messages]
    for m in reversed(msgs):
        if m.get("role") == "user":
            m["content"] = (m.get("content") or "") + "\n\n" + text
            return msgs
    return msgs


_OLLAMA_TAIL_REMINDER = (
    "(system reminder: If this request needs an image to be created or modified, you "
    "MUST call the generate_image or edit_image tool — never print prompt tags as "
    "plain text and never claim you cannot generate images. If no image is needed, "
    "ignore this reminder and answer normally.)"
)

_OLLAMA_RETRY_NUDGE = (
    "(system reminder) Your previous reply did not call any tool, but the user's "
    "message looks like an image request. If an image is indeed wanted, call the "
    "generate_image tool NOW (or edit_image for the attached image) with "
    "comma-separated English danbooru tags. If no image is actually needed, reply "
    "with an empty message."
)

# ---- 退化式重複偵測 ----
# 模型（尤其本地模型）偶爾會陷入無限重複迴圈（例如自己編 negative prompt 時同一串
# tags 一直循環），燒光 token 也叫不到工具。偵測到就中止這輪串流，讓補救重試接手。
_DEGEN_CHECK_EVERY = 600  # 每累積這麼多新字元檢查一次
_DEGEN_MIN_UNIT = 12      # 重複單元最短長度（避免誤殺正常的短字重複）
_DEGEN_MAX_UNIT = 300
_DEGEN_MIN_SPAN = 480     # 結尾連續重複區段總長超過此值＝退化
_DEGEN_NOTE = "\n[偵測到模型輸出陷入重複迴圈，已中止這輪輸出]\n"


def _looks_degenerate(text: str) -> bool:
    """結尾是否以某個片段（12~300 字元）連續重複了至少 4 次、共 480 字元以上。"""
    tail = text[-2400:]
    n = len(tail)
    for p in range(_DEGEN_MIN_UNIT, min(_DEGEN_MAX_UNIT, n // 4) + 1):
        # 從結尾往回比對週期 p：tail[i] == tail[i+p] 能延伸多長
        i = n - p - 1
        while i >= 0 and tail[i] == tail[i + p]:
            i -= 1
        span = n - 1 - i
        if span >= _DEGEN_MIN_SPAN and span >= 4 * p:
            return True
    return False


class _DegenWatch:
    """累積 thinking+content 串流，週期性檢查是否陷入重複迴圈。"""

    def __init__(self) -> None:
        self.buf = ""
        self.next_check = _DEGEN_CHECK_EVERY

    def feed(self, text: str) -> bool:
        """回傳 True 表示偵測到退化，呼叫端應中止這輪串流。"""
        self.buf += text
        if len(self.buf) < self.next_check:
            return False
        self.next_check = len(self.buf) + _DEGEN_CHECK_EVERY
        return _looks_degenerate(self.buf)


# 模型把 tool call 印在文字裡的常見殘骸格式
_TOOL_CALL_BLOCK_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_SALVAGE_TOOLS = ("generate_image", "edit_image", "web_search", "fetch_url", "read_png_info")


def _salvage_tool_calls(text: str) -> list[dict[str, Any]]:
    """模型沒發出正式 tool call、卻把呼叫 JSON 印在文字裡時，撿回來照常執行。"""
    calls: list[dict[str, Any]] = []
    seen: set[str] = set()
    candidates = _TOOL_CALL_BLOCK_RE.findall(text) + _JSON_FENCE_RE.findall(text)
    for raw in candidates:
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict):
            continue
        if isinstance(d.get("function"), dict):  # 也接受 {"function": {...}} 包一層
            d = d["function"]
        name = d.get("name")
        args = d.get("arguments") or d.get("parameters") or {}
        if name not in _SALVAGE_TOOLS or not isinstance(args, dict):
            continue
        key = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
        if key in seen:
            continue
        seen.add(key)
        calls.append({"function": {"name": name, "arguments": args}})
    return calls


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _oss_level(effort: str | None) -> str:
    """把通用 effort 映射成 gpt-oss 接受的思考等級 low/medium/high。"""
    e = (effort or "").lower()
    if e in ("minimal", "low"):
        return "low"
    if e in ("high", "xhigh", "max"):
        return "high"
    return "medium"


def _inject_skill(
    messages: list[dict[str, Any]], skill: str | None
) -> list[dict[str, Any]]:
    """把選定技能的指示注入 system（接在既有 system prompt 之前）。

    所有引擎都從 system 訊息取 system prompt，所以注入一則 system 即可全引擎通用。
    技能不存在 / 未啟用時原樣回傳。"""
    if not skill:
        return messages
    # "__auto__"＝讓模型自行從所有技能裡判斷要不要用、用哪個
    if skill == "__auto__":
        skill_text = skills_store.build_auto_prompt()
    else:
        skill_text = skills_store.build_prompt(skill)
    if not skill_text:
        return messages
    msgs = [dict(m) for m in messages]
    for m in msgs:
        if m.get("role") == "system":
            m["content"] = skill_text + "\n\n" + (m.get("content") or "")
            return msgs
    return [{"role": "system", "content": skill_text}, *msgs]


def _last_init_image(messages: list[dict[str, Any]]) -> str | None:
    """取最後一則含 images 的 user 訊息的第一張圖，作為 img2img 初始圖。"""
    for m in reversed(messages):
        if m.get("role") == "user":
            imgs = m.get("images")
            if imgs:
                return imgs[0]
    return None


async def _generate_with_progress(
    kind: str, kwargs: dict[str, Any]
) -> AsyncIterator[dict[str, Any]]:
    """執行 txt2img/img2img，期間 yield 進度事件，最後 yield 完成事件。"""
    coro = (
        a1111_client.img2img(**kwargs)
        if kind == "img2img"
        else a1111_client.txt2img(**kwargs)
    )
    task = asyncio.create_task(coro)

    while not task.done():
        await asyncio.sleep(POLL_INTERVAL)
        if task.done():
            break
        try:
            prog = await a1111_client.get_progress()
        except Exception:
            continue
        state = prog.get("state") or {}
        yield {
            "type": "progress",
            "value": prog.get("progress") or 0,
            "step": state.get("sampling_step"),
            "steps": state.get("sampling_steps"),
            "eta": prog.get("eta_relative"),
            "preview": prog.get("current_image") or None,
        }

    result = await task  # 失敗會在此拋出
    yield {
        "type": "image",
        "url": result["url"],
        "params": result["params"],
        "info": result.get("info", ""),  # A1111 完整 geninfo（含實際 seed/model）
    }


def _fmt_search(query: str, results: list[dict]) -> str:
    if not results:
        return f"No web results for '{query}'."
    lines = [f"Web search results for '{query}':"]
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. {r['title']}\n   URL: {r['url']}\n   {r['snippet']}"
        )
    lines.append(
        "Cite the sources you used. Call fetch_url to read a result in full if needed."
    )
    return "\n".join(lines)


async def run_chat(
    model: str,
    messages: list[dict[str, Any]],
    tools_enabled: bool,
    image_settings: dict[str, Any] | None,
    think: bool | None = None,
    web_enabled: bool = False,
    num_ctx: int | None = None,
    image_sources: list[str] | None = None,
    engine: str = "ollama",
    effort: str | None = None,
    skill: str | None = None,
) -> AsyncIterator[str]:
    """主迴圈，yield SSE 字串。

    事件型別：thinking / token / tool_call / progress / image / sources / usage / error / done
    """
    # 啟用技能：把指示注入 system（全引擎通用）
    messages = _inject_skill(messages, skill)

    if engine == "claude_cli":
        async for s in _run_cli_engine(
            claude_client, _claude_ctx(model),
            model, messages, tools_enabled, image_settings, bool(think), effort
        ):
            yield s
        return
    if engine == "codex":
        async for s in _run_codex(
            model, messages, tools_enabled, image_settings, bool(think), effort
        ):
            yield s
        return

    can_tools = await ollama_client.model_supports_tools(model)
    # gpt-oss 支援思考等級：think 開啟時把 effort 映射成 low/medium/high；其他模型維持布林開關
    ollama_think = think
    if think and effort and "gpt-oss" in model.lower():
        ollama_think = _oss_level(effort)
    init_image = _last_init_image(messages)
    # read_png_info 要讀「原圖」metadata；image_sources 是本回合未經縮圖的原始位元組，
    # 沒有時退回 init_image（縮圖後的 JPEG 通常已無 metadata）。
    png_source = (image_sources or [None])[-1] or init_image

    tool_schema: list[dict[str, Any]] = []
    if can_tools and tools_enabled:
        tool_schema += tools_mod.image_tools(bool(init_image))
    if can_tools and web_enabled:
        tool_schema += tools_mod.web_tools_schema()
    tool_schema = tool_schema or None

    convo = [dict(m) for m in messages]
    # 防遺忘 1)：把工具提醒接在最後一則 user 訊息尾端
    if can_tools and tools_enabled:
        convo = _append_to_last_user(convo, _OLLAMA_TAIL_REMINDER)
    # 非 vision 模型若收到 images 會 500，先剝除（img2img 仍可用 init_image）
    if not await ollama_client.model_supports_vision(model):
        for m in convo:
            m.pop("images", None)

    try:
        answered = False
        prompt_tokens = 0
        image_generated = False  # 本回合是否已（嘗試）生圖
        nudged = False           # 防遺忘 2) 的補救重試只做一次
        suppress_text = False    # 補救輪的文字不重複輸出給使用者
        for _round in range(MAX_TOOL_ROUNDS + 1):  # +1：保留給補救輪
            assistant_content = ""
            tool_calls: list[dict[str, Any]] = []
            degen = _DegenWatch()
            degenerated = False

            stream = ollama_client.chat_stream(
                model, convo, tools=tool_schema, think=ollama_think, num_ctx=num_ctx
            )
            async for chunk in stream:
                if chunk.get("error"):
                    yield _sse({"type": "error", "message": str(chunk["error"])})
                    yield _sse({"type": "done"})
                    return
                if chunk.get("prompt_eval_count"):
                    prompt_tokens = chunk["prompt_eval_count"]
                msg = chunk.get("message") or {}
                if msg.get("thinking"):
                    yield _sse({"type": "thinking", "delta": msg["thinking"]})
                    degenerated = degen.feed(msg["thinking"])
                if msg.get("content"):
                    assistant_content += msg["content"]
                    if not suppress_text:
                        yield _sse({"type": "token", "delta": msg["content"]})
                    degenerated = degenerated or degen.feed(msg["content"])
                if msg.get("tool_calls"):
                    tool_calls.extend(msg["tool_calls"])
                if degenerated:
                    # 中止這輪串流（斷線後 ollama 會停止生成）；補救重試接手
                    yield _sse({"type": "thinking", "delta": _DEGEN_NOTE})
                    break
            if degenerated:
                await stream.aclose()  # 確實斷線，讓 ollama 停止生成

            # 防遺忘 3)：沒有正式 tool call 時，撿模型印在文字裡的呼叫殘骸
            if not tool_calls and can_tools and tools_enabled and assistant_content:
                tool_calls = _salvage_tool_calls(assistant_content)

            if not tool_calls:
                # 防遺忘 2)：使用者明顯要圖卻整輪沒生圖 → 補一輪糾正重試
                if (
                    can_tools
                    and tools_enabled
                    and not image_generated
                    and not nudged
                    and _wants_image(messages)
                ):
                    nudged = True
                    suppress_text = True
                    convo.append({"role": "assistant", "content": assistant_content})
                    convo.append({"role": "user", "content": _OLLAMA_RETRY_NUDGE})
                    continue
                answered = True
                break

            suppress_text = False  # 有正常動作了，之後的文字照常輸出
            convo.append(
                {
                    "role": "assistant",
                    "content": assistant_content,
                    "tool_calls": tool_calls,
                }
            )

            for call in tool_calls:
                fn = call.get("function", {})
                name = fn.get("name")
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                if name in IMAGE_TOOLS:
                    image_generated = True

                async for content in _run_tool(
                    name, args, image_settings, init_image, png_source
                ):
                    if isinstance(content, str):
                        convo.append({"role": "tool", "content": content})
                    else:
                        yield _sse(content)

        # 用完輪數仍想呼叫工具 → 最後再不帶工具讓模型用文字收尾（不報錯）
        if not answered:
            async for chunk in ollama_client.chat_stream(
                model, convo, tools=None, think=ollama_think, num_ctx=num_ctx
            ):
                if chunk.get("error"):
                    yield _sse({"type": "error", "message": str(chunk["error"])})
                    break
                if chunk.get("prompt_eval_count"):
                    prompt_tokens = chunk["prompt_eval_count"]
                msg = chunk.get("message") or {}
                if msg.get("thinking"):
                    yield _sse({"type": "thinking", "delta": msg["thinking"]})
                if msg.get("content"):
                    yield _sse({"type": "token", "delta": msg["content"]})

        if prompt_tokens:
            yield _sse({"type": "usage", "prompt_tokens": prompt_tokens, "num_ctx": num_ctx})
        yield _sse({"type": "done"})
    except Exception as e:
        yield _sse({"type": "error", "message": str(e)})
        yield _sse({"type": "done"})


# ===================== CLI 引擎（Claude CLI / OpenAI Codex）=====================
#
# 這些 CLI agent 不開放外部工具給我們，所以「生圖」不走原生 function calling，
# 而是請模型在文字裡輸出一段指令標記（directive），由後端邊串流邊解析出來、
# 跑 A1111、把圖塞回對話。Claude 與 Codex 共用同一條解析路徑。

_OPENERS = {"[[GENIMG]]": "genimg", "[[EDITIMG]]": "editimg"}
_CLOSERS = {"genimg": "[[/GENIMG]]", "editimg": "[[/EDITIMG]]"}


def _safe_emit_len(buf: str, openers: list[str]) -> int:
    """可安全輸出的長度：保留結尾可能是「半個開頭標記」的尾巴，避免漏字或誤判。"""
    maxlen = max(len(o) for o in openers)
    for k in range(min(maxlen - 1, len(buf)), 0, -1):
        tail = buf[-k:]
        if any(o.startswith(tail) for o in openers):
            return len(buf) - k
    return len(buf)


class _DirectiveParser:
    """串流文字解析器：吐出 ('text', str) 或 ('directive', name, json_str)。"""

    def __init__(self) -> None:
        self.buf = ""
        self.capturing: str | None = None

    def feed(self, text: str) -> list[tuple]:
        self.buf += text
        out: list[tuple] = []
        while True:
            if self.capturing is None:
                idx, which, openlen = -1, None, 0
                for opener, name in _OPENERS.items():
                    p = self.buf.find(opener)
                    if p != -1 and (idx == -1 or p < idx):
                        idx, which, openlen = p, name, len(opener)
                if idx == -1:
                    cut = _safe_emit_len(self.buf, list(_OPENERS))
                    if cut > 0:
                        out.append(("text", self.buf[:cut]))
                        self.buf = self.buf[cut:]
                    break
                if idx > 0:
                    out.append(("text", self.buf[:idx]))
                self.buf = self.buf[idx + openlen :]
                self.capturing = which
            else:
                closer = _CLOSERS[self.capturing]
                p = self.buf.find(closer)
                if p == -1:
                    break
                out.append(("directive", self.capturing, self.buf[:p]))
                self.buf = self.buf[p + len(closer) :]
                self.capturing = None
        return out

    def flush(self) -> list[tuple]:
        if self.capturing is None and self.buf:
            text, self.buf = self.buf, ""
            return [("text", text)]
        return []


def _base_system(messages: list[dict[str, Any]]) -> str:
    base_parts = [
        m["content"]
        for m in messages
        if m.get("role") == "system" and m.get("content")
    ]
    return "\n\n".join(base_parts) or (
        "You are a helpful assistant. Reply in the user's language."
    )


def _directive_system(
    messages: list[dict[str, Any]], tools_enabled: bool, has_init_image: bool
) -> str:
    base = _base_system(messages)
    if not tools_enabled:
        return base

    instr = [
        "",
        "# Image generation (IMPORTANT)",
        "You are a chat assistant with NO file system and NO shell. Do NOT run "
        "commands, do NOT create or edit files, do NOT use any tools. You cannot "
        "save an image to disk.",
        "The ONLY way to show the user an image is to print this marker inline in "
        "your reply (the app intercepts it, runs Stable Diffusion / A1111, and "
        "replaces it with the rendered image):",
        '[[GENIMG]]{"prompt": "comma, separated, english, danbooru, tags", '
        '"width": 1024, "height": 1024}[[/GENIMG]]',
        "So whenever the user asks you to draw / paint / create / generate / show "
        "an image, you MUST output that marker. Rules: the prompt MUST be "
        "comma-separated English tags (these are SDXL / Pony / Illustrious anime "
        "models, not full sentences). width/height optional (multiples of 64). Do "
        "NOT include steps/sampler/seed/cfg — the app controls those. USUALLY OMIT "
        "'negative_prompt' — the app already applies a curated negative prompt; "
        "only set it for user-requested specifics, AT MOST 15 short tags, never "
        "repeat a tag.",
        "Write one short natural sentence first, THEN the marker on its own line. "
        "Never explain the marker, never wrap it in code fences, and never claim "
        "you cannot generate images — emitting the marker IS how you generate them.",
    ]
    if has_init_image:
        instr += [
            "To redraw / restyle / edit the image the user just attached, use this "
            "marker instead of GENIMG:",
            '[[EDITIMG]]{"prompt": "desired result as english tags", '
            '"negative_prompt": "optional", "denoising_strength": 0.6}[[/EDITIMG]]',
        ]
    return base + "\n".join(instr)


async def _run_directive(
    name: str,
    payload: str,
    image_settings: dict[str, Any] | None,
    init_image: str | None,
) -> AsyncIterator[dict[str, Any]]:
    try:
        args = json.loads(payload.strip())
        if not isinstance(args, dict):
            raise ValueError("not an object")
    except (json.JSONDecodeError, ValueError):
        yield {"type": "error", "message": "圖片指令解析失敗"}
        return

    tool = "edit_image" if name == "editimg" else "generate_image"
    yield {"type": "tool_call", "name": tool, "args": args}
    try:
        kind, kwargs = tools_mod.build_call(tool, args, image_settings, init_image)
        async for ev in _generate_with_progress(kind, kwargs):
            yield ev
    except Exception as e:
        yield {"type": "error", "message": f"圖片生成失敗：{e}"}


_CLI_TAIL_REMINDER = (
    "(system reminder: If this request needs an image to be created or modified, you "
    "MUST emit the [[GENIMG]]{...}[[/GENIMG]] marker — or [[EDITIMG]] for the attached "
    "image — exactly as instructed in the system prompt. Never print prompt tags "
    "without the marker. If no image is needed, ignore this reminder and answer "
    "normally.)"
)

_CLI_RETRY_PROMPT = (
    "(system reminder) Your previous reply did not emit the [[GENIMG]] marker even "
    "though the user asked for an image. If an image is indeed wanted, output ONLY "
    'the marker now — e.g. [[GENIMG]]{"prompt": "comma, separated, english, tags"}'
    "[[/GENIMG]] (or [[EDITIMG]] for the attached image) — with no other text. "
    "If no image is actually needed, reply with the single word: SKIP."
)


async def _run_cli_engine(
    client,
    ctx_len: int,
    model: str,
    messages: list[dict[str, Any]],
    tools_enabled: bool,
    image_settings: dict[str, Any] | None,
    think: bool,
    effort: str | None = None,
) -> AsyncIterator[str]:
    """通用 CLI 引擎路徑：串流文字 + 解析生圖指令。client 為 claude_client / codex_client。"""
    init_image = _last_init_image(messages)
    system = _directive_system(messages, tools_enabled, bool(init_image))
    parser = _DirectiveParser()
    prompt_tokens = 0
    image_done = False  # 本回合是否出現過生圖指令
    reply_text = ""     # 完整回覆文字（補救重試時當歷史）
    send_messages = (
        _append_to_last_user(messages, _CLI_TAIL_REMINDER)  # 防遺忘 1)
        if tools_enabled
        else messages
    )

    degen = _DegenWatch()

    try:
        stream = client.chat_stream(
            model, send_messages, system, think=think, effort=effort
        )
        try:
            async for ev in stream:
                kind = ev.get("type")
                if kind == "error":
                    yield _sse({"type": "error", "message": ev["message"]})
                    yield _sse({"type": "done"})
                    return
                degenerated = False
                if kind == "usage":
                    prompt_tokens = ev["prompt_tokens"]
                elif kind == "thinking":
                    yield _sse({"type": "thinking", "delta": ev["delta"]})
                    degenerated = degen.feed(ev["delta"])
                elif kind == "text":
                    degenerated = degen.feed(ev["delta"])
                    for item in parser.feed(ev["delta"]):
                        if item[0] == "text":
                            if item[1]:
                                reply_text += item[1]
                                yield _sse({"type": "token", "delta": item[1]})
                        else:
                            image_done = True
                            async for out in _run_directive(
                                item[1], item[2], image_settings, init_image
                            ):
                                yield _sse(out)
                if degenerated:
                    # 模型陷入重複迴圈：中止串流（client 端會 kill 子行程），
                    # 讓下面的補救重試接手
                    yield _sse({"type": "thinking", "delta": _DEGEN_NOTE})
                    break
        finally:
            await stream.aclose()
        for item in parser.flush():
            if item[1]:
                reply_text += item[1]
                yield _sse({"type": "token", "delta": item[1]})

        # 防遺忘 2)：使用者明顯要圖卻沒出現指令 → 補跑一次，只取指令、不重複輸出文字
        if tools_enabled and not image_done and _wants_image(messages):
            retry_messages = [
                *messages,
                {"role": "assistant", "content": reply_text},
                {"role": "user", "content": _CLI_RETRY_PROMPT},
            ]
            retry_parser = _DirectiveParser()
            retry_degen = _DegenWatch()
            try:
                retry_stream = client.chat_stream(
                    model, retry_messages, system, think=False, effort=effort
                )
                try:
                    async for ev in retry_stream:
                        if ev.get("type") != "text":
                            continue  # 補救輪只關心生圖指令；錯誤/思考/用量都忽略
                        if retry_degen.feed(ev["delta"]):
                            break  # 補救輪也退化：直接放棄，別等到逾時
                        for item in retry_parser.feed(ev["delta"]):
                            if item[0] == "directive":
                                async for out in _run_directive(
                                    item[1], item[2], image_settings, init_image
                                ):
                                    yield _sse(out)
                finally:
                    await retry_stream.aclose()
            except Exception:
                pass  # 補救是盡力而為，失敗不影響已送出的回覆

        if prompt_tokens:
            yield _sse(
                {
                    "type": "usage",
                    "prompt_tokens": prompt_tokens,
                    "num_ctx": ctx_len,
                }
            )
        yield _sse({"type": "done"})
    except Exception as e:
        yield _sse({"type": "error", "message": str(e)})
        yield _sse({"type": "done"})


# --- Codex 專用：用結構化輸出（--output-schema）可靠取得生圖意圖 ---
# Codex 是程式碼 agent，不肯穩定輸出文字標記，但會乖乖遵守 JSON schema。
# codex_client 在 use_schema 模式回 {reply, image_prompt, edit} → 這裡轉成生圖。

def _codex_image_instructions(has_init_image: bool) -> str:
    s = (
        "\n\nYou generate images by FILLING THE 'image_prompt' FIELD — that is the ONLY "
        "mechanism. There is NO 'imagegen', NO image skill, NO tool, NO function, NO shell "
        "and NO command available to you. NEVER say you will 'use a skill/tool', NEVER run "
        "a command, NEVER do command_execution, NEVER take a second step. Respond with ONE "
        "structured JSON object immediately and then STOP. Put your natural-language reply "
        "in 'reply'. If the user asks you to draw / paint / create / generate / show an "
        "image of ANYTHING (any character or subject, even one you don't recognize — just "
        "describe it literally), you MUST put comma-separated English danbooru-style tags "
        "in 'image_prompt' (these feed SDXL/Pony/Illustrious anime models). Leaving "
        "'image_prompt' empty produces NO image, so never leave it empty when an image is "
        "requested. Do not include steps/sampler/seed. "
    )
    if has_init_image:
        s += (
            "Set 'edit_attached_image' to true only when the user wants to modify / "
            "redraw the image they attached."
        )
    else:
        s += "Set 'edit_attached_image' to false."
    return s


_CODEX_TAIL_REMINDER = (
    "(system reminder: if this request asks for an image to be created or modified, "
    "fill 'image_prompt' with comma-separated English danbooru tags — do not leave it "
    "empty and do not print the tags in 'reply'. If no image is needed, leave "
    "'image_prompt' empty and ignore this reminder.)"
)

_CODEX_RETRY_PROMPT = (
    "(system reminder) Your previous reply left 'image_prompt' empty even though the "
    "user asked for an image. Respond again: if an image is indeed wanted, put the "
    "comma-separated English danbooru tags in 'image_prompt' now and keep 'reply' to "
    "one short sentence. If no image is actually needed, leave 'image_prompt' empty."
)


def _claude_ctx(model: str) -> int:
    """該 claude 模型的 context 長度（測試會用假 client 替換模組，故要能後備）。"""
    try:
        return claude_client.context_length_for(model)
    except AttributeError:
        return CLAUDE_CONTEXT_LENGTH or 200_000


def _codex_ctx(model: str) -> int:
    """該 codex 模型的 context 長度（測試會用假 client 替換模組，故要能後備）。"""
    try:
        return codex_client.context_length_for(model)
    except Exception:
        from config import CODEX_CONTEXT_LENGTH

        return CODEX_CONTEXT_LENGTH


async def _run_codex(
    model: str,
    messages: list[dict[str, Any]],
    tools_enabled: bool,
    image_settings: dict[str, Any] | None,
    think: bool,
    effort: str | None = None,
) -> AsyncIterator[str]:
    init_image = _last_init_image(messages)
    use_schema = bool(tools_enabled)
    system = _base_system(messages)
    if use_schema:
        system += _codex_image_instructions(bool(init_image))
    send_messages = (
        _append_to_last_user(messages, _CODEX_TAIL_REMINDER)  # 防遺忘 1)
        if use_schema
        else messages
    )

    prompt_tokens = 0
    image_done = False  # 本回合是否有生圖請求
    reply_text = ""     # 完整回覆文字（補救重試時當歷史）
    degen = _DegenWatch()
    try:
        stream = codex_client.chat_stream(
            model,
            send_messages,
            system,
            think=think,
            use_schema=use_schema,
            has_init_image=bool(init_image),
            effort=effort,
        )
        try:
            async for ev in stream:
                kind = ev.get("type")
                if kind == "error":
                    yield _sse({"type": "error", "message": ev["message"]})
                    yield _sse({"type": "done"})
                    return
                degenerated = False
                if kind == "usage":
                    prompt_tokens = ev["prompt_tokens"]
                elif kind == "thinking":
                    yield _sse({"type": "thinking", "delta": ev["delta"]})
                    degenerated = degen.feed(ev["delta"])
                elif kind == "text":
                    if ev.get("delta"):
                        reply_text += ev["delta"]
                        yield _sse({"type": "token", "delta": ev["delta"]})
                        degenerated = degen.feed(ev["delta"])
                elif kind == "image_request":
                    image_done = True
                    async for out in _run_directive(
                        ev["name"], json.dumps(ev["args"]), image_settings, init_image
                    ):
                        yield _sse(out)
                if degenerated:
                    # 模型陷入重複迴圈：中止串流（client 端會 kill codex 子行程），
                    # 讓下面的補救重試接手
                    yield _sse({"type": "thinking", "delta": _DEGEN_NOTE})
                    break
        finally:
            await stream.aclose()

        # 防遺忘 2)：使用者明顯要圖但 image_prompt 空白 → 補跑一次，只取生圖請求
        if use_schema and not image_done and _wants_image(messages):
            retry_messages = [
                *messages,
                {"role": "assistant", "content": reply_text},
                {"role": "user", "content": _CODEX_RETRY_PROMPT},
            ]
            try:
                async for ev in codex_client.chat_stream(
                    model,
                    retry_messages,
                    system,
                    think=False,
                    use_schema=True,
                    has_init_image=bool(init_image),
                    effort=effort,
                ):
                    if ev.get("type") != "image_request":
                        continue  # 補救輪只關心生圖請求；文字/錯誤/用量都忽略
                    async for out in _run_directive(
                        ev["name"], json.dumps(ev["args"]), image_settings, init_image
                    ):
                        yield _sse(out)
            except Exception:
                pass  # 補救是盡力而為，失敗不影響已送出的回覆

        if prompt_tokens:
            yield _sse(
                {
                    "type": "usage",
                    "prompt_tokens": prompt_tokens,
                    "num_ctx": _codex_ctx(model),
                }
            )
        yield _sse({"type": "done"})
    except Exception as e:
        yield _sse({"type": "error", "message": str(e)})
        yield _sse({"type": "done"})


def _fmt_png_info(d: dict[str, Any]) -> str:
    if not d.get("info"):
        return (
            "The attached image has NO embedded Stable Diffusion metadata "
            "(it may be a screenshot, a re-saved / recompressed file, or not "
            "AI-generated). Tell the user the generation parameters can't be read."
        )
    p = d.get("params") or {}
    lines = ["PNG Info — generation parameters embedded in the image:"]
    if d.get("prompt"):
        lines.append(f"Prompt: {d['prompt']}")
    if d.get("negative_prompt"):
        lines.append(f"Negative prompt: {d['negative_prompt']}")
    keys = ["Steps", "Sampler", "CFG scale", "Seed", "Size", "Model", "Denoising strength"]
    extra = ", ".join(f"{k}: {p[k]}" for k in keys if k in p)
    if extra:
        lines.append(extra)
    lines.append(
        "Present these to the user in their language. Do not call the tool again."
    )
    return "\n".join(lines)


async def _run_tool(
    name: str,
    args: dict[str, Any],
    image_settings: dict[str, Any] | None,
    init_image: str | None,
    png_source: str | None = None,
) -> AsyncIterator[Any]:
    """執行單一工具。yield dict=SSE 事件、yield str=要 append 回對話的 tool 訊息。"""
    # --- 讀 PNG 生成參數 ---
    if name == "read_png_info":
        yield {"type": "tool_call", "name": "read_png_info", "args": {}}
        if not png_source:
            yield "No attached image to read PNG info from."
            return
        try:
            info = await a1111_client.png_info(png_source)
            yield _fmt_png_info(info)
        except Exception as e:
            yield {"type": "error", "message": f"讀取 PNG 參數失敗：{e}"}
            yield f"Failed to read PNG info: {e}"
        return

    # --- 生圖 ---
    if name in IMAGE_TOOLS:
        yield {"type": "tool_call", "name": name, "args": args}
        try:
            kind, kwargs = tools_mod.build_call(name, args, image_settings, init_image)
            params = {}
            async for ev in _generate_with_progress(kind, kwargs):
                if ev["type"] == "image":
                    params = ev["params"]
                yield ev
            yield (
                "Image generated successfully and shown to the user. "
                f"Prompt used: {params.get('prompt')}. "
                "Briefly describe it to the user in their language; "
                "do not call the tool again unless asked."
            )
        except Exception as e:
            yield {"type": "error", "message": f"圖片生成失敗：{e}"}
            yield f"圖片生成失敗：{e}"
        return

    # --- web 搜尋 ---
    if name == "web_search":
        query = (args.get("query") or "").strip()
        yield {"type": "tool_call", "name": "web_search", "args": {"query": query}}
        try:
            results = await web_tools.web_search(query, args.get("max_results"))
            yield {"type": "sources", "query": query, "results": results}
            yield _fmt_search(query, results)
        except Exception as e:
            yield {"type": "error", "message": f"搜尋失敗：{e}"}
            yield f"Web search failed: {e}"
        return

    # --- 抓網頁 ---
    if name == "fetch_url":
        url = (args.get("url") or "").strip()
        yield {"type": "tool_call", "name": "fetch_url", "args": {"url": url}}
        try:
            page = await web_tools.fetch_url(url)
            yield {
                "type": "sources",
                "results": [
                    {"title": page["title"] or url, "url": page["url"], "snippet": ""}
                ],
            }
            note = " …(truncated)" if page.get("truncated") else ""
            yield (
                f"Fetched page.\nTitle: {page['title']}\nURL: {page['url']}\n\n"
                f"{page['text']}{note}"
            )
        except Exception as e:
            yield {"type": "error", "message": f"抓取失敗：{e}"}
            yield f"Fetch failed: {e}"
        return

    yield f"未知工具：{name}"

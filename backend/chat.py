"""Agentic 聊天迴圈：串流 ollama、處理工具（生圖 / web 搜尋）、即時進度，輸出 SSE。"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx

import a1111_client
import claude_client
import codex_client
import ollama_client
import settings_store
import skill_tools
import skills_store
import strata_client
import tool_gateway
import tools as tools_mod
import web_tools
from config import CLAUDE_CONTEXT_LENGTH

log = logging.getLogger(__name__)

# 工具呼叫不限次數（多張圖的故事、多步查詢都要能一次做完）。唯一的保護是「卡住偵測」：
# 同一個非生圖工具＋同樣參數在這次回覆已經跑過就不重跑，連續 STUCK_ROUNDS 輪都只是
# 這種重複呼叫 → 視為卡住，改成不帶工具讓模型用文字收尾。生圖可以合理地重複同一組參數
#（例如「同一個 prompt 畫 4 張」），所以不算重複。
STUCK_ROUNDS = 3
_REPEAT_CALL_NOTE = (
    "You already called this tool with exactly these arguments in this reply; its result "
    "is above. Use that result, call it with different arguments, or answer the user now."
)
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

# 防遺忘 4)：多張圖的故事，模型寫完下一段（「## Scene 10 …」）卻沒呼叫生圖就結束回覆
_OLLAMA_CONTINUE_NUDGE = (
    "(system reminder) You wrote the text of \"{heading}\" but ended your reply without "
    "generating its image. Call the image tool for that section NOW — do not repeat its "
    "text. After the image, continue with the remaining sections of your plan, one section "
    "and its image at a time, until the whole story is finished."
)
# 帶編號的標題行：## Scene 3 — …、### 第 3 幕、## 3. …（取第一個數字當編號）
_NUMBERED_HEADING_RE = re.compile(r"^ {0,3}#{1,6}[ \t]*([^\n]*?(\d+)[^\n]*)$", re.MULTILINE)


def _numbered_headings(text: str) -> list[tuple[int, str]]:
    return [(int(m.group(2)), m.group(1).strip()) for m in _NUMBERED_HEADING_RE.finditer(text or "")]


def _unillustrated_section(round_text: str, last_illustrated: int) -> str | None:
    """這輪（最後一次生圖之後）的文字若開了「下一個」編號段落（上一張圖所在段落的編號 +1），
    回傳該標題；代表模型寫了下一段卻沒生圖就停了。總結段落的編號對不上，不會誤判。"""
    heads = _numbered_headings(round_text)
    if last_illustrated and heads and heads[0][0] == last_illustrated + 1:
        return heads[0][1]
    return None


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


def _salvage_tool_calls(text: str, extra: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """模型沒發出正式 tool call、卻把呼叫 JSON 印在文字裡時，撿回來照常執行。

    extra：本回合額外允許的工具名（技能 API 工具）。"""
    allowed = set(_SALVAGE_TOOLS) | set(extra)
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
        if name not in allowed or not isinstance(args, dict):
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
    """取最後一則含 images 的 user 訊息的第一張圖，作為 img2img 初始圖。
    _attach_context_images 附上的「上一則回覆生成的圖」不算（context_images 記張數）。"""
    for m in reversed(messages):
        if m.get("role") == "user":
            imgs = list(m.get("images") or [])
            own = imgs[: len(imgs) - int(m.get("context_images") or 0)]
            if own:
                return own[0]
    return None


def vision_copy(b64: str, max_side: int = 768) -> str:
    """給模型看的圖：長邊超過 max_side 就縮小並轉 JPEG（省 context 與傳輸）；讀不了就原樣。"""
    import base64
    import io

    from PIL import Image

    try:
        img = Image.open(io.BytesIO(base64.b64decode(b64)))
        if max(img.size) <= max_side and img.format in ("JPEG", "PNG", "WEBP"):
            return b64
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=88)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return b64


# 上一則回覆生成 / 編輯的圖：下一輪附給看得見圖的模型（只附緊接在前的那則，免得每輪都塞舊圖）
_RECENT_IMAGES_MAX = 4
_RECENT_IMAGES_NOTE = (
    "(The image(s) you generated in your previous reply are attached to this message, after any "
    "images the user attached, so you can look at them when the user refers to them.)"
)


def _recent_generated(messages: list[dict[str, Any]]) -> list[str]:
    """緊接在最後一則 user 之前的助理回覆所生成 / 編輯的圖（前端以 generated_images 帶網址）→ base64。"""
    last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    if last_user <= 0 or messages[last_user - 1].get("role") != "assistant":
        return []
    out = []
    for url in (messages[last_user - 1].get("generated_images") or [])[-_RECENT_IMAGES_MAX:]:
        b64 = _load_generated(url)
        if b64:
            out.append(vision_copy(b64))
    return out


def _attach_context_images(messages: list[dict[str, Any]], images: list[str]) -> list[dict[str, Any]]:
    """把圖接在最後一則 user 訊息的 images 後面並加一句說明；不影響 img2img 的來源圖。"""
    if not images:
        return messages
    msgs = [dict(m) for m in messages]
    for m in reversed(msgs):
        if m.get("role") == "user":
            m["images"] = [*(m.get("images") or []), *images]
            m["context_images"] = len(images)
            m["content"] = (m.get("content") or "") + "\n\n" + _RECENT_IMAGES_NOTE
            break
    return msgs


def _load_generated(url: str) -> str | None:
    """/images/<檔名>（本 app 生成或編輯後存下的圖）→ base64；找不到回 None。"""
    import base64

    name = str(url or "").split("?", 1)[0].rsplit("/", 1)[-1]
    if not name:
        return None
    fp = settings_store.find_image(name)
    if not fp:
        return None
    try:
        return base64.b64encode(fp.read_bytes()).decode()
    except OSError:
        return None


def _last_edit_image(messages: list[dict[str, Any]]) -> str | None:
    """技能編輯工具要改的圖：對話中「最近」的一張——使用者附的圖，或助理訊息裡
    A1111 生成 / sd.cpp 編輯後的圖（前端以 generated_images 帶 /images 網址），取較新者。"""
    for m in reversed(messages):
        if m.get("role") == "user" and m.get("images"):
            return m["images"][0]
        if m.get("role") == "assistant":
            for url in reversed(m.get("generated_images") or []):
                b64 = _load_generated(url)
                if b64:
                    return b64
    return None


def _tool_message_with_images(result: dict[str, Any], can_see: bool) -> dict[str, Any]:
    """技能工具附帶的圖（如 Civitai 範例圖）：視覺模型就附在工具訊息的 images 上讓它真的看到；
    否則只給文字並說明看不到。kind=generated：剛用 A1111 生成的圖。"""
    if result.get("kind") == "generated":
        if not (can_see and result.get("images")):
            return {"role": "tool", "content": result["content"]}
        return {
            "role": "tool",
            "content": result["content"]
            + "\n\n(The generated image is attached to this message. Look at it and describe what "
            "it actually shows; if something clearly went wrong — extra limbs, broken hands, a "
            "requested detail missing — say so briefly.)",
            "images": result["images"],
            "generated_image": True,
        }
    labels = ", ".join(result.get("labels") or []) or f"{len(result.get('images') or [])} images"
    if can_see and result.get("images"):
        return {
            "role": "tool",
            "content": result["content"]
            + f"\n\n(Example images {labels} are attached to this message in that order. Look at them: you "
            "can describe what they show, compare them, and use them when recommending a prompt.)",
            "images": result["images"],
        }
    return {
        "role": "tool",
        "content": result["content"]
        + "\n\n(The example images could not be attached because this model cannot view images; "
        "rely on the prompts above and do not describe the pictures.)",
    }


def _strip_client_fields(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """移除只給後端用的欄位，避免送進各引擎。"""
    return [
        {k: v for k, v in m.items() if k != "generated_images"} if "generated_images" in m else m
        for m in messages
    ]


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
    # 技能編輯工具的來源圖（含 A1111 生成的圖）；取完就剝掉前端專用欄位
    edit_image = _last_edit_image(messages)
    # 上一則回覆生成的圖：看得見圖的模型這一輪也看得到（問「剛剛那張」時）
    recent_images = _recent_generated(messages)
    messages = _strip_client_fields(messages)
    # 啟用技能：把指示注入 system（全引擎通用）
    messages = _inject_skill(messages, skill)
    # 技能宣告的工具（tools.json）：各引擎都經 MCP 閘道（Ollama / Strata 由這裡呼叫，CLI 原生 MCP）
    skill_tool_defs = skills_store.tools_for(skill)
    skill_tool_map = {t["name"]: t for t in skill_tool_defs}

    if engine in ("claude_cli", "codex"):
        # 原生 MCP：CLI 直接呼叫 webui 閘道的工具（生圖、搜尋、技能工具），畫面事件由閘道推回來
        async for s in _run_cli_mcp(
            engine, model, _attach_context_images(messages, recent_images),
            tools_enabled=tools_enabled, web_enabled=web_enabled,
            skill=skill if skill_tool_defs else None, image_settings=image_settings,
            think=bool(think), effort=effort, edit_image=edit_image,
            png_source=(image_sources or [None])[-1],
        ):
            yield s
        return

    # Ollama 與 Strata（OpenAI 相容）共用下面的主迴圈：strata_client 的介面跟 ollama_client 一樣
    llm = strata_client if engine == "strata" else ollama_client
    can_tools = await llm.model_supports_tools(model)
    # gpt-oss 支援思考等級：think 開啟時把 effort 映射成 low/medium/high；其他模型維持布林開關
    ollama_think = think
    if think and effort and "gpt-oss" in model.lower():
        ollama_think = _oss_level(effort)
    if engine == "strata":
        # 思考開關＋強度 → reasoning_effort（none/low/medium/high）；context 由伺服器決定
        ollama_think = strata_client.reasoning_effort(think, effort)
        num_ctx = await strata_client.context_length(model) or num_ctx
    init_image = _last_init_image(messages)
    # read_png_info 要讀「原圖」metadata；image_sources 是本回合未經縮圖的原始位元組，
    # 沒有時退回 init_image（縮圖後的 JPEG 通常已無 metadata）。
    png_source = (image_sources or [None])[-1] or init_image

    # 工具一律經由 webui 的 MCP 閘道（tool_gateway）：清單來自它的 tools/list，執行走 tools/call
    tool_ctx = tool_gateway.ToolContext(
        image_tools=tools_enabled, web=web_enabled, skill=skill if skill_tool_defs else None,
        image_settings=image_settings, init_image=init_image, edit_image=edit_image, png_source=png_source,
    )
    tool_schema = (await tool_gateway.schemas(tool_ctx) if can_tools else []) or None

    convo = [dict(m) for m in messages]
    # 防遺忘 1)：把工具提醒接在最後一則 user 訊息尾端
    if can_tools and tools_enabled:
        convo = _append_to_last_user(convo, _OLLAMA_TAIL_REMINDER)
    # 非 vision 模型若收到 images 會 500，先剝除（img2img 仍可用 init_image）
    can_see = await llm.model_supports_vision(model)
    if not can_see:
        for m in convo:
            m.pop("images", None)
    else:
        convo = _attach_context_images(convo, recent_images)

    try:
        answered = False
        prompt_tokens = 0
        image_generated = False  # 本回合是否已（嘗試）生圖
        nudged = False           # 防遺忘 2) 的補救重試只做一次
        suppress_text = False    # 補救輪的文字不重複輸出給使用者
        seen_calls: set[str] = set()  # 這次回覆跑過的非生圖工具呼叫（名稱＋參數）
        stuck = 0                     # 連續「只重複舊呼叫」的輪數
        turn_text = ""                # 這次回覆到目前為止的全部文字（找段落編號用）
        images_done = 0               # 這次回覆呼叫生圖的次數
        last_illustrated = 0          # 最近一張圖所在段落的編號（## Scene N）
        continue_mark = -1            # 上次「接著畫」提醒時的 images_done（沒新圖就不再提醒）
        while True:
            assistant_content = ""
            tool_calls: list[dict[str, Any]] = []
            degen = _DegenWatch()
            degenerated = False

            stream = llm.chat_stream(
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
            if not tool_calls and can_tools and (tools_enabled or skill_tool_map) and assistant_content:
                tool_calls = _salvage_tool_calls(assistant_content, tuple(skill_tool_map))

            turn_text += assistant_content

            if not tool_calls:
                # 防遺忘 4)：故事寫了下一段卻沒生圖就停 → 提醒它畫這段並接著做完。
                # 每次提醒後要有新圖才會再提醒，模型不肯畫時不會一直繞。
                heading = _unillustrated_section(assistant_content, last_illustrated)
                if can_tools and tools_enabled and heading and images_done > continue_mark:
                    log.info("chat %s: section %r has no image; nudging to continue", model, heading)
                    continue_mark = images_done
                    suppress_text = True
                    convo.append({"role": "assistant", "content": assistant_content})
                    convo.append({"role": "user", "content": _OLLAMA_CONTINUE_NUDGE.format(heading=heading)})
                    continue
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

            fresh = False  # 這輪有沒有新的（非重複的）呼叫
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
                    fresh = True
                    images_done += 1
                    heads = _numbered_headings(turn_text)
                    if heads:
                        last_illustrated = heads[-1][0]
                else:
                    key = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)}"
                    if key in seen_calls:
                        convo.append({"role": "tool", "content": _REPEAT_CALL_NOTE})
                        continue
                    seen_calls.add(key)
                    fresh = True

                async for content in tool_gateway.run(tool_ctx, name, args):
                    if isinstance(content, str):
                        convo.append({"role": "tool", "content": content})
                    elif content.get("type") == "_tool_result":
                        tool_msg = _tool_message_with_images(content, can_see)
                        if tool_msg.get("generated_image"):
                            # 只留最新一張生成圖給模型看（多圖故事不會把 context 塞滿）
                            for old in convo:
                                if old.pop("generated_image", None):
                                    old.pop("images", None)
                        convo.append(tool_msg)
                    else:
                        yield _sse(content)

            stuck = 0 if fresh else stuck + 1
            if stuck >= STUCK_ROUNDS:
                log.warning("chat %s: stuck repeating tool calls for %d rounds", model, stuck)
                break

        # 卡在重複呼叫工具 → 最後再不帶工具讓模型用文字收尾（不報錯）
        if not answered:
            async for chunk in llm.chat_stream(
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
# 原生 MCP：啟動 CLI 時掛上 webui 的 MCP 閘道（tool_gateway，這次對話專用的網址），
# CLI 自己呼叫工具（生圖、搜尋、技能與 A1111 / Civitai Helper 的工具）；閘道把畫面事件推回來，
# 跟 CLI 的文字串流合併輸出（_run_cli_mcp）。


def _base_system(messages: list[dict[str, Any]]) -> str:
    base_parts = [
        m["content"]
        for m in messages
        if m.get("role") == "system" and m.get("content")
    ]
    return "\n\n".join(base_parts) or (
        "You are a helpful assistant. Reply in the user's language."
    )


def _tool_results_message(results: list[str]) -> str:
    return (
        "(tool results — sent by the app, not by the user)\n\n"
        + "\n\n".join(results)
        + "\n\nContinue your reply to the user using these results, in the user's "
        "language. Emit another [[CALL]] marker only if you still need more data."
    )


_MCP_TAIL_REMINDER = (
    "(system reminder: if this request needs an image to be created or changed, call the "
    "generate_image tool — or edit_image for the attached image — instead of describing it or "
    "printing prompt tags. If no image is needed, ignore this reminder.)"
)


def _mcp_instructions(names: list[str]) -> str:
    """CLI 引擎的 system 補充：工具來自 webui 的 MCP 伺服器（名稱以 mcp__webui__ 開頭）。"""
    lines = [
        "",
        "# Tools (IMPORTANT)",
        "You have NO shell and NO file system. Your tools come from the app's MCP server \"webui\" "
        f"(in your tool list they start with mcp__webui__): {', '.join(names)}. Tool names mentioned "
        "by a skill are these same tools. Use them whenever they help; never invent tool results "
        "and never claim you cannot use them.",
    ]
    if "generate_image" in names:
        lines.append(
            "To show the user an image, CALL generate_image (its description explains the prompt "
            "format). The picture appears in the chat by itself — afterwards describe it briefly; do "
            "not paste the prompt, a link or markdown for it."
        )
    if "edit_image" in names:
        lines.append("To change the image the user attached, call edit_image.")
    return "\n".join(lines)


async def _run_cli_mcp(
    engine: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    tools_enabled: bool,
    web_enabled: bool,
    skill: str | None,
    image_settings: dict[str, Any] | None,
    think: bool,
    effort: str | None,
    edit_image: str | None,
    png_source: str | None,
) -> AsyncIterator[str]:
    """Claude CLI / Codex：掛上 webui 的 MCP 閘道（這次對話專用的網址），CLI 自己呼叫工具。
    CLI 的文字串流與閘道推來的畫面事件（工具呼叫、生圖進度、圖片、搜尋來源、卡片）合併輸出。"""
    init_image = _last_init_image(messages)
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(ev: dict[str, Any]) -> None:
        await queue.put(("tool", ev))

    ctx = tool_gateway.ToolContext(
        image_tools=tools_enabled, web=web_enabled, skill=skill, image_settings=image_settings,
        init_image=init_image, edit_image=edit_image, png_source=png_source or init_image, emit=emit,
    )
    names = [t["function"]["name"] for t in await tool_gateway.schemas(ctx)]
    system = _base_system(messages) + (_mcp_instructions(names) if names else "")
    send = _append_to_last_user(messages, _MCP_TAIL_REMINDER) if "generate_image" in names else messages
    token = tool_gateway.open_session(ctx) if names else None
    url = tool_gateway.session_url(token) if token else None
    if engine == "claude_cli":
        stream = claude_client.chat_stream(model, send, system, think=think, effort=effort, mcp_url=url)
        ctx_len = _claude_ctx(model)
    else:
        stream = codex_client.chat_stream(model, send, system, think=think, effort=effort, mcp_url=url)
        ctx_len = _codex_ctx(model)

    async def pump() -> None:
        try:
            async for ev in stream:
                await queue.put(("cli", ev))
        except Exception as e:  # noqa: BLE001
            await queue.put(("cli", {"type": "error", "message": str(e)}))
        finally:
            await queue.put(("end", None))

    task = asyncio.create_task(pump())
    prompt_tokens = 0
    degen = _DegenWatch()
    try:
        while True:
            kind, ev = await queue.get()
            if kind == "end":
                break
            if kind == "tool":
                yield _sse(ev)
                continue
            t = ev.get("type")
            degenerated = False
            if t == "error":
                yield _sse({"type": "error", "message": ev["message"]})
                break
            if t == "usage":
                prompt_tokens = ev["prompt_tokens"]
            elif t == "thinking":
                yield _sse({"type": "thinking", "delta": ev["delta"]})
                degenerated = degen.feed(ev["delta"])
            elif t == "text" and ev.get("delta"):
                yield _sse({"type": "token", "delta": ev["delta"]})
                degenerated = degen.feed(ev["delta"])
            if degenerated:
                yield _sse({"type": "thinking", "delta": _DEGEN_NOTE})
                break
        while not queue.empty():  # CLI 結束前閘道最後推來的事件
            kind, ev = queue.get_nowait()
            if kind == "tool":
                yield _sse(ev)
        if prompt_tokens:
            yield _sse({"type": "usage", "prompt_tokens": prompt_tokens, "num_ctx": ctx_len})
        yield _sse({"type": "done"})
    except Exception as e:
        yield _sse({"type": "error", "message": str(e)})
        yield _sse({"type": "done"})
    finally:
        if not task.done():
            task.cancel()  # 中止（退化、連線斷了）：取消會一路殺掉 CLI 子行程
        if token:
            tool_gateway.close_session(token)


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


async def _with_progress(start: Callable[[Any], Awaitable[Any]]) -> AsyncIterator[Any]:
    """執行 start(on_progress)；執行中 yield progress 事件，最後 yield 它的結果。"""
    queue: asyncio.Queue = asyncio.Queue()

    async def on_progress(value: float | None, message: str | None) -> None:
        await queue.put({"type": "progress", "value": value or 0, **({"text": message} if message else {})})

    task = asyncio.ensure_future(start(on_progress))
    try:
        while not task.done():
            getter = asyncio.ensure_future(queue.get())
            done, _ = await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                yield getter.result()
            else:
                getter.cancel()
        yield task.result()
    finally:
        if not task.done():
            task.cancel()


async def _run_tool(
    name: str,
    args: dict[str, Any],
    image_settings: dict[str, Any] | None,
    init_image: str | None,
    png_source: str | None = None,
    skill_tool_map: dict[str, dict[str, Any]] | None = None,
    edit_image: str | None = None,
) -> AsyncIterator[Any]:
    """執行單一工具。yield dict=SSE 事件、yield str=要 append 回對話的 tool 訊息。"""
    # --- 技能 API 工具（tools.json）---
    if skill_tool_map and name in skill_tool_map:
        yield {"type": "tool_call", "name": name, "args": args}
        try:
            out = None
            # MCP 工具執行中的進度（例如 MMD 算圖、sd.cpp 改圖）邊跑邊送給前端
            async for item in _with_progress(
                lambda on_progress: skill_tools.call_full(skill_tool_map[name], args, image=edit_image or init_image,
                                                          on_progress=on_progress)
            ):
                if isinstance(item, skill_tools.ToolOutput):
                    out = item
                else:
                    yield item
            for ev in out.events:  # 例如 civitai 候選卡片、範例圖庫、sd.cpp 編輯後的圖
                yield ev
            if out.vision:  # 要給視覺模型看的圖：由主迴圈附在工具訊息上
                yield {"type": "_tool_result", "content": out.text, "images": out.vision, "labels": out.vision_labels,
                       **({"kind": out.vision_kind} if out.vision_kind else {})}
            else:
                yield out.text
        except Exception as e:
            yield {"type": "error", "message": f"技能工具失敗：{e}"}
            yield f"Tool {name} failed: {e}"
        return

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
            params: dict[str, Any] = {}
            url = ""
            async for ev in _generate_with_progress(kind, kwargs):
                if ev["type"] == "image":
                    params, url = ev["params"], ev["url"]
                yield ev
            text = (
                "Image generated successfully and shown to the user. "
                f"Prompt used: {params.get('prompt')}. "
                "Briefly describe it to the user in their language; "
                "do not call the tool again unless asked."
            )
            b64 = _load_generated(url) if url else None
            # 視覺模型看得到剛生成的圖（由 _tool_message_with_images 決定附不附）
            yield {"type": "_tool_result", "kind": "generated", "content": text,
                   "images": [vision_copy(b64)] if b64 else []}
        except Exception as e:
            yield {"type": "error", "message": f"圖片生成失敗：{e}"}
            note = (
                " (This is an error of the image server or its model setup, not of the prompt: "
                "do not retry with a changed prompt; tell the user what failed.)"
                if isinstance(e, (a1111_client.A1111Error, httpx.HTTPError))  # 伺服器錯誤或連不上
                else ""
            )
            yield f"圖片生成失敗：{e}{note}"
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

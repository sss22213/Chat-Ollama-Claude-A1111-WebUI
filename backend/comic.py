"""漫畫分鏡（storyboard）：請 LLM 把一段劇情拆成多格，每格產生
danbooru 風格的「場景提示詞」＋對白＋旁白，回傳結構化 JSON。

出圖本身重用既有的 txt2img（/api/generate-image）；本模組只負責「文字 → 分鏡腳本」。
角色的固定外觀 tag / LoRA 由前端的「角色卡」維護並在出圖時拼進提示詞，
所以這裡每格只描述「場景 / 動作 / 構圖」與「出場角色名」，不重複角色外觀。
表情獨立成 expression 欄位（只能從 expression_tags 白名單挑），前端組合提示詞時
會加權放在畫風之後，才不會被角色固定 tag / LoRA 壓過。

讀得懂英文句子的 checkpoint（Anima）另外要 description 欄位：2–4 句英文描述這格的畫面，
前端整段放在標籤前面（不拆、不去重）。漫畫自己選的技能（SKILL.md）接在 system 後面，
並附上漫畫用的轉接說明（沒有工具、只輸出 JSON、哪些東西由 app 自己帶）。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import a1111_client
import claude_client
import codex_client
import ollama_client
import skills_store
import strata_client
from expression_tags import EXPRESSION_TAGS, clean_expression, split_scene

log = logging.getLogger(__name__)

# 分鏡格數上限（避免一次要求過多格把 LLM / A1111 拖垮）
MAX_PANELS = 16


PANEL_JSON_SHAPE = (
    '{"prompt": "...", "expression": "...", "characters": ["..."], '
    '"dialogue": [{"speaker": "...", "text": "..."}], "caption": "..."}'
)


_PROMPT_RULE = (
        "- prompt: 8-15 comma-separated ENGLISH danbooru-style tags (never fewer than 8 — "
        "if the scene is simple, add lighting, background detail and prop tags) describing "
        "ONLY this panel's scene, in this order: subject count first (1girl, 1boy, 2girls, "
        "\"1girl, 1boy\", multiple girls, no humans for panels with no person), then "
        "camera/shot (close-up, portrait, upper body, cowboy shot, wide shot, from above, "
        "from side...), the characters' pose / action / gesture, props, and the background "
        "(location, time of day, lighting, weather). Use real danbooru tags, not sentences. "
        "NEVER write a character's name in prompt — the count tag plus pose identifies "
        "them. Do NOT put facial expressions here — they go in 'expression'. Do NOT "
        "restate a character's fixed look (hair color, outfit, etc.) — that is added "
        "separately. Do NOT include quality tags (masterpiece, best quality...), steps, "
        "sampler or seed.\n"
)
_EXPRESSION_RULE = (
        "- expression: 1-3 comma-separated danbooru tags for the visible character's FACE "
        "in this panel, chosen ONLY from this list: "
        + ", ".join(EXPRESSION_TAGS)
        + ". Combine an emotion with an eye/mouth state when useful (e.g. "
        "\"scared, wide-eyed, open mouth\"). If the word you want is not in the list, "
        "use the closest one that is. The expression MUST follow the story beat "
        "and change between panels — consecutive panels should not all share the same "
        "face. Use \"\" only if no face is visible.\n"
)


def panel_rules() -> str:
    """每格分鏡的欄位規則（comic 與 story 兩個入口共用）。"""
    return (
        "For EACH panel return:\n"
        + _PROMPT_RULE
        + _EXPRESSION_RULE
        + "- characters: array of the character NAMES (exactly as given in the cast) that "
        "appear in this panel. Use [] if none.\n"
        "- dialogue: array of {speaker, text} spoken lines for this panel, written "
        "entirely in the SAME LANGUAGE as the user's premise — do not mix in English "
        "words unless the premise itself uses them. Keep each line short (comic bubble "
        "length). Use [] if the panel has no dialogue.\n"
        "- caption: optional short narration / caption box text in the user's language "
        "(\"\" if none).\n\n"
        "Shot selection: when the emotional beat matters, use close-up / portrait / upper "
        "body so the face is large enough to read; use wide shots only to establish a "
        "location."
    )


def _system_prompt() -> str:
    return (
        "You are a professional comic storyboard artist and a Stable Diffusion "
        "(SDXL / Pony / Illustrious anime models) prompt engineer. The user gives you "
        "a short story premise and a cast of characters. Break the story into a fixed "
        "number of comic panels that flow as a coherent sequence.\n\n"
        + panel_rules()
        + "\n\nReturn STRICT JSON only, no markdown, no commentary, in exactly this shape:\n"
        '{"panels": [' + PANEL_JSON_SHAPE + "]}"
    )


def default_system() -> str:
    """內建的分鏡 system 範本（給前端「載入預設」來編輯）。"""
    return _system_prompt()


# ---------------- 英文句子（Anima）與技能 ----------------

PROMPT_MODES = ("auto", "tags", "sentences")

_DESCRIPTION_RULE = (
    "- description: 2-4 English sentences (present tense, third person) describing ONLY "
    "this panel's picture: who is in frame and where (\"On the left …\", \"Behind her …\" "
    "when there are several, one sentence per character), each character's pose, action "
    "and gesture, the visible expression, the props, the place and background, the time "
    "of day, weather and light, and the framing (\"Close-up.\", \"Wide shot from above.\"). "
    "NEVER write a cast member's name in description — not the original, not romanized, "
    "not translated: the image model does not know them. Refer to each one by a short "
    "look taken from the cast list instead (\"The girl with short orange hair and a yellow "
    "raincoat crouches …\", \"the boy with glasses\"); only a well-known character of an "
    "existing series may be named. Turn feelings into something visible. No dialogue, "
    "captions, sound effects or other text, no quality words, no <lora:…> tags.\n"
    "- prompt stays a list of 8-15 SHORT danbooru tags (1-3 words each, e.g. \"bus stop, "
    "rain, umbrella, crouching, from below\") of the same picture — never phrases or "
    "sentences there. The sentences say how things relate, the tags pin down each detail.\n"
)


def _description_section(shape: str) -> str:
    """句子模式：接在 system 範本後面（自訂範本也適用），多要一個 description 欄位。"""
    return (
        "\n\n# Natural-language description (this checkpoint reads English sentences)\n"
        "The image model for this comic understands plain English sentences as well as "
        "danbooru tags. Besides the fields above, write:\n"
        + _DESCRIPTION_RULE
        + "Return the JSON in exactly this shape:\n"
        + shape
    )


def _comic_adapter(sentences: bool) -> str:
    return (
        "\n\n# Runtime adapter (Comic Studio — READ THIS, overrides the skills where they "
        "conflict)\n"
        "You are writing a comic storyboard as JSON, not chatting: there are NO tools, NO "
        "scripts and NO image-generation calls here. Use the skills above only for how to "
        "write each panel's picture — which tags and words to choose and what to describe. "
        "Keep exactly the JSON fields and rules of this system message; never answer with a "
        "prompt line, a tool call or markdown. The app builds each panel's image prompt "
        "itself: the comic's style line (quality words, artist, safety tag), "
        + ("the 'description' sentences, " if sentences else "")
        + "the panel's expression, each character's fixed look and LoRA from their card, "
        "then the scene tags. So do not write quality prefixes, <lora:…> tags, negative "
        "prompts, sizes or sampler settings, and do not restate a character's fixed look in "
        "the tags. "
        + (
            "Write 'description' the way the skill describes its natural-language part."
            if sentences
            else "This checkpoint gets tags only: if a skill asks for English sentences, "
            "leave them out and put everything into the tags."
        )
    )


def _skills_section(skills: list[str] | None, sentences: bool) -> str:
    """漫畫選的技能：說明＋references（受設定頁長度上限）＋漫畫轉接層；自動模式不適用。"""
    slugs = [x for x in skills_store.parse_selection(skills or []) if x != skills_store.AUTO]
    if not slugs:
        return ""
    text = skills_store.build_prompt(slugs, adapter=_comic_adapter(sentences))
    return "\n\n" + text if text else ""


async def wants_sentences(mode: str, checkpoint: str) -> bool:
    """這次要不要 description。auto：checkpoint 是 Anima 才要（留空就問 Forge 目前選的）。"""
    if mode == "sentences":
        return True
    if mode == "tags":
        return False
    ckpt = (checkpoint or "").strip() or await a1111_client.get_current_model() or ""
    return await a1111_client.checkpoint_family(ckpt) == "Anima"


def _extras(skills: list[str] | None, sentences: bool, shape: str, user_system: str) -> str:
    """system 範本之後依序接：句子規則 → 技能＋轉接層 → 使用者的額外指示（最後，優先）。"""
    out = _description_section(shape) if sentences else ""
    out += _skills_section(skills, sentences)
    if (user_system or "").strip():
        out += "\n\n# Additional direction from the user (style/tone/content)\n" + user_system.strip()
    return out


_LORA_TAG_RE = re.compile(r"<lora:[^>]*>", re.IGNORECASE)


def clean_description(text: Any) -> str:
    """一行、去掉 <lora:…>（LoRA 由角色卡 / 畫風帶）。"""
    return re.sub(r"\s+", " ", _LORA_TAG_RE.sub("", str(text or ""))).strip()


def _user_prompt(
    premise: str,
    panel_count: int,
    characters: list[dict[str, Any]] | None,
    style: str,
    lang: str,
) -> str:
    lines = [f"Number of panels: {panel_count}.", f"Dialogue language: {lang}.", ""]
    if style.strip():
        lines.append(f"Overall art style / mood: {style.strip()}")
    cast = characters or []
    if cast:
        lines.append("Cast of characters (use these exact names in 'characters'):")
        for c in cast:
            name = (c.get("name") or "").strip()
            if not name:
                continue
            look = (c.get("appearance") or "").strip()
            lines.append(f"- {name}" + (f": {look}" if look else ""))
        lines.append(
            "In EVERY panel, list in 'characters' each cast member who is in frame, "
            "including anyone who speaks in that panel; leave it empty only for panels "
            "with no cast member visible (props, scenery, crowds)."
        )
    else:
        lines.append(
            "No named cast provided — invent consistent characters as needed and refer "
            "to them by a short name."
        )
    lines.append("")
    lines.append("Story premise:")
    lines.append(premise.strip())
    lines.append("")
    lines.append(
        f"Produce exactly {panel_count} panels as STRICT JSON described in the system message."
    )
    return "\n".join(lines)


# 模型把思考寫進 content（模板沒把 thinking 分開）時，先把它剝掉
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
# JSON 不允許的尾逗號：{"a": 1,} / [1, 2,]
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _balanced_object(text: str, start: int) -> str | None:
    """從 text[start]（應為 '{'）掃到與之配對的 '}'，跳過字串內的括號；
    掃到結尾都沒配對到就回 None——代表 JSON 沒有結尾（被截斷）。"""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def looks_truncated(text: str) -> bool:
    """回覆有開頭的 '{' 卻沒有配對的 '}'：多半是輸出被截斷（超出 num_ctx / num_predict）。"""
    text = _THINK_RE.sub("", text or "")
    start = text.find("{")
    return start != -1 and _balanced_object(text, start) is None


def _extract_json(text: str) -> dict[str, Any]:
    """從 LLM 回覆中盡量穩健地抽出 JSON 物件。

    依序嘗試：直接 parse → ```json``` 圍欄內文 → 第一個 '{' 到與之配對的 '}'
    → 第一個 '{' 到最後一個 '}'；每個候選再容忍尾逗號與字串內的換行（strict=False）。
    都失敗時，錯誤訊息帶上回覆的開頭 / 結尾，並指出是否像被截斷。
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("LLM 回傳空白")
    text = _THINK_RE.sub("", text).strip()

    candidates = [text]
    for m in re.finditer(r"```(?:json)?\s*(.+?)```", text, re.DOTALL):
        candidates.append(m.group(1).strip())
    start = text.find("{")
    if start != -1:
        bal = _balanced_object(text, start)
        if bal:
            candidates.append(bal)
        end = text.rfind("}")
        if end > start:
            candidates.append(text[start : end + 1])

    for cand in candidates:
        for fixed in (cand, _TRAILING_COMMA_RE.sub(r"\1", cand)):
            try:
                obj = json.loads(fixed, strict=False)
            except (ValueError, TypeError):
                continue
            if isinstance(obj, dict):
                return obj

    squash = lambda t: re.sub(r"\s+", " ", t)  # noqa: E731
    if looks_truncated(text):
        raise ValueError(
            "LLM 回覆的 JSON 沒有結尾，看起來被截斷了（輸出超過 num_ctx 或模型的輸出上限）。"
            "請調高 num_ctx、減少格數，或關閉思考模式再試。回覆結尾：…"
            + squash(text[-160:])
        )
    raise ValueError("無法從 LLM 回覆解析出 JSON。回覆開頭：" + squash(text[:160]) + "…")


# ---------------- 呼叫 LLM（comic 與 story 共用） ----------------

async def ask(
    engine: str,
    model: str,
    system: str,
    user: str,
    images: list[str] | None = None,
    num_ctx: int | None = None,
    think: bool | None = None,
) -> str:
    """呼叫所選引擎的非串流聊天；圖片放在 user 訊息的 images（三個 client 都認得）。"""
    msg: dict[str, Any] = {"role": "user", "content": user}
    if images:
        msg["images"] = images
    if engine == "claude_cli":
        return await claude_client.chat_once(model, [msg], system)
    if engine == "codex":
        return await codex_client.chat_once(model, [msg], system)
    if engine == "strata":
        return await strata_client.chat_once(model, [msg], system, think=think)
    messages = [{"role": "system", "content": system}, msg]
    return await ollama_client.chat_once(model, messages, num_ctx, think=think)


JSON_ATTEMPTS = 3
JSON_RETRY_HINT = (
    "\n\nYour previous answer was not valid JSON. Reply with ONLY the JSON object, nothing else."
)
JSON_TRUNCATED_HINT = (
    "\n\nYour previous answer was cut off before the JSON ended. Reply with ONLY the JSON "
    "object and keep it compact: short prompts, short dialogue lines, no extra fields."
)


MISSING_DESCRIPTION_HINT = (
    "\n\nYour previous answer left out 'description' in some panels. EVERY panel object "
    "needs all its fields, including a 'description' of 2-4 English sentences. Reply with "
    "ONLY the JSON object."
)


def _missing_descriptions(storyboard: dict[str, Any]) -> int:
    return sum(1 for p in storyboard["panels"] if not p["description"])


def json_retry_hint(text: str) -> str:
    return JSON_TRUNCATED_HINT if looks_truncated(text) else JSON_RETRY_HINT


async def ask_json(
    engine: str,
    model: str,
    system: str,
    user: str,
    images: list[str] | None = None,
    num_ctx: int | None = None,
    think: bool | None = None,
    *,
    label: str = "json",
) -> dict[str, Any]:
    """要模型回一個 JSON 物件。回覆不是 JSON（多講話、被截斷、格式錯）時，
    把提醒接在 user 訊息後面重試，共 JSON_ATTEMPTS 次；每次失敗都記 log 方便追。"""
    for attempt in range(1, JSON_ATTEMPTS + 1):
        text = await ask(engine, model, system, user, images, num_ctx, think)
        try:
            return _extract_json(text)
        except ValueError as e:
            log.warning(
                "%s attempt %d/%d: %s | head=%r | tail=%r",
                label, attempt, JSON_ATTEMPTS, e, (text or "")[:200], (text or "")[-200:],
            )
            if attempt == JSON_ATTEMPTS:
                raise
            user += json_retry_hint(text)
    raise AssertionError("unreachable")


def _name_key(s: Any) -> str:
    """比對角色名用：去空白 / 底線 / 連字號 / 間隔號、忽略大小寫。"""
    return re.sub(r"[\s_\-·•・]+", "", str(s or "")).casefold()


def canonical_characters(
    names: list[str], speakers: list[str], cast_names: list[str] | None
) -> list[str]:
    """把模型回的角色名對回角色卡上的名字（忽略大小寫、空白；再退一步用包含關係，
    例如「小雨（女主角）」→「小雨」），並把有台詞卻沒被列進 characters 的角色補上。
    對不上的名字原樣保留（沒有角色卡時模型自己取的名字）；沒對上的說話者不補。"""
    if not cast_names:
        return list(dict.fromkeys(n for n in names if n))
    keyed = {_name_key(c): c for c in cast_names if _name_key(c)}

    def resolve(n: str) -> str | None:
        k = _name_key(n)
        if not k:
            return None
        if k in keyed:
            return keyed[k]
        hits = [c for kc, c in keyed.items() if kc in k or k in kc]
        return hits[0] if len(hits) == 1 else None

    out: list[str] = []
    for n in names:
        r = resolve(n) or n
        if r and r not in out:
            out.append(r)
    for sp in speakers:
        r = resolve(sp)
        if r and r not in out:
            out.append(r)
    return out


def _tag_key(t: str) -> str:
    return " ".join(str(t or "").strip().lower().replace("_", " ").split())


def _restates_look(tag: str, fixed: set[str]) -> bool:
    """場景 tag 是否只是重述角色卡的固定外觀：完全相同，或（兩個字以上且）每個字都出現在
    同一個外觀 tag 裡（"black hair" / "messy hair" ⊂ "messy brown hair"）。"""
    k = _tag_key(tag)
    if not k:
        return False
    if k in fixed:
        return True
    words = set(k.split())
    if len(words) < 2:
        return False  # 單字（school、hair…）只在完全相同時算，免得把場景 tag 誤刪
    return any(words <= set(f.split()) for f in fixed)


def _normalize(
    obj: dict[str, Any], panel_count: int, cast: list[Any] | None = None
) -> dict[str, Any]:
    """把 LLM 回傳整理成穩定的形狀，容忍鍵名/型別差異。

    cast：角色卡（{"name", "appearance"} 或純名字）。有角色卡時把角色名對回卡片上的寫法，
    並把場景 prompt 裡重述該格出場角色固定外觀的 tag（school uniform、black hair…）拿掉：
    這些 tag 出圖時會由角色卡自動帶入，留在場景裡只是重複。"""
    raw_panels = obj.get("panels")
    if not isinstance(raw_panels, list):
        raise ValueError("JSON 缺少 panels 陣列")
    cast_names: list[str] = []
    look: dict[str, set[str]] = {}
    for c in cast or []:
        if isinstance(c, dict):
            name = str(c.get("name") or "").strip()
            tags = {_tag_key(t) for t in str(c.get("appearance") or "").split(",") if t.strip()}
        else:
            name, tags = str(c or "").strip(), set()
        if name:
            cast_names.append(name)
            look[name] = tags

    panels: list[dict[str, Any]] = []
    for p in raw_panels[:panel_count]:
        if not isinstance(p, dict):
            continue
        prompt = str(p.get("prompt") or p.get("scene") or "").strip()
        expression = clean_expression(p.get("expression") or p.get("face") or "")
        # LLM 若把表情 / 品質詞混進場景（或用了舊版 system 沒有 expression 欄位）：
        # 表情搬到 expression、品質詞丟掉，場景只留場景。
        scene_tags, stray = split_scene(prompt)
        for t in stray:
            if t not in expression:
                expression.append(t)
        prompt = ", ".join(scene_tags)
        chars = p.get("characters") or p.get("cast") or []
        if isinstance(chars, str):
            chars = [c.strip() for c in chars.split(",") if c.strip()]
        chars = [str(c).strip() for c in chars if str(c).strip()]

        dialogue_out: list[dict[str, str]] = []
        for d in p.get("dialogue") or p.get("lines") or []:
            if isinstance(d, dict):
                speaker = str(d.get("speaker") or d.get("name") or "").strip()
                txt = str(d.get("text") or d.get("line") or d.get("content") or "").strip()
            else:
                speaker, txt = "", str(d).strip()
            if txt:
                dialogue_out.append({"speaker": speaker, "text": txt})

        chars = canonical_characters(chars, [d["speaker"] for d in dialogue_out], cast_names)
        fixed = set().union(*(look.get(c, set()) for c in chars)) if chars else set()
        if fixed:
            prompt = ", ".join(t for t in prompt.split(", ") if not _restates_look(t, fixed))

        caption = str(p.get("caption") or p.get("narration") or "").strip()
        panels.append(
            {
                "prompt": prompt,
                "description": clean_description(p.get("description") or p.get("sentences")),
                "expression": ", ".join(expression[:4]),
                "characters": chars,
                "dialogue": dialogue_out,
                "caption": caption,
            }
        )

    if not panels:
        raise ValueError("分鏡為空")
    return {"panels": panels}


# ---------------- 單格：重新生成關鍵字 ----------------

def _panel_prompt_system() -> str:
    return (
        "You are a professional comic storyboard artist and a Stable Diffusion "
        "(SDXL / Pony / Illustrious anime models) prompt engineer. An existing comic "
        "storyboard is given. Rewrite the scene tags and the facial expression of ONE "
        "target panel only, keeping it consistent with the premise, the cast and the "
        "neighbouring panels, and following the user's direction when one is given. "
        "Give a fresh, better take — do not just copy the current tags.\n\n"
        "Rules for the two fields:\n" + _PROMPT_RULE + _EXPRESSION_RULE
        + "\nReturn STRICT JSON only, no markdown, no commentary, in exactly this shape:\n"
        '{"prompt": "...", "expression": "..."}'
    )


def _panel_line(i: int, p: dict[str, Any]) -> str:
    dlg = "; ".join(
        f"{(d.get('speaker') or '').strip()}: {(d.get('text') or '').strip()}".strip(": ")
        for d in (p.get("dialogue") or [])
        if isinstance(d, dict) and (d.get("text") or "").strip()
    )
    chars = ", ".join(str(c) for c in (p.get("characters") or []))
    desc = f" | description: {p['description']}" if (p.get("description") or "").strip() else ""
    return (
        f"[Panel {i}] prompt: {p.get('prompt') or '-'}{desc} | expression: {p.get('expression') or '-'}"
        f" | characters: {chars or '-'} | dialogue: {dlg or '-'} | caption: {p.get('caption') or '-'}"
    )


async def panel_prompt(
    *,
    engine: str,
    model: str,
    panels: list[dict[str, Any]],
    index: int,
    premise: str = "",
    characters: list[dict[str, Any]] | None = None,
    style: str = "",
    lang: str = "zh-TW",
    instruction: str = "",
    num_ctx: int | None = None,
    system: str = "",
    think: bool | None = None,
    skills: list[str] | None = None,
    prompt_mode: str = "auto",
    checkpoint: str = "",
) -> dict[str, Any]:
    """只為第 index 格（0 起算）重新產生場景關鍵字與表情（句子模式連 description）；
    對白、旁白、出場角色不動。回傳 {"prompt", "expression", "description", "sentences", "notices"}。"""
    if not isinstance(panels, list) or not panels:
        raise ValueError("缺少分鏡")
    if not (0 <= index < len(panels)):
        raise ValueError("分鏡格編號超出範圍")
    target = panels[index] if isinstance(panels[index], dict) else {}
    notices = ollama_client.start_notices()

    sentences = await wants_sentences(prompt_mode, checkpoint)
    system_prompt = _panel_prompt_system() + _extras(
        skills, sentences, '{"prompt": "...", "description": "...", "expression": "..."}', system
    )
    lines = [f"Dialogue language: {lang}.", ""]
    if (style or "").strip():
        lines.append(f"Overall art style / mood: {style.strip()}")
    cast = [c for c in (characters or []) if (c.get("name") or "").strip()]
    if cast:
        lines.append("Cast of characters:")
        for c in cast:
            look = (c.get("appearance") or "").strip()
            lines.append(f"- {c['name'].strip()}" + (f": {look}" if look else ""))
    if (premise or "").strip():
        lines += ["", "Story premise:", premise.strip()]
    lines += ["", f"Storyboard ({len(panels)} panels):"]
    lines += [_panel_line(i + 1, p if isinstance(p, dict) else {}) for i, p in enumerate(panels)]
    lines += [
        "",
        f"Target: panel {index + 1}. Its dialogue, caption and characters stay as they are; "
        + (
            "rewrite ONLY 'prompt', 'description' and 'expression' for this panel."
            if sentences
            else "rewrite ONLY 'prompt' and 'expression' for this panel."
        ),
        f"Current prompt: {target.get('prompt') or '-'}",
        *([f"Current description: {target.get('description') or '-'}"] if sentences else []),
        f"Current expression: {target.get('expression') or '-'}",
        "Direction from the user: "
        + ((instruction or "").strip() or "none — produce a better, more detailed set of tags for this panel."),
        "",
        "Return STRICT JSON as described in the system message.",
    ]
    obj = await ask_json(
        engine, model, system_prompt, "\n".join(lines), None, num_ctx, think, label="panel prompt"
    )
    # 走同一套整理：表情同義對應、場景裡的表情搬走、重述出場角色外觀的 tag 拿掉
    one = {
        "panels": [
            {
                "prompt": obj.get("prompt") or obj.get("scene") or "",
                "description": obj.get("description") if sentences else "",
                "expression": obj.get("expression") or "",
                "characters": target.get("characters") or [],
                "dialogue": target.get("dialogue") or [],
                "caption": target.get("caption") or "",
            }
        ]
    }
    out = _normalize(one, 1, characters)["panels"][0]
    if not out["prompt"].strip():
        raise ValueError("模型沒有回傳關鍵字")
    return {
        "prompt": out["prompt"],
        "expression": out["expression"],
        "description": out["description"],
        "sentences": sentences,
        "notices": notices,
    }


async def storyboard(
    *,
    engine: str,
    model: str,
    premise: str,
    panel_count: int = 6,
    characters: list[dict[str, Any]] | None = None,
    style: str = "",
    lang: str = "zh-TW",
    num_ctx: int | None = None,
    system: str = "",
    system_base: str = "",
    think: bool | None = None,
    skills: list[str] | None = None,
    prompt_mode: str = "auto",
    checkpoint: str = "",
) -> dict[str, Any]:
    """產生分鏡腳本。回傳 {"panels": [...], "sentences": bool, "notices": [...]}。
    notices：這次生成中使用者該知道的事（見 ollama_client.start_notices），前端顯示。

    think：Ollama 思考型模型是否先思考（None＝模型預設）；CLI 引擎另有自己的推理設定。

    system_base：覆寫內建的分鏡 system 範本（空＝用 default_system()）。
    system：使用者自訂的額外指示，接在 system 範本之後（不覆蓋）。
    skills：漫畫選的技能 slug；說明接在 system 範本之後、使用者額外指示之前。
    prompt_mode：auto（checkpoint 是 Anima 才寫句子）/ tags / sentences；
    checkpoint：漫畫出圖設定的 checkpoint（空＝Forge 目前選的）。
    """
    premise = (premise or "").strip()
    if not premise:
        raise ValueError("缺少劇情描述")
    panel_count = max(1, min(MAX_PANELS, int(panel_count or 6)))
    notices = ollama_client.start_notices()  # 例如：思考沒給出答案、自動改用不思考

    sentences = await wants_sentences(prompt_mode, checkpoint)
    shape = '{"panels": [' + PANEL_JSON_SHAPE.replace(
        '"prompt": "...", ', '"prompt": "...", "description": "...", '
    ) + "]}"
    system_prompt = ((system_base or "").strip() or _system_prompt()) + _extras(
        skills, sentences, shape, system
    )
    user = _user_prompt(premise, panel_count, characters, style, lang)

    obj = await ask_json(
        engine, model, system_prompt, user, None, num_ctx, think, label="storyboard"
    )
    out = _normalize(obj, panel_count, characters)
    if sentences and _missing_descriptions(out):
        # 偶爾有格漏寫句子（連對白、角色一起漏）：再問一次，留比較完整的那份
        log.warning(
            "storyboard: %d panel(s) without description, asking once more",
            _missing_descriptions(out),
        )
        try:
            again = _normalize(
                await ask_json(
                    engine, model, system_prompt, user + MISSING_DESCRIPTION_HINT, None,
                    num_ctx, think, label="storyboard",
                ),
                panel_count,
                characters,
            )
            if _missing_descriptions(again) < _missing_descriptions(out):
                out = again
        except ValueError as e:
            log.warning("storyboard retry failed: %s", e)
    if not sentences:
        for p in out["panels"]:
            p["description"] = ""
    return {**out, "sentences": sentences, "notices": notices}

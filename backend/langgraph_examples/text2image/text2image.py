"""文字轉圖片 workflow（A1111）。

列出底模類型 → 【人】輸入關鍵字與底模 → 【人】輸入人物範例關鍵字
  ├ 有範例：分離範例特徵（人物 / 服裝 / 場景）→ 依關鍵字調整範例特徵 → 統合成底模關鍵字
  └ 沒有範例：直接統合成底模關鍵字
→ 【人】審核關鍵字與理由 → 生成圖片 → LLM 看圖檢查 → 【人】確認圖片 → 完成
任何一關「不符合預期」都帶著意見回到「分離範例特徵」重新調整（沒有範例時這兩步會直接略過）。

【人】的三個節點用 webui_app.ask 在工作流頁面跳出表單（LangGraph interrupt）。
輸入可以留空，或先填一段文字 / {"keywords": "..."} 當表單裡關鍵字的預設值。
"""
import json
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

import webui_app

MAX_LLM_REJECTS = 2  # LLM 看圖連續判定不符合幾次後，直接交給人確認（避免一直重畫）

# 節點名稱（流程圖上顯示的就是這些）
LIST = "列出底模類型"
ASK_REQUEST = "輸入關鍵字與底模"
ASK_EXAMPLE = "輸入人物範例關鍵字"
SPLIT = "分離範例特徵"
ADJUST = "調整範例特徵"
COMPOSE = "統合成底模關鍵字"
REVIEW = "人工審核關鍵字"
DRAW = "生成圖片"
CHECK = "LLM看圖檢查"
CONFIRM = "人工確認圖片"

OK = "符合預期"
REDO = "不符合預期"

# 各底模的 prompt 寫法（整理自 app 的 SD Prompt Guide skills）
_TAGS_ORDER = (
    "count first (1girl, solo / 1boy / no humans), character and series names, hair and eyes, every clothing "
    "item and accessory, expression, pose and action, held objects, place and background, time / weather / "
    "lighting, camera framing (full body, cowboy shot, upper body, close-up, from above ...)"
)
STYLES = {
    "Illustrious": {
        "guide": "Comma-separated lowercase danbooru tags only, no sentences, in this order: " + _TAGS_ORDER
        + ". End with exactly: masterpiece, best quality, amazing quality — no other quality or aesthetic "
        "words. Weights (tag:1.1)-(tag:1.4) only for the one or two things that must win.",
        "negative": "worst quality, low quality, bad anatomy, bad hands, extra fingers, text, watermark",
    },
    "Pony": {
        "guide": "Start with: score_9, score_8_up, score_7_up, source_anime, then comma-separated lowercase "
        "danbooru tags, no sentences, in this order: " + _TAGS_ORDER + ".",
        "negative": "score_4, score_5, score_6, worst quality, low quality, bad anatomy, bad hands, text, watermark",
    },
    "SDXL": {
        "guide": "One short English sentence about the subject and scene, then comma-separated tags in this "
        "order: " + _TAGS_ORDER + ". End with: masterpiece, best quality, highly detailed.",
        "negative": "worst quality, low quality, blurry, bad anatomy, bad hands, text, watermark",
    },
    "SD 1.5": {
        "guide": "Start with: masterpiece, best quality, then comma-separated lowercase danbooru tags, no "
        "sentences, in this order: " + _TAGS_ORDER + ". Keep it under about 60 tags.",
        "negative": "worst quality, low quality, lowres, bad anatomy, bad hands, extra fingers, missing fingers, "
        "text, watermark, jpeg artifacts",
        "size": (512, 768),
    },
    "Anima": {
        "guide": "One line in this order: (1) head: masterpiece, best quality, score_7, then the character's "
        "name or LoRA trigger word if any, then safe; (2) 2-5 English sentences in present tense: who, "
        "appearance, the outfit piece by piece, action and pose, expression, place and background, time and "
        "light, framing; (3) the same picture again as 20-40 lowercase danbooru tags with spaces (long hair, "
        "not long_hair) in this order: " + _TAGS_ORDER + "; (4) LoRA tags at the very end. Weights need "
        "(tag:1.5)-(tag:2). No BREAK, no embeddings.",
        "negative": "worst quality, low quality, score_1, score_2, score_3, artist name, blurry, jpeg artifacts, "
        "lowres, censor",
    },
    "Flux": {
        "guide": "Natural English prose, 2-5 sentences: subject, appearance, outfit, action, place, light and "
        "camera. No tag lists, no quality tags, no weights.",
        "negative": "",
    },
}
STYLES["NoobAI"] = STYLES["Illustrious"]
# 個別 checkpoint 的預設（名稱含這段文字時套用）
CHECKPOINT_PRESETS = {
    "obsession": {
        "guide": STYLES["Anima"]["guide"].replace(
            "masterpiece, best quality, score_7",
            "masterpiece, best quality, amazing quality, very awa, absurdres, newest, very aesthetic, "
            "depth of field, highres"),
        "negative": "worst quality, normal quality, anatomical nonsense, bad anatomy, interlocked fingers, "
        "extra fingers, watermark, simple background, transparent, low quality, logo, text, signature, "
        "face backlighting",
    },
}


class Input(TypedDict, total=False):
    keywords: str  # 生成圖片的關鍵字（可留空，在表單裡輸入）


class Output(TypedDict, total=False):
    image: str
    prompt: str
    negative_prompt: str
    reasons: str
    base_model: str
    checkpoint: str


class State(Input, Output, total=False):
    families: dict  # 底模 → [checkpoint 名稱]
    current: str  # A1111 目前載入的 checkpoint
    example: str
    parts: dict  # 範例拆出來的 {"character", "clothing", "scene", "other"}
    parts_of: str  # parts 是從哪段範例拆的（範例沒變就不用重拆）
    adjusted: dict
    feedback: str  # 最近一次「不符合預期」的意見（人或 LLM）
    llm_review: str
    llm_rejects: int
    approved: bool  # 最近一關的判斷
    lookups: str  # 組 prompt 時模型查過的工具


# ---------------- 小工具 ----------------

def _json(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        value = json.loads(match.group(0)) if match else {}
    except ValueError:
        value = {}
    return value if isinstance(value, dict) else {}


def _items(value) -> list[str]:
    if isinstance(value, str):
        value = [v for v in value.split(",")]
    return [str(v).strip() for v in value or [] if str(v).strip()]


def _style(state: State) -> dict:
    ckpt = (state.get("checkpoint") or "").lower()
    for key, preset in CHECKPOINT_PRESETS.items():
        if key in ckpt and state.get("base_model") == "Anima":
            return {**STYLES["Anima"], **preset}
    return STYLES.get(state.get("base_model") or "", STYLES["Illustrious"])


def _feedback_note(state: State) -> str:
    if not state.get("feedback"):
        return ""
    return (f"\n\nThe previous result was rejected. Previous prompt: {state.get('prompt', '')}\n"
            f"What was wrong (fix this): {state['feedback']}")


def _verdict(state: State) -> str:
    return OK if state.get("approved") else REDO


# ---------------- 節點 ----------------

def list_families(state: State) -> dict:
    data = webui_app.list_checkpoints()
    families: dict[str, list[str]] = {}
    for c in data.get("checkpoints") or []:
        base = c.get("base") or ""
        if base and "video" not in base.lower():  # 影片模型不能用 txt2img
            families.setdefault(base, []).append(c["name"])
    if not families:
        raise RuntimeError("A1111 沒有可辨識底模的 checkpoint（或連不上 A1111）")
    families = dict(sorted(families.items(), key=lambda kv: -len(kv[1])))
    webui_app.emit("A1111 的底模：" + "、".join(f"{b}（{len(n)}）" for b, n in families.items()))
    return {"families": families, "current": data.get("current") or ""}


def ask_request(state: State) -> dict:
    families, current = state["families"], state.get("current") or ""
    current_base = next((b for b, names in families.items() if current in names), "")
    answer = webui_app.ask(
        "輸入生成圖片的關鍵字和底模類型",
        [
            {"name": "keywords", "label": "生成圖片的關鍵字", "type": "textarea", "required": True,
             "default": state.get("keywords") or "",
             "placeholder": "例如：雨夜的書店門口，撐著透明傘的女孩，暖色燈光"},
            {"name": "base_model", "label": "A1111 底模類型", "type": "select", "required": True,
             "default": current_base or next(iter(families)),
             "options": [{"value": b, "label": f"{b}（{len(n)} 個 checkpoint）" + ("・目前載入" if b == current_base else "")}
                         for b, n in families.items()]},
            {"name": "checkpoint", "label": "指定 checkpoint（可不選）", "type": "select", "default": "",
             "help": "不選：底模跟目前載入的相同就用目前的，否則用該底模的第一個",
             "options": [{"value": "", "label": "自動"}]
             + [{"value": n, "label": f"[{b}] {n}"} for b, names in families.items() for n in names]},
        ],
        message=f"A1111 目前載入：`{current or '未知'}`" + (f"（{current_base}）" if current_base else ""),
    )
    base = answer.get("base_model") or current_base
    checkpoint = answer.get("checkpoint") or ""
    if checkpoint:
        picked = next((b for b, names in families.items() if checkpoint in names), base)
        if picked != base:
            webui_app.emit(f"{checkpoint} 是 {picked}，底模改用 {picked}")
            base = picked
    else:
        names = families.get(base) or []
        checkpoint = current if current in names else (names[0] if names else "")
    return {"keywords": (answer.get("keywords") or "").strip(), "base_model": base, "checkpoint": checkpoint}


def ask_example(state: State) -> dict:
    answer = webui_app.ask(
        "輸入人物參考的範例關鍵字",
        [{"name": "example", "label": "範例關鍵字（可留空）", "type": "textarea", "default": state.get("example") or "",
          "placeholder": "貼上喜歡的人物 prompt（例如 Civitai 圖片的 prompt）；留空就只用上一步的關鍵字"}],
        message="有範例時，會先把它拆成**人物特徵、衣服服裝、場景**，再依你的關鍵字調整。",
    )
    return {"example": (answer.get("example") or "").strip()}


def has_example(state: State) -> str:
    return "若輸入不為空" if state.get("example") else "輸入為空"


def split_example(state: State) -> dict:
    example = state.get("example") or ""
    if not example:
        webui_app.emit("沒有範例關鍵字，略過")
        return {"parts": {}, "parts_of": ""}
    if state.get("parts") and state.get("parts_of") == example:
        webui_app.emit("範例沒變，沿用上次的分離結果")
        return {}
    raw = webui_app.chat(
        "Split this Stable Diffusion prompt into groups. Reply with JSON only:\n"
        '{"character": [...], "clothing": [...], "scene": [...], "other": [...]}\n'
        "- character: who it is and how they look — count tags (1girl, solo), character / series names, hair, "
        "eyes, face, body, expression, LoRA tags <lora:...> and their trigger words\n"
        "- clothing: every clothing item and accessory\n"
        "- scene: pose and action, held objects, place, background, time, weather, lighting, camera / framing\n"
        "- other: quality, score, rating, style, artist and meta tags\n"
        "Keep every item exactly as written; split sentences into short phrases.\n\n"
        f"Prompt: {example}"
    )
    parts = _json(raw)
    parts = {k: _items(parts.get(k)) for k in ("character", "clothing", "scene", "other")}
    if not any(parts.values()):
        raise RuntimeError(f"LLM 沒有回傳可用的分離結果：{raw[:300]}")
    webui_app.emit({k: ", ".join(v) for k, v in parts.items()})
    return {"parts": parts, "parts_of": example}


def adjust_example(state: State) -> dict:
    parts = state.get("parts") or {}
    if not parts:
        return {"adjusted": {}}
    raw = webui_app.chat(
        f"The user wants this picture (may be in Chinese): {state['keywords']}\n\n"
        f"A reference prompt split into groups:\n{json.dumps(parts, ensure_ascii=False)}\n\n"
        "Adjust the character, clothing and scene groups so the picture matches what the user wants: keep the "
        "reference's details where the user says nothing about them, replace what the request changes or "
        "contradicts (another place, outfit, action, hair colour ...), and add what the request needs that the "
        "reference lacks. Write new items in English, in the same form as the reference (tags stay tags). Keep "
        "LoRA tags and trigger words from the reference."
        + _feedback_note(state)
        + '\n\nReply with JSON only: {"character": [...], "clothing": [...], "scene": [...], "other": [...], '
        '"changes": "one short sentence in Traditional Chinese about what you changed"}'
    )
    data = _json(raw)
    adjusted = {k: _items(data.get(k)) for k in ("character", "clothing", "scene", "other")}
    if not any(adjusted.values()):
        adjusted = parts
    if data.get("changes"):
        webui_app.emit(f"調整：{data['changes']}")
    return {"adjusted": adjusted}


def compose_prompt(state: State) -> dict:
    """組 prompt。模型可以自己挑 MCP 工具先查資料（tools="auto"、read_only：查 LoRA、trigger words、
    範例 prompt、模型資訊……），但這一步不給生圖、換模型、下載之類會改東西的工具。"""
    base = state.get("base_model") or "Illustrious"
    style = _style(state)
    adjusted = state.get("adjusted") or {}
    reference = (f"\n\nAdjusted reference groups (use all of them, they already follow the request):\n"
                 f"{json.dumps(adjusted, ensure_ascii=False)}") if adjusted else ""
    r = webui_app.chat(
        f"Write the final Stable Diffusion prompt for a {base} checkpoint ({state.get('checkpoint', '')}).\n\n"
        f"How to write prompts for {base}: {style['guide']}\n\n"
        f"What the picture must show (the user's keywords, may be in Chinese — write everything in English): "
        f"{state['keywords']}"
        + reference
        + _feedback_note(state)
        + "\n\nBefore writing, you may look things up with your tools when it helps — for example an "
        f"installed LoRA for a named character or style (civitai_lora_inventory with base \"{base}\", or "
        "list_loras), its trigger words and example prompts (civitai_model_examples), or the checkpoint's "
        f"details. Use a LoRA only when it clearly fits the request and was made for {base}; write it as "
        "<lora:FILE_NAME:0.8> (file name without extension) together with its trigger words. Skip tools you do "
        "not need, and never invent a LoRA file name."
        + "\n\nWhen you are done, reply with JSON only: "
        '{"prompt": "...", "negative_prompt": "...", "reasons": ["...", "..."]}\n'
        + (f"- negative_prompt: start from \"{style['negative']}\" and add only what the request must exclude.\n"
           if style["negative"] else "- negative_prompt: empty string (this family does not use one).\n")
        + f"- reasons: 3-6 short points in Traditional Chinese (繁體中文) explaining why these keywords — which "
        f"come from the user's request, which from the reference or from what you looked up (LoRA, trigger "
        f"words), and which the {base} format requires.",
        tools="auto", read_only=True, details=True, max_rounds=6,
    )
    raw = r["text"]
    lookups = "、".join(dict.fromkeys(c["name"] for c in r["calls"]))
    data = _json(raw)
    prompt = re.sub(r"\s+", " ", str(data.get("prompt") or "")).strip()
    if not prompt:
        raise RuntimeError(f"LLM 沒有回傳 prompt：{raw[:300]}")
    negative = str(data.get("negative_prompt") or style["negative"]).strip()
    reasons = data.get("reasons") or []
    reasons = "\n".join(f"- {x}" for x in _items(reasons)) if isinstance(reasons, list) else str(reasons)
    return {"prompt": prompt, "negative_prompt": negative, "reasons": reasons, "lookups": lookups}


def review_prompt(state: State) -> dict:
    answer = webui_app.ask(
        "審核關鍵字",
        [
            {"name": "decision", "label": "這組關鍵字", "type": "choice", "required": True,
             "options": [{"value": "ok", "label": "符合預期，開始生圖"}, {"value": "redo", "label": "不符合預期，重新調整"}]},
            {"name": "prompt", "label": "Prompt（可以直接修改）", "type": "textarea", "default": state["prompt"]},
            {"name": "feedback", "label": "哪裡不符合（選「不符合預期」時填）", "type": "textarea",
             "placeholder": "例如：衣服改成和服、背景要白天、不要拿傘"},
        ],
        message=(f"**底模**：{state.get('base_model')}　**checkpoint**：`{state.get('checkpoint')}`\n\n"
                 f"**為什麼用這些關鍵字**\n{state.get('reasons') or '（沒有說明）'}\n\n"
                 + (f"**組 prompt 時查過**：{state['lookups']}\n\n" if state.get("lookups") else "")
                 + f"**Negative prompt**\n```\n{state.get('negative_prompt') or '（無）'}\n```"),
    )
    prompt = re.sub(r"\s+", " ", answer.get("prompt") or "").strip() or state["prompt"]
    if answer.get("decision") == "ok":
        return {"prompt": prompt, "approved": True, "feedback": ""}
    return {"prompt": prompt, "approved": False,
            "feedback": (answer.get("feedback") or "").strip() or "使用者覺得這組關鍵字不符合預期，換一種寫法"}


def draw(state: State) -> dict:
    width, height = _style(state).get("size", (None, None))
    img = webui_app.generate_image(
        state["prompt"], negative_prompt=state.get("negative_prompt") or None,
        checkpoint=state.get("checkpoint") or None, width=width, height=height,
    )
    return {"image": img["url"]}


def llm_check(state: State) -> dict:
    try:
        raw = webui_app.chat(
            "Look at the attached image. Does it show what the user asked for?\n"
            f"User's keywords: {state['keywords']}\nPrompt used: {state['prompt']}\n\n"
            'Reply with JSON only: {"ok": true or false, "seen": "one sentence in Traditional Chinese describing '
            'the image", "fix": "what to change, in Traditional Chinese; empty if ok"}. Judge the content '
            "(people, clothing, scene, action), not small drawing flaws.",
            images=[state["image"]],
        )
    except RuntimeError as e:  # 目前的模型看不到圖片
        webui_app.emit(f"略過 LLM 看圖檢查：{e}")
        return {"llm_review": "（模型看不到圖片，沒有檢查）", "approved": True, "llm_rejects": 0}
    verdict = _json(raw)
    ok = bool(verdict.get("ok", True))
    seen = str(verdict.get("seen") or raw.strip()[:300])
    fix = str(verdict.get("fix") or "")
    rejects = state.get("llm_rejects", 0)
    if not ok and rejects >= MAX_LLM_REJECTS:
        webui_app.emit(f"LLM 已經連續 {rejects + 1} 次判定不符合，交給人確認")
        return {"llm_review": f"{seen}（LLM 認為不符合：{fix}）", "approved": True, "llm_rejects": 0}
    if ok:
        return {"llm_review": seen, "approved": True, "feedback": "", "llm_rejects": 0}
    return {"llm_review": f"{seen}（不符合：{fix}）", "approved": False, "llm_rejects": rejects + 1,
            "feedback": fix or "圖片跟關鍵字不符"}


def confirm_image(state: State) -> dict:
    answer = webui_app.ask(
        "確認圖片是否符合預期",
        [
            {"name": "decision", "label": "這張圖", "type": "choice", "required": True,
             "options": [{"value": "ok", "label": "符合預期，完成"}, {"value": "redo", "label": "不符合預期，重新調整"}]},
            {"name": "feedback", "label": "哪裡不符合（選「不符合預期」時填）", "type": "textarea"},
        ],
        message=f"**LLM 檢查**：{state.get('llm_review') or '—'}\n\n**Prompt**\n```\n{state['prompt']}\n```",
        images=[state["image"]],
    )
    if answer.get("decision") == "ok":
        return {"approved": True, "feedback": ""}
    return {"approved": False,
            "feedback": (answer.get("feedback") or "").strip() or "使用者覺得圖片不符合預期，換一種寫法"}


builder = StateGraph(State, input_schema=Input, output_schema=Output)
builder.add_node(LIST, list_families)
builder.add_node(ASK_REQUEST, ask_request)
builder.add_node(ASK_EXAMPLE, ask_example)
builder.add_node(SPLIT, split_example)
builder.add_node(ADJUST, adjust_example)
builder.add_node(COMPOSE, compose_prompt)
builder.add_node(REVIEW, review_prompt)
builder.add_node(DRAW, draw)
builder.add_node(CHECK, llm_check)
builder.add_node(CONFIRM, confirm_image)

builder.add_edge(START, LIST)
builder.add_edge(LIST, ASK_REQUEST)
builder.add_edge(ASK_REQUEST, ASK_EXAMPLE)
builder.add_conditional_edges(ASK_EXAMPLE, has_example, {"若輸入不為空": SPLIT, "輸入為空": COMPOSE})
builder.add_edge(SPLIT, ADJUST)
builder.add_edge(ADJUST, COMPOSE)
builder.add_edge(COMPOSE, REVIEW)
builder.add_conditional_edges(REVIEW, _verdict, {OK: DRAW, REDO: SPLIT})
builder.add_edge(DRAW, CHECK)
builder.add_conditional_edges(CHECK, _verdict, {OK: CONFIRM, REDO: SPLIT})
builder.add_conditional_edges(CONFIRM, _verdict, {OK: END, REDO: SPLIT})
# 每一輪「不符合預期」大約 6 步，預設的步數上限不夠來回幾次
graph = builder.compile().with_config(recursion_limit=200)

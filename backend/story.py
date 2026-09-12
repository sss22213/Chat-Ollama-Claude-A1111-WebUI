"""圖片說故事：使用者上傳圖片，LLM 看圖後生成「故事」、「漫畫腳本」或「圖片分鏡的文字」。

與漫畫工作室分開的入口，但漫畫模式的輸出沿用 comic.py 的分鏡格式
（prompt / expression / characters / dialogue / caption），再加上從圖片推得的
角色卡（name + 外觀 danbooru tag）、標題、劇情大綱與畫風，前端可一鍵送進
漫畫工作室出圖。三個引擎都走各自的 chat_once（vision 由 messages 的 images 帶入）。

「圖片分鏡」模式改用兩段式（逐張描述 → 統一寫故事），因為一次送多張圖時
模型會把相鄰圖片混在一起、格數對不上；一次一張就不可能對錯格。
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
import uuid
from typing import Any

import comic
import ollama_client
import settings_store

log = logging.getLogger(__name__)

# 張數不設上限：每張約 2k token，超出 context 由前端預估提醒、使用者自行調整 num_ctx
_LENGTH_HINT = {
    "short": "short (about 300 words, or ~500 characters for CJK languages)",
    "medium": "medium (about 800 words, or ~1200 characters for CJK languages)",
    "long": "long (about 1500 words, or ~2500 characters for CJK languages)",
}


def _strip_data_url(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("data:"):
        return s.split(",", 1)[-1]
    return s


def _prep_images(images: list[str] | None) -> list[str]:
    out = [_strip_data_url(i) for i in (images or []) if (i or "").strip()]
    if not out:
        raise ValueError("請至少上傳一張圖片")
    return out


# ---------------- 故事 ----------------

def _story_system(lang: str, length: str) -> str:
    return (
        "You are a skilled fiction writer. The user gives you one or more images. "
        "Look at them carefully — characters, setting, mood, era, details, what may "
        "have just happened and what may happen next — and write an original short "
        f"story inspired by the image(s). Write in {lang}. Length: "
        f"{_LENGTH_HINT.get(length, _LENGTH_HINT['medium'])}.\n\n"
        "Format: the first line is the title as a Markdown heading (`# Title`), then a "
        "blank line, then the story in Markdown paragraphs. If several images are given, "
        "treat them as scenes of ONE story in the order given. Do not describe the images "
        "literally as a list; tell a story with a beginning, a turn, and an ending. "
        "No commentary before or after the story."
    )


def _parse_story(text: str) -> dict[str, str]:
    text = (text or "").strip()
    if not text:
        raise ValueError("LLM 回傳空白")
    # 去掉整段被 ``` 包起來的情況
    fenced = re.fullmatch(r"```(?:markdown|md)?\s*(.+?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    lines = text.splitlines()
    title = ""
    body_start = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^#{1,3}\s*(.+?)\s*#*$", s)
        if m:
            title = m.group(1).strip()
            body_start = i + 1
        else:
            # 沒有標題行：用第一行（≤ 40 字）當標題，否則留空
            if len(s) <= 40 and not s.endswith(("。", ".", "!", "?", "！", "？")):
                title = s
                body_start = i + 1
        break
    body = "\n".join(lines[body_start:]).strip()
    return {"title": title, "story": body or text}


# ---------------- 漫畫腳本 ----------------

def _comic_system(lang: str, panel_count: int) -> str:
    return (
        "You are a professional comic storyboard artist and a Stable Diffusion "
        "(SDXL / Pony / Illustrious anime models) prompt engineer. The user gives you "
        "one or more images. Study them and:\n"
        "1. Identify the main character(s) (at most 3). For each, give a short NAME "
        "(invent one if unknown; keep any name the user provides) and an 'appearance' "
        "string: comma-separated ENGLISH danbooru tags describing the FIXED look only — "
        "gender/count tag (1girl/1boy), hair color & length & style, eye color, skin, "
        "notable outfit and accessories. Do NOT include expressions, poses, "
        "background or quality tags.\n"
        "2. Write 'style': 3-6 danbooru-style tags for the art style seen in the "
        "image(s) (e.g. anime style, watercolor, flat color, sketch, monochrome). "
        "No quality tags.\n"
        "3. Invent a coherent short story inspired by the image(s) and summarise it as "
        f"'premise' (2-4 sentences, in {lang}). Give it a 'title' in {lang}.\n"
        f"4. Break that story into exactly {panel_count} comic panels.\n\n"
        + comic.panel_rules()
        + f"\nDialogue and caption must be written in {lang}. 'characters' in each panel "
        "must use the exact names from your cast.\n\n"
        "Return STRICT JSON only, no markdown, no commentary, in exactly this shape:\n"
        '{"title": "...", "premise": "...", "style": "...", '
        '"cast": [{"name": "...", "appearance": "..."}], '
        '"panels": [' + comic.PANEL_JSON_SHAPE + "]}"
    )


def _normalize_comic(obj: dict[str, Any], panel_count: int) -> dict[str, Any]:
    cast_raw = obj.get("cast") or obj.get("characters") or []
    cast: list[dict[str, str]] = []
    if isinstance(cast_raw, list):
        for c in cast_raw:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name") or "").strip()
            if not name:
                continue
            look = c.get("appearance") or c.get("look") or c.get("tags") or ""
            if isinstance(look, list):
                look = ", ".join(str(x) for x in look)
            cast.append({"name": name, "appearance": str(look).strip()})
    panels = comic._normalize(obj, panel_count, cast)["panels"]
    return {
        "title": str(obj.get("title") or "").strip(),
        "premise": str(obj.get("premise") or obj.get("story") or "").strip(),
        "style": str(obj.get("style") or "").strip(),
        "characters": cast,
        "panels": panels,
    }


# ---------------- 圖片即分鏡：每張圖一格，補上場景 / 對白 / 旁白 ----------------
# 兩段式：先「一張一張」請模型客觀描述（一次只給一張圖，格位由程式保證不會錯），
# 再把編號好的描述交給模型統一寫故事（純文字）。實測一次塞多張圖時，模型在 7 張以上
# 會把相鄰兩張看成同一格、格數少算，左上角畫編號也救不回來，所以不再一次送多張。
_DESCRIBE_SYSTEM = (
    "You describe ONE comic/storyboard panel for a writer who cannot see it. In English, in 2-4 "
    "plain sentences, state only what is visible: who is there (count, gender, hair/clothes or "
    "other traits that tell them apart), what each one is doing, facial expressions and body "
    "language, the setting and time of day, objects that matter to the action, and any text, "
    "signs or speech visible in the image (quote it). No story, no guesses about what happens "
    "before or after, no preamble, no lists."
)


async def _describe_panels(
    engine: str, model: str, imgs: list[str], num_ctx: int | None, think: bool | None
) -> list[str]:
    """逐張描述。ollama 一次一張（伺服器本來就排隊）；CLI 引擎最多 3 張並行。"""
    sem = asyncio.Semaphore(1 if engine == "ollama" else 3)

    async def one(i: int, b64: str) -> str:
        async with sem:
            text = await comic.ask(
                engine,
                model,
                _DESCRIBE_SYSTEM,
                f"Describe panel {i} of {len(imgs)}.",
                [b64],
                num_ctx,
                think,
            )
        text = re.sub(r"\s+", " ", (text or "")).strip()
        return text or "(the model returned no description for this panel)"

    return list(await asyncio.gather(*(one(i + 1, b) for i, b in enumerate(imgs))))


def _panels_system(lang: str, n: int) -> str:
    return (
        f"You are a comic writer. The user's storyboard has {n} panels; you get a numbered, "
        "objective description of each panel in reading order (panel 1 first). Write the story "
        "these panels tell. For EACH panel, in order, return:\n"
        f"- scene: one or two sentences in {lang} describing what happens in this panel "
        "(who is there, what they do, the mood), faithful to its description.\n"
        f"- dialogue: array of {{speaker, text}} — short speech-bubble lines in {lang} for the "
        "characters present in that panel. Invent short consistent names for unnamed characters "
        "and keep the same names in every panel. Use [] if nobody speaks.\n"
        f"- caption: optional narration / caption box text in {lang} (\"\" if none). Use it for "
        "time/place changes or the narrator's voice, not to repeat the dialogue.\n\n"
        f"Also return 'title' and 'premise' (2-3 sentences) in {lang}. Keep the story coherent "
        "across all panels: characters, names, and tone must stay consistent, and the last panel "
        "should land the ending. Never merge, skip, or reorder panels; never mention the panel "
        "numbers or descriptions themselves.\n\n"
        "Return STRICT JSON only, no markdown, no commentary, in exactly this shape:\n"
        '{"title": "...", "premise": "...", "panels": [{"panel": 1, "scene": "...", '
        '"dialogue": [{"speaker": "...", "text": "..."}], "caption": "..."}]} '
        f"with exactly {n} entries in 'panels', panel numbers 1..{n}."
    )


def _normalize_panels(obj: dict[str, Any], n: int) -> tuple[dict[str, Any], int]:
    """整理成固定 n 格：有 panel 編號就依編號放，否則依序；缺的補空格。回傳 (結果, 實際填到的格數)。"""
    raw = obj.get("panels")
    if not isinstance(raw, list):
        raise ValueError("JSON 缺少 panels 陣列")
    slots: list[dict[str, Any] | None] = [None] * n
    seq = 0
    for p in raw:
        if not isinstance(p, dict):
            continue
        idx = None
        try:
            idx = int(p.get("panel") or p.get("index") or 0) - 1
        except (TypeError, ValueError):
            idx = None
        if idx is None or not (0 <= idx < n) or slots[idx] is not None:
            while seq < n and slots[seq] is not None:
                seq += 1
            if seq >= n:
                break
            idx = seq
        dialogue: list[dict[str, str]] = []
        for d in p.get("dialogue") or p.get("lines") or []:
            if isinstance(d, dict):
                speaker = str(d.get("speaker") or d.get("name") or "").strip()
                txt = str(d.get("text") or d.get("line") or "").strip()
            else:
                speaker, txt = "", str(d).strip()
            if txt:
                dialogue.append({"speaker": speaker, "text": txt})
        slots[idx] = {
            "scene": str(p.get("scene") or p.get("description") or "").strip(),
            "dialogue": dialogue,
            "caption": str(p.get("caption") or p.get("narration") or "").strip(),
        }
    filled = sum(1 for s in slots if s is not None)
    panels = [s or {"scene": "", "dialogue": [], "caption": ""} for s in slots]
    return {
        "title": str(obj.get("title") or "").strip(),
        "premise": str(obj.get("premise") or "").strip(),
        "panels": panels,
    }, filled


async def _write_panels(
    engine: str,
    model: str,
    lang: str,
    descriptions: list[str],
    extra: str,
    num_ctx: int | None,
    think: bool | None,
) -> dict[str, Any]:
    """第二段：把編號描述交給模型寫故事（不附圖）。非 JSON 或格數不齊就重試（最多 3 次），仍不齊則用描述補位。"""
    n = len(descriptions)
    lines = [f"Storyboard with {n} panels. Panel descriptions:", ""]
    for i, d in enumerate(descriptions, 1):
        lines += [f"[Panel {i}]", d, ""]
    if extra:
        lines += ["Additional direction from the user:", extra, ""]
    lines.append(f"Return exactly {n} panels as STRICT JSON described in the system message.")
    user = "\n".join(lines)
    system = _panels_system(lang, n)
    data, filled = None, -1
    for attempt in range(3):
        text = await comic.ask(engine, model, system, user, [], num_ctx, think)
        try:
            obj = comic._extract_json(text)
        except ValueError as e:
            # 偶爾會回非 JSON（多講話、被截斷）；最後一次才放棄
            log.warning(
                "panels pass 2 attempt %d: %s | head=%r | tail=%r",
                attempt + 1, e, (text or "")[:200], (text or "")[-200:],
            )
            if attempt == 2:
                raise
            user += comic.json_retry_hint(text)
            continue
        data, filled = _normalize_panels(obj, n)
        if filled >= n:
            break
        user += f"\n\nYour previous answer had {filled} panels; it MUST have all {n}, numbered 1..{n}."
    for p, d in zip(data["panels"], descriptions):
        if not p["scene"]:
            p["scene"] = d  # 模型漏寫的格子退回用客觀描述，至少不留白
    return data


def _save_upload(b64: str) -> str:
    """把上傳圖存進圖片目錄（與生成圖同處），回傳 /images/<name> 供漫畫工作室直接引用。"""
    raw = base64.b64decode(b64)
    ext = "png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else "webp" if raw[:4] == b"RIFF" else "jpg"
    filename = f"panel_{uuid.uuid4().hex}.{ext}"
    image_dir = settings_store.get_image_dir()
    image_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / filename).write_bytes(raw)
    return f"/images/{filename}"


# ---------------- 入口 ----------------

async def from_image(
    *,
    engine: str,
    model: str,
    images: list[str] | None,
    mode: str = "story",
    lang: str = "zh-TW",
    instructions: str = "",
    length: str = "medium",
    panel_count: int = 6,
    num_ctx: int | None = None,
    think: bool | None = None,
) -> dict[str, Any]:
    imgs = _prep_images(images)
    extra = (instructions or "").strip()
    notices = ollama_client.start_notices()  # 例如：思考沒給出答案、自動改用不思考
    user_lines = [f"{len(imgs)} image(s) attached."]
    if extra:
        user_lines += ["", "Additional direction from the user:", extra]

    if mode == "panels":
        descriptions = await _describe_panels(engine, model, imgs, num_ctx, think)
        data = await _write_panels(engine, model, lang, descriptions, extra, num_ctx, think)
        # LLM 成功後才落地存圖（失敗不留孤兒檔），讓漫畫工作室能直接用這些圖當分鏡
        urls = [_save_upload(b) for b in imgs]
        for i, p in enumerate(data["panels"]):
            p["index"] = i + 1
            p["image_url"] = urls[i]
            p["description"] = descriptions[i]
        return {"mode": "panels", **data, "notices": notices}

    if mode == "comic":
        panel_count = max(1, min(comic.MAX_PANELS, int(panel_count or 6)))
        user_lines.append("")
        user_lines.append(
            f"Produce the cast and exactly {panel_count} panels as STRICT JSON described "
            "in the system message."
        )
        obj = await comic.ask_json(
            engine, model, _comic_system(lang, panel_count), "\n".join(user_lines), imgs, num_ctx, think,
            label="story comic",
        )
        data = _normalize_comic(obj, panel_count)
        return {"mode": "comic", **data, "notices": notices}

    user_lines.append("")
    user_lines.append("Write the story now.")
    text = await comic.ask(engine, model, _story_system(lang, length), "\n".join(user_lines), imgs, num_ctx, think)
    return {"mode": "story", **_parse_story(text), "notices": notices}

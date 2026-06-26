"""漫畫分鏡（storyboard）：請 LLM 把一段劇情拆成多格，每格產生
danbooru 風格的「場景提示詞」＋對白＋旁白，回傳結構化 JSON。

出圖本身重用既有的 txt2img（/api/generate-image）；本模組只負責「文字 → 分鏡腳本」。
角色的固定外觀 tag / LoRA 由前端的「角色卡」維護並在出圖時拼進提示詞，
所以這裡每格只描述「場景 / 動作 / 構圖 / 表情」與「出場角色名」，不重複角色外觀。
"""
from __future__ import annotations

import json
import re
from typing import Any

import claude_client
import codex_client
import ollama_client

# 分鏡格數上限（避免一次要求過多格把 LLM / A1111 拖垮）
MAX_PANELS = 16


def _system_prompt() -> str:
    return (
        "You are a professional comic storyboard artist and a Stable Diffusion "
        "(SDXL / Pony / Illustrious anime models) prompt engineer. The user gives you "
        "a short story premise and a cast of characters. Break the story into a fixed "
        "number of comic panels that flow as a coherent sequence.\n\n"
        "For EACH panel return:\n"
        "- prompt: comma-separated ENGLISH danbooru-style tags describing ONLY this "
        "panel's scene, camera/shot (e.g. close-up, wide shot, from above), the "
        "characters' pose / action / expression, and the background. Do NOT restate a "
        "character's fixed look (hair color, outfit, etc.) — that is added separately. "
        "Do NOT include quality tags, steps, sampler or seed.\n"
        "- characters: array of the character NAMES (exactly as given in the cast) that "
        "appear in this panel. Use [] if none.\n"
        "- dialogue: array of {speaker, text} spoken lines for this panel, written in the "
        "SAME LANGUAGE as the user's premise. Keep each line short (comic bubble length). "
        "Use [] if the panel has no dialogue.\n"
        "- caption: optional short narration / caption box text in the user's language "
        "(\"\" if none).\n\n"
        "Return STRICT JSON only, no markdown, no commentary, in exactly this shape:\n"
        '{"panels": [{"prompt": "...", "characters": ["..."], '
        '"dialogue": [{"speaker": "...", "text": "..."}], "caption": "..."}]}'
    )


def default_system() -> str:
    """內建的分鏡 system 範本（給前端「載入預設」來編輯）。"""
    return _system_prompt()


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


def _extract_json(text: str) -> dict[str, Any]:
    """從 LLM 回覆中盡量穩健地抽出 JSON 物件。

    依序嘗試：直接 parse → 去掉 ```json``` 圍欄 → 取第一個 '{' 到最後一個 '}' 的切片。
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("LLM 回傳空白")

    # 去掉 markdown code fence
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    candidates = [text]
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    # 大括號切片
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except (ValueError, TypeError):
            continue
    raise ValueError("無法從 LLM 回覆解析出 JSON")


def _normalize(obj: dict[str, Any], panel_count: int) -> dict[str, Any]:
    """把 LLM 回傳整理成穩定的形狀，容忍鍵名/型別差異。"""
    raw_panels = obj.get("panels")
    if not isinstance(raw_panels, list):
        raise ValueError("JSON 缺少 panels 陣列")

    panels: list[dict[str, Any]] = []
    for p in raw_panels[:panel_count]:
        if not isinstance(p, dict):
            continue
        prompt = str(p.get("prompt") or p.get("scene") or "").strip()
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

        caption = str(p.get("caption") or p.get("narration") or "").strip()
        panels.append(
            {
                "prompt": prompt,
                "characters": chars,
                "dialogue": dialogue_out,
                "caption": caption,
            }
        )

    if not panels:
        raise ValueError("分鏡為空")
    return {"panels": panels}


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
) -> dict[str, Any]:
    """產生分鏡腳本。回傳 {"panels": [...]}。

    system_base：覆寫內建的分鏡 system 範本（空＝用 default_system()）。
    system：使用者自訂的額外指示，接在 system 範本之後（不覆蓋）。
    """
    premise = (premise or "").strip()
    if not premise:
        raise ValueError("缺少劇情描述")
    panel_count = max(1, min(MAX_PANELS, int(panel_count or 6)))

    system_prompt = (system_base or "").strip() or _system_prompt()
    if (system or "").strip():
        system_prompt += (
            "\n\n# Additional direction from the user (style/tone/content)\n"
            + system.strip()
        )
    user = _user_prompt(premise, panel_count, characters, style, lang)

    if engine == "claude_cli":
        text = await claude_client.chat_once(model, [{"role": "user", "content": user}], system_prompt)
    elif engine == "codex":
        text = await codex_client.chat_once(model, [{"role": "user", "content": user}], system_prompt)
    else:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user},
        ]
        text = await ollama_client.chat_once(model, messages, num_ctx)

    return _normalize(_extract_json(text), panel_count)

"""技能「觸發時才載入」模式（settings.skills = ["__lazy__"]）。

自動模式把所有技能的全文都放進 system prompt（9 個技能＋工具約 3 萬多 tokens），本地小模型
容易被不相干的規則稀釋。這個模式改成：
1. 每一輪送出前，用同一個模型做一次很小的判斷（只給技能目錄、目前的 checkpoint、上一輪用的
   技能和使用者最近幾句話），回 {"skills": [...]}；不靠主對話的模型自己記得去載入。
2. 判斷出來的技能才把全文注入（跟手動指定一樣），工具也只給那幾個技能的。
3. 同一段對話沿用：上一則助理訊息記著它用了哪些技能（skills_loaded），判斷時一併給，
   延續同一件事（重畫、修改、下一張）就留著；判斷失敗也沿用上一輪的。
4. 後備：Ollama / Strata 另外給 load_skill 工具，判斷漏掉時模型還能自己載入（見 chat.run_chat）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import skills_store

log = logging.getLogger("webui")

LAZY = skills_store.LAZY
MAX_PICK = 3            # 一輪最多幾個技能
ROUTER_TIMEOUT = 90.0   # 判斷最多等幾秒（逾時就沿用上一輪）
_DESC_MAX = 500         # 目錄裡每個技能描述的字數上限
_PREV_USER = 2          # 除了最新一句，再給幾句較早的使用者訊息
_TEXT_MAX = 600         # 較早的使用者訊息各取多少字
_LATEST_MAX = 2000      # 最新一句取多少字

ROUTER_SYSTEM = (
    "You route a chat request to the app's skills (sets of instructions for the assistant). "
    'Reply with JSON only, exactly {"skills": ["slug", ...]}, and nothing else.\n'
    "- Pick the skills the assistant needs for the LATEST user message: usually one, sometimes "
    "two that work together (for example an image prompt guide plus the skill whose tools look up "
    f"LoRAs), at most {MAX_PICK}.\n"
    "- For image requests, pick the prompt guide that fits the image checkpoint. When the picture "
    "shows a named character or style (from a series, or the user's own), or the user mentions a "
    "LoRA, also pick the skill whose tools list the installed LoRAs, so the assistant can check "
    "which LoRAs exist.\n"
    "- Previously active skills: keep them when the latest message continues the same task (a "
    "redraw, a change, another picture, a question about the result). Drop them only when the user "
    "clearly moved on to something else.\n"
    "- Use [] when no skill fits (small talk, general questions).\n"
    "- Use only slugs from the list."
)


def catalog(skills: list[dict[str, Any]]) -> str:
    lines = []
    for s in skills:
        desc = re.sub(r"\s+", " ", str(s.get("description") or "")).strip()
        if len(desc) > _DESC_MAX:
            desc = desc[:_DESC_MAX].rstrip() + "…"
        lines.append(f"- {s['slug']}: {s.get('name') or s['slug']} — {desc}")
    return "\n".join(lines)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # OpenAI 式的分段內容
        return " ".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return ""


def _user_texts(messages: list[dict[str, Any]]) -> list[str]:
    return [t for t in (_text(m.get("content")).strip() for m in messages if m.get("role") == "user") if t]


def sticky_from(messages: list[dict[str, Any]], valid: set[str] | None = None) -> list[str]:
    """最近一則助理訊息用了哪些技能（前端送來的 skills_loaded）；沒有就空清單。"""
    for m in reversed(messages):
        if m.get("role") != "assistant":
            continue
        got = m.get("skills_loaded")
        if not isinstance(got, list):
            return []
        out = []
        for slug in got:
            slug = str(slug or "").strip()
            if slug and slug not in out and (valid is None or slug in valid):
                out.append(slug)
        return out
    return []


def parse_reply(text: str, valid: set[str]) -> list[str] | None:
    """模型的回答 → slug 清單；看不懂回 None（呼叫端沿用上一輪）。"""
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
        except ValueError:
            obj = None
        if isinstance(obj, dict) and isinstance(obj.get("skills"), list):
            out: list[str] = []
            for slug in obj["skills"]:
                slug = str(slug or "").strip()
                if slug in valid and slug not in out:
                    out.append(slug)
            return out[:MAX_PICK]
    # 沒照格式：找回答裡出現的 slug（照出現順序）
    hits = sorted(
        (i.start(), slug) for slug in valid
        for i in re.finditer(rf"(?<![\w-]){re.escape(slug)}(?![\w-])", text)
    )
    if hits:
        out = []
        for _, slug in hits:
            if slug not in out:
                out.append(slug)
        return out[:MAX_PICK]
    if re.fullmatch(r"\[\s*\]|none|no skills?\.?", text, re.IGNORECASE):
        return []
    return None


def router_prompt(skills: list[dict[str, Any]], messages: list[dict[str, Any]], sticky: list[str],
                  checkpoint: str) -> str:
    texts = _user_texts(messages)
    latest = texts[-1][:_LATEST_MAX] if texts else ""
    earlier = [t[:_TEXT_MAX] for t in texts[-1 - _PREV_USER:-1]]
    parts = [
        "Skills:\n" + catalog(skills),
        f"Image checkpoint: {checkpoint or 'unknown'}",
        f"Previously active skills: {', '.join(sticky) if sticky else 'none'}",
    ]
    if earlier:
        parts.append("Earlier user messages (oldest first):\n" + "\n".join(f"- {t}" for t in earlier))
    parts.append(f"Latest user message:\n{latest}")
    parts.append("JSON:")
    return "\n\n".join(parts)


async def _ask(engine: str, model: str, system: str, user: str, num_ctx: int | None) -> str:
    """跟聊天同一個引擎 / 模型，不思考（判斷只要回一行 JSON）。
    Ollama 帶跟聊天一樣的 num_ctx，不然 Ollama 會為了不同的 context 重載模型。"""
    msg = {"role": "user", "content": user}
    if engine == "claude_cli":
        import claude_client
        return await claude_client.chat_once(model, [msg], system)
    if engine == "codex":
        import codex_client
        return await codex_client.chat_once(model, [msg], system)
    if engine == "strata":
        import strata_client
        return await strata_client.chat_once(model, [msg], system, think=False)
    import ollama_client
    return await ollama_client.chat_once(model, [{"role": "system", "content": system}, msg],
                                         num_ctx, think=False)


async def pick(engine: str, model: str, messages: list[dict[str, Any]], *, num_ctx: int | None = None,
               checkpoint: str = "") -> tuple[list[str], str]:
    """這一輪要載入哪些技能 → (slug 清單, 來源)。來源：router（判斷的）、sticky（判斷失敗，沿用上一輪）、
    none（沒有技能或沒有使用者訊息）。"""
    skills = skills_store.list_skills()
    valid = {s["slug"] for s in skills}
    sticky = sticky_from(messages, valid)
    if not skills or not _user_texts(messages):
        return sticky, "none"
    user = router_prompt(skills, messages, sticky, checkpoint)
    try:
        reply = await asyncio.wait_for(_ask(engine, model, ROUTER_SYSTEM, user, num_ctx), ROUTER_TIMEOUT)
    except Exception as e:  # noqa: BLE001 — 判斷失敗不能擋住聊天
        log.warning("skill router %s/%s failed: %s; keeping %s", engine, model, e, sticky)
        return sticky, "sticky"
    picked = parse_reply(reply, valid)
    if picked is None:
        log.warning("skill router %s/%s: unreadable reply %r; keeping %s", engine, model, reply[:200], sticky)
        return sticky, "sticky"
    log.info("skill router %s/%s: %s (previous %s)", engine, model, picked, sticky)
    return picked, "router"


def event(slugs: list[str], source: str) -> dict[str, Any]:
    """給前端的 skills 事件：存進助理訊息（skills、skillNames），下一輪再當 skills_loaded 送回來。"""
    names = {s["slug"]: s.get("name") or s["slug"] for s in skills_store.list_skills()}
    return {"type": "skills", "skills": list(slugs), "names": [names.get(s, s) for s in slugs], "source": source}


def load_tool(active: list[str]) -> dict[str, Any] | None:
    """後備的 load_skill 工具（還沒載入的技能才列）；全都載入了回 None。"""
    rest = [s for s in skills_store.list_skills() if s["slug"] not in active]
    if not rest:
        return None
    listing = "; ".join(f"{s['slug']} ({s.get('name') or s['slug']})" for s in rest)
    return {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": (
                "Load the full instructions of one of the app's skills when this request needs a skill "
                f"that is not active yet. Available: {listing}. The result is the skill's instructions: "
                "follow them for the rest of this reply."
            ),
            "parameters": {
                "type": "object",
                "properties": {"skill": {"type": "string", "enum": [s["slug"] for s in rest],
                                         "description": "The skill's slug"}},
                "required": ["skill"],
            },
        },
    }


def load_result(slug: str, active: list[str]) -> str:
    """load_skill 的結果文字；成功時 active 會加上 slug（呼叫端再更新工具清單）。"""
    slug = str(slug or "").strip()
    if slug in active:
        return f"The skill '{slug}' is already active: its instructions are in the system message."
    if slug not in {s["slug"] for s in skills_store.list_skills()}:
        return f"There is no skill '{slug}'."
    text = skills_store.build_prompt(slug)
    if not text:
        return f"The skill '{slug}' could not be loaded."
    active.append(slug)
    return f"Loaded the skill '{slug}'. Follow these instructions for the rest of this reply:\n\n{text}"
